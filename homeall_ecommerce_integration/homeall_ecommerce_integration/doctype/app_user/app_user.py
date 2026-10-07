# Copyright (c) 2026, Tes Pheakdey and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class AppUser(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		full_name: DF.Data | None
		is_verify: DF.Check
		party: DF.DynamicLink | None
		party_type: DF.Link | None
		photo: DF.AttachImage | None
		user_id: DF.Data | None
	# end: auto-generated types

	_DOCTYPE_NAME = "App User"
