# PnL Task: Delta Group consolidation (Odoo)

## Project
An Odoo module for Delta Group, three companies in one database:
- Delta US Inc. (USD, parent; the group reports in USD)
- Delta Ukraine LLC (UAH)
- Delta Poland sp. z o.o. (PLN)

The module eliminates intercompany transactions and balances and produces a consolidated P&L and Balance Sheet in USD for a chosen month, next to each company's own results.

Full spec: `.claude/spec/eliminations_spec.md`.

## Stack
- Odoo **19.0** (`odoo:19.0` image) + **Enterprise** addons
- PostgreSQL 17
- docker compose: services `pnl-db` and `pnl-odoo`, at http://localhost:8069

## Layout
- `addons/`: custom modules, mounted at `/mnt/extra-addons`
- `enterprise_addons/`: Odoo Enterprise 19.0 source, mounted at `/mnt/enterprise_addons`. **Git-ignored; never commit or publish it.**
- `config/odoo.conf`: `addons_path`, DB connection, `http_interface = 0.0.0.0`
- `.claude/spec/`: task spec (`eliminations_spec.md`)
- `docs/`: decision note (`DECISIONS.md`) and assumptions (`ASSUMPTIONS.md`); `README.md` has install steps and controller steps

## Modules (`addons/`)
- `delta_intercompany_demo`: shared demo scenario (`scenario.build(env, suffix)`), independent of the elimination method; constants are the single source for test expectations.
- `delta_elimination_document`: variant 1 (recommended). `delta.consolidation.group` + monthly `delta.elimination.document` (Compute/Approve, mail.thread, PDF), nothing posted in any ledger; own pivot report `delta.group.report` (transient) with CTA per company. Depends on `accountant` (Accounting app) like variant 2; translation is its own code (no account_reports currency table). Each document is self-contained (carries earlier months' IC result in equity).
- `delta_elimination_document_demo`: one-command demo for variant 1.
- `delta_elimination_company`: variant 2 (alternative on standard Enterprise reports). Consolidation company "Delta Group" holds one elimination entry per month (`delta.elimination.period`). Translation reuses the Enterprise CTA currency table (`res.currency._create_currency_table` + `account.report._currency_table_aml_join`), so IC lines net to zero in monthly reports.
- `delta_elimination_company_demo`: one-command demo for variant 2 (scenario + "Delta Group" + Jan-Apr runs).
- Variants 1 and 2 never depend on each other; both demos can share one DB. Both must give identical group figures on the scenario.

## Commands
```bash
docker compose up -d --build                    # start / rebuild
docker compose logs -f pnl-odoo                 # logs
docker compose exec pnl-odoo odoo -d <db> -i <module> --stop-after-init --no-http   # install (-u to update)
docker compose exec pnl-odoo odoo -d delta_document -i delta_elimination_document_demo --stop-after-init --no-http   # demo DB variant 1
docker compose exec pnl-odoo odoo -d delta_company -i delta_elimination_company_demo --stop-after-init --no-http   # demo DB variant 2
docker compose exec pnl-odoo odoo -d delta_document_test -i delta_elimination_document --test-tags /delta_elimination_document --stop-after-init --http-port=8070  # tests v1
docker compose exec pnl-odoo odoo -d delta_company_test -i delta_elimination_company --test-tags /delta_elimination_company --stop-after-init --http-port=8070  # tests v2
```

## Key constraints (from the spec)
- A company's standard P&L must always show its real books, so never post eliminations in a member company's books.
- Eliminations must exist as an entry the auditor can open.
- Tests must assert numbers, not screens.
- Demo data must load with one command.

## Gotchas
- A DB created under a different Odoo major version can't be opened. Drop or recreate it.
- Odoo must listen on `0.0.0.0` inside the container (set in `config/odoo.conf`), otherwise localhost:8069 is unreachable.
- The Accounting app (menus under "Accounting", not "Invoicing") is the Enterprise module `accountant`, not `account_accountant`; depend on it.
- Tests start an HTTP server even with `--no-http`: use `--http-port=8070` while the main server runs.
- `-i` on a test DB where the module is already installed runs 0 tests: use `-u` (or drop the test DB).
- Generic chart codes are 6 digits (4000 -> 400000) and `account.account.code` is company-dependent: read it with `with_company(...)`; prefer `account.chart.template.with_company(c).ref('income')`.
- Loading `generic_coa` resets the company currency to USD: write the real currency back right after `try_loading`.
- Odoo auto-reconciles a credit note with its reversed invoice; in a foreign currency this creates a realised FX entry.
