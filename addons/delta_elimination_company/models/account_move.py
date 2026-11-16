from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    delta_elimination_period_id = fields.Many2one(
        'delta.elimination.period', string="Elimination Period", readonly=True, index='btree_not_null', copy=False)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    delta_elim_company_id = fields.Many2one(
        'res.company', string="Eliminated Company", readonly=True, index='btree_not_null',
        help="Member company whose intercompany balance this elimination line removes.")
    delta_counterpart_company_id = fields.Many2one(
        'res.company', string="Counterpart Company", readonly=True,
        help="The other group company of the intercompany relationship.")
