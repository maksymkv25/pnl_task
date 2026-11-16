{
    'name': 'Delta Group - Consolidation Company Demo',
    'version': '19.0.1.0.0',
    'author': 'Maksym Koriahin',
    'category': 'Accounting/Accounting',
    'summary': 'Loads the Delta Group scenario, creates the "Delta Group" consolidation company and runs January-April',
    'depends': ['delta_elimination_company', 'delta_intercompany_demo'],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'license': 'LGPL-3',
}
