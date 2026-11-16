from collections import defaultdict

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.delta_intercompany_demo import scenario as sc

# Monthly rates, units per USD (rates only change on the 1st, so month average == spot).
UAH = {1: 40.0, 2: 41.0, 3: 42.0, 4: 43.0}
PLN = {1: 4.0, 2: 4.1, 3: 4.2, 4: 4.0}


@tagged('post_install', '-at_install')
class TestDeltaEliminationDocuments(TransactionCase):
    """Proves the group numbers on the Delta Group scenario (delta_intercompany_demo.scenario),
    with eliminations kept in approved documents instead of journal entries.

    The expected figures are derived by hand from the scenario constants and rates.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        companies = sc.build(cls.env, suffix=' (doc test)')
        cls.us, cls.ua, cls.pl = companies['us'], companies['ua'], companies['pl']
        cls.members = cls.us | cls.ua | cls.pl
        cls.moves_before = cls.env['account.move'].search_count([])
        cls.group = cls.env['delta.consolidation.group'].create({
            'name': 'Delta Group (doc test)',
            'currency_id': cls.env.ref('base.USD').id,
            'member_company_ids': [(6, 0, cls.members.ids)],
        })
        cls.documents = cls.env['delta.elimination.document'].create([
            {'group_id': cls.group.id, 'date_from': f'2026-0{month}-01'} for month in (1, 2, 3, 4)
        ])
        cls.documents.action_confirm()
        cls.document = {d.date_from.month: d for d in cls.documents}

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _report(self, month, **kwargs):
        report = self.env['delta.group.report'].create({
            'group_id': self.group.id, 'date_from': f'2026-0{month}-01', **kwargs})
        report.action_generate()
        return report

    @staticmethod
    def _sum(lines, field='amount', **criteria):
        return sum(line[field] for line in lines if all(line[key] == value for key, value in criteria.items()))

    def _line(self, month, line_type, company, counterpart, account_xmlid=None):
        lines = self.document[month].line_ids.filtered(
            lambda l: l.line_type == line_type and l.company_id == company and l.counterpart_company_id == counterpart)
        if account_xmlid:
            account = self.env['account.chart.template'].with_company(company).ref(account_xmlid)
            lines = lines.filtered(lambda l: l.account_id == account)
        return sum(lines.mapped('balance'))

    def _difference(self, month, first, second):
        return sum(self.document[month].line_ids.filtered(
            lambda l: l.line_type == 'difference'
            and {l.company_id, l.counterpart_company_id} == {first, second}).mapped('balance'))

    # -------------------------------------------------------------------------
    # The documents
    # -------------------------------------------------------------------------

    def test_documents_balanced_and_outside_the_ledger(self):
        """BR-3 / BR-4: approved, numbered, balanced documents; no journal entry created anywhere."""
        self.assertEqual(self.env['account.move'].search_count([]), self.moves_before)
        for document in self.documents:
            self.assertEqual(document.state, 'confirmed')
            self.assertTrue(document.name.startswith('ELIM/'))
            self.assertAlmostEqual(sum(document.line_ids.mapped('balance')), 0.0, places=2)

    def test_chatter_shows_computation_and_approval(self):
        """Created and approved in one transaction (like the demo): the chatter still names the approver."""
        bodies = self.document[3].message_ids.mapped('body')
        self.assertTrue(any('Eliminations computed' in body for body in bodies))
        self.assertTrue(any(f'Approved by {self.env.user.name}' in body for body in bodies))
        self.document[3].action_reset_to_draft()
        self.assertIn('Reset to draft', self.document[3].message_ids[0].body)

    def test_approved_document_is_locked(self):
        document = self.document[3]
        with self.assertRaises(UserError):
            document.action_compute()
        with self.assertRaises(UserError):
            document.date_from = '2026-05-01'
        with self.assertRaises(UserError):
            document.unlink()
        document.action_reset_to_draft()
        before = sorted((l.line_type, l.company_id.id, l.counterpart_company_id.id, l.account_code or '', l.balance)
                        for l in document.line_ids)
        document.action_compute()
        after = sorted((l.line_type, l.company_id.id, l.counterpart_company_id.id, l.account_code or '', l.balance)
                       for l in document.line_ids)
        self.assertEqual(after, before, "Recomputing gives the same eliminations")

    def test_compute_and_report_with_one_company_selected(self):
        """The engine reads every member company, whatever the company switcher shows."""
        accountant = new_test_user(self.env, login='delta_doc_accountant', groups='account.group_account_manager',
                                   company_id=self.us.id, company_ids=[(6, 0, self.members.ids)])
        document = self.document[3].with_user(accountant).with_context(allowed_company_ids=[self.us.id])
        key = lambda l: (l.line_type, l.company_id.id, l.counterpart_company_id.id, l.account_code or '', l.balance)
        before = sorted(map(key, document.line_ids))
        document.action_reset_to_draft()
        document.action_compute()
        self.assertEqual(sorted(map(key, document.line_ids)), before)
        document.action_confirm()

        report = self.env['delta.group.report'].with_user(accountant).with_context(
            allowed_company_ids=[self.us.id]).create({'group_id': self.group.id, 'date_from': '2026-03-01'})
        report.action_generate()
        external_sales = 170000.0 + 400000.0 / UAH[3] + 300000.0 / PLN[3]
        costs = (60000.0 + 10000.0) + (1500000.0 + 120000.0) / UAH[3] + (150000.0 + 20000.0) / PLN[3]
        self.assertAlmostEqual(self._sum(report.line_ids, statement='pnl'),
                               external_sales + 500.0 / PLN[3] - costs, places=2)

        outsider = new_test_user(self.env, login='delta_doc_outsider', groups='account.group_account_manager',
                                 company_id=self.us.id, company_ids=[(6, 0, (self.us | self.ua).ids)])
        with self.assertRaises(UserError):
            self.document[3].with_user(outsider).with_context(
                allowed_company_ids=[self.us.id]).group_id._fetch_balances(self.document[3].date_to)

    def test_document_does_not_depend_on_earlier_documents(self):
        """A March document computed alone (no January/February documents) is identical."""
        alone = self.env['delta.consolidation.group'].create({
            'name': 'March only', 'member_company_ids': [(6, 0, self.members.ids)]})
        march = self.env['delta.elimination.document'].create({'group_id': alone.id, 'date_from': '2026-03-01'})
        march.action_compute()
        key = lambda l: (l.line_type, l.company_id.id, l.counterpart_company_id.id, l.account_code or '', l.balance)
        self.assertEqual(sorted(map(key, march.line_ids)), sorted(map(key, self.document[3].line_ids)))

    # -------------------------------------------------------------------------
    # Group P&L
    # -------------------------------------------------------------------------

    def test_group_pnl_march(self):
        lines = self._report(3).line_ids
        external_sales = 170000.0 + 400000.0 / UAH[3] + 300000.0 / PLN[3]
        realised_fx_gain = 500.0 / PLN[3]
        costs = (60000.0 + 10000.0) + (1500000.0 + 120000.0) / UAH[3] + (150000.0 + 20000.0) / PLN[3]
        self.assertAlmostEqual(self._sum(lines, statement='pnl'), external_sales + realised_fx_gain - costs, places=2)
        self.assertAlmostEqual(self._sum(lines, statement='pnl', section='revenue'),
                               external_sales + realised_fx_gain, places=2)
        self.assertAlmostEqual(self._sum(lines, statement='pnl', column='Eliminations'), -50000.0, places=2)

    def test_group_pnl_april(self):
        lines = self._report(4).line_ids
        external = (170000.0 - 60000.0 - 10000.0) + (400000.0 - 1500000.0 - 120000.0) / UAH[4] \
            + (300000.0 - 150000.0 - 20000.0) / PLN[4]
        self.assertAlmostEqual(self._sum(lines, statement='pnl'), external, places=2)

    def test_standalone_results_next_to_group(self):
        """Each company's own result, in its own currency and translated, is in the same report."""
        lines = self._report(3).line_ids
        self.assertAlmostEqual(self._sum(lines, 'amount_local', statement='pnl', company_id=self.us), 80000.0, places=2)
        self.assertAlmostEqual(self._sum(lines, 'amount_local', statement='pnl', company_id=self.ua), 880000.0, places=2)
        self.assertAlmostEqual(self._sum(lines, 'amount_local', statement='pnl', company_id=self.pl), 214500.0, places=2)
        self.assertAlmostEqual(self._sum(lines, statement='pnl', company_id=self.ua), 880000.0 / UAH[3], places=2)

    # -------------------------------------------------------------------------
    # Group balance sheet
    # -------------------------------------------------------------------------

    def test_group_balance_sheet_balances(self):
        """Every column balances (CTA closes each company's translation), so the group does."""
        for month in (1, 2, 3, 4):
            lines = self._report(month).line_ids.filtered(lambda l: l.statement == 'bs')
            per_column = defaultdict(float)
            for line in lines:
                per_column[line.column] += line.balance
            for column, balance in per_column.items():
                self.assertAlmostEqual(balance, 0.0, places=2, msg=f"2026-0{month} {column}")
            self.assertAlmostEqual(self._sum(lines, section='assets'),
                                   -(self._sum(lines, section='liabilities') + self._sum(lines, section='equity')),
                                   places=1)
            # The pivot sums the balance sheet to zero, so its grand total is the group profit
            self.assertAlmostEqual(self._sum(lines), 0.0, places=1, msg=f"2026-0{month}")

    def test_intercompany_balances_eliminated(self):
        """31 March: receivables are external clients only; IC payables and the loan are gone."""
        lines = self._report(3).line_ids
        external_receivables = 3 * 170000.0 + 3 * 400000.0 / UAH[3] + 3 * 300000.0 / PLN[3]
        self.assertAlmostEqual(self._sum(lines, account_code='121000'), external_receivables, places=2)
        self.assertAlmostEqual(self._sum(lines, account_code='211000'), 0.0, places=2)
        self.assertAlmostEqual(self._sum(lines, account_code='191500') + self._sum(lines, account_code='291500'),
                               0.0, places=2)

    def test_draft_document_not_used_unless_asked(self):
        self.document[3].action_reset_to_draft()
        self.assertAlmostEqual(self._sum(self._report(3).line_ids, column='Eliminations'), 0.0, places=2)
        self.assertAlmostEqual(self._sum(self._report(3, include_draft=True).line_ids, statement='pnl',
                                         column='Eliminations'), -50000.0, places=2)

    # -------------------------------------------------------------------------
    # Cut-off, credit note, cash in transit
    # -------------------------------------------------------------------------

    def test_cutoff_ukraine_march_invoice(self):
        """Dated 31 March by Ukraine, booked 2 April by Delta US: revenue eliminated in March, cost in April."""
        self.assertAlmostEqual(self._line(3, 'pnl', self.ua, self.us, 'income'), 50000.0, places=2)
        self.assertAlmostEqual(self._line(3, 'pnl', self.us, self.ua, 'expense'), 0.0, places=2)
        self.assertAlmostEqual(self._line(4, 'pnl', self.us, self.ua, 'expense'), -50000.0, places=2)

    def test_partial_credit_note(self):
        self.assertAlmostEqual(self._line(3, 'pnl', self.pl, self.us, 'income'), 25000.0 - 5000.0, places=2)
        self.assertAlmostEqual(self._line(3, 'pnl', self.us, self.pl, 'expense'), -(25000.0 - 5000.0), places=2)

    def test_differences_cash_in_transit_and_fx(self):
        ua_receivable_uah = 40000.0 * UAH[1] + 45000.0 * UAH[2] + 50000.0 * UAH[3]
        loan_uah = 200000.0 * UAH[1]
        pl_receivable_mar = 20000.0 * PLN[1] + 22000.0 * PLN[2] + 25000.0 * PLN[3] - 5000.0 * PLN[2]
        pl_receivable_apr = pl_receivable_mar - 20000.0 * PLN[1]
        self.assertAlmostEqual(self._difference(3, self.ua, self.us),
                               (200000.0 - loan_uah / UAH[3]) - (135000.0 - ua_receivable_uah / UAH[3]), places=2)
        self.assertAlmostEqual(self._difference(4, self.ua, self.us),
                               (200000.0 - loan_uah / UAH[4]) - (135000.0 - ua_receivable_uah / UAH[4]), places=2)
        in_transit, open_ic_usd = 20000.0, 20000.0 + 22000.0 + 25000.0 - 5000.0
        self.assertAlmostEqual(self._difference(3, self.pl, self.us),
                               in_transit - (open_ic_usd - pl_receivable_mar / PLN[3]), places=2)  # 18,642.86
        self.assertAlmostEqual(self._difference(4, self.pl, self.us), pl_receivable_apr / PLN[4] - 42000.0, places=2)
