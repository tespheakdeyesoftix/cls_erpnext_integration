frappe.ui.form.on('Item', {
    refresh(frm) {
       
        if (!frm.is_new()) {
            frm.page.add_menu_item(__('Sync Product to App Database'), function() {
                frappe.confirm(
                    __('Are you sure you want to sync this product?'),
                    function() {
                        frappe.call({
                            method: "homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.sync.sync_per_product",
                            args: {
                                item_code: frm.doc.item_code || frm.doc.name,
                                disabled: frm.doc.disabled || 0
                            },
                            freeze: true,
                            freeze_message: __('Syncing product...'),
                            callback: function(r) {
                                if (!r.exc) {
                                    frappe.show_alert({
                                        message: __('Product synced successfully.'),
                                        indicator: 'green'
                                    });
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                );
            });
        }
    }
});