"""Delta Group demo scenario.

All figures live in the constants below so tests can derive expected group
numbers from the same source. Rates change on the 1st of each month only, so
a month's average rate equals its spot rate.
"""
from odoo import Command, fields

# Units of currency per 1 USD, effective from the given date.
RATES = {
    'UAH': {'2026-01-01': 40.0, '2026-02-01': 41.0, '2026-03-01': 42.0, '2026-04-01': 43.0},
    'PLN': {'2026-01-01': 4.0, '2026-02-01': 4.1, '2026-03-01': 4.2, '2026-04-01': 4.0},
}

MONTH_ENDS = ['2026-01-31', '2026-02-28', '2026-03-31', '2026-04-30']

# Intercompany invoices in USD: (seller invoice date, buyer accounting date, amount)
UA_TO_US = [
    ('2026-01-31', '2026-01-31', 40000.0),
    ('2026-02-28', '2026-02-28', 45000.0),
    ('2026-03-31', '2026-04-02', 50000.0),  # booked by Delta US on 2 April
]
PL_TO_US = [
    ('2026-01-31', '2026-01-31', 20000.0),
    ('2026-02-28', '2026-02-28', 22000.0),
    ('2026-03-31', '2026-03-31', 25000.0),
]
PL_CREDIT_NOTE = ('2026-03-15', 5000.0)  # partial credit note on the February invoice
US_PAYMENT_TO_PL = ('2026-03-31', '2026-04-01', 20000.0)  # pays the January invoice
US_LOAN_TO_UA = ('2026-01-15', 200000.0)

# External activity per month (Jan-Apr), in each company's own currency.
EXTERNAL = {
    'us': {'sales': 170000.0, 'payroll': 60000.0, 'rent': 10000.0},
    'ua': {'sales': 400000.0, 'payroll': 1500000.0, 'rent': 120000.0},
    'pl': {'sales': 300000.0, 'payroll': 150000.0, 'rent': 20000.0},
}

COMPANIES = {
    'us': ('Delta US Inc.', 'USD', 'base.us', 'Acme Corp'),
    'ua': ('Delta Ukraine LLC', 'UAH', 'base.ua', 'Kyiv Retail LLC'),
    'pl': ('Delta Poland sp. z o.o.', 'PLN', 'base.pl', 'Warsaw Design SA'),
}

IC_LOAN_RECEIVABLE = ('191500', 'Intercompany Loans Receivable', 'asset_non_current')
IC_LOAN_PAYABLE = ('291500', 'Intercompany Loans Payable', 'liability_non_current')


def build(env, suffix='', us_company=None):
    """Create the whole scenario and return a dict with the companies.

    :param suffix: appended to company names so tests can build a fresh copy
                   next to an installed demo (company names are unique).
    :param us_company: existing company to turn into Delta US Inc. (the demo uses the
                       database's main company); a new company is created when empty.
    """
    _ensure_rates(env)
    companies = {key: _setup_company(env, key, suffix, us_company if key == 'us' else None) for key in COMPANIES}
    clients = {
        key: env['res.partner'].create({'name': COMPANIES[key][3] + suffix, 'company_id': companies[key].id})
        for key in COMPANIES
    }
    us, ua, pl = companies['us'], companies['ua'], companies['pl']
    usd = env.ref('base.USD')

    loan_receivable = _create_account(env, us, *IC_LOAN_RECEIVABLE)
    loan_payable = _create_account(env, ua, *IC_LOAN_PAYABLE)

    # Loan Delta US -> Delta Ukraine
    loan_date, loan_amount = US_LOAN_TO_UA
    _entry(env, us, 'bank', loan_date, 'Loan to Delta Ukraine', [
        (loan_receivable, loan_amount, ua.partner_id, None),
        (_bank_account(env, us), -loan_amount, None, None),
    ])
    _entry(env, ua, 'bank', loan_date, 'Loan from Delta US', [
        (_bank_account(env, ua), loan_amount, None, usd),
        (loan_payable, -loan_amount, us.partner_id, usd),
    ])

    # Ukraine -> US
    for seller_date, buyer_date, amount in UA_TO_US:
        _invoice(env, ua, 'out_invoice', us.partner_id, seller_date, seller_date, amount, usd, 'income',
                 'Engineering services')
        _invoice(env, us, 'in_invoice', ua.partner_id, seller_date, buyer_date, amount, usd, 'expense',
                 'Engineering services - Delta Ukraine')

    # Poland -> US
    pl_invoices, us_bills = [], []
    for seller_date, buyer_date, amount in PL_TO_US:
        pl_invoices.append(_invoice(env, pl, 'out_invoice', us.partner_id, seller_date, seller_date, amount,
                                    usd, 'income', 'Design services'))
        us_bills.append(_invoice(env, us, 'in_invoice', pl.partner_id, seller_date, buyer_date, amount, usd,
                                 'expense', 'Design services - Delta Poland'))

    cn_date, cn_amount = PL_CREDIT_NOTE
    _invoice(env, pl, 'out_refund', us.partner_id, cn_date, cn_date, cn_amount, usd, 'income',
             'Partial credit - February design services', reversed_entry=pl_invoices[1])
    _invoice(env, us, 'in_refund', pl.partner_id, cn_date, cn_date, cn_amount, usd, 'expense',
             'Partial credit - February design services', reversed_entry=us_bills[1])

    # Payment Delta US -> Delta Poland for the January invoice (cash in transit over month end)
    us_pay_date, pl_pay_date, pay_amount = US_PAYMENT_TO_PL
    us_payment = _entry(env, us, 'bank', us_pay_date, 'Payment to Delta Poland - January invoice', [
        (_account(env, us, 'payable'), pay_amount, pl.partner_id, None),
        (_bank_account(env, us), -pay_amount, None, None),
    ])
    _reconcile(us_payment, us_bills[0], 'liability_payable')
    pl_receipt = _entry(env, pl, 'bank', pl_pay_date, 'Receipt from Delta US - January invoice', [
        (_bank_account(env, pl), pay_amount, None, usd),
        (_account(env, pl, 'receivable'), -pay_amount, us.partner_id, usd),
    ])
    _reconcile(pl_receipt, pl_invoices[0], 'asset_receivable')

    # External activity
    for month_end in MONTH_ENDS:
        sale_date = month_end[:8] + '20'
        for key, company in companies.items():
            figures = EXTERNAL[key]
            _invoice(env, company, 'out_invoice', clients[key], sale_date, sale_date, figures['sales'],
                     company.currency_id, 'income', 'Services to external client')
            _entry(env, company, 'general', month_end, 'Payroll', [
                (_account(env, company, 'expense_salary'), figures['payroll'], None, None),
                (_account(env, company, 'salary_payable'), -figures['payroll'], None, None),
            ])
            _entry(env, company, 'bank', month_end, 'Office rent', [
                (_account(env, company, 'expense_rent'), figures['rent'], None, None),
                (_bank_account(env, company), -figures['rent'], None, None),
            ])
    return companies


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_rates(env):
    Rate = env['res.currency.rate']
    for code, rates in RATES.items():
        currency = env.ref(f'base.{code}')
        currency.active = True
        for date, rate in rates.items():
            if not Rate.search([('currency_id', '=', currency.id), ('name', '=', date), ('company_id', '=', False)]):
                Rate.create({'currency_id': currency.id, 'name': date, 'rate': rate, 'company_id': False})


def _setup_company(env, key, suffix, company=None):
    """Create the company (or rename and configure ``company``) with the generic chart of accounts."""
    name, currency_code, country_ref, _client = COMPANIES[key]
    vals = {
        'name': name + suffix,
        'currency_id': env.ref(f'base.{currency_code}').id,
        'country_id': env.ref(country_ref).id,
    }
    if company:
        company.write(vals)
    else:
        company = env['res.company'].create(vals)
    env.user.company_ids |= company
    admin = env.ref('base.user_admin', raise_if_not_found=False)
    if admin:
        admin.company_ids |= company
    if company.chart_template != 'generic_coa':
        env['account.chart.template'].try_loading('generic_coa', company=company, install_demo=False)
    # Loading the generic chart resets the currency to the template country's (USD): restore it.
    # Demo data is tax-free: no default taxes on invoice lines.
    company.write({
        'currency_id': env.ref(f'base.{currency_code}').id,
        'account_sale_tax_id': False,
        'account_purchase_tax_id': False,
    })
    return company


def _account(env, company, template_xmlid):
    """Account of ``company`` created from the generic chart template record ``template_xmlid``."""
    return env['account.chart.template'].with_company(company).ref(template_xmlid)


def _create_account(env, company, code, name, account_type):
    return env['account.account'].with_company(company).create({
        'code': code,
        'name': name,
        'account_type': account_type,
        'company_ids': [Command.set(company.ids)],
    })


def _journal(env, company, journal_type):
    return env['account.journal'].search([
        *env['account.journal']._check_company_domain(company),
        ('type', '=', journal_type),
    ], limit=1)


def _bank_account(env, company):
    return _journal(env, company, 'bank').default_account_id


def _invoice(env, company, move_type, partner, invoice_date, accounting_date, amount, currency, account_xmlid,
             label, reversed_entry=None):
    journal_type = 'sale' if move_type in ('out_invoice', 'out_refund') else 'purchase'
    move = env['account.move'].with_company(company).create({
        'move_type': move_type,
        'partner_id': partner.id,
        'journal_id': _journal(env, company, journal_type).id,
        'invoice_date': invoice_date,
        'date': accounting_date,
        'currency_id': currency.id,
        'reversed_entry_id': reversed_entry.id if reversed_entry else False,
        'invoice_line_ids': [Command.create({
            'name': label,
            'quantity': 1.0,
            'price_unit': amount,
            'account_id': _account(env, company, account_xmlid).id,
            'tax_ids': [Command.clear()],
        })],
    })
    move.action_post()
    return move


def _entry(env, company, journal_type, date, ref, lines):
    """Post a journal entry. ``lines`` is a list of (account, amount, partner, currency) where
    ``amount`` is expressed in ``currency`` (company currency when None)."""
    company_currency = company.currency_id
    line_vals = []
    for account, amount, partner, currency in lines:
        currency = currency or company_currency
        balance = currency._convert(amount, company_currency, company, fields.Date.to_date(date))
        line_vals.append(Command.create({
            'name': ref,
            'account_id': account.id,
            'partner_id': partner.id if partner else False,
            'currency_id': currency.id,
            'amount_currency': amount,
            'balance': balance,
        }))
    move = env['account.move'].with_company(company).create({
        'move_type': 'entry',
        'journal_id': _journal(env, company, journal_type).id,
        'date': date,
        'ref': ref,
        'line_ids': line_vals,
    })
    move.action_post()
    return move


def _reconcile(move_a, move_b, account_type):
    lines = (move_a.line_ids | move_b.line_ids).filtered(
        lambda line: line.account_id.account_type == account_type and not line.reconciled)
    lines.reconcile()
