import frappe
from frappe.model.document import Document
import uuid
import re

def is_valid_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

@frappe.whitelist()
def  update_sync_status(doc: Document, method: str):
    if doc.doctype in ["Business Profile", "Business Type"]:    
        if doc.get("is_synced") == 1: 
            doc.db_set("is_synced", 0)
    else:
        if not is_valid_uuid(doc.get("custom_supabase_id")):
            doc.db_set("custom_supabase_id", str(uuid.uuid4()))
            
        if doc.get("custom_is_synced") == 1: 
            doc.db_set("custom_is_synced", 0)
        
@frappe.whitelist()
def update_item(doc: Document, method: str):
    if doc.doctype == "Item Price": 
        if doc.price_list == "Standard Selling":
            prices = frappe.db.sql("""select 
                    max(price_list_rate) as price_list_rate 
                from `tabItem Price` 
                where 
                    item_code = %(item_code)s""", 
                {"item_code": doc.item_code},
                as_dict = 1 )
            
            if prices:
                item = frappe.get_doc("Item", doc.item_code)                
                if item.standard_rate != prices[0].price_list_rate:
                    item.db_set("standard_rate", prices[0].price_list_rate)
                    item.db_set("custom_is_synced", 0)