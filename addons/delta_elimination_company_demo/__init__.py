from odoo.addons.delta_intercompany_demo.scenario import COMPANIES, MONTH_ENDS

CONSOLIDATION_COMPANY_NAME = 'Delta Group'


def post_init_hook(env):
    members = env['res.company'].search([('name', 'in', [name for name, *_rest in COMPANIES.values()])])
    group = env['res.company']._delta_create_consolidation_company(CONSOLIDATION_COMPANY_NAME, members)
    periods = env['delta.elimination.period'].create([
        {'company_id': group.id, 'date_from': month_end[:8] + '01'} for month_end in MONTH_ENDS
    ])
    periods.action_run()
