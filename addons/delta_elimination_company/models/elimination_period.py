from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL

CURRENCY_TABLE_PERIOD_KEY = 'delta_elimination'

# Never intercompany: cash moves out of one company and into another, and equity is not eliminated here.
EXCLUDED_ACCOUNT_TYPES = ('asset_cash', 'liability_credit_card', 'equity', 'equity_unaffected', 'off_balance')


class DeltaEliminationPeriod(models.Model):
    """One month of intercompany eliminations for a consolidation company.

    Rule applied when the period is run (amounts in the consolidation company's currency,
    translated with the standard CTA currency table of the reports):

    * every intercompany P&L account of every member has zero group movement in the month;
    * every intercompany balance-sheet account has zero group balance at month end
      (the entry only posts the change against the eliminations of earlier months).

    Whatever does not net to zero between two companies (cash in transit, FX translation)
    goes to the difference account, one line per company pair.
    """
    _name = 'delta.elimination.period'
    _description = "Intercompany Elimination Period"
    _order = 'company_id, date_from desc'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', string="Consolidation Company", required=True, index=True,
        domain=[('delta_is_consolidation_company', '=', True)],
        default=lambda self: self.env.company if self.env.company.delta_is_consolidation_company else False)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date_from = fields.Date(string="Month", required=True,
                            default=lambda self: fields.Date.today().replace(day=1))
    date_to = fields.Date(compute='_compute_date_to', store=True)
    move_id = fields.Many2one('account.move', string="Elimination Entry", readonly=True, copy=False,
                              check_company=True)
    move_line_ids = fields.One2many(related='move_id.line_ids', string="Elimination Lines")
    state = fields.Selection([('draft', "Not run"), ('done', "Eliminated")], compute='_compute_state', store=True)
    difference_amount = fields.Monetary(
        compute='_compute_difference_amount', string="Elimination Difference",
        help="Net amount posted to the elimination difference account by this entry.")

    _company_month_uniq = models.Constraint(
        'unique (company_id, date_from)',
        "There is already an elimination period for this month.",
    )

    @api.depends('company_id', 'date_from')
    def _compute_name(self):
        for period in self:
            period.name = period.date_from and f"{period.company_id.name} {period.date_from:%Y-%m}"

    @api.depends('date_from')
    def _compute_date_to(self):
        for period in self:
            period.date_to = period.date_from and period.date_from + relativedelta(day=31)

    @api.depends('move_id.state')
    def _compute_state(self):
        for period in self:
            period.state = 'done' if period.move_id.state == 'posted' else 'draft'

    @api.depends('move_id.line_ids.balance')
    def _compute_difference_amount(self):
        for period in self:
            account = period.company_id.delta_difference_account_id
            period.difference_amount = sum(
                period.move_id.line_ids.filtered(lambda l: l.account_id == account).mapped('balance'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('date_from'):
                vals['date_from'] = fields.Date.to_date(vals['date_from']).replace(day=1)
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    def action_run(self):
        """(Re)compute the elimination entries. Later periods of the same company are recomputed too,
        because their balance-sheet eliminations are posted as a change against earlier months."""
        for company in self.company_id:
            first = min(self.filtered(lambda p: p.company_id == company).mapped('date_from'))
            periods = self.search([('company_id', '=', company.id), ('date_from', '>=', first)], order='date_from')
            for period in periods:
                period._run()
        return True

    def action_open_move(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'views': [(False, 'form')],
            'context': {'allowed_company_ids': self.company_id.ids},
        }

    # -------------------------------------------------------------------------
    # Engine
    # -------------------------------------------------------------------------

    def _run(self):
        self.ensure_one()
        company = self.company_id
        if not company.delta_member_company_ids:
            raise UserError(_("%s has no consolidated companies.", company.name))
        company._delta_ensure_setup()

        line_vals = self._prepare_elimination_line_vals()
        move = self.move_id
        if not line_vals:
            if move:
                move.button_draft()
                move.line_ids = [Command.clear()]
            return

        move_vals = {
            'move_type': 'entry',
            'journal_id': company.delta_elimination_journal_id.id,
            'date': self.date_to,
            'ref': _("Intercompany eliminations %s", f"{self.date_from:%Y-%m}"),
            'delta_elimination_period_id': self.id,
        }
        if move:
            # Keep the same entry (and its number): rewrite its lines.
            move.button_draft()
            move.write({**move_vals, 'line_ids': [Command.clear()] + [Command.create(v) for v in line_vals]})
        else:
            move = self.env['account.move'].with_company(company).create({
                **move_vals,
                'line_ids': [Command.create(v) for v in line_vals],
            })
            self.move_id = move
        move.action_post()

    def _prepare_elimination_line_vals(self):
        """Return the account.move.line values of this period's elimination entry."""
        self.ensure_one()
        company = self.company_id
        members = company.delta_member_company_ids
        currency = company.currency_id
        partner_to_company = {member.partner_id.id: member for member in members}

        amounts = defaultdict(float)  # (member, consolidation account, counterpart) -> elimination amount
        for member_id, account_id, partner_id, is_pnl, translated in self._query_intercompany_balances():
            member = self.env['res.company'].browse(member_id)
            counterpart = partner_to_company[partner_id]
            if counterpart == member:
                continue
            account = self._map_account(member, self.env['account.account'].browse(account_id))
            amounts[member, account, counterpart, is_pnl] -= translated

        # Balance-sheet eliminations are cumulative: only post the change since earlier periods.
        for (member, account, counterpart), posted in self._previous_balance_sheet_eliminations().items():
            amounts[member, account, counterpart, False] -= posted

        def line_order(key):
            member, account, counterpart, _is_pnl = key
            return member.id, counterpart.id, account.code or ''

        line_vals = []
        pair_totals = defaultdict(float)
        for key in sorted(amounts, key=line_order):
            member, account, counterpart, _is_pnl = key
            amount = currency.round(amounts[key])
            if currency.is_zero(amount):
                continue
            pair_totals[tuple(sorted((member, counterpart), key=lambda c: c.id))] += amount
            line_vals.append({
                'name': _("Elimination %(company)s / %(counterpart)s: %(account)s",
                          company=member.name, counterpart=counterpart.name, account=account.display_name),
                'account_id': account.id,
                'partner_id': counterpart.partner_id.id,
                'balance': amount,
                'delta_elim_company_id': member.id,
                'delta_counterpart_company_id': counterpart.id,
            })

        for (first, second), total in pair_totals.items():
            if currency.is_zero(total):
                continue
            line_vals.append({
                'name': _("Elimination difference %(first)s / %(second)s (FX translation, items in transit)",
                          first=first.name, second=second.name),
                'account_id': company.delta_difference_account_id.id,
                'balance': -currency.round(total),
                'delta_elim_company_id': first.id,
                'delta_counterpart_company_id': second.id,
            })
        return line_vals

    def _query_intercompany_balances(self):
        """Intercompany amounts of the members, translated to the consolidation currency.

        P&L lines: movement of the month (average rate of the month).
        Balance-sheet lines: balance at month end (closing rate).
        Yields (member_id, account_id, counterpart_partner_id, is_pnl, translated_amount).
        """
        company = self.company_id
        members = company.delta_member_company_ids
        Currency = self.env['res.currency'].with_company(company)
        report = self.env['account.report'].with_company(company)

        if Currency._check_currency_table_monocurrency(members | company):
            rate = SQL("1")
            currency_table_join = SQL()
        else:
            Currency._create_currency_table(
                members, [(CURRENCY_TABLE_PERIOD_KEY, self.date_from, self.date_to)], use_cta_rates=True)
            options = {
                'currency_table': {'type': 'cta'},
                'date': {'currency_table_period_key': CURRENCY_TABLE_PERIOD_KEY},
            }
            rate = SQL("COALESCE(account_currency_table.rate, 1)")
            currency_table_join = report._currency_table_aml_join(options, aml_alias=SQL("aml"))

        fx_accounts = (members.income_currency_exchange_account_id | members.expense_currency_exchange_account_id)
        is_pnl = SQL("(acc.account_type LIKE %s OR acc.account_type LIKE %s)", 'income%', 'expense%')
        query = SQL(
            """
            SELECT aml.company_id,
                   aml.account_id,
                   partner.commercial_partner_id,
                   %(is_pnl)s AS is_pnl,
                   SUM(aml.balance * %(rate)s)
              FROM account_move_line aml
              JOIN account_account acc ON acc.id = aml.account_id
              JOIN res_partner partner ON partner.id = aml.partner_id
              %(currency_table_join)s
             WHERE aml.parent_state = 'posted'
               AND aml.company_id IN %(member_ids)s
               AND partner.commercial_partner_id IN %(partner_ids)s
               AND acc.account_type NOT IN %(excluded_types)s
               AND aml.account_id NOT IN %(fx_account_ids)s
               AND aml.date <= %(date_to)s
               AND (aml.date >= %(date_from)s OR NOT %(is_pnl)s)
          GROUP BY 1, 2, 3, 4
            """,
            is_pnl=is_pnl,
            rate=rate,
            currency_table_join=currency_table_join,
            member_ids=tuple(members.ids),
            partner_ids=tuple(members.partner_id.ids),
            excluded_types=EXCLUDED_ACCOUNT_TYPES,
            fx_account_ids=tuple(fx_accounts.ids) or (0,),
            date_from=self.date_from,
            date_to=self.date_to,
        )
        return self.env.execute_query(query)

    def _previous_balance_sheet_eliminations(self):
        """Balance-sheet elimination amounts already posted by earlier periods,
        keyed by (member, consolidation account, counterpart)."""
        company = self.company_id
        groups = self.env['account.move.line']._read_group(
            domain=[
                ('company_id', '=', company.id),
                ('parent_state', '=', 'posted'),
                ('move_id.delta_elimination_period_id', '!=', False),
                ('move_id.delta_elimination_period_id', '!=', self.id),
                ('date', '<', self.date_from),
                ('delta_elim_company_id', '!=', False),
                ('account_id', '!=', company.delta_difference_account_id.id),
                ('account_id.account_type', 'not in', ('income', 'income_other', 'expense', 'expense_depreciation',
                                                        'expense_direct_cost')),
            ],
            groupby=['delta_elim_company_id', 'account_id', 'delta_counterpart_company_id'],
            aggregates=['balance:sum'],
        )
        return {(member, account, counterpart): balance for member, account, counterpart, balance in groups}

    def _map_account(self, member, member_account):
        """The consolidation company's account with the same code as the member's account."""
        code = member_account.with_company(member).code
        return self.company_id._delta_get_or_create_account(code, member_account.name, member_account.account_type)
