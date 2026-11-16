# Assumptions

## Setup
- Odoo 19.0 Enterprise with the Accounting app (`accountant`).
- Delta US Inc. is the parent and the database's main company; the group reports in USD.
- All companies use the same generic chart of accounts, so accounts match by code.
- Fiscal year = calendar 2026, no year-end closing; no VAT.

## Eliminations
- An intercompany item is a posted line whose partner is another group company.
- Eliminations are done per month, and the group is read per month.
- Not eliminated: realised FX (a real group gain or loss), cash, equity and share capital (no investments in the demo).
- What does not match between two companies (cash in transit, FX) goes to one "elimination difference" per pair.
- Variant 1: only approved documents count in the group report; managers approve.
- Variant 2: "Delta Group" is a technical company, not a legal entity; nobody works in it except to run eliminations.

## Currency translation
- P&L at the month's average rate, assets and liabilities at the month-end rate, equity at historical rates.
- The resulting translation difference (CTA) is never posted. Variant 1 shows it as a line per company.
  Variant 2 uses the standard Balance Sheet, which has no CTA line, so the group balance sheet is off by the CTA
  (USD 4,921.88 at 31 March). This comes from translating Ukraine and Poland, not from the eliminations.

## Demo data
- Rates change on the 1st only: UAH 40 / 41 / 42 / 43 and PLN 4.0 / 4.1 / 4.2 / 4.0 per USD, January-April 2026.
- Same external activity every month: sales on the 20th, payroll and rent at month end (payroll as a journal entry).
- Intercompany invoices are services with no margin.
- Loan USD 200,000 from Delta US to Ukraine: no interest, not repaid.
- Delta US pays Poland's January invoice (USD 20,000) on 31 March; Poland receives it on 1 April.
- Credit note USD 5,000 on Poland's February invoice, 15 March; Odoo's automatic reconciliation leaves 500 PLN realised FX in Poland.
- Payments are bank entries reconciled with invoices, no bank statements.
