import frappe
import uuid
import json
from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.fn_sync_to_supabase import init_supabase
from homeall_ecommerce_integration.controller import is_valid_uuid
from postgrest.exceptions import APIError


@frappe.whitelist(methods=["POST"])
def sync_to_supabase(parenttype: str = None, parent: str=None, batch_size: int = 100):
    filters = {
        "is_synced":0
    }
    if parenttype:
        filters["parenttype"] = parenttype
    
    if parent:
        filters["parent"] = parent
        
    app_translations = frappe.get_all("App Translations",filters,pluck="name")
    table_name = "translations"
 
    
 
    def upsert_records(data_list, record_names):
        if not data_list:
            return 0

        try:
            sup = init_supabase()
            response = (
                sup.table(table_name)
                .upsert(
                    data_list,
                    on_conflict="doctype,lang,parent_id"
                )
                .execute()
            )

            if response.data is None:
                raise Exception(
                    f"Supabase returned no data: {response}"
                )

            for record_name in record_names:
                frappe.db.set_value(
                    "App Translations",
                    record_name,
                    "is_synced",
                    1,
                    update_modified=False
                )

            frappe.db.commit()

            return len(record_names)

        except APIError as e:
            frappe.db.rollback()
            error_details = {
                "message": str(e),
                "code": getattr(e, "code", None),
                "details": getattr(e, "details", None),
                "hint": getattr(e, "hint", None),
                "table": table_name,
                "data": data_list,
            }
            print(f"Supabase {table_name} API Error: {json.dumps(error_details, indent=2, default=str)}")

            frappe.log_error(
                title=f"Supabase {table_name} API Error",
                message=json.dumps(
                    error_details,
                    indent=2,
                    default=str
                )
            )

            raise

        except Exception:
            frappe.db.rollback()
            frappe.log_error(
                title=f"Supabase {table_name} Sync Error",
                message=frappe.get_traceback()
            )

            raise
    
    
    if not app_translations:
        return {
            "success": True,
            "synced_count": 0,
            "message": "No records to synchronize"
        } 
        
    total_synced = 0
    for i in range(0, len(app_translations), batch_size):
        batch_names = app_translations[i:i + batch_size]    
        data_list = []
        for record_name in batch_names:
            child = frappe.get_doc("App Translations", record_name)        
            data = _prepare_record(child)
            data_list.append(data)
            
        synced_count = upsert_records(
            data_list=data_list,
            record_names=batch_names
        )

        total_synced += synced_count

    return {
        "success": total_synced == len(app_translations),
        "synced_count": total_synced,
        "total_records": len(app_translations)
    }


def sync_to_supabase_queues(parenttype: str = None, parent: str=None, batch_size: int = 100):  
    frappe.enqueue(
            "homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.sync_app_translation.sync_to_supabase", # python function or a module path as string
            queue="long", # one of short, default, long
            job_name="sync_product", # specify a job name
            parenttype=parenttype,
            parent=parent,
            batch_size=batch_size,
            # enqueue_after_commit=True,
        )
    
# prepare data of item price
def _prepare_record(record):
    data = {
        "doctype": record.parenttype,
        "lang": record.language,
        "parent_id": record.parent_id,
        "title": record.title,
    }
    return data
