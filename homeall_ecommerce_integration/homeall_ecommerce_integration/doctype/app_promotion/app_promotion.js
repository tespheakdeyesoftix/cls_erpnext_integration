// Copyright (c) 2026, Tes Pheakdey and contributors
// For license information, please see license.txt

const PROMOTION_SERVICE =
	"homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.app_promotion_sync";

const PROMOTION_RULE_TABLES = [
	{
		fieldname: "apply_for",
		label: "Apply For",
		doctype: "App Promotion Apply For",
		list_columns: { apply_for_type: 180, apply_for: 280, uom: 140, limit_qty: 120 },
	},
	{
		fieldname: "price_discount_slabs",
		label: "Price Discount Slabs",
		doctype: "App Promotion Price Discount Slabs",
		list_columns: { min_qty: 100, max_qty: 100, rate_or_discount: 220, price_or_discount_value: 200 },
	},
	{
		fieldname: "product_discount_slabs",
		label: "Product Discount Slabs",
		doctype: "App Promotion Product Discount Slabs",
		list_columns: { free_product: 280, min_qty: 100, free_product_qty: 180, unit: 140 },
	},
];

frappe.ui.form.on("App Promotion", {
	add_promotion_rule(frm) {
		return show_promotion_rule_dialog(frm);
	},

	promotion_rules(frm) {
		return render_promotion_rules(frm);
	},

	refresh(frm) {
		render_promotion_rules(frm);
		// if (frm.doc.docstatus == 0 || !frm.has_perm("write")) {
		// 	return;
		// }

		if (frm.doc.docstatus == 2) {
			frm.add_custom_button(
				__("Remove Promotion from App"),
				() => {
					frappe.confirm(
						__(
							"This action will disable the promotion in the app. If the promotion has no orders, its record will be deleted from the app database. Do you want to continue?"
						),
						() =>
							run_promotion_action(
								frm,
								"remove_promotion_from_app",
								__("Removing promotion from app..."),
								__("Promotion disabled or deleted from the App Database"),
								true
							)
					);
				},
				__("Sync to App Database")
			);
			return;
		}

		frm.add_custom_button(
			__("Submit to App Database (Supabase)"),
			() =>
				run_promotion_action(
					frm,
					"submit_to_app_database",
					__("Submitting promotion..."),
					__("Promotion submitted to the App Database"),
					true
				),
			__("Sync to App Database")
		);

		if (!frm.doc.is_synced) {
			return;
		}

		frm.add_custom_button(
			__("Generate Promotion Pricing Rules"),
			() =>
				run_promotion_action(
					frm,
					"generate_promotion_pricing_rules",
					__("Generating promotion pricing rules..."),
					__("Promotion pricing rules generated")
				),
			__("Sync to App Database")
		);

		frm.add_custom_button(
			__("Generate Notification to Customer / User"),
			() => {
				frappe.confirm(
					__(
						"Send this promotion notification now? Running this action again may notify customers more than once."
					),
					() =>
						run_promotion_action(
							frm,
							"notify_promotion_users",
							__("Sending promotion notifications..."),
							__("Promotion notifications generated")
						)
				);
			},
			__("Sync to App Database")
		);
	},
});

function run_promotion_action(frm, method, freeze_message, success_message, reload = false) {
	return frappe
		.call({
			method: `${PROMOTION_SERVICE}.${method}`,
			args: { name: frm.doc.name },
			freeze: true,
			freeze_message,
		})
		.then(async () => {
			if (reload) {
				await frm.reload_doc();
			}
			frappe.show_alert({ message: success_message, indicator: "green" });
		});
}

function promotion_rules_can_edit(frm) {
	return (
		frm.doc.docstatus === 0 &&
		!frm.read_only &&
		frm.has_perm("write")
	);
}

function read_promotion_rules(value) {
	if (value == null || (typeof value === "string" && !value.trim())) return [];
	let rules;
	try {
		rules = typeof value === "string" ? JSON.parse(value) : value;
		// Dialogs and mutations must never share objects with frm.doc.
		rules = JSON.parse(JSON.stringify(rules));
	} catch {
		throw new Error(__("Promotion Rules must contain a valid JSON array."));
	}
	if (
		!Array.isArray(rules) ||
		rules.some(
			(rule) =>
				!rule ||
				typeof rule !== "object" ||
				Array.isArray(rule) ||
				PROMOTION_RULE_TABLES.some(({ fieldname }) =>
					rule[fieldname] !== undefined &&
					(!Array.isArray(rule[fieldname]) ||
						rule[fieldname].some(
							(row) => !row || typeof row !== "object" || Array.isArray(row)
						))
				)
		)
	) {
		throw new Error(__("Promotion Rules must be an array of rules containing row arrays."));
	}
	return rules;
}

function promotion_rule_error(error) {
	frappe.msgprint({
		title: __("Promotion Rules"),
		message: frappe.utils.escape_html(error?.message || __("Unable to update promotion rules.")),
		indicator: "red",
	});
}

function promotion_rule_number(value) {
	const number = Number(value || 0);
	if (!Number.isFinite(number)) {
		throw new Error(__("Numeric fields must contain finite numbers."));
	}
	return number;
}

function promotion_rule_bounds(row) {
	return {
		min_qty: promotion_rule_number(row.min_qty),
		max_qty: promotion_rule_number(row.max_qty) || null,
		min_amount: promotion_rule_number(row.min_amount),
		max_amount: promotion_rule_number(row.max_amount) || null,
	};
}

async function promotion_rule_payload(values, tables) {
	for (const table of tables) {
		for (const [index, row] of (values[table.fieldname] || []).entries()) {
			for (const field of table.fields) {
				const is_apply_uom = table.fieldname === "apply_for" && field.fieldname === "uom";
				const required = is_apply_uom ? row.apply_for_type === "Item" : field.reqd;
				const value = row[field.fieldname];
				if (required && (
					value == null || (typeof value === "string" && !value.trim()) ||
					(is_apply_uom && typeof value !== "string")
				)) {
					throw new Error(__("{0} row {1}: {2} is required.", [
						__(table.label), index + 1, __(field.label),
					]));
				}
			}
		}
	}

	const lookups = new Map();
	async function uuid(doctype, name, label, index) {
		if (!["Item", "Item Group"].includes(doctype) || !name) {
			throw new Error(__("{0} row {1}: select a valid Item or Item Group.", [__(label), index + 1]));
		}
		const key = `${doctype}:${name}`;
		if (!lookups.has(key)) {
			lookups.set(key, frappe.db.get_value(doctype, name, "custom_supabase_id"));
		}
		const id = (await lookups.get(key)).message?.custom_supabase_id;
		if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id || "")) {
			throw new Error(__("{0} row {1}: {2} has no valid Supabase UUID. Update its local record first.", [
				__(label), index + 1, name,
			]));
		}
		return id;
	}

	const apply_for = await Promise.all((values.apply_for || []).map(async (row, index) => ({
		apply_for: await uuid(row.apply_for_type, row.apply_for, "Apply For", index),
		apply_for_type: row.apply_for_type,
		uom: row.apply_for_type === "Item" ? row.uom.trim() : "",
		limit_qty: promotion_rule_number(row.limit_qty),
		max_qty_per_user: promotion_rule_number(row.max_qty_per_user),
		max_qty_per_order: promotion_rule_number(row.max_qty_per_order),
	})));
	const price_discount_slabs = (values.price_discount_slabs || []).map((row, index) => {
		if (!["Rate", "Discount Percentage", "Discount Amount"].includes(row.rate_or_discount)) {
			throw new Error(__("Price Discount Slabs row {0}: select a Discount Type.", [index + 1]));
		}
		const value = promotion_rule_number(row.price_or_discount_value);
		return {
			...promotion_rule_bounds(row),
			rate_or_discount: row.rate_or_discount,
			rate: row.rate_or_discount === "Rate" ? value : 0,
			discount_amount: row.rate_or_discount === "Discount Amount" ? value : 0,
			discount_percentage: row.rate_or_discount === "Discount Percentage" ? value : 0,
		};
	});
	const product_discount_slabs = await Promise.all((values.product_discount_slabs || []).map(async (row, index) => ({
		...promotion_rule_bounds(row),
		free_product_id: await uuid("Item", row.free_product, "Product Discount Slabs", index),
		free_product_unit: row.unit || "",
		free_product_quantity: promotion_rule_number(row.free_product_qty),
		free_is_recursive: Boolean(promotion_rule_number(row.is_recursive)),
		recurse_for: promotion_rule_number(row.recurse_for),
		apply_recursion_over: promotion_rule_number(row.apply_recursion_over),
	})));
	return { apply_for, price_discount_slabs, product_discount_slabs };
}

async function promotion_rule_references(rules) {
	const references = new Map();
	function add(doctype, id) {
		if (["Item", "Item Group"].includes(doctype) && id) {
			if (!references.has(doctype)) references.set(doctype, new Set());
			references.get(doctype).add(id);
		}
	}
	for (const rule of rules) {
		for (const row of rule.apply_for || []) add(row.apply_for_type, row.apply_for);
		for (const row of rule.product_discount_slabs || []) add("Item", row.free_product_id);
	}
	const records = new Map();
	await Promise.all(Array.from(references, async ([doctype, ids]) => {
		// xcall rejects on read/permission failures; db.get_list only resolves its success callback.
		const rows = await frappe.xcall("frappe.client.get_list", {
			doctype,
			filters: { custom_supabase_id: ["in", Array.from(ids)] },
			fields: ["name", "custom_supabase_id", ...(doctype === "Item" ? ["item_name", "stock_uom"] : [])],
			limit_page_length: ids.size,
		});
		for (const row of rows || []) records.set(`${doctype}:${row.custom_supabase_id}`, row);
	}));
	return records;
}

function promotion_rule_dialog_values(rule, references) {
	const warnings = [];
	function name(doctype, id, label, index) {
		const record = references.get(`${doctype}:${id}`);
		if (!record) {
			warnings.push(__("{0} row {1}: cannot resolve {2}. Select the record again before saving.", [
				__(label), index + 1, id || __("missing UUID"),
			]));
		}
		return record?.name || "";
	}
	return {
		warnings,
		apply_for: (rule?.apply_for || []).map((row, index) => ({
			apply_for_type: row.apply_for_type,
			apply_for: name(row.apply_for_type, row.apply_for, "Apply For", index),
			uom: row.apply_for_type === "Item"
				? (typeof row.uom === "string" && row.uom.trim() ? row.uom : references.get(`Item:${row.apply_for}`)?.stock_uom || "")
				: "",
			limit_qty: row.limit_qty,
			max_qty_per_user: row.max_qty_per_user,
			max_qty_per_order: row.max_qty_per_order,
		})),
		price_discount_slabs: (rule?.price_discount_slabs || []).map((row) => ({
			...promotion_rule_bounds(row),
			rate_or_discount: row.rate_or_discount,
			price_or_discount_value: {
				Rate: row.rate,
				"Discount Amount": row.discount_amount,
				"Discount Percentage": row.discount_percentage,
			}[row.rate_or_discount] ?? 0,
		})),
		product_discount_slabs: (rule?.product_discount_slabs || []).map((row, index) => ({
			...promotion_rule_bounds(row),
			free_product: name("Item", row.free_product_id, "Product Discount Slabs", index),
			unit: row.free_product_unit,
			free_product_qty: row.free_product_quantity,
			is_recursive: row.free_is_recursive ? 1 : 0,
			recurse_for: row.recurse_for,
			apply_recursion_over: row.apply_recursion_over,
		})),
	};
}

function promotion_rule_control_row(control) {
	return control.doc || control.grid_row?.doc || control.layout?.grid_row?.doc;
}

function promotion_rule_set_row_value(control, fieldname, value) {
	const row = promotion_rule_control_row(control);
	row[fieldname] = value;
	const grid_row = control.grid_row || control.layout?.grid_row;
	grid_row?.refresh_field(fieldname);
	grid_row?.refresh_dependency();
}

function promotion_rule_table_fields(table, pending_defaults) {
	const fields = frappe.get_meta(table.doctype).fields.map((field) => ({ ...field }));
	if (table.fieldname === "apply_for") {
		let uom = fields.find((field) => field.fieldname === "uom");
		if (!uom) {
			// Keep the dialog usable while the site's child DocType metadata is cached.
			uom = { fieldname: "uom", fieldtype: "Link", label: __("UOM"), options: "UOM" };
			fields.splice(fields.findIndex((field) => field.fieldname === "apply_for") + 1, 0, uom);
		}
		Object.assign(uom, {
			reqd: 0,
			mandatory_depends_on: "eval:doc.apply_for_type == 'Item'",
			read_only_depends_on: "eval:doc.apply_for_type != 'Item'",
		});
		const type = fields.find((field) => field.fieldname === "apply_for_type");
		type.get_query = () => ({ filters: { name: ["in", ["Item", "Item Group"]] } });
		// Dialog rows share docfields. Define change directly so Frappe does not wrap
		// onchange in a closure bound to the first row's control.
		type.change = function () {
			promotion_rule_set_row_value(this, "apply_for", "");
			promotion_rule_set_row_value(this, "uom", "");
		};
		const target = fields.find((field) => field.fieldname === "apply_for");
		target.get_options = (control) =>
			promotion_rule_control_row(control)?.apply_for_type || "";
		target.change = function () {
			const row = promotion_rule_control_row(this);
			const product = row.apply_for;
			promotion_rule_set_row_value(this, "uom", "");
			if (row.apply_for_type !== "Item" || !product) return;
			const pending = frappe.db.get_value("Item", product, "stock_uom")
				.then(({ message }) => {
					if (row.apply_for_type === "Item" && row.apply_for === product && !row.uom) {
						promotion_rule_set_row_value(this, "uom", message?.stock_uom || "");
					}
				})
				.catch(promotion_rule_error);
			pending_defaults.add(pending);
			pending.finally(() => pending_defaults.delete(pending));
		};
	}
	if (table.fieldname === "product_discount_slabs") {
		fields.find((field) => field.fieldname === "free_product").change = function () {
			const row = promotion_rule_control_row(this);
			const product = row.free_product;
			promotion_rule_set_row_value(this, "unit", "");
			if (!product) return;
			const pending = frappe.db.get_value("Item", product, "stock_uom")
				.then(({ message }) => {
					if (row.free_product === product && !row.unit) {
						promotion_rule_set_row_value(this, "unit", message?.stock_uom || "");
					}
				})
				.catch(promotion_rule_error);
			pending_defaults.add(pending);
			pending.finally(() => pending_defaults.delete(pending));
		};
	}
	// Limit the grid preview; keep every field available in Frappe's row editor.
	for (const field of fields) {
		field.in_list_view = table.list_columns[field.fieldname] ? 1 : 0;
		if (field.in_list_view) field.width = table.list_columns[field.fieldname];
	}
	return fields;
}

async function write_promotion_rules(frm, rules, snapshot) {
	if (!promotion_rules_can_edit(frm)) {
		throw new Error(__("Promotion rules can only be changed on a writable draft."));
	}
	if (JSON.stringify(read_promotion_rules(frm.doc.promotion_rules)) !== snapshot) {
		throw new Error(__("Promotion Rules changed while this action was open. Reopen it and try again."));
	}
	const ids = new Set();
	const updated = rules.map((rule) => {
		let id = rule.id;
		if (typeof id !== "string" || !id || ids.has(id)) {
			id = typeof crypto.randomUUID === "function"
				? crypto.randomUUID()
				: "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (digit) =>
					(Number(digit) ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (Number(digit) / 4)))).toString(16)
				);
		}
		ids.add(id);
		return { ...rule, id };
	});
	await frm.set_value("promotion_rules", JSON.stringify(updated, null, 2));
}

async function show_promotion_rule_dialog(frm, index) {
	if (
		!promotion_rules_can_edit(frm) ||
		frm.__promotion_rule_opening ||
		frm.__promotion_rule_dialog?.is_visible ||
		frm.__promotion_rule_dialog?.display
	) return;
	frm.__promotion_rule_opening = true;
	try {
		const rules = read_promotion_rules(frm.doc.promotion_rules);
		const snapshot = JSON.stringify(rules);
		const rule = index === undefined ? null : rules[index];
		if (index !== undefined && !rule) return;
		const [, references] = await Promise.all([
			Promise.all(PROMOTION_RULE_TABLES.map(({ doctype }) => frappe.model.with_doctype(doctype))),
			promotion_rule_references(rule ? [rule] : []),
		]);
		const values = promotion_rule_dialog_values(rule, references);
		const pending_defaults = new Set();
		const tables = PROMOTION_RULE_TABLES.map((table) => ({
			fieldtype: "Table",
			fieldname: table.fieldname,
			label: __(table.label),
			// Allow Frappe to show its pencil icon and expand the complete row form.
			in_place_edit: false,
			description: __("Click the edit icon in a row to edit all fields."),
			// Use independent dialog fields/data, without attaching a child DocType to the grid.
			fields: promotion_rule_table_fields(table, pending_defaults),
			data: values[table.fieldname],
		}));
		let saving = false;
		const dialog = new frappe.ui.Dialog({
			title: __("Add Promotion Rule"),
			size: "extra-large",
			onhide() {
				if (frm.__promotion_rule_dialog === dialog) frm.__promotion_rule_dialog = null;
			},
			fields: [
				...(values.warnings.length ? [{
					fieldtype: "HTML",
					fieldname: "unresolved_references",
					options: `<div class="alert alert-warning">${values.warnings.map((warning) =>
						frappe.utils.escape_html(warning)).join("<br>")}</div>`,
				}] : []),
				...tables,
			],
			primary_action_label: __("Save"),
			async primary_action() {
				if (saving) return;
				saving = true;
				dialog.get_primary_btn().prop("disabled", true);
				try {
					await Promise.all(Array.from(pending_defaults));
					const data = dialog.get_values();
					if (!data) return;
					const payload = await promotion_rule_payload(JSON.parse(JSON.stringify(data)), tables);
					if (frm.__promotion_rule_dialog !== dialog) return;
					const updated = index === undefined
						? [...rules, payload]
						: rules.map((existing, position) => position === index ? { ...rule, ...payload } : existing);
					await write_promotion_rules(frm, updated, snapshot);
					dialog.hide();
				} catch (error) {
					promotion_rule_error(error);
				} finally {
					saving = false;
					dialog.get_primary_btn().prop("disabled", false);
				}
			},
		});
		frm.__promotion_rule_dialog = dialog;
		dialog.show();
	} catch (error) {
		promotion_rule_error(error);
	} finally {
		frm.__promotion_rule_opening = false;
	}
}

function delete_promotion_rule(frm, index) {
	if (!promotion_rules_can_edit(frm)) return;
	try {
		const rules = read_promotion_rules(frm.doc.promotion_rules);
		if (!rules[index]) return;
		const snapshot = JSON.stringify(rules);
		frappe.confirm(__("Delete promotion rule {0}?", [index + 1]), async () => {
			try {
				await write_promotion_rules(frm, rules.filter((rule, position) => position !== index), snapshot);
			} catch (error) {
				promotion_rule_error(error);
			}
		});
	} catch (error) {
		promotion_rule_error(error);
	}
}

function promotion_rule_html(rules, references, editable, expanded = new Set()) {
	const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
	const label = (doctype, id) => {
		const record = references.get(`${doctype}:${id}`);
		return record ? [record.name, record.item_name].filter(Boolean).join(" · ") : id || "";
	};
	const table = (title, headers, rows) => `
		<h6 class="mt-3">${escape(__(title))}</h6>
		${rows.length ? `<div class="table-responsive"><table class="table table-bordered table-sm mb-0">
			<thead><tr>${headers.map((header) => `<th>${escape(__(header))}</th>`).join("")}</tr></thead>
			<tbody>${rows.map((row) => `<tr>${row.map((value) => `<td>${escape(value)}</td>`).join("")}</tr>`).join("")}</tbody>
		</table></div>` : `<p class="text-muted small">${escape(__("No rows"))}</p>`}`;
	const bounds = (row) => [row.min_qty ?? 0, row.max_qty || __("No limit"), row.min_amount ?? 0, row.max_amount || __("No limit")];
	const range_headers = ["Min Qty", "Max Qty", "Min Amount", "Max Amount"];
	if (!rules.length) return `<p class="text-muted">${escape(__("No promotion rules added yet."))}</p>`;
	return rules.map((rule, index) => {
		const key = typeof rule.id === "string" && rule.id ? `id:${rule.id}` : `index:${index}`;
		return `
		<details class="border rounded mb-3" data-rule-key="${escape(key)}"${expanded.has(key) ? " open" : ""}>
			<summary class="p-3" style="cursor: pointer;">
				<strong>${escape(__("Promotion Rule {0}", [index + 1]))}</strong>
				${editable ? `<span class="float-right">
					<button type="button" class="btn btn-default btn-xs" data-rule-action="edit" data-rule-index="${index}">${escape(__("Edit"))}</button>
					<button type="button" class="btn btn-danger btn-xs" data-rule-action="delete" data-rule-index="${index}">${escape(__("Delete"))}</button>
				</span>` : ""}
			</summary>
			<div class="px-3 pb-3">
			${table("Apply For", ["Apply For Type", "Apply For", "UOM", "Limit Qty", "Max Qty Per Order", "Max Qty Per User"],
				(rule.apply_for || []).map((row) => [row.apply_for_type, label(row.apply_for_type, row.apply_for), row.apply_for_type === "Item" ? row.uom : "", row.limit_qty ?? 0, row.max_qty_per_order ?? 0, row.max_qty_per_user ?? 0]))}
			${table("Price Discount Slabs", [...range_headers, "Discount Type", "Price or Discount Value"],
				(rule.price_discount_slabs || []).map((row) => [...bounds(row), row.rate_or_discount,
					{ Rate: row.rate, "Discount Percentage": row.discount_percentage, "Discount Amount": row.discount_amount }[row.rate_or_discount] ?? 0]))}
			${table("Product Discount Slabs", ["Free Product", ...range_headers, "Free Product Qty", "Unit", "Is Recursive", "Recurse Every", "Apply Recursion Over"],
				(rule.product_discount_slabs || []).map((row) => [label("Item", row.free_product_id), ...bounds(row), row.free_product_quantity ?? 0,
					row.free_product_unit, row.free_is_recursive ? __("Yes") : __("No"), row.recurse_for ?? 0, row.apply_recursion_over ?? 0]))}
			</div>
		</details>`;
	}).join("");
}

async function render_promotion_rules(frm) {
	const editable = promotion_rules_can_edit(frm);
	frm.toggle_display("add_promotion_rule", editable);
	const wrapper = frm.fields_dict.html_promotion_rule_display?.$wrapper;
	if (!wrapper) return;
	const render_id = (frm.__promotion_rules_render_id || 0) + 1;
	frm.__promotion_rules_render_id = render_id;
	wrapper.off("click.promotion-rules");
	let rendered = false;
	try {
		const rules = read_promotion_rules(frm.doc.promotion_rules);
		const display = (references) => {
			// Keep open cards expanded when item-name lookups finish or rules refresh.
			const expanded = new Set(Array.from(
				wrapper[0]?.querySelectorAll("details[data-rule-key][open]") || [],
				(element) => element.dataset.ruleKey
			));
			wrapper.html(promotion_rule_html(rules, references, promotion_rules_can_edit(frm), expanded));
		};
		display(new Map());
		rendered = true;
		wrapper.on("click.promotion-rules", "[data-rule-action]", (event) => {
			const button = event.currentTarget;
			const index = Number(button.dataset.ruleIndex);
			if (button.dataset.ruleAction === "edit") show_promotion_rule_dialog(frm, index);
			else delete_promotion_rule(frm, index);
		});
		const references = await promotion_rule_references(rules);
		if (frm.__promotion_rules_render_id === render_id) {
			display(references);
		}
	} catch (error) {
		if (frm.__promotion_rules_render_id !== render_id) return;
		const message = `<p class="text-danger">${frappe.utils.escape_html(error.message || __("Unable to load item names."))}</p>`;
		if (rendered) wrapper.prepend(message);
		else wrapper.html(message);
	}
}
