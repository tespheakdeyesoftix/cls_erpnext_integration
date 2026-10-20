# Copyright (c) 2026, Tes Pheakdey and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class AppUserType(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		customer_group: DF.Link | None
		disabled: DF.Check
		is_synced: DF.Check
		price_list: DF.Link | None
		title: DF.Data
	# end: auto-generated types

	_DOCTYPE_NAME = "App User Type"
