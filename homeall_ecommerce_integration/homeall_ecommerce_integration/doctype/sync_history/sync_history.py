# Copyright (c) 2026, Tes Pheakdey and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.sync import  (
	sync_brands_queues,
 	sync_business_types_queues,
	sync_business_profiles_queues,
	sync_item_groups_queues,
	sync_products_queues,
)

class SyncHistory(Document): 
	def on_update(self):
		pass
 
	def on_submit(self):		
		SYNC_DOCTYPES = [
			"Brand",
			"Business Type",
			"Business Profile",
			"Item Group",
			"Item",
		]
		DOCTYPES = [d for d in SYNC_DOCTYPES if d in [x.sync_doctype for x in self.sync_doctypes]]  
		for doc in DOCTYPES:
			if doc == "Brand":
				sync_brands_queues()
			elif doc == "Business Type":
				sync_business_types_queues()
			elif doc == "Business Profile":
				sync_business_profiles_queues()
			elif doc == "Item Group":
				sync_item_groups_queues()
			elif doc == "Item":
				sync_products_queues()