from collections import defaultdict
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import SQL

# Never intercompany: cash moves out of one company and into another, and equity is not eliminated here.
EXCLUDED_ACCOUNT_TYPES = ('asset_cash', 'liability_credit_card', 'equity', 'equity_unaffected', 'off_balance')
PNL_ACCOUNT_TYPES = ('income', 'income_other', 'expense', 'expense_depreciation', 'expense_direct_cost')
EQUITY_ACCOUNT_TYPES = ('equity', 'equity_unaffected')


class DeltaConsolidationGroup(models.Model):
    """A group of companies reported together in one currency.

    Translation to the group currency (IAS 21, the same principle as the Enterprise CTA option):
    P&L at the average rate of each month, assets and liabilities at the closing rate,
    equity at the historical rate; the translation difference is shown as CTA.
    """
    _name = 'delta.consolidation.group'
    _description = "Consolidation Group"

    name = fields.Char(required=True)
    currency_id = fields.Many2one('res.currency', string="Reporting Currency", required=True,
                                  default=lambda self: self.env.ref('base.USD'))
    member_company_ids = fields.Many2many('res.company', string="Member Companies", required=True)
    document_ids = fields.One2many('delta.elimination.document', 'group_id', string="Elimination Documents")
    document_count = fields.Integer(compute='_compute_document_count')

    @api.depends('document_ids')
    def _compute_document_count(self):
        for group in self:
            group.document_count = len(group.document_ids)

    @api.constrains('member_company_ids')
    def _check_members(self):
        for group in self:
            if len(group.member_company_ids) < 2:
                raise ValidationError(_("A consolidation group needs at least two companies."))

    def action_open_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Elimination Documents"),
            'res_model': 'delta.elimination.document',
            'view_mode': 'list,form',
            'domain': [('group_id', '=', self.id)],
            'context': {'default_group_id': self.id},
        }

    # -------------------------------------------------------------------------
    # Currency translation
    # -------------------------------------------------------------------------

    def _rate(self, currency, date):
        """Factor converting an amount in ``currency`` into the group currency at ``date``."""
        self.ensure_one()
        if currency == self.currency_id:
            return 1.0
        return currency._get_conversion_rate(currency, self.currency_id, self.env.company, date)

    def _average_rate(self, currency, date_from, date_to):
        """Daily-weighted average rate over [date_from, date_to]."""
        self.ensure_one()
        if currency == self.currency_id:
            return 1.0
        days = (date_to - date_from).days + 1
        return sum(self._rate(currency, date_from + timedelta(days=day)) for day in range(days)) / days

    def _translate(self, company, balance, account_type, date, cache):
        """Translate a company-currency ``balance`` booked on ``account_type``.

        :param date: the month (first day) for P&L, the line date for equity, the closing date otherwise.
        """
        currency = company.currency_id
        if account_type in PNL_ACCOUNT_TYPES:
            key = (currency, 'average', date)
            if key not in cache:
                cache[key] = self._average_rate(currency, date, date + relativedelta(day=31))
        else:
            key = (currency, 'spot', date)
            if key not in cache:
                cache[key] = self._rate(currency, date)
        return balance * cache[key]

    # -------------------------------------------------------------------------
    # Data
    # -------------------------------------------------------------------------

    def _with_member_companies(self):
        """This group with every member company allowed, so the engine can read their accounts whatever the
        company switcher shows. The user must have access to all member companies."""
        self.ensure_one()
        # Read without the switcher's filter: otherwise unselected members silently drop out of the group
        members = self.sudo().member_company_ids
        missing = members - self.env.user.company_ids
        if missing and not self.env.su:
            raise UserError(_("You need access to every company of %(group)s to run its eliminations: %(missing)s.",
                              group=self.name, missing=", ".join(missing.sudo().mapped('name'))))
        allowed = self.env.companies.ids
        allowed += [company_id for company_id in members.ids if company_id not in allowed]
        return self.with_context(allowed_company_ids=allowed)

    def _fetch_balances(self, date_to, intercompany_only=False):
        """Posted balances of the member companies up to ``date_to``.

        Returns a list of dicts with company, account, counterpart (intercompany only), account_type,
        month (first day) and date (for equity lines only) and balance in company currency.
        """
        self.ensure_one()
        group = self._with_member_companies()
        members = group.member_company_ids
        conditions = [
            SQL("aml.parent_state = 'posted'"),
            SQL("aml.company_id IN %s", tuple(members.ids)),
            SQL("aml.date <= %s", date_to),
        ]
        counterpart = SQL("NULL::integer")
        if intercompany_only:
            fx_accounts = members.income_currency_exchange_account_id | members.expense_currency_exchange_account_id
            counterpart = SQL("partner.commercial_partner_id")
            conditions += [
                SQL("partner.commercial_partner_id IN %s", tuple(members.partner_id.ids)),
                SQL("acc.account_type NOT IN %s", EXCLUDED_ACCOUNT_TYPES),
                SQL("aml.account_id NOT IN %s", tuple(fx_accounts.ids) or (0,)),
            ]
        query = SQL(
            """
            SELECT aml.company_id,
                   aml.account_id,
                   %(counterpart)s,
                   acc.account_type,
                   DATE_TRUNC('month', aml.date)::date,
                   CASE WHEN acc.account_type IN %(equity_types)s THEN aml.date END,
                   SUM(aml.balance)
              FROM account_move_line aml
              JOIN account_account acc ON acc.id = aml.account_id
         LEFT JOIN res_partner partner ON partner.id = aml.partner_id
             WHERE %(conditions)s
          GROUP BY 1, 2, 3, 4, 5, 6
            """,
            counterpart=counterpart,
            equity_types=EQUITY_ACCOUNT_TYPES,
            conditions=SQL(" AND ").join(conditions),
        )
        partner_to_company = {company.partner_id.id: company for company in members}
        Company, Account = group.env['res.company'], group.env['account.account']
        result = []
        for company_id, account_id, partner_id, account_type, month, date, balance in self.env.execute_query(query):
            company = Company.browse(company_id)
            counterpart_company = partner_to_company.get(partner_id, Company)
            if intercompany_only and counterpart_company == company:
                continue
            result.append({
                'company': company,
                'account': Account.browse(account_id),
                'counterpart': counterpart_company,
                'account_type': account_type,
                'month': month,
                'date': date,
                'balance': balance,
            })
        return result

    def _translated_balances(self, date_from, date_to, intercompany_only=False):
        """Balances translated to the group currency, split as the group report needs them.

        Returns a dict with:
        - 'pnl':   {(company, account, counterpart): amount} P&L movement of [date_from, date_to]
        - 'prior': {(company, counterpart): amount} P&L result before date_from (profit to date)
        - 'bs':    {(company, account, counterpart): amount} assets/liabilities/equity at date_to
        """
        self.ensure_one()
        cache = {}
        result = {'pnl': defaultdict(float), 'prior': defaultdict(float), 'bs': defaultdict(float)}
        for row in self._fetch_balances(date_to, intercompany_only=intercompany_only):
            company, account_type = row['company'], row['account_type']
            if account_type in PNL_ACCOUNT_TYPES:
                amount = self._translate(company, row['balance'], account_type, row['month'], cache)
                if row['month'] >= date_from:
                    result['pnl'][company, row['account'], row['counterpart']] += amount
                else:
                    result['prior'][company, row['counterpart']] += amount
            else:
                rate_date = row['date'] if account_type in EQUITY_ACCOUNT_TYPES else date_to
                amount = self._translate(company, row['balance'], account_type, rate_date, cache)
                result['bs'][company, row['account'], row['counterpart']] += amount
        return result
