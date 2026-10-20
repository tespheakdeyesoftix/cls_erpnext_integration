# Copyright (c) 2026, Tes Pheakdey and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class AppPromotionProductDiscountSlabs(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		apply_recursion_over: DF.Float
		free_product: DF.Link
		free_product_qty: DF.Float
		is_recursive: DF.Check
		max_amount: DF.Float
		max_qty: DF.Float
		min_amount: DF.Float
		min_qty: DF.Float
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		recurse_for: DF.Float
	# end: auto-generated types

	_DOCTYPE_NAME = "App Promotion Product Discount Slabs"
