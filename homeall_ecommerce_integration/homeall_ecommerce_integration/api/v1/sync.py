import frappe
import json
from frappe.utils import get_datetime
from supabase import create_client, Client
import uuid
from homeall_ecommerce_integration.controller import is_valid_uuid,slugify

def init_supabase():
    site_config = frappe.get_site_config()
    url = site_config.get("supabase_api_url")
    key = site_config.get("supabase_api_key")
    if not url:
        frappe.throw("Supabase API URL is not configured")

    if not key:
        frappe.throw("Supabase API key is not configured")
        
    supabase =  create_client(url, key)    
    return supabase

@frappe.whitelist(allow_guest=True, methods=["POST"])
def sync_data():  
    return {"message": "Sync process has been initiated."}


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
def sync_products():   
    currency = frappe.defaults.get_global_default("currency")   
    items = frappe.get_all("Item", 
                           filters={ "custom_is_synced": 0 }, 
                           fields=["*"]
                        )  
    ##
    item_group_names = list({
        row.item_group
        for row in items
        if row.item_group
    })
    ##
    item_groups = frappe.get_all("Item Group", 
                                filters={
                                    "name": ["in", item_group_names],
                                    # "custom_is_synced": 0 
                                }, 
                                fields=["*"])
    if item_groups:
        for group in item_groups:
            if not group.custom_is_synced:
                group.custom_supabase_id = upsert_item_group(group)
                
        item_group_map = {
            group.name: group
            for group in item_groups
        }
        for item in items:
            if item.item_group in item_group_map:
                item.item_group_id = item_group_map[item.item_group].custom_supabase_id
            else:
                item.item_group_id = None
                
    product_data_list = []        
    item_supabase_ids = []
    sup = init_supabase()  
    
    for item in items:  
        supabase_id = str(uuid.uuid4())
        if is_valid_uuid(item.get("custom_supabase_id")):
            supabase_id = item.get("custom_supabase_id")
            
        product_data = item_to_product(item,supabase_id,currency)  
        if product_data:
            product_data_list.append(product_data)
            item_supabase_ids.append({
                "name": item.name,
                "supabase_id": supabase_id
            })
    
    if product_data_list:
        try:
            response = (
                sup
                .table("products")
                .upsert(
                    product_data_list, 
                    on_conflict="id"
                ).execute()
            )
        
        
            if response.data:
                # Update Frappe only after successful Supabase upsert
                for item_data in item_supabase_ids:
                    frappe.db.set_value(
                        "Item",
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
        
    # Prevent infinite recursion if a circular parent relationship exists
    if group.name in visited:
        frappe.throw(
            f"Circular Item Group hierarchy detected at {group.name}"
        )

    visited.add(group.name)

    # Resolve and sync the parent first 
    parent_supabase_id = None
    if group.parent_item_group: 
        parent_group = frappe.get_doc(
            "Item Group",
            group.parent_item_group
        )
        parent_supabase_id = parent_group.get("custom_supabase_id")
        if not is_valid_uuid(parent_supabase_id):
            parent_supabase_id = None
            
                                
        # Sync parent first if it has not been synced or has no valid ID
        if (
            not parent_group.custom_is_synced
            or not parent_supabase_id
        ):
            parent_supabase_id = upsert_item_group(
                parent_group,
                visited
            )

            if not parent_supabase_id:
                frappe.throw(
                    f"Failed to sync parent Item Group: "
                    f"{parent_group.name}"
                )

            
            
    # Reuse existing UUID, otherwise create a new one
    supabase_id = group.get("custom_supabase_id")
    if not is_valid_uuid(supabase_id):
        supabase_id = str(uuid.uuid4())
        
    # Prepare payload
    group_data = prepare_item_group_data(
        group,
        supabase_id,
        parent_supabase_id
    )

    sup = init_supabase() 
    response = (
        sup
        .table("item_groups")
        .upsert(
            group_data, 
            on_conflict="id"
        ).execute()
    )
    
    if response.data:
        group.custom_is_synced = 1
        group.custom_supabase_id = supabase_id
        
        frappe.db.set_value(
            "Item Group",
            group.name,
            {
                "custom_is_synced": 1,
                "custom_supabase_id": supabase_id
            },
             update_modified=False
        )
        return supabase_id
    else:
        frappe.log_error(
            title="Supabase Sync Error",
            message=f"Failed to sync item group {group.name}: {response.data}"
        )
        return None
  

## Prepare Data for Supabase  
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
            photo_urls.append(str(f.file_url))
        

    modified = get_datetime(item.modified)
    
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
        "price": float(item.standard_rate or 0),
        "currency": currency, 
        "photos":photo_urls,
        "business_id": item.custom_business_profile,
        "erp_modified_at": modified.isoformat(),
        "is_new": bool(item.custom_is_new),
        "is_feature": bool(item.custom_is_feature),
        "is_publish": bool(item.custom_is_publish),
        "is_popular": bool(item.custom_is_popular),
    } 
    
    
    return data