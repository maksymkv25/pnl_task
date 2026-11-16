from odoo import Command
from odoo.addons.delta_intercompany_demo.scenario import COMPANIES, MONTH_ENDS

GROUP_NAME = 'Delta Group'


def post_init_hook(env):
    members = env['res.company'].search([('name', 'in', [name for name, *_rest in COMPANIES.values()])])
    group = env['delta.consolidation.group'].create({
        'name': GROUP_NAME,
        'currency_id': env.ref('base.USD').id,
        'member_company_ids': [Command.set(members.ids)],
    })
    documents = env['delta.elimination.document'].create([
        {'group_id': group.id, 'date_from': month_end[:8] + '01'} for month_end in MONTH_ENDS
    ])
    documents.action_compute()
    documents.action_confirm()
