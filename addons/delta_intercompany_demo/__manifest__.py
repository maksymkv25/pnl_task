{
    'name': 'Delta Group - Intercompany Demo Scenario',
    'version': '19.0.1.0.0',
    'author': 'Maksym Koriahin',
    'category': 'Accounting/Accounting',
    'summary': 'Three Delta Group companies with intercompany and external activity, January-April 2026',
    'description': """
Builds the Delta Group demo scenario used by the consolidation modules:

* Delta US Inc. (USD), Delta Ukraine LLC (UAH), Delta Poland sp. z o.o. (PLN)
* UAH / PLN rates against USD (one rate per month)
* Monthly Ukraine -> US and Poland -> US invoices (January-March)
* Ukraine March invoice dated 31 March, booked by Delta US on 2 April
* Partial credit note on the February Poland -> US invoice
* Delta US payment to Delta Poland on 31 March, recorded by Poland on 1 April
* USD 200,000 loan from Delta US to Delta Ukraine on 15 January
* External sales, payroll and rent for each company

The scenario is independent of the elimination method, so every consolidation
variant can reuse it (see ``scenario.build``).
""",
    'depends': ['account'],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'license': 'LGPL-3',
}
