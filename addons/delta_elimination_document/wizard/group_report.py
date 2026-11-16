from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

STATEMENTS = [('pnl', "Profit and Loss"), ('bs', "Balance Sheet")]
SECTIONS = [
    ('revenue', "Revenue"),
    ('other_income', "Other Income"),
    ('cost_of_revenue', "Cost of Revenue"),
    ('expenses', "Expenses"),
    ('assets', "Assets"),
    ('liabilities', "Liabilities"),
    ('equity', "Equity"),
]
SECTION_BY_ACCOUNT_TYPE = {
    'income': 'revenue',
    'income_other': 'other_income',
    'expense_direct_cost': 'cost_of_revenue',
    'expense': 'expenses',
    'expense_depreciation': 'expenses',
}
ELIMINATIONS_COLUMN = "Eliminations"


def _section(account_type):
    if account_type in SECTION_BY_ACCOUNT_TYPE:
        return SECTION_BY_ACCOUNT_TYPE[account_type]
    if account_type.startswith('asset'):
        return 'assets'
    if account_type.startswith('liability'):
        return 'liabilities'
    return 'equity'


class DeltaGroupReport(models.TransientModel):
    """Group Profit and Loss (month) and Balance Sheet (month end): each member company translated
    to the group currency, the eliminations of the approved document, and the group total."""
    _name = 'delta.group.report'
    _description = "Group Results"

    group_id = fields.Many2one('delta.consolidation.group', string="Consolidation Group", required=True,
                               default=lambda self: self.env['delta.consolidation.group'].search([], limit=1))
    date_from = fields.Date(string="Month", required=True,
                            default=lambda self: fields.Date.today().replace(day=1) - relativedelta(months=1))
    date_to = fields.Date(compute='_compute_date_to')
    document_id = fields.Many2one('delta.elimination.document', compute='_compute_document_id',
                                  string="Approved Elimination Document")
    include_draft = fields.Boolean(string="Include draft document",
                                   help="Use the month's elimination document even if it is not approved yet.")
    line_ids = fields.One2many('delta.group.report.line', 'report_id')

    @api.depends('date_from')
    def _compute_date_to(self):
        for report in self:
            report.date_to = report.date_from and report.date_from.replace(day=1) + relativedelta(day=31)

    @api.depends('group_id', 'date_from', 'include_draft')
    def _compute_document_id(self):
        for report in self:
            states = ('draft', 'confirmed') if report.include_draft else ('confirmed',)
            report.document_id = report.group_id and report.date_from and self.env['delta.elimination.document'].search([
                ('group_id', '=', report.group_id.id),
                ('date_from', '=', report.date_from.replace(day=1)),
                ('state', 'in', states),
            ], limit=1)

    def action_generate(self):
        self.ensure_one()
        self.date_from = self.date_from.replace(day=1)
        self.line_ids.unlink()
        self.env['delta.group.report.line'].create(self._prepare_line_vals())
        return {
            'type': 'ir.actions.act_window',
            'name': _("Group Results %(group)s %(month)s", group=self.group_id.name, month=f"{self.date_from:%Y-%m}"),
            'res_model': 'delta.group.report.line',
            'view_mode': 'pivot,list',
            'views': [(self.env.ref('delta_elimination_document.view_delta_group_report_line_pivot').id, 'pivot'),
                      (self.env.ref('delta_elimination_document.view_delta_group_report_line_list').id, 'list')],
            'domain': [('report_id', '=', self.id)],
            'context': {'search_default_groupby_statement': 1, 'search_default_groupby_section': 1},
        }

    # -------------------------------------------------------------------------

    def _prepare_line_vals(self):
        self.ensure_one()
        group = self.group_id._with_member_companies()
        balances = group._translated_balances(self.date_from, self.date_to)
        local = self._local_balances()

        vals_list = []
        bs_totals = defaultdict(float)  # company -> translated balance of all balance-sheet lines

        def add(statement, section, column, balance, code=False, name=False, company=None, amount_local=0.0):
            """Add a report line; returns the rounded balance actually stored."""
            balance = group.currency_id.round(balance)
            if group.currency_id.is_zero(balance) and not amount_local:
                return 0.0
            # P&L: revenue and profit positive. Balance sheet: debit positive, so each column totals zero.
            sign = -1 if statement == 'pnl' else 1
            vals_list.append({
                'report_id': self.id,
                'statement': statement,
                'section': section,
                'account_code': code,
                'account_label': f"{code} {name}" if code else name,
                'column': column,
                'company_id': company.id if company else False,
                'balance': balance,
                'amount': sign * balance,
                'amount_local': sign * amount_local,
                'local_currency_id': company.currency_id.id if company else group.currency_id.id,
            })
            return balance

        for (company, account, _counterpart), balance in balances['pnl'].items():
            code = account.with_company(company).code
            add('pnl', _section(account.account_type), company.name, balance, code, account.name, company,
                local['pnl'].get((company, account), 0.0))
        for (company, account, _counterpart), balance in balances['bs'].items():
            code = account.with_company(company).code
            bs_totals[company] += add('bs', _section(account.account_type), company.name, balance, code, account.name,
                                      company, local['bs'].get((company, account), 0.0))

        # Profit to date and CTA per company
        profit_to_date = defaultdict(float)
        for (company, _account, _counterpart), balance in balances['pnl'].items():
            profit_to_date[company] += balance
        for (company, _counterpart), balance in balances['prior'].items():
            profit_to_date[company] += balance
        for company in group.member_company_ids:
            profit = add('bs', 'equity', company.name, profit_to_date[company], name=_("Profit / loss to date"),
                         company=company, amount_local=local['profit'].get(company, 0.0))
            cta = -(bs_totals[company] + profit)
            add('bs', 'equity', company.name, cta, name=_("Cumulative translation adjustment"), company=company)

        # Eliminations of the month's document
        for line in self.document_id.line_ids:
            if line.line_type == 'pnl':
                add('pnl', _section(line.account_type), ELIMINATIONS_COLUMN, line.balance,
                    line.account_code, line.account_name)
                add('bs', 'equity', ELIMINATIONS_COLUMN, line.balance, name=_("Profit / loss to date"))
            elif line.line_type == 'balance_sheet':
                add('bs', _section(line.account_type), ELIMINATIONS_COLUMN, line.balance,
                    line.account_code, line.account_name)
            elif line.line_type == 'prior_result':
                add('bs', 'equity', ELIMINATIONS_COLUMN, line.balance, name=_("Profit / loss to date"))
            else:
                add('bs', 'assets', ELIMINATIONS_COLUMN, line.balance,
                    name=_("Intercompany elimination difference (in transit / FX)"))
        return vals_list

    def _local_balances(self):
        """Same split as the translated balances, in each company's own currency (standalone view)."""
        result = {'pnl': defaultdict(float), 'bs': defaultdict(float), 'profit': defaultdict(float)}
        for row in self.group_id._fetch_balances(self.date_to):
            company, account = row['company'], row['account']
            if _section(row['account_type']) in SECTION_BY_ACCOUNT_TYPE.values():
                result['profit'][company] += row['balance']
                if row['month'] >= self.date_from:
                    result['pnl'][company, account] += row['balance']
            else:
                result['bs'][company, account] += row['balance']
        return result


class DeltaGroupReportLine(models.TransientModel):
    _name = 'delta.group.report.line'
    _description = "Group Results Line"
    _order = 'statement, section, account_code, column'

    report_id = fields.Many2one('delta.group.report', required=True, ondelete='cascade', index=True)
    statement = fields.Selection(STATEMENTS, required=True)
    section = fields.Selection(SECTIONS, required=True)
    account_code = fields.Char()
    account_label = fields.Char(string="Account")
    column = fields.Char(string="Company / Eliminations")
    company_id = fields.Many2one('res.company', string="Company")
    currency_id = fields.Many2one(related='report_id.group_id.currency_id')
    balance = fields.Monetary(string="Balance (group currency)", help="Positive = debit.")
    amount = fields.Monetary(string="Amount (group currency)",
                             help="P&L: revenue and profit positive, costs negative. Balance sheet: assets positive, "
                                  "liabilities and equity negative, so it totals zero and the grand total is the profit.")
    local_currency_id = fields.Many2one('res.currency', string="Company Currency")
    amount_local = fields.Monetary(string="Amount (company currency)", currency_field='local_currency_id')
