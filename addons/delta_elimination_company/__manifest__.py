{
    'name': 'Delta Group - Eliminations in a Consolidation Company',
    'version': '19.0.1.0.0',
    'author': 'Maksym Koriahin',
    'category': 'Accounting/Accounting',
    'summary': 'Monthly intercompany elimination entries posted in a dedicated consolidation company',
    'description': """
Intercompany eliminations for a multi-company, multi-currency group.

* A consolidation company (e.g. "Delta Group") lists the member companies it consolidates.
* For each month, one elimination journal entry is posted in the consolidation company only,
  so every member's standard Profit and Loss keeps showing its real books.
* Amounts are translated with the same CTA currency table as the standard Enterprise reports,
  so intercompany lines net to zero in the group Profit and Loss / Balance Sheet.
* Group view = standard reports with the consolidation company and its members selected;
  a "by company" horizontal group shows each company next to the eliminations.
""",
    'depends': ['accountant'],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'views/res_company_views.xml',
        'views/elimination_period_views.xml',
        'views/account_move_views.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
