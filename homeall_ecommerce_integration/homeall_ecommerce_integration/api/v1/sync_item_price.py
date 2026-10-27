import frappe
import uuid
import json
from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.fn_sync_to_supabase import init_supabase
from homeall_ecommerce_integration.controller import is_valid_uuid
from postgrest.exceptions import APIError


@frappe.whitelist(methods=["POST"])
def sync_to_supabase(name: str=None,batch_size: int = 100):
    """
    Generic Frappe to Supabase synchronization.

    Args:
        name: Optional single document name.
        batch_size: Number of records per batch.
    """

    if batch_size < 1:
        raise ValueError("batch_size must be greater than 0")
    
    uuid_field = "custom_supabase_id"
    table_name = "product_prices"
    
    def prepare_record(doc):
        supabase_id = doc.get(uuid_field)
        if not is_valid_uuid(supabase_id):
            supabase_id = str(uuid.uuid4())

            # Persist ID to ensure retries use the same ID
            frappe.db.set_value(
                "Item Price",
                doc.name,
                uuid_field,
                supabase_id,
                update_modified=False
            )

        return _prepare_item_price_data(doc, str(supabase_id))
    
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
                    "Item Price",
                    record_name,
                    "custom_is_synced",
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
        filters = {
            "item_code": name,
            # "price_list": ["!=","Standard Selling"],
            "selling": 1
        } 
        result = frappe.db.get_value("Item Price", filters, ["name", "price_list"],as_dict=True)   
                    
        if result:
            doc = frappe.get_doc("Item Price", result.name)
           
            pl_supabase_id = frappe.db.get_value("Price List", result.price_list, "custom_supabase_id")
            if not is_valid_uuid(pl_supabase_id):
                pl_supabase_id = str(uuid.uuid4())
                frappe.db.set_value(
                    "Price List",
                    result.price_list,
                    "custom_supabase_id",
                    pl_supabase_id,
                    update_modified=False
                )
                from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.sync import sync_price_list                
                sync_price_list(name=result.price_list)
                 
            product_supabase_id = frappe.db.get_value("Item", {"name": doc.item_code, "custom_is_synced": 1}, "custom_supabase_id") 
            if not product_supabase_id:
                return {
                    "success": False,
                    "synced_count": 0,
                    "message": f"Item with code {doc.item_code} is not synced to Supabase"
                }

            doc.supabase_price_list_id = pl_supabase_id   
            doc.supabase_product_id = product_supabase_id   
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
                "message": f"No record found for Item Price with filters: {filters}"
            }    
            
    # Bulk synchronization
    record_names = frappe.get_all(
            "Item Price",
            filters = {
                # "price_list": ["!=","Standard Selling"],
                "selling": 1,
                "custom_is_synced": 0
            } ,
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
            doc = frappe.get_doc("Item Price", record_name)
            product_supabase_id = frappe.db.get_value("Item", {"name": doc.item_code, "custom_is_synced": 1}, "custom_supabase_id") 
            if not product_supabase_id:
                continue  # Skip if the item does not have a Supabase ID
                
            pl_supabase_id = frappe.db.get_value("Price List", doc.price_list, "custom_supabase_id")
            if not is_valid_uuid(pl_supabase_id):
                pl_supabase_id = str(uuid.uuid4())
                frappe.db.set_value(
                    "Price List",
                    doc.price_list,
                    "custom_supabase_id",
                    pl_supabase_id,
                    update_modified=False
                )
                from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.sync import sync_price_list                
                sync_price_list(name=doc.price_list)
                
            
            
            doc.supabase_price_list_id = pl_supabase_id
            doc.supabase_product_id = product_supabase_id
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
    
    
# prepare data of item price
def _prepare_item_price_data(record,supabase_id):
    data = {
        "id": supabase_id,
        "price_list_id": record.supabase_price_list_id,
        "product_id": record.supabase_product_id,
        "start_date": record.valid_from.isoformat() if record.valid_from else None,
        "end_date": record.valid_upto.isoformat() if record.valid_upto else None,
        "uom": record.uom,
        "price": record.price_list_rate,
    }
    return data
