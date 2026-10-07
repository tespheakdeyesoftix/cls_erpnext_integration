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
        
    