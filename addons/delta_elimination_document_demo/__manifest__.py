{
    'name': 'Delta Group - Elimination Documents Demo',
    'version': '19.0.1.0.0',
    'author': 'Maksym Koriahin',
    'category': 'Accounting/Accounting',
    'summary': 'Loads the Delta Group scenario, creates the consolidation group and approves January-April documents',
    'depends': ['delta_elimination_document', 'delta_intercompany_demo'],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'license': 'LGPL-3',
}
