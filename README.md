# Delta Group: intercompany eliminations (Odoo 19)

Group P&L and Balance Sheet in USD for Delta US Inc. (USD), Delta Ukraine LLC (UAH) and Delta Poland sp. z o.o. (PLN),
with intercompany transactions and balances eliminated. Each company's own books stay untouched.

Two independent solutions on the same demo data:

| | Variant 1 (recommended): elimination documents | Variant 2 (alternative): consolidation company |
|---|---|---|
| Module / demo | `delta_elimination_document` / `..._demo` | `delta_elimination_company` / `..._demo` |
| Eliminations kept as | Approved document (number, history, PDF), outside the ledger | Journal entry in a technical company "Delta Group" |
| Group report | Own pivot: companies, eliminations, group total | Standard Enterprise P&L / Balance Sheet |

The shared scenario (`delta_intercompany_demo`) covers January-April 2026: intercompany invoices, a 31 March /
2 April cut-off, a partial credit note, a payment in transit, a USD 200,000 loan, external sales and costs.

## Install and run

Needs Docker and the **Odoo 19.0 Enterprise** source in `enterprise_addons/` (not included).

```bash
docker compose up -d --build
# Variant 1: database "delta_document"
docker compose exec pnl-odoo odoo -d delta_document -i delta_elimination_document_demo --stop-after-init --no-http
# Variant 2: database "delta_company"
docker compose exec pnl-odoo odoo -d delta_company -i delta_elimination_company_demo --stop-after-init --no-http
```

Open http://localhost:8069, pick the database, log in with `admin` / `admin`.

## Run the tests

The server must be running (`docker compose up -d`). Each command creates its own test database, installs the module
with the demo scenario and runs its tests; port 8070 is used because the server already listens on 8069.

```bash
# Variant 1
docker compose exec pnl-odoo odoo -d delta_document_test -i delta_elimination_document \
    --test-tags /delta_elimination_document --stop-after-init --http-port=8070
# Variant 2
docker compose exec pnl-odoo odoo -d delta_company_test -i delta_elimination_company \
    --test-tags /delta_elimination_company --stop-after-init --http-port=8070
```

The last log line gives the result, e.g. `0 failed, 0 error(s) of 13 tests`. To show only the summary, add
`2>&1 | grep -E "FAIL|ERROR|tests"`.

`-i` runs the tests only when it installs the module, i.e. on a new database. To re-run on an existing test database,
use `-u` instead of `-i`; otherwise the result is `of 0 tests`.

The tests check numbers, not screens: group P&L for March and April, each company's own result, eliminated
intercompany balances, the 31 March / 2 April cut-off, the partial credit note, cash in transit and FX, re-running
gives the same result, a balanced group balance sheet (variant 1) and that no entry is ever posted in the member
companies' books.

To start from scratch, drop the test database and run the `-i` command again:
`docker compose exec pnl-db dropdb -U odoo delta_document_test` (or `delta_company_test`).

## Try it: variant 1

1. **Accounting > Accounting > Elimination Documents**: one approved document per month (ELIM/2026/0001-0004).
2. Open **ELIM/2026/0003** (March): lines by company, counterpart and account; debit = credit. **Print** gives the PDF; the chatter shows who computed and approved it.
3. Click **Group Results**: one column per company in USD, an **Eliminations** column and the group total. March net profit 102,023.81.
4. **Balance Sheet** totals zero in every column (assets positive, liabilities and equity negative; a CTA line per company). Receivables are external clients only; intercompany payables and the loan are zero.
5. List view, **Standalone (own currency)**: each company's own figures in UAH / PLN / USD.

## Try it: variant 2

1. In the company switcher, tick all four companies with **Delta Group** active.
2. **Accounting > Reporting > Profit and Loss**, March 2026: net profit 102,023.81.
3. Horizontal group **"Delta Group by company"**: the **Delta Group** column holds the eliminations (−50,000 in March).
4. **Accounting > Accounting > Intercompany Eliminations > Delta Group 2026-03 > Elimination Entry**: the journal entry for the auditor.
5. Select only **Delta Ukraine LLC**: its real books in UAH, untouched.

See [docs/DECISIONS.md](docs/DECISIONS.md) and [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md).
