from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError

ELIMINATION_JOURNAL_CODE = 'ELIM'
DIFFERENCE_ACCOUNT = ('129900', 'Intercompany Elimination Difference (FX / in transit)', 'asset_current')


class ResCompany(models.Model):
    _inherit = 'res.company'

    delta_is_consolidation_company = fields.Boolean(
        string="Consolidation Company",
        help="This company holds no business of its own: it only carries the intercompany "
             "elimination entries of the member companies.")
    delta_member_company_ids = fields.Many2many(
        comodel_name='res.company',
        relation='delta_consolidation_member_rel',
        column1='consolidation_company_id',
        column2='member_company_id',
        string="Consolidated Companies")
    delta_elimination_journal_id = fields.Many2one('account.journal', string="Elimination Journal")
    delta_difference_account_id = fields.Many2one(
        'account.account', string="Elimination Difference Account",
        help="Receives what does not net to zero between two companies: cash in transit, "
             "FX translation differences on intercompany balances.")
    delta_horizontal_group_id = fields.Many2one('account.report.horizontal.group', string="By-Company Report Group")

    @api.constrains('delta_is_consolidation_company', 'delta_member_company_ids')
    def _check_delta_members(self):
        for company in self.filtered('delta_is_consolidation_company'):
            if company in company.delta_member_company_ids:
                raise ValidationError(_("A consolidation company cannot consolidate itself."))
            if company.delta_member_company_ids.filtered('delta_is_consolidation_company'):
                raise ValidationError(_("A consolidation company cannot be a member of another one."))

    @api.model
    def _delta_create_consolidation_company(self, name, members, currency=None):
        """Create a consolidation company for ``members`` with everything it needs:
        chart of accounts, elimination journal, difference account and by-company report columns."""
        currency = currency or members.sorted('id')[:1].currency_id
        company = self.create({
            'name': name,
            'currency_id': currency.id,
            'country_id': members.sorted('id')[:1].country_id.id,
            'delta_is_consolidation_company': True,
            'delta_member_company_ids': [Command.set(members.ids)],
        })
        self.env.user.company_ids |= company
        admin = self.env.ref('base.user_admin', raise_if_not_found=False)
        if admin:
            admin.company_ids |= company
        self.env['account.chart.template'].try_loading('generic_coa', company=company, install_demo=False)
        company.currency_id = currency  # the chart template resets it to its country's currency
        company._delta_ensure_setup()
        return company

    def _delta_ensure_setup(self):
        """Idempotently create the elimination journal, difference account and report group."""
        for company in self.filtered('delta_is_consolidation_company'):
            Journal = self.env['account.journal'].with_company(company)
            if not company.delta_elimination_journal_id:
                company.delta_elimination_journal_id = Journal.create({
                    'name': _("Intercompany Eliminations"),
                    'code': ELIMINATION_JOURNAL_CODE,
                    'type': 'general',
                    'company_id': company.id,
                })
            if not company.delta_difference_account_id:
                code, name, account_type = DIFFERENCE_ACCOUNT
                company.delta_difference_account_id = company._delta_get_or_create_account(code, name, account_type)
            company._delta_sync_horizontal_group()

    def _delta_get_or_create_account(self, code, name, account_type):
        """Account with ``code`` in this company; created with the given name/type if missing."""
        self.ensure_one()
        Account = self.env['account.account'].with_company(self)
        account = Account.search([*Account._check_company_domain(self), ('code', '=', code)], limit=1)
        if not account:
            account = Account.create({
                'code': code,
                'name': name,
                'account_type': account_type,
                'company_ids': [Command.set(self.ids)],
            })
        return account

    def _delta_sync_horizontal_group(self):
        """Keep a 'by company' horizontal group on the standard P&L and Balance Sheet, with one
        column per member company plus one for the consolidation company (the eliminations)."""
        reports = self.env.ref('account_reports.profit_and_loss') | self.env.ref('account_reports.balance_sheet')
        for company in self.filtered('delta_is_consolidation_company'):
            company_ids = (company.delta_member_company_ids | company).ids
            rule_vals = {'field_name': 'company_id', 'domain': str([('id', 'in', company_ids)])}
            group = company.delta_horizontal_group_id
            if group:
                group.rule_ids.write(rule_vals)
            else:
                company.delta_horizontal_group_id = self.env['account.report.horizontal.group'].create({
                    'name': _("%s by company", company.name),
                    'rule_ids': [Command.create(rule_vals)],
                    'report_ids': [Command.set(reports.ids)],
                })

    def write(self, vals):
        res = super().write(vals)
        if 'delta_member_company_ids' in vals or vals.get('delta_is_consolidation_company'):
            self.filtered(lambda c: c.delta_is_consolidation_company and c.chart_template)._delta_ensure_setup()
        return res
