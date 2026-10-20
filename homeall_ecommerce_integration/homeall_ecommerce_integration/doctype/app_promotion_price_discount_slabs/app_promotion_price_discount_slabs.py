# Copyright (c) 2026, Tes Pheakdey and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class AppPromotionPriceDiscountSlabs(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		max_amount: DF.Float
		max_qty: DF.Float
		min_amount: DF.Float
		min_qty: DF.Float
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		price_or_discount_value: DF.Float
		rate_or_discount: DF.Literal["Rate", "Discount Percentage", "Discount Amount"]
	# end: auto-generated types

	_DOCTYPE_NAME = "App Promotion Price Discount Slabs"
