{
    'name': 'Delta Group - Elimination Documents',
    'version': '19.0.1.0.0',
    'author': 'Maksym Koriahin',
    'category': 'Accounting/Accounting',
    'summary': 'Intercompany eliminations as approved documents (no journal entries) and a group P&L / balance sheet',
    'description': """
Intercompany eliminations kept outside the general ledger.

* A consolidation group lists its member companies and its reporting currency.
* For each month, an elimination document (numbered, approved, printable, with history) lists every
  intercompany amount removed from the group view. Nothing is posted in any company's books.
* The group report (pivot) shows each company translated to the group currency, the eliminations
  and the group total, for a Profit and Loss of the month and a Balance Sheet at month end.
* Part of the Accounting app (menus under Accounting); translation does not rely on the Enterprise report engine.
""",
    'depends': ['accountant'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        'report/elimination_document_report.xml',
        'views/consolidation_group_views.xml',
        'views/elimination_document_views.xml',
        'wizard/group_report_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
