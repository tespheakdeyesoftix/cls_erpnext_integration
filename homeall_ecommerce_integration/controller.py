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
def  update_sync_status(doc: Document, method: str, *args, **kwargs):
    if doc.doctype in ["Business Profile", "Business Type", "App User Type","App Promotion"]:    
        if doc.get("is_synced") == 1: 
            doc.db_set("is_synced", 0)
    else:
        if not is_valid_uuid(doc.get("custom_supabase_id")):
            doc.db_set("custom_supabase_id", str(uuid.uuid4()))
            
        if doc.get("custom_is_synced") == 1: 
            doc.db_set("custom_is_synced", 0)
    
    if doc.doctype == "Item":
        # 1
        item_update(doc, method)
        
    elif doc.doctype == "Item Price":
        item_price_update(doc, method)
        
@frappe.whitelist()
def item_price_update(doc: Document, method: str):
    if doc.doctype == "Item Price": 
        if doc.price_list == "Standard Selling":
            item = frappe.get_doc("Item", doc.item_code)      
            prices = frappe.db.sql("""select 
                    max(price_list_rate) as price_list_rate 
                from `tabItem Price` 
                where 
                    item_code = %(item_code)s
                    and uom = %(uom)s""", 
                {"item_code": doc.item_code, "uom": item.stock_uom}, as_dict = 1 )
            
            if prices:           
                if item.standard_rate != prices[0].price_list_rate:
                    item.db_set("standard_rate", prices[0].price_list_rate)
                    item.db_set("custom_is_synced", 0)


@frappe.whitelist()
def item_update(doc: Document, method: str = None):
    translated_text = " ".join(
        x.title
        for x in (doc.custom_translation or [])
        if x.get("title")
    )

    # Update translation parent_id,is_synced
    if doc.custom_supabase_id:
        for x in (doc.custom_translation or []):
            if x.get("parent_id") != doc.custom_supabase_id:
                x.db_set(
                    "parent_id",
                    doc.custom_supabase_id,
                    update_modified=False
                )
                
            x.db_set(
                "is_synced",
                0,
                update_modified=False
            )

    # Build search text
    search_text = " ".join(
        str(value)
        for value in [
            doc.name,
            doc.item_name,
            doc.custom_app_product_name,
            translated_text
        ]
        if value
    )

    # Update only if changed
    if doc.custom_search_text != search_text:
        doc.db_set(
            "custom_search_text",
            search_text,
            update_modified=False
        )
    

    