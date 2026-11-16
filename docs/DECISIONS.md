# Decisions

## The main rule
A company's own P&L must show its real books, and the auditor must be able to open the eliminations.
So **nothing is ever posted in the books of Delta US, Delta Ukraine or Delta Poland**.

## How eliminations work (both variants)
- Each month, intercompany income and costs of that month are reversed, and intercompany receivables, payables and
  loans at month end are reversed.
- Amounts are translated to USD (see ASSUMPTIONS); what still does not match between two companies (cash in transit,
  FX) goes to one elimination difference per pair.
- A cut-off (Ukraine invoices on 31 March, Delta US books it on 2 April) needs no special handling: each side is
  eliminated in its own month.

## Variant 1 (recommended): elimination documents
- One document per month: **Compute**, then **Approve**; numbered, locked once approved, with history and PDF.
- Each document is complete on its own, so months can be computed in any order.
- The group report is the module's own pivot, one month at a time, and the balance sheet balances (CTA per company).
- Why: no ledger is touched and no extra company is needed; an approved document is what an auditor expects.

## Variant 2 (alternative): consolidation company
- A technical company "Delta Group" (not a branch: branches roll into the parent's reports) gets one elimination
  journal entry per month (**Run Eliminations**; re-running gives the same entry).
- The group is read in the standard Enterprise P&L and Balance Sheet with all four companies selected.
- Why: standard reports with drill-down to journal entries.
- Limits: exact only month by month (a multi-month report leaves small residuals), and the standard Balance Sheet
  has no CTA line, so the group balance sheet does not balance.

## Rejected
- Eliminations only inside a report: nothing for the auditor to open or approve.
- Elimination journal in Delta US: its own P&L would include the eliminations.
- Automatic mirror entries on every intercompany invoice: break on cut-off, credit notes and FX.
- Enterprise Consolidation app: not available in Odoo 19.
