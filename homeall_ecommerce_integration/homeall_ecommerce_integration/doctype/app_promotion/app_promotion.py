# Copyright (c) 2026, Tes Pheakdey and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class AppPromotion(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from homeall_ecommerce_integration.homeall_ecommerce_integration.doctype.app_promotion_applicable_for.app_promotion_applicable_for import AppPromotionApplicableFor
		from homeall_ecommerce_integration.homeall_ecommerce_integration.doctype.app_translations.app_translations import AppTranslations
		from homeall_ecommerce_integration.homeall_ecommerce_integration.doctype.flash_sale_banner_product.flash_sale_banner_product import FlashSaleBannerProduct

		amended_from: DF.Link | None
		applicable_for: DF.Table[AppPromotionApplicableFor]
		application_scope: DF.Literal["product_line", "eligible_cart", "entire_cart"]
		badge_bg_color: DF.Color | None
		business_id: DF.Link
		card_action_product_id: DF.Link | None
		card_action_type: DF.Literal["native_detail", "product_detail", "promotion_products", "webview"]
		card_action_url: DF.SmallText | None
		cart_qualification_uom: DF.Link | None
		countdown_placement: DF.Literal["top_left", "top_center", "top_right", "bottom_left", "bottom_center", "bottom_right", "middle_left", "middle_right", "middle_center"]
		description: DF.MarkdownEditor | None
		disabled: DF.Check
		end_date: DF.Datetime | None
		flash_banner_corner_radius: DF.Int
		flash_banner_full_width: DF.Check
		flash_banner_height: DF.Int
		flash_banner_products: DF.Table[FlashSaleBannerProduct]
		flash_banner_style: DF.Literal["style_1", "style_2", "style_3"]
		flash_product_limit: DF.Int
		flash_product_source: DF.Literal["apply_for", "manual"]
		is_synced: DF.Check
		maximum_cart_discount_amount: DF.Currency
		photo: DF.AttachImage | None
		priority: DF.Int
		promotion_rules: DF.JSON | None
		promotion_type: DF.Literal["Standard", "Flash Sale"]
		show_countdown: DF.Check
		show_sold_progress: DF.Check
		show_upcoming: DF.Check
		start_date: DF.Datetime
		terms_and_conditions: DF.MarkdownEditor | None
		title: DF.Data
		translation: DF.Table[AppTranslations]
		upcoming_display: DF.Literal["label", "countdown"]
	# end: auto-generated types

	_DOCTYPE_NAME = "App Promotion"

	def before_submit(self):
		from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.app_promotion_sync import (
			validate_promotion,
		)

		validate_promotion(self)

	def on_update_after_submit(self):
		if self.is_synced:
			self.db_set("is_synced", 0, update_modified=False)

	def on_cancel(self):
		self.db_set("disabled", 1, update_modified=False)
		frappe.msgprint(
			"Use Sync to App Database > Remove Promotion from App to disable this promotion in the app. "
			"If it has no orders, its record will be deleted from the app database."
		)
