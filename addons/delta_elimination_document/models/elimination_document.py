from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

LINE_TYPES = [
    ('pnl', "P&L of the month"),
    ('balance_sheet', "Balance at month end"),
    ('prior_result', "Result of earlier months"),
    ('difference', "Elimination difference"),
]


class DeltaEliminationDocument(models.Model):
    """Intercompany eliminations of one month, kept outside the general ledger.

    Each document is complete on its own (it does not depend on earlier documents). Per pair of
    companies, in the group currency:

    * P&L of the month: every intercompany P&L amount of the month is reversed;
    * balance at month end: every intercompany asset/liability balance is reversed;
    * result of earlier months: intercompany P&L of earlier months, reversed inside equity
      (profit to date), so the group balance sheet stays consistent with the P&L;
    * elimination difference: what does not net to zero between the two companies
      (cash in transit, FX translation of intercompany balances). The document always balances.
    """
    _name = 'delta.elimination.document'
    _description = "Intercompany Elimination Document"
    _inherit = ['mail.thread']
    _order = 'date_from desc, id desc'

    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False, tracking=True)
    group_id = fields.Many2one('delta.consolidation.group', string="Consolidation Group", required=True,
                               tracking=True)
    currency_id = fields.Many2one(related='group_id.currency_id')
    date_from = fields.Date(string="Month", required=True, tracking=True,
                            default=lambda self: fields.Date.today().replace(day=1))
    date_to = fields.Date(compute='_compute_date_to', store=True)
    # Approval and reset are logged explicitly: field tracking is skipped for records created in the same transaction
    state = fields.Selection([('draft', "Draft"), ('confirmed', "Approved")], default='draft', required=True,
                             copy=False)
    line_ids = fields.One2many('delta.elimination.document.line', 'document_id', string="Lines", copy=False)
    computed_on = fields.Datetime(readonly=True, copy=False)
    approved_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    pnl_elimination = fields.Monetary(compute='_compute_totals', string="Effect on Group Result",
                                      help="Change of the group profit of the month caused by the eliminations.")
    difference_amount = fields.Monetary(compute='_compute_totals', string="Elimination Difference")

    _group_month_uniq = models.Constraint(
        'unique (group_id, date_from)',
        "There is already an elimination document for this group and month.",
    )

    @api.depends('date_from')
    def _compute_date_to(self):
        for document in self:
            document.date_to = document.date_from and document.date_from + relativedelta(day=31)

    @api.depends('line_ids.balance', 'line_ids.line_type')
    def _compute_totals(self):
        for document in self:
            lines = document.line_ids
            document.pnl_elimination = -sum(lines.filtered(lambda l: l.line_type == 'pnl').mapped('balance'))
            document.difference_amount = sum(lines.filtered(lambda l: l.line_type == 'difference').mapped('balance'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('date_from'):
                vals['date_from'] = fields.Date.to_date(vals['date_from']).replace(day=1)
            if vals.get('name', _("New")) == _("New"):
                vals['name'] = self.env['ir.sequence'].next_by_code('delta.elimination.document') or _("New")
        return super().create(vals_list)

    def write(self, vals):
        if 'date_from' in vals:
            vals['date_from'] = fields.Date.to_date(vals['date_from']).replace(day=1)
        if self.filtered(lambda d: d.state == 'confirmed') and set(vals) - {'state', 'approved_by_id'} \
                - set(self.env['mail.thread']._fields):
            raise UserError(_("An approved elimination document cannot be changed. Reset it to draft first."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda d: d.state == 'confirmed'):
            raise UserError(_("An approved elimination document cannot be deleted."))
        return super().unlink()

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    def action_compute(self):
        for document in self:
            if document.state != 'draft':
                raise UserError(_("Only draft documents can be recomputed."))
            document.write({
                'line_ids': [Command.clear()] + [Command.create(vals) for vals in document._prepare_line_vals()],
                'computed_on': fields.Datetime.now(),
            })
            document.message_post(body=_("Eliminations computed: %(count)s lines, difference %(amount)s.",
                                         count=len(document.line_ids), amount=document.difference_amount))
        return True

    def action_confirm(self):
        for document in self:
            if not document.line_ids:
                document.action_compute()
            document.write({'state': 'confirmed', 'approved_by_id': self.env.user.id})
            document.message_post(body=_("Approved by %(user)s.", user=self.env.user.name))
        return True

    def action_reset_to_draft(self):
        self.write({'state': 'draft', 'approved_by_id': False})
        for document in self:
            document.message_post(body=_("Reset to draft by %(user)s.", user=self.env.user.name))
        return True

    def action_print(self):
        return self.env.ref('delta_elimination_document.action_report_elimination_document').report_action(self)

    def action_open_group_report(self):
        self.ensure_one()
        report = self.env['delta.group.report'].create({'group_id': self.group_id.id, 'date_from': self.date_from})
        return report.action_generate()

    # -------------------------------------------------------------------------
    # Engine
    # -------------------------------------------------------------------------

    def _prepare_line_vals(self):
        self.ensure_one()
        group = self.group_id
        currency = group.currency_id
        balances = group._translated_balances(self.date_from, self.date_to, intercompany_only=True)

        line_vals = []
        pair_totals = defaultdict(float)

        def add(line_type, company, counterpart, amount, account=None):
            amount = currency.round(-amount)
            if currency.is_zero(amount):
                return
            pair_totals[tuple(sorted((company, counterpart), key=lambda c: c.id))] += amount
            line_vals.append({
                'line_type': line_type,
                'company_id': company.id,
                'counterpart_company_id': counterpart.id,
                'account_id': account.id if account else False,
                'account_code': account.with_company(company).code if account else False,
                'account_name': account.name if account else False,
                'account_type': account.account_type if account else False,
                'balance': amount,
            })

        def line_order(item):
            (company, account, counterpart), _amount = item
            return company.id, counterpart.id, account.with_company(company).code or ''

        def prior_order(item):
            (company, counterpart), _amount = item
            return company.id, counterpart.id

        for (company, account, counterpart), amount in sorted(balances['pnl'].items(), key=line_order):
            add('pnl', company, counterpart, amount, account)
        for (company, account, counterpart), amount in sorted(balances['bs'].items(), key=line_order):
            add('balance_sheet', company, counterpart, amount, account)
        for (company, counterpart), amount in sorted(balances['prior'].items(), key=prior_order):
            add('prior_result', company, counterpart, amount)

        for (first, second), total in pair_totals.items():
            if not currency.is_zero(total):
                line_vals.append({
                    'line_type': 'difference',
                    'company_id': first.id,
                    'counterpart_company_id': second.id,
                    'balance': -currency.round(total),
                })
        for sequence, vals in enumerate(line_vals, start=1):
            vals['sequence'] = sequence
        return line_vals


class DeltaEliminationDocumentLine(models.Model):
    _name = 'delta.elimination.document.line'
    _description = "Intercompany Elimination Document Line"
    _order = 'document_id, sequence, id'

    document_id = fields.Many2one('delta.elimination.document', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer()
    currency_id = fields.Many2one(related='document_id.currency_id')
    line_type = fields.Selection(LINE_TYPES, string="Type", required=True)
    company_id = fields.Many2one('res.company', string="Eliminated Company", required=True)
    counterpart_company_id = fields.Many2one('res.company', string="Counterpart", required=True)
    account_id = fields.Many2one('account.account', string="Account (company)")
    account_code = fields.Char()
    account_name = fields.Char()
    account_type = fields.Char()
    label = fields.Char(compute='_compute_label')
    balance = fields.Monetary(help="Elimination amount in the group currency (positive = debit).")
    debit = fields.Monetary(compute='_compute_debit_credit')
    credit = fields.Monetary(compute='_compute_debit_credit')

    @api.depends('balance')
    def _compute_debit_credit(self):
        for line in self:
            line.debit = max(line.balance, 0.0)
            line.credit = max(-line.balance, 0.0)

    @api.depends('line_type', 'account_code', 'account_name', 'company_id', 'counterpart_company_id')
    def _compute_label(self):
        labels = dict(LINE_TYPES)
        for line in self:
            if line.account_code:
                line.label = f"{line.account_code} {line.account_name}"
            elif line.line_type == 'difference':
                line.label = _("Cash in transit / FX translation")
            else:
                line.label = labels.get(line.line_type)
