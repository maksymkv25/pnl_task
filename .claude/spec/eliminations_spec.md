# Technical Task: Delta Group Intercompany Eliminations & Consolidated Reporting (Odoo)

> Source: `2026-11-11 - TechnicalTask - Odoo Engineer.pdf` (Miratech, Finance System Programme, Nov 2026).
> The scenario is fictional and uses no Miratech data. Questions go to the recruiter who sent the task.

---

## 1. Business context

Delta Group has three companies. Each keeps its own books in its own currency, and all three work in **one Odoo database**.

| Company | Currency | Role |
|---|---|---|
| **Delta US Inc.** | USD | Parent company. Sells to clients in the US. **The group reports in USD.** Payroll in USD. |
| **Delta Ukraine LLC** | UAH | Delivers engineering for Delta US client projects and **invoices Delta US monthly in USD**. Payroll in UAH. Received a **USD 200,000 loan from Delta US on 15 January**. |
| **Delta Poland sp. z o.o.** | PLN | Sells to its own clients in Poland. Also delivers design work for Delta US and **invoices Delta US monthly in USD**. Payroll in PLN. |

### 1.1 Intercompany (IC) relationships

| # | Direction | Type | Currency |
|---|---|---|---|
| IC-1 | Delta Ukraine → Delta US | Monthly service invoices | USD |
| IC-2 | Delta Poland → Delta US | Monthly service invoices | USD |
| IC-3 | Delta US → Delta Ukraine | Loan of USD 200,000, 15 January | USD |

There are two intercompany invoicing directions: **Ukraine → US** and **Poland → US**.

---

## 2. Business requirements

| ID | Requirement |
|---|---|
| BR-1 | **Standalone books** for each company, in its own currency. |
| BR-2 | **Group results in USD**, as if the group were one company: what the group earned from **outside clients**, and what it owns and owes to the **outside world**. |
| BR-3 | The **standard Profit and Loss must always show a company's real books**. Eliminations must not distort any company's own P&L. |
| BR-4 | The **auditor wants an elimination entry they can open**, so eliminations must exist as auditable records. |

---

## 3. Functional requirements

### FR-1. Eliminations (core of the task)
- The module removes **transactions and balances between group companies** from the group view.
- **How and when** eliminations are created is up to the candidate (see §5).
- Eliminations must produce an **entry the auditor can open** (BR-4) and must **not change the standard P&L** of any company (BR-3).

### FR-2. Standalone and group results
- A **consolidated Profit and Loss** and **Balance Sheet** for a **chosen month**,
- shown **alongside each company's own results**.
- Accepted formats: **a report, a pivot view or an export**.

### FR-3. Demo data
- Must prove that the module works (no real data is available).
- Someone else must be able to **load it with one command**.
- Minimum content:

| # | Data | Details |
|---|---|---|
| D-1 | IC invoices Ukraine → US | Monthly, **January–March**. |
| D-2 | IC invoices Poland → US | Monthly, **January–March**. |
| D-3 | Cut-off case (Ukraine March invoice) | **USD 50,000**, dated **31 March** by Delta Ukraine and **booked by Delta US on 2 April**. |
| D-4 | Partial credit note | On **one Poland → US invoice**. |
| D-5 | Payment in transit | Delta US pays Delta Poland on **31 March**; Delta Poland records it on **1 April**. |
| D-6 | External activity | **External sales and costs for each of the three companies.** |
| D-7 | IC loan *(from the business context)* | USD 200,000 from Delta US to Delta Ukraine on 15 January. |

### FR-4. Automated tests
- Automated tests that **prove the numbers, not just the screens**.

---

## 4. Edge cases the solution must handle

These come from the demo-data requirements and the business context.

| Case | Where it appears | Why it matters |
|---|---|---|
| Cut-off / timing difference on an invoice | D-3: 31 Mar (UA) vs 2 Apr (US) | At 31 March one side of the IC pair exists and the other does not. |
| Cash in transit | D-5: 31 Mar (US) vs 1 Apr (PL) | The IC payable and receivable do not match at month end. |
| Partial credit note | D-4 | IC revenue and expense must be eliminated net of the credit note. |
| Multi-currency | UA books in UAH, PL books in PLN, IC documents in USD, group in USD | Translation to USD and FX differences on IC balances. |
| IC loan (balance sheet only) | D-7 | IC balances must be eliminated, not only P&L items. |

---

## 5. Open design decisions (to decide and document)

The task leaves these to the candidate. Each decision must be documented.

- **Where** eliminations are recorded, given BR-3 and BR-4.
- **How** they are created: which transactions and balances count as IC, and how they are matched.
- **When** they are created: manually, per period, automatically, and so on.
- Currency translation method for the group view in USD.
- How timing and FX differences between IC counterparts are treated.
- Report format: report, pivot or export.
- Anything else the task does not specify must be stated as an assumption.

---

## 6. Acceptance criteria

### Module and installation
- [ ] The module installs on a clean database.
- [ ] Demo data loads with **one command**.

### Eliminations (FR-1)
- [ ] Group results exclude IC revenue and IC expenses (Ukraine → US, Poland → US).
- [ ] Group results exclude IC receivables, payables and the IC loan.
- [ ] Eliminations exist as an **entry the auditor can open**.
- [ ] Each company's **standard P&L is unchanged** by eliminations.
- [ ] The cut-off case (D-3), cash in transit (D-5) and partial credit note (D-4) are handled correctly.

### Reporting (FR-2)
- [ ] A consolidated P&L and Balance Sheet in **USD** for a **chosen month**.
- [ ] Each company's own results are shown alongside the group figures.

### Demo data (FR-3)
- [ ] D-1 to D-6 are all present (D-7 recommended, per the business context).

### Tests (FR-4)
- [ ] Automated tests assert the **numbers**, for example group totals, eliminated amounts and balancing.

---


## 7. Project environment (our context, not part of the source task)

| Item | Value |
|---|---|
| Odoo | **19.0** (`odoo:19.0` docker image) + **Enterprise** addons |
| Enterprise source | `enterprise_addons/` (branch 19.0), mounted at `/mnt/enterprise_addons`, **git-ignored** (must not be published) |
| Database | PostgreSQL 17, service `pnl-db` |
| Odoo service | `pnl-odoo`, http://localhost:8069 |
| Config | `config/odoo.conf` (`addons_path = /mnt/extra-addons,/mnt/enterprise_addons`) |
| Start | `docker compose up -d --build` |

> Note: the reviewers need their own Odoo 19 Enterprise source to install a module that depends on Enterprise.
