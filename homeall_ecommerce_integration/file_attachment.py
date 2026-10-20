import frappe

SYNC_DOCTYPES = [
    "App User Type",
    "Price List",
    "App Promotion",
    "Brand",
    "Business Type",
    "Business Profile",
    "Item Group",
    "Item",    
]

def reset_linked_doc_sync_status(file_doc):
    """
    Reset custom_is_synced to 0 on the document linked to an attachment.
    """ 

    if not file_doc.attached_to_doctype or not file_doc.attached_to_name:
        return
    
    if file_doc.attached_to_doctype not in SYNC_DOCTYPES:   
        return

 
                
    doctype = file_doc.attached_to_doctype
    docname = file_doc.attached_to_name

    # Only update DocTypes that contain custom_is_synced
    if not frappe.db.exists("DocType", doctype):
        return

    meta = frappe.get_meta(doctype)

    if meta.has_field("custom_is_synced") or meta.has_field("is_synced"): 
        if not frappe.db.exists(doctype, docname):
            return
        sync_field = "custom_is_synced" if meta.has_field("custom_is_synced") else "is_synced"
        
        frappe.db.set_value(
            doctype,
            docname,
            sync_field,
            0,
            update_modified=False
        )


def after_insert(doc, method=None):
    reset_linked_doc_sync_status(doc)


def on_update(doc, method=None):
    reset_linked_doc_sync_status(doc)


def on_trash(doc, method=None):
    reset_linked_doc_sync_status(doc)