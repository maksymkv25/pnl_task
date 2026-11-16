from collections import defaultdict

from odoo.tests import TransactionCase, tagged

from odoo.addons.delta_intercompany_demo import scenario as sc

# Monthly rates, units per USD (rates only change on the 1st, so month average == spot).
UAH = {1: 40.0, 2: 41.0, 3: 42.0, 4: 43.0}
PLN = {1: 4.0, 2: 4.1, 3: 4.2, 4: 4.0}


@tagged('post_install', '-at_install')
class TestDeltaEliminations(TransactionCase):
    """Proves the group numbers on the Delta Group scenario (delta_intercompany_demo.scenario).

    The expected figures below are derived by hand from the scenario constants and rates.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        companies = sc.build(cls.env, suffix=' (test)')
        cls.us, cls.ua, cls.pl = companies['us'], companies['ua'], companies['pl']
        cls.members = cls.us | cls.ua | cls.pl
        cls.group = cls.env['res.company']._delta_create_consolidation_company('Delta Group (test)', cls.members)
        cls.periods = cls.env['delta.elimination.period'].create([
            {'company_id': cls.group.id, 'date_from': f'2026-0{month}-01'} for month in (1, 2, 3, 4)
        ])
        cls.periods.action_run()
        cls.period = {p.date_from.month: p for p in cls.periods}

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _report_value(self, companies, date_from, date_to, code, report_ref='account_reports.profit_and_loss'):
        """Value of the report line ``code`` in the standard Enterprise report for ``companies``
        (the first company is the main one and gives the reporting currency)."""
        report = self.env.ref(report_ref).with_context(allowed_company_ids=companies.ids)
        options = report.get_options({
            'selected_variant_id': report.id,
            'date': {'date_from': date_from, 'date_to': date_to, 'mode': 'range', 'filter': 'custom'},
        })
        line_id = report._get_generic_line_id('account.report.line', report.line_ids.filtered(lambda l: l.code == code).id)
        line = next(line for line in report._get_lines(options) if line['id'] == line_id)
        return line['columns'][0]['no_format']

    def _difference_by_pair(self, up_to_month):
        """Cumulative balance of the elimination difference account per company pair."""
        lines = self.env['account.move.line'].search([
            ('company_id', '=', self.group.id),
            ('account_id', '=', self.group.delta_difference_account_id.id),
            ('parent_state', '=', 'posted'),
            ('date', '<=', self.period[up_to_month].date_to),
        ])
        result = defaultdict(float)
        for line in lines:
            result[frozenset((line.delta_elim_company_id, line.delta_counterpart_company_id))] += line.balance
        return result

    def _elimination_line(self, month, member, counterpart, account_xmlid):
        account = self.env['account.chart.template'].with_company(member).ref(account_xmlid)
        lines = self.period[month].move_id.line_ids.filtered(
            lambda l: l.delta_elim_company_id == member and l.delta_counterpart_company_id == counterpart
            and l.account_id.with_company(self.group).code == account.with_company(member).code)
        return sum(lines.mapped('balance'))

    # -------------------------------------------------------------------------
    # Standalone books stay real
    # -------------------------------------------------------------------------

    def test_standalone_pnl_unchanged(self):
        """BR-3: each company's standard P&L shows its real books, in its own currency."""
        # US March: sales 170,000 - payroll 60,000 - rent 10,000 - Poland design (25,000 - 5,000 credit note)
        self.assertAlmostEqual(self._report_value(self.us, '2026-03-01', '2026-03-31', 'NEP'), 80000.0, places=2)
        # Ukraine March, UAH: 400,000 sales + 50,000 x 42 IC - 1,500,000 payroll - 120,000 rent
        self.assertAlmostEqual(self._report_value(self.ua, '2026-03-01', '2026-03-31', 'NEP'), 880000.0, places=2)
        # Poland March, PLN: 300,000 sales + 25,000 x 4.2 IC - 5,000 x 4.2 credit note
        # + 500 realised FX gain (credit note reconciled with the February invoice at 4.1) - 150,000 - 20,000
        self.assertAlmostEqual(self._report_value(self.pl, '2026-03-01', '2026-03-31', 'NEP'), 214500.0, places=2)

    def test_eliminations_only_in_consolidation_company(self):
        """BR-3 / BR-4: elimination entries are posted, balanced and live in the consolidation company only."""
        moves = self.periods.move_id
        self.assertEqual(len(moves), 4)
        for move in moves:
            self.assertEqual(move.state, 'posted')
            self.assertEqual(move.company_id, self.group)
            self.assertEqual(move.journal_id, self.group.delta_elimination_journal_id)
            self.assertAlmostEqual(sum(move.line_ids.mapped('balance')), 0.0, places=2)
        self.assertFalse(self.env['account.move'].search_count([
            ('company_id', 'in', self.members.ids),
            ('delta_elimination_period_id', '!=', False),
        ]))

    # -------------------------------------------------------------------------
    # Group P&L
    # -------------------------------------------------------------------------

    def test_group_pnl_march(self):
        """Group March P&L = external activity only, translated to USD."""
        group_view = self.group | self.members
        external_sales = 170000.0 + 400000.0 / UAH[3] + 300000.0 / PLN[3]
        realised_fx_gain = 500.0 / PLN[3]
        costs = (60000.0 + 10000.0) + (1500000.0 + 120000.0) / UAH[3] + (150000.0 + 20000.0) / PLN[3]
        self.assertAlmostEqual(
            self._report_value(group_view, '2026-03-01', '2026-03-31', 'REV'), external_sales + realised_fx_gain, places=2)
        self.assertAlmostEqual(
            self._report_value(group_view, '2026-03-01', '2026-03-31', 'NEP'),
            external_sales + realised_fx_gain - costs, places=2)  # 102,023.81

    def test_group_pnl_april(self):
        """April: Delta US books Ukraine's March invoice (2 April); the group P&L still shows no intercompany cost."""
        group_view = self.group | self.members
        external = (170000.0 - 60000.0 - 10000.0) + (400000.0 - 1500000.0 - 120000.0) / UAH[4] \
            + (300000.0 - 150000.0 - 20000.0) / PLN[4]
        self.assertAlmostEqual(self._report_value(group_view, '2026-04-01', '2026-04-30', 'NEP'), external, places=2)

    def test_eliminations_change_group_result_only_by_intercompany_margin(self):
        """March: the sum of the standalone results minus the group result = Ukraine's unmatched IC revenue."""
        standalone = self._report_value(self.members, '2026-03-01', '2026-03-31', 'NEP')
        group = self._report_value(self.group | self.members, '2026-03-01', '2026-03-31', 'NEP')
        self.assertAlmostEqual(standalone - group, 50000.0, places=2)

    # -------------------------------------------------------------------------
    # Intercompany balances are fully eliminated
    # -------------------------------------------------------------------------

    def test_intercompany_accounts_net_to_zero(self):
        """After each month's entry, IC P&L movements of the month and IC balances at month end are zero."""
        for month, period in self.period.items():
            remaining = defaultdict(float)
            for member_id, account_id, _partner, is_pnl, translated in period._query_intercompany_balances():
                member = self.env['res.company'].browse(member_id)
                code = self.env['account.account'].browse(account_id).with_company(member).code
                remaining[member, code, is_pnl] += translated
            domain = [('company_id', '=', self.group.id), ('parent_state', '=', 'posted'),
                      ('delta_elim_company_id', '!=', False),
                      ('account_id', '!=', self.group.delta_difference_account_id.id)]
            for line in self.env['account.move.line'].search(domain + [('date', '<=', period.date_to)]):
                is_pnl = line.account_id.internal_group in ('income', 'expense')
                if is_pnl and line.date < period.date_from:
                    continue
                remaining[line.delta_elim_company_id, line.account_id.with_company(self.group).code, is_pnl] += line.balance
            for key, amount in remaining.items():
                self.assertAlmostEqual(amount, 0.0, places=2, msg=f"{period.name}: {key} not eliminated")

    def test_loan_eliminated(self):
        """The USD 200,000 loan disappears from the group balance sheet (closing rate for Ukraine's side)."""
        def loan_eliminations(member, account_type, month):
            return sum(self.periods.move_id.line_ids.filtered(
                lambda l: l.delta_elim_company_id == member and l.account_id.account_type == account_type
                and l.date <= self.period[month].date_to).mapped('balance'))
        self.assertAlmostEqual(loan_eliminations(self.us, 'asset_non_current', 3), -200000.0, places=2)
        self.assertAlmostEqual(loan_eliminations(self.ua, 'liability_non_current', 3),
                               200000.0 * UAH[1] / UAH[3], places=2)

    # -------------------------------------------------------------------------
    # Cut-off, credit note, cash in transit
    # -------------------------------------------------------------------------

    def test_cutoff_ukraine_march_invoice(self):
        """Dated 31 March by Ukraine, booked 2 April by Delta US: revenue eliminated in March, cost in April."""
        self.assertAlmostEqual(self._elimination_line(3, self.ua, self.us, 'income'), 50000.0, places=2)
        self.assertAlmostEqual(self._elimination_line(3, self.us, self.ua, 'expense'), 0.0, places=2)
        self.assertAlmostEqual(self._elimination_line(4, self.us, self.ua, 'expense'), -50000.0, places=2)

    def test_partial_credit_note(self):
        """Poland's March IC revenue is eliminated net of the 5,000 credit note, on both sides."""
        self.assertAlmostEqual(self._elimination_line(3, self.pl, self.us, 'income'), 25000.0 - 5000.0, places=2)
        self.assertAlmostEqual(self._elimination_line(3, self.us, self.pl, 'expense'), -(25000.0 - 5000.0), places=2)

    def test_differences_cash_in_transit_and_fx(self):
        """What does not net to zero per pair: FX translation of IC balances, plus cash in transit at 31 March."""
        ua_receivable_uah = 40000.0 * UAH[1] + 45000.0 * UAH[2] + 50000.0 * UAH[3]
        loan_uah = 200000.0 * UAH[1]
        # Poland: invoices at their month's rate, credit note at the February rate it was reconciled with,
        # the January invoice paid on 1 April at 4.0 (same as January, no realised FX).
        pl_receivable_mar = 20000.0 * PLN[1] + 22000.0 * PLN[2] + 25000.0 * PLN[3] - 5000.0 * PLN[2]
        pl_receivable_apr = pl_receivable_mar - 20000.0 * PLN[1]

        march, april = self._difference_by_pair(3), self._difference_by_pair(4)
        ua_us, pl_us = frozenset((self.ua, self.us)), frozenset((self.pl, self.us))

        # UA/US: IC P&L nets to zero (both sides at the same monthly rate), only FX on the balances remains.
        self.assertAlmostEqual(march[ua_us], (200000.0 - loan_uah / UAH[3]) - (135000.0 - ua_receivable_uah / UAH[3]),
                               places=2)  # 6,547.62
        self.assertAlmostEqual(april[ua_us], (200000.0 - loan_uah / UAH[4]) - (135000.0 - ua_receivable_uah / UAH[4]),
                               places=2)  # 7,906.98
        # PL/US at 31 March: 20,000 paid by Delta US, not yet received by Delta Poland (in transit), net of FX.
        self.assertAlmostEqual(march[pl_us], pl_receivable_mar / PLN[3] - 42000.0, places=2)  # 18,642.86
        in_transit, open_ic_usd = 20000.0, 20000.0 + 22000.0 + 25000.0 - 5000.0
        self.assertAlmostEqual(march[pl_us], in_transit - (open_ic_usd - pl_receivable_mar / PLN[3]), places=2)
        # 30 April: the payment has arrived, only FX remains.
        self.assertAlmostEqual(april[pl_us], pl_receivable_apr / PLN[4] - 42000.0, places=2)  # 1,675.00

    # -------------------------------------------------------------------------
    # Re-running
    # -------------------------------------------------------------------------

    def test_rerun_is_idempotent(self):
        def snapshot():
            return {p.date_from.month: (p.move_id.id, sorted((l.account_id.id, l.delta_elim_company_id.id,
                                                              l.delta_counterpart_company_id.id, l.balance)
                                                             for l in p.move_id.line_ids))
                    for p in self.periods}
        before = snapshot()
        self.period[2].action_run()  # recomputes February and every later month
        self.assertEqual(snapshot(), before)
