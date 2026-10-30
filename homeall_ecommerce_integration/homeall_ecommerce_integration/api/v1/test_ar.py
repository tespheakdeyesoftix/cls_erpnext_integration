from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1 import ar


class TestCustomerAccounts(TestCase):
	def setUp(self):
		self.customer = MagicMock()
		self.company = MagicMock()
		self.get_doc = MagicMock(side_effect=lambda doctype, name: {
			"Customer": self.customer, "Company": self.company,
		}[doctype])
		for target, name, value in (
			(ar, "_", lambda text: text),
			(ar, "nowdate", lambda: "2026-10-30"),
			(frappe, "get_doc", self.get_doc),
			(frappe, "has_permission", MagicMock(return_value=True)),
		):
			mock = patch.object(target, name, value)
			mock.start()
			self.addCleanup(mock.stop)

	def test_balance_returns_only_signed_amount_including_credit_and_zero(self):
		for amount in (150.75, -80.25, 0.0):
			with self.subTest(amount=amount), patch.object(ar, "get_balance_on", return_value=amount):
				self.assertEqual(ar.get_ar_balance("CUST-001", company="Homeall"), amount)

	def test_balance_is_current_and_scoped_to_one_company_in_company_currency(self):
		with patch.object(ar, "get_balance_on", return_value=12.0) as balance:
			ar.get_ar_balance("CUST-001", company="Other Company")
		args = balance.call_args.kwargs
		self.assertEqual(args["party_type"], "Customer")
		self.assertEqual(args["party"], "CUST-001")
		self.assertEqual(args["company"], "Other Company")
		self.assertEqual(args["date"], "2026-10-30")
		self.assertFalse(args["in_account_currency"])
		self.assertTrue(args["apply_gl_entry_permissions"])
		self.assertTrue(args["include_default_fb_balances"])

	def test_ledger_scope_excludes_cancelled_future_and_unrelated_entries(self):
		# More than Frappe's default page length must remain available.
		rows = [{
			"name": f"GL-{index:02d}", "posting_date": "2026-10-29", "creation": "2026-10-29 10:00:00",
		} for index in range(25)]
		with (
			patch.object(frappe, "get_cached_value", return_value="Default Book"),
			patch.object(frappe, "get_list", return_value=rows) as get_list,
		):
			self.assertEqual(ar.get_ar_general_ledger("CUST-001", company="Homeall"), rows)
		args = get_list.call_args.kwargs
		self.assertEqual(args["filters"], {
			"party_type": "Customer", "party": "CUST-001", "company": "Homeall",
			"is_cancelled": 0, "posting_date": ["<=", "2026-10-30"],
		})
		self.assertEqual(args["or_filters"], [
			["finance_book", "is", "not set"], ["finance_book", "=", "Default Book"],
		])
		self.assertEqual(args["limit_page_length"], 0)
		self.assertEqual(args["order_by"], "posting_date asc, creation asc, name asc")

	def test_permissions_are_checked_before_reading_balances_or_ledger(self):
		for document in (self.customer, self.company):
			document.check_permission.side_effect = frappe.PermissionError
			with patch.object(ar, "get_balance_on") as balance, patch.object(frappe, "get_list") as ledger:
				for method in (ar.get_ar_balance, ar.get_ar_general_ledger):
					with self.assertRaises(frappe.PermissionError):
						method("CUST-001", company="Homeall")
				balance.assert_not_called()
				ledger.assert_not_called()
			document.check_permission.side_effect = None

	def test_gl_permission_is_required_for_both_methods(self):
		with patch.object(frappe, "has_permission", side_effect=frappe.PermissionError):
			for method in (ar.get_ar_balance, ar.get_ar_general_ledger):
				with self.assertRaises(frappe.PermissionError):
					method("CUST-001")

	def test_blank_customer_cannot_fall_back_to_a_company_wide_balance(self):
		with patch.object(frappe, "throw", side_effect=frappe.ValidationError):
			for method in (ar.get_ar_balance, ar.get_ar_general_ledger):
				with self.assertRaises(frappe.ValidationError):
					method("  ")
		self.get_doc.assert_not_called()

	def test_empty_or_omitted_company_sums_all_permitted_company_balances(self):
		for kwargs in ({}, {"company": None}, {"company": ""}, {"company": "  "}):
			with (
				self.subTest(kwargs=kwargs),
				patch.object(frappe, "get_list", return_value=["Homeall", "Other Company"]) as companies,
				patch.object(ar, "get_balance_on", side_effect=[150.75, -80.25]) as balance,
			):
				self.assertEqual(ar.get_ar_balance("CUST-001", **kwargs), 70.5)
				companies.assert_called_once_with("Company", pluck="name", limit_page_length=0)
				self.assertEqual(
					[call.kwargs["company"] for call in balance.call_args_list], ["Homeall", "Other Company"]
				)

	def test_all_company_ledger_merges_entries_in_chronological_order(self):
		older = {"name": "GL-A", "posting_date": "2026-10-28", "creation": "2026-10-28 10:00:00"}
		newer = {"name": "GL-B", "posting_date": "2026-10-29", "creation": "2026-10-29 10:00:00"}
		for company in (None, ""):
			with (
				self.subTest(company=company),
				patch.object(frappe, "get_list", return_value=["Homeall", "Other Company"]),
				patch.object(ar, "_get_company_ledger", side_effect=[[newer], [older]]) as ledger,
			):
				self.assertEqual(ar.get_ar_general_ledger("CUST-001", company=company), [older, newer])
				self.assertEqual(
					[call.args[1] for call in ledger.call_args_list], ["Homeall", "Other Company"]
				)

	def test_no_permitted_companies_returns_zero_balance_and_empty_ledger(self):
		with (
			patch.object(frappe, "get_list", return_value=[]),
			patch.object(ar, "get_balance_on") as balance,
			patch.object(ar, "_get_company_ledger") as ledger,
		):
			self.assertEqual(ar.get_ar_balance("CUST-001"), 0.0)
			self.assertEqual(ar.get_ar_general_ledger("CUST-001"), [])
			balance.assert_not_called()
			ledger.assert_not_called()
