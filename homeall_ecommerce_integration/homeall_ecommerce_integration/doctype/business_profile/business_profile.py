# Copyright (c) 2026, Tes Pheakdey and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class BusinessProfile(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		address: DF.SmallText | None
		business_name: DF.Data
		business_type: DF.Link
		description: DF.TextEditor | None
		disabled: DF.Check
		email: DF.Data | None
		is_feature: DF.Check
		is_publish: DF.Check
		is_record_new: DF.Check
		is_synced: DF.Check
		phone: DF.Data | None
		photo: DF.AttachImage | None
		sort_order: DF.Int
	# end: auto-generated types

	_DOCTYPE_NAME = "Business Profile"
