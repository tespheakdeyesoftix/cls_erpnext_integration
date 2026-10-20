import json
import uuid
from supabase import Client, ClientOptions, create_client
import frappe
from postgrest.exceptions import APIError
from homeall_ecommerce_integration.controller import is_valid_uuid,slugify


SUPABASE_TIMEOUT_SECONDS = 30


def init_supabase() -> Client:
    """Create the server-side Supabase client from the current site config."""
    site_config = frappe.get_site_config()
    url = (site_config.get("supabase_url") or "").strip().rstrip("/")
    key = (site_config.get("supabase_service_role_key") or "").strip()

    if not url:
        frappe.throw("Supabase URL is not configured in site_config.json.")

    if not key:
        frappe.throw("Supabase service-role key is not configured in site_config.json.")

    if key.startswith("sb_publishable_"):
        frappe.throw(
            "Supabase is configured with a publishable key. "
            "Configure a server-side sb_secret_ key instead."
        )

    try:
        return create_client(
            url,
            key,
            options=ClientOptions(
                postgrest_client_timeout=SUPABASE_TIMEOUT_SECONDS,
                storage_client_timeout=SUPABASE_TIMEOUT_SECONDS,
                function_client_timeout=SUPABASE_TIMEOUT_SECONDS,
            ),
        )
    except Exception:
        frappe.log_error(
            title="Supabase Client Initialization Error",
            message="Unable to initialize the Supabase server client.",
        )
        frappe.throw("Unable to initialize the Supabase connection.")

def sync_to_supabase(
    doctype: str,
    table_name: str,
    prepare_data,
    name: str = None,
    batch_size: int = 100,
    sync_field: str = "custom_is_synced",
    filters: dict = None,
    uuid_field: str = None,
):
    """
    Generic Frappe to Supabase synchronization.

    Args:
        doctype: Frappe DocType.
        table_name: Supabase table.
        prepare_data: Function to prepare Supabase data.
        name: Optional single document name.
        batch_size: Number of records per batch.
        sync_field: Frappe synchronization status field.
        uuid_field: Optional Frappe UUID field.
    """

    if batch_size < 1:
        raise ValueError("batch_size must be greater than 0")
    


    def prepare_record(doc):
        if uuid_field:
            supabase_id = doc.get(uuid_field)

            if not is_valid_uuid(supabase_id):
                supabase_id = str(uuid.uuid4())

                # Persist ID to ensure retries use the same ID
                frappe.db.set_value(
                    doctype,
                    doc.name,
                    uuid_field,
                    supabase_id,
                    update_modified=False
                )

            return prepare_data(doc, str(supabase_id))

        return prepare_data(doc)

    def upsert_records(data_list, record_names):
        if not data_list:
            return 0

        try:
            sup = init_supabase()

            response = (
                sup.table(table_name)
                .upsert(
                    data_list,
                    on_conflict="id"
                )
                .execute()
            )

            if response.data is None:
                raise Exception(
                    f"Supabase returned no data: {response}"
                )

            for record_name in record_names:
                frappe.db.set_value(
                    doctype,
                    record_name,
                    sync_field,
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

    # Single synchronization
    if name:
        if filters:            
            name = frappe.db.get_value(doctype, filters, "name")   
                 
        if name:
            doc = frappe.get_doc(doctype, name)
            data = prepare_record(doc)
            synced_count = upsert_records(
                data_list=[data],
                record_names=[doc.name]
            )
            return {
                "success": synced_count > 0,
                "synced_count": synced_count
            }
        else:
            return {
                "success": False,
                "synced_count": 0,
                "message": f"No record found for {doctype} with filters: {filters}"
            }    

    # Bulk synchronization
    if  filters is None:
        filters = {sync_field: 0} 
        
    record_names = frappe.get_all(
        doctype,
        filters=filters,
        pluck="name"
    )
    

    if not record_names:
        return {
            "success": True,
            "synced_count": 0,
            "message": "No records to synchronize"
        }

    total_synced = 0

    for i in range(0, len(record_names), batch_size):
        batch_names = record_names[i:i + batch_size]

        data_list = []
        

        for record_name in batch_names:
            doc = frappe.get_doc(doctype, record_name)
            data = prepare_record(doc)
            data_list.append(data)
            
        synced_count = upsert_records(
            data_list=data_list,
            record_names=batch_names
        )

        total_synced += synced_count

    return {
        "success": total_synced == len(record_names),
        "synced_count": total_synced,
        "total_records": len(record_names)
    }
