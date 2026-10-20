import frappe
import json
from frappe.utils import get_datetime
import uuid
from homeall_ecommerce_integration.controller import is_valid_uuid,slugify
from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1 import fn_sync_to_supabase as sync
from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1 import app_promotion_sync as app_promotion
from postgrest.exceptions import APIError

init_supabase = sync.init_supabase

@frappe.whitelist(methods=["POST"])
def sync_data():
    frappe.only_for("System Manager")
    return sync_price_list()

## sync price list
def sync_price_list(name: str = None, batch_size: int = 100): 
    return sync.sync_to_supabase(
        doctype="Price List",
        table_name="price_lists",
        prepare_data=prepare_price_list_data,
        name=name,
        batch_size=batch_size,
        sync_field="custom_is_synced",
        uuid_field="custom_supabase_id"
    )
    
def sync_price_list_queues(): 
    frappe.enqueue(
        "homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.sync.sync_price_list", # python function or a module path as string
        queue="short", # one of short, default, long
        job_name="sync_price_list", # specify a job name
        # enqueue_after_commit=True,
    )  
## end sync price list

## sync app user type
def sync_app_user_types(name: str = None, batch_size: int = 100):     
    return sync.sync_to_supabase(
        doctype="App User Type",
        table_name="user_types",
        prepare_data=prepare_app_user_type_data,
        name=name,
        batch_size=batch_size,
        sync_field="is_synced"
    ) 
    

def sync_app_user_types_queues(): 
    frappe.enqueue(
        "homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.sync.sync_app_user_types", # python function or a module path as string
        queue="short", # one of short, default, long
        job_name="sync_app_user_types", # specify a job name
        # enqueue_after_commit=True,
    )
##end sync app user type

#sync business type
def sync_business_types():
    business_types = frappe.get_all("Business Type", 
                                filters={
                                    "is_synced": 0 
                                }, 
                                fields=["*"])
    if business_types:    
        data_list = []        
        item_supabase_ids = []
        sup = init_supabase()  
            
        for bt in business_types:
            data = prepare_business_type_data(bt)  
            data_list.append(data)
            item_supabase_ids.append({ "name": bt.name}) 
            
        if data_list:
            try:
                response = (
                    sup
                    .table("business_types")
                    .upsert(
                        data_list, 
                        on_conflict="id"
                    ).execute()
                )       
            
                if response.data:
                    # Update Frappe only after successful Supabase upsert
                    for item_data in item_supabase_ids:
                        frappe.db.set_value(
                            "Business Type",
                            item_data["name"],
                            {
                                "is_synced": 1,
                            },
                            update_modified=False
                        )

                    frappe.db.commit()
                else:
                    frappe.log_error(
                        title="Supabase Bulk Sync Error",
                        message=f"Supabase returned no data: {response}"
                    )
            except Exception:
                frappe.log_error(
                    title="Supabase Bulk Sync Error",
                    message=frappe.get_traceback()
                )
                raise

def sync_business_types_queues(): 
    frappe.enqueue(
        "homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.sync.sync_business_types", # python function or a module path as string
        queue="long", # one of short, default, long
        job_name="sync_business_types", # specify a job name
        # enqueue_after_commit=True,
    )   
    
# sync business profile
def sync_business_profiles():
    sync_business_types()
        
    business_profiles = frappe.get_all("Business Profile", 
                                filters={
                                    "is_synced": 0 
                                }, 
                                fields=["*"])
    if business_profiles:    
        data_list = []        
        item_supabase_ids = []
        sup = init_supabase()          
        for bp in business_profiles:
            data = prepare_business_profile_data(bp)
            data_list.append(data)
            item_supabase_ids.append({ "name": bp.name})     
            
        if data_list:
            try:
                response = (
                    sup
                    .table("business_profiles")
                    .upsert(
                        data_list, 
                        on_conflict="id"
                    ).execute()
                )       
            
                if response.data:
                    # Update Frappe only after successful Supabase upsert
                    for item_data in item_supabase_ids:
                        frappe.db.set_value(
                            "Business Profile",
                            item_data["name"],
                            {
                                "is_synced": 1,
                            },
                            update_modified=False
                        )

                    frappe.db.commit()
                else:
                    frappe.log_error(
                        title="Supabase Bulk Sync Error",
                        message=f"Supabase returned no data: {response}"
                    )
            except Exception:
                frappe.log_error(
                    title="Supabase Bulk Sync Error",
                    message=frappe.get_traceback()
                )
                raise         

def sync_business_profiles_queues(): 
    frappe.enqueue(
        "homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.sync.sync_business_profiles", # python function or a module path as string
        queue="long", # one of short, default, long
        job_name="sync_business_profiles", # specify a job name
        # enqueue_after_commit=True,
    )   

# sync brand
def sync_brands():
    brands = frappe.get_all("Brand", 
                            filters={
                                "custom_is_synced": 0 
                            }, 
                            fields=["*"]) 
            
    if brands:    
        data_list = []        
        item_supabase_ids = []
        sup = init_supabase()  
                    
        for brand in brands:
            supabase_id = str(uuid.uuid4())
            if is_valid_uuid(brand.get("custom_supabase_id")):
                supabase_id = brand.get("custom_supabase_id")
                
            data = prepare_brand_data(brand,supabase_id)  
            data_list.append(data)
            item_supabase_ids.append({
                "name": brand.name,
                "supabase_id": supabase_id
            })
        # return data_list
            
        if data_list:
            try:
                response = (
                    sup
                    .table("brands")
                    .upsert(
                        data_list, 
                        on_conflict="id"
                    ).execute()
                )       
            
                if response.data:
                    # Update Frappe only after successful Supabase upsert
                    for item_data in item_supabase_ids:
                        frappe.db.set_value(
                            "Brand",
                            item_data["name"],
                            {
                                "custom_is_synced": 1,
                                "custom_supabase_id": item_data["supabase_id"]
                            },
                            update_modified=False
                        )

                    frappe.db.commit()
                    
                else:
                    frappe.log_error(
                        title="Supabase Bulk Sync Error",
                        message=f"Supabase returned no data: {response}"
                    )
                    
            except Exception:
                frappe.log_error(
                    title="Supabase Bulk Sync Error",
                    message=frappe.get_traceback()
                )
                raise

def sync_brands_queues(): 
    frappe.enqueue(
        "homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.sync.sync_brands", # python function or a module path as string
        queue="long", # one of short, default, long
        job_name="sync_brands", # specify a job name
        # enqueue_after_commit=True,
    )   
    
# sync product group
def sync_item_groups():
    item_groups = frappe.get_all(
        "Item Group",
        filters={"custom_is_synced": 0},
        fields=["name"]
    )

    for row in item_groups:
        try:
            group = frappe.get_doc("Item Group", row.name)
            upsert_item_group(group)
        except Exception:
            frappe.log_error(
                title="Item Group Sync Error",
                message=frappe.get_traceback()
            )
        
def sync_item_groups_queues(): 
    frappe.enqueue(
        "homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.sync.sync_item_groups", # python function or a module path as string
        queue="long", # one of short, default, long
        job_name="sync_item_groups", # specify a job name
        # enqueue_after_commit=True,
    )       

# sync products
def sync_products(batch_size=100):   
    currency = frappe.defaults.get_global_default("currency")   
    items = frappe.db.sql("""
        SELECT *
        FROM `tabItem`
        WHERE IFNULL(custom_is_synced, 0) = 0
        AND custom_business_profile IS NOT NULL
        AND TRIM(custom_business_profile) != ''
    """, as_dict=True)  
    
    if not items:
        return {
            "success": True,
            "synced_count": 0,
            "message": "No products to synchronize.",
        }
        
    sup = init_supabase()   
    
    # Collect Item Groups referenced by products.
    item_group_names = list({
        row.item_group
        for row in items
        if row.item_group
    })
    item_group_map = {}
    
    # --------------------------------------------------
    # 1. Synchronize Item Groups first
    # --------------------------------------------------
    if item_group_names:
        item_groups = frappe.get_all("Item Group", 
                                    filters={
                                        "name": ["in", item_group_names],
                                    }, 
                                    fields=["*"])
        # Include parent groups recursively through upsert_item_group().
        for group in item_groups:
            group_id = upsert_item_group(group)
            if not is_valid_uuid(group_id):
                frappe.throw(
                    f"Failed to synchronize Item Group: {group.name}"
                )
                                
            item_group_map[group.name] = group_id
   
    # --------------------------------------------------
    # 2. Prepare product payloads
    # --------------------------------------------------
    product_data_list = []        
    item_supabase_ids = []
    sup = init_supabase()       
    
    for item in items:  
        supabase_id = item.custom_supabase_id
        # Reuse an existing valid UUID.
        if not is_valid_uuid(supabase_id):
            supabase_id = str(uuid.uuid4())
            # Persist the ID before the remote request.
            frappe.db.set_value(
                "Item",
                item.name,
                "custom_supabase_id",
                supabase_id,
                update_modified=False,
            )
        
        # Resolve the Item Group's Supabase UUID.
        item_group_id = item_group_map.get(item.item_group)
        
        item_doc = frappe.get_doc("Item", item.name)
        
        # Provide the mapped ID expected by item_to_product().
        item_doc.item_group_id = item_group_id
        
        product_data = item_to_product(
            item_doc,
            supabase_id,
            currency,
        )
        
        if not product_data:
            continue
        
        # Never send a group ID that has not been resolved.
        if product_data.get("item_group_id") and not item_group_id:
            frappe.throw(
                f"Unable to resolve Supabase Item Group ID "
                f"for Item {item.name}, "
                f"Item Group {item.item_group}"
            )
        
        product_data_list.append(product_data)
        item_supabase_ids.append({
            "name": item.name,
            "supabase_id": supabase_id
        })
        
    # Persist UUID assignments before remote product upserts.
    frappe.db.commit()
        
    if not product_data_list:
        return {
            "success": True,
            "synced_count": 0,
            "message": "No valid product data to synchronize.",
        }

    # --------------------------------------------------
    # 3. Upload products in batches
    # --------------------------------------------------
    
    total_synced = 0
    
    for start in range(0, len(product_data_list), batch_size):
        batch_data = product_data_list[start:start + batch_size]

        batch_items = item_supabase_ids[
            start:start + batch_size
        ] 
        
        try:
            response = (
                sup
                .table("products")
                .upsert(
                    batch_data, 
                    on_conflict="id"
                ).execute()
            )   
            
            # Update Frappe only after successful upsert.
            for item_data in batch_items:
                frappe.db.set_value(
                    "Item",
                    item_data["name"],
                    {
                        "custom_is_synced": 1,
                        "custom_supabase_id": item_data["supabase_id"],
                    },
                    update_modified=False,
                )
                
            frappe.db.commit()
            total_synced += len(batch_items)
            
        except APIError as e:
            frappe.db.rollback()

            error_details = {
                "message": str(e),
                "code": getattr(e, "code", None),
                "details": getattr(e, "details", None),
                "hint": getattr(e, "hint", None),
                "batch_start": start,
                "product_count": len(batch_items),
                "data": batch_data,
            }

            frappe.log_error(
                title="Supabase Product API Error",
                message=json.dumps(
                    error_details,
                    indent=2,
                    default=str,
                ),
            )
            print(error_details)

            raise
                    
        except Exception:
            frappe.db.rollback()

            frappe.log_error(
                title="Supabase Product Sync Error",
                message=(
                    f"Batch starting at index {start}\n"
                    f"Product count: {len(batch_items)}\n\n"
                    f"{frappe.get_traceback()}"
                ),
            )

            raise
        
    return {
        "success": True,
        "synced_count": total_synced,
        "total_products": len(product_data_list),
    }


def sync_products_queues(): 
    frappe.enqueue(
        "homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.sync.sync_products", # python function or a module path as string
        queue="long", # one of short, default, long
        job_name="sync_product", # specify a job name
        # enqueue_after_commit=True,
    )

# method to upsert item group
def upsert_item_group(group,visited=None):
    if visited is None:
        visited = set()
        
    # Accept either a document or a document name.
    if isinstance(group, str):
        group = frappe.get_doc("Item Group", group)

    group_name = group.name
        
    # Prevent circular parent relationships.
    if group_name in visited:
        frappe.throw(
            f"Circular Item Group hierarchy detected at {group.name}"
        )

    visited.add(group.name)

    try:
        parent_supabase_id = None
        # Synchronize the parent before the child.
        parent_name = group.get("parent_item_group")
        if parent_name:
            parent_supabase_id = upsert_item_group(
                parent_name,
                visited,
            )
            
            if not is_valid_uuid(parent_supabase_id):
                frappe.throw(
                    f"Failed to synchronize parent Item Group: "
                    f"{parent_name}"
                )
                
        # Reuse the existing UUID.
        supabase_id = group.get("custom_supabase_id")

        if not is_valid_uuid(supabase_id):
            supabase_id = str(uuid.uuid4())
        
        # Build the Supabase payload.
        group_data = prepare_item_group_data(
            group,
            supabase_id,
            parent_supabase_id,
        )
        
        sup = init_supabase()
        
        # Upsert even if Frappe says the group is already synced.
        (
            sup.table("item_groups")
            .upsert(
                group_data,
                on_conflict="id",
            )
            .execute()
        )
        
        # Update Frappe only after a successful request.
        frappe.db.set_value(
            "Item Group",
            group_name,
            {
                "custom_is_synced": 1,
                "custom_supabase_id": supabase_id,
            },
            update_modified=False,
        )

        group.custom_is_synced = 1
        group.custom_supabase_id = supabase_id

        return supabase_id
    
    except Exception:
        frappe.log_error(
            title="Supabase Item Group Sync Error",
            message=(
                f"Item Group: {group_name}\n\n"
                f"{frappe.get_traceback()}"
            ),
        )
        raise

    finally:
        visited.discard(group_name)
  

## Prepare Data for Supabase  
# prepare data of app user type
def prepare_price_list_data(record,supabase_id):
    data = {
        "id": supabase_id,
        "price_list_name": record.price_list_name
    }
    return data

# prepare data of app user type
def prepare_app_user_type_data(record):
    data = {
        "id": record.name,
        "name": record.title, 
        "is_active": not bool(record.disabled),
    }
    return data

# prepare data of business type
def prepare_business_type_data(record):
    data = {
        "id": record.name,
        "slug": slugify(record.business_type_name),
        "name": record.business_type_name, 
        "description": record.description or None,
        "sort_order": record.sort_order,
        "is_active": not bool(record.disabled),
    }
    return data
            
# prepare data of business profile
def prepare_business_profile_data(record):
    modified = get_datetime(record.modified)
    if record.photo:
        if record.photo.startswith("/files/") or record.photo.startswith("/private/files/") or record.photo.startswith("/api/method/frappe_s3_attachment"):
            record.photo = f"https://cloudsvr01.homeall.asia{record.photo}"
            
    data = {
        "id": record.name,
        "business_type_id": record.business_type,
        "erp_name": record.name,
        "name": record.business_name, 
        "phone": record.phone or None, 
        "email": record.email or None, 
        "address": record.address or None, 
        "description": record.description or None,
        "logo_url": record.photo or None,
        "sort_order": record.sort_order,
        "is_active": not bool(record.disabled),
        "erp_modified_at": modified.isoformat(),
        "is_new": bool(record.is_record_new),
        "is_publish": bool(record.is_publish),
        "is_feature": bool(record.is_feature),
    }
    return data

# prepare data of brand
def prepare_brand_data(record, supabase_id): 
    if record.image:
        if record.image.startswith("/files/") or record.image.startswith("/private/files/") or record.image.startswith("/api/method/frappe_s3_attachment"):
            record.image = f"https://cloudsvr01.homeall.asia{record.image}"
            
    data = {
        "id": supabase_id,
        "name": record.name, 
        "description": record.description or "",
        "image_url": record.image or None,
        "sort_order": record.custom_sort_order,
        "is_feature": bool(record.custom_is_feature),
        "is_publish": bool(record.custom_is_publish),
    }
    return data           

# prepare data of item group
def prepare_item_group_data(item_group, supabase_id, parent_supabase_id):
    if item_group.image:
        if item_group.image.startswith("/files/") or item_group.image.startswith("/private/files/") or item_group.image.startswith("/api/method/frappe_s3_attachment"):
            item_group.image = f"https://cloudsvr01.homeall.asia{item_group.image}"
            
    data = {
        "id": supabase_id,
        "parent_id": parent_supabase_id,
        "name": item_group.name,
        "image_url": item_group.image,
        "sort_order": item_group.custom_sort_order,
        "is_new": bool(item_group.custom_is_new),
        "is_active": bool(item_group.custom_is_active),
        "is_feature":bool(item_group.custom_is_feature),
        "background_color": item_group.custom_background_color,
    }
    return data

# prepare data of item to product
def item_to_product(item, supabase_id, currency):
    if not item.custom_business_profile:
        return None
    
    files = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Item",
            "attached_to_name": item.name,
        },
        fields=["file_name", "file_url", "is_private"],
    ) 
    
    photo_urls = []
    for f in files:
        if f.file_url:
            if f.file_url.startswith("/files/") or f.file_url.startswith("/private/files/") or f.file_url.startswith("/api/method/frappe_s3_attachment"):
                f.file_url = f"https://cloudsvr01.homeall.asia{f.file_url}" 
                
            photo_urls.append(str(f.file_url))
        

    modified = get_datetime(item.modified)
    
    if item.image:
        if item.image.startswith("/files/") or item.image.startswith("/private/files/") or item.image.startswith("/api/method/frappe_s3_attachment"):
            item.image = f"https://cloudsvr01.homeall.asia{item.image}"
            
    data = {
        "id": str(supabase_id) if supabase_id else None,
        "item_group_id": str(item.item_group_id) if item.item_group_id else None,
        "erp_item_code": item.item_code,
        "name": item.item_name,
        "description": item.description or None,
        "brand": item.brand or None,
        "uom": item.stock_uom or None,
        "default_image_url": item.image or None,
        "is_active": not bool(item.disabled),
        "is_stock_item": bool(item.is_stock_item),
        "currency": currency, 
        "photos":photo_urls,
        "business_id": item.custom_business_profile,
        "erp_modified_at": modified.isoformat(),
        "is_new": bool(item.custom_is_new),
        "is_feature": bool(item.custom_is_feature),
        "is_publish": bool(item.custom_is_publish),
        "is_popular": bool(item.custom_is_popular),
        "min_order_quantity": item.custom_min_order_quantity or 1,
        "show_free_delivery_badge": item.custom_show_free_delivery_badge or 0,
        "show_cod_badge": item.custom_show_cod_badge or 0,
        "availability_status": item.custom_availability_status or "in_stock"
    } 
    
    
    return data
