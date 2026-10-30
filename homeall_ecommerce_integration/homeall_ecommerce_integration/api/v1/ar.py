import frappe
from frappe import _
from frappe.utils import cstr, nowdate

from erpnext.accounts.utils import get_balance_on


def _validate_customer_and_company(customer_code, company):
	customer_code = cstr(customer_code).strip()
	if not customer_code:
		frappe.throw(_("Customer code is required."))
	frappe.get_doc("Customer", customer_code).check_permission("read")
	frappe.has_permission("GL Entry", "read", throw=True)

	company = cstr(company).strip() or None
	if company:
		frappe.get_doc("Company", company).check_permission("read")
	return customer_code, company


def _get_companies(company):
	if company:
		return [company]
	return frappe.get_list("Company", pluck="name", limit_page_length=0)


@frappe.whitelist(methods=["GET"])
def get_ar_balance(customer_code: str, company: str | None = None) -> float:
	"""Return net AR through today; customer credit is negative.

	Empty company includes all permitted companies, using each company's default
	Finance Book and entries without a Finance Book. Amounts are summed in their
	respective company currencies without conversion. Positive amounts are owed.
	"""
	customer_code, company = _validate_customer_and_company(customer_code, company)
	posting_date = nowdate()
	return sum(
		(
			get_balance_on(
				date=posting_date,
				party_type="Customer",
				party=customer_code,
				company=company_name,
				in_account_currency=False,
				include_default_fb_balances=True,
				apply_gl_entry_permissions=True,
			)
			for company_name in _get_companies(company)
		),
		0.0,
	)


@frappe.whitelist(methods=["GET"])
def get_ar_general_ledger(customer_code: str, company: str | None = None) -> list[dict]:
	"""Return active customer GL entries through today, oldest first.

	Empty company includes all permitted companies. Debit and credit are in each
	company's currency. Company and Finance Book scope match get_ar_balance;
	normal GL Entry permissions apply to both methods.
	"""
	customer_code, company = _validate_customer_and_company(customer_code, company)
	entries = []
	posting_date = nowdate()
	for company_name in _get_companies(company):
		entries.extend(_get_company_ledger(customer_code, company_name, posting_date))
	return sorted(entries, key=lambda entry: (entry["posting_date"], entry["creation"], entry["name"]))


def _get_company_ledger(customer_code, company, posting_date):
	default_finance_book = frappe.get_cached_value("Company", company, "default_finance_book")
	return frappe.get_list(
		"GL Entry",
		filters={
			"party_type": "Customer",
			"party": customer_code,
			"company": company,
			"is_cancelled": 0,
			"posting_date": ["<=", posting_date],
		},
		or_filters=[
			["finance_book", "is", "not set"],
			["finance_book", "=", default_finance_book or ""],
		],
		fields=[
			"name", "posting_date", "creation", "account", "company", "finance_book",
			"voucher_type", "voucher_no", "against_voucher_type", "against_voucher",
			"debit", "credit", "account_currency", "debit_in_account_currency",
			"credit_in_account_currency", "is_opening", "remarks",
		],
		order_by="posting_date asc, creation asc, name asc",
		limit_page_length=0,
	)
