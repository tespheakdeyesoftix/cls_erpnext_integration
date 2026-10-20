# Copyright (c) 2026, Tes Pheakdey and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class AppPromotionApplyFor(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		apply_for: DF.DynamicLink | None
		apply_for_type: DF.Link | None
		limit_qty: DF.Float
		max_qty_per_order: DF.Float
		max_qty_per_user: DF.Float
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
	# end: auto-generated types

	_DOCTYPE_NAME = "App Promotion Apply For"
