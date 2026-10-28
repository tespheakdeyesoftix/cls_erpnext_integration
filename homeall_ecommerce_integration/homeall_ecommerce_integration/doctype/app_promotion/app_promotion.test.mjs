import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";
import vm from "node:vm";

const script = readFileSync(new URL("./app_promotion.js", import.meta.url), "utf8");
const childTypes = ["apply_for", "price_discount_slabs", "product_discount_slabs"];
const metadata = Object.fromEntries(childTypes.map((type) => {
	const name = `app_promotion_${type}`;
	const meta = JSON.parse(readFileSync(new URL(`../${name}/${name}.json`, import.meta.url), "utf8"));
	return [meta.name, meta];
}));
const plain = (value) => JSON.parse(JSON.stringify(value));
const clone = plain;
const ids = {
	item: "0b64fbba-8065-4e61-bbb4-c3ef47cbe7e6",
	group: "25af9e4b-58e6-4c2f-8c38-6facdc2fa8d4",
	free: "1c7dd67d-6afb-4d58-a3d5-8f7d63fbf3e6",
};
const example = {
	apply_for: [
		{ apply_for: ids.item, uom: "Bag", limit_qty: 100, apply_for_type: "Item", max_qty_per_user: 0, max_qty_per_order: 0 },
		{ apply_for: ids.group, uom: "", limit_qty: 0, apply_for_type: "Item Group", max_qty_per_user: 0, max_qty_per_order: 0 },
	],
	price_discount_slabs: [
		{ rate: 0, max_qty: 10, min_qty: 1, max_amount: null, min_amount: 0, discount_amount: 0, rate_or_discount: "Discount Percentage", discount_percentage: 10 },
		{ rate: 0, max_qty: null, min_qty: 11, max_amount: null, min_amount: 0, discount_amount: 0, rate_or_discount: "Discount Percentage", discount_percentage: 20 },
	],
	product_discount_slabs: [
		{ max_qty: null, min_qty: 10, max_amount: null, min_amount: 0, recurse_for: 0, free_product_id: ids.free, free_is_recursive: false, free_product_unit: "Ton តោន", apply_recursion_over: 0, free_product_quantity: 1 },
	],
};

function harness(initial = "") {
	const dialogs = [];
	const messages = [];
	const confirmations = [];
	const reads = [];
	const meta = clone(metadata);
	let handlers;
	const records = {
		Item: [
			{ name: "000100427", item_name: "Cement", custom_supabase_id: ids.item, stock_uom: "Bag" },
			{ name: "FREE-ITEM", item_name: "Free cement", custom_supabase_id: ids.free, stock_uom: "Ton តោន" },
		],
		"Item Group": [{ name: "Cement ស៊ីម៉ង់", custom_supabase_id: ids.group }],
	};
	class Dialog {
		constructor(options) {
			Object.assign(this, options);
			this.fields_dict = Object.fromEntries(options.fields.map((field) => [field.fieldname, { df: field }]));
			dialogs.push(this);
		}
		show() { this.is_visible = true; }
		hide() { this.is_visible = false; this.onhide?.(); }
		get_values() {
			return Object.fromEntries(this.fields.filter((field) => field.fieldtype === "Table").map((field) => [field.fieldname, field.data]));
		}
		get_primary_btn() {
			return { prop: (key, value) => { this[key] = value; } };
		}
	}
	const wrapper = {
		content: "",
		handlers: new Map(),
		html(value) { this.content = value; return this; },
		prepend(value) { this.content = value + this.content; return this; },
		off(event) { this.handlers.delete(event); return this; },
		on(event, selector, callback) { this.handlers.set(event, callback); return this; },
		click(action, index) {
			this.handlers.get("click.promotion-rules")({ currentTarget: { dataset: { ruleAction: action, ruleIndex: String(index) } } });
		},
	};
	const frappe = {
		ui: { form: { on: (doctype, value) => { handlers = value; } }, Dialog },
		get_meta: (doctype) => meta[doctype],
		model: { with_doctype: async () => {} },
		utils: {
			escape_html: (value) => String(value).replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]),
		},
		db: {
			async get_value(doctype, name, fields) {
				reads.push({ doctype, name, fields });
				return { message: records[doctype]?.find((record) => record.name === name) || {} };
			},
		},
		async xcall(method, args) {
			assert.equal(method, "frappe.client.get_list");
			assert.equal(args.limit_page_length, args.filters.custom_supabase_id[1].length);
			return records[args.doctype].filter((record) => args.filters.custom_supabase_id[1].includes(record.custom_supabase_id));
		},
		msgprint: (message) => messages.push(message),
		confirm: (message, callback) => confirmations.push({ message, callback }),
	};
	const context = vm.createContext({
		frappe,
		crypto: webcrypto,
		__: (message, args = []) => message.replace(/\{(\d+)\}/g, (match, index) => args[index]),
	});
	vm.runInContext(script, context);
	const frm = {
		doc: { docstatus: 0, promotion_rules: initial, apply_for: [{ apply_for: "existing-child" }] },
		writable: true,
		has_perm: () => frm.writable,
		fields_dict: {
			promotion_rules: { get_status: () => frm.field_status || "Write" },
			html_promotion_rule_display: { $wrapper: wrapper },
		},
		toggle_display(fieldname, visible) { this.add_button_visible = visible; },
		writes: 0,
		async set_value(fieldname, value) {
			this.doc[fieldname] = value;
			this.writes++;
			await handlers.promotion_rules(this);
		},
		add_custom_button() {},
	};
	return {
		context, frappe, frm, wrapper, records, dialogs, messages, confirmations, reads, meta, handlers,
		async open(index) { await context.show_promotion_rule_dialog(frm, index); return dialogs.at(-1); },
		rules() { return JSON.parse(frm.doc.promotion_rules); },
	};
}

test("the supplied UUID payload survives editing, normal form persistence, and reopening", async () => {
	const h = harness(JSON.stringify([example]));
	const dialog = await h.open(0);
	assert.equal(dialog.title, "Add Promotion Rule");
	assert.equal(dialog.size, "extra-large");
	assert.equal(dialog.primary_action_label, "Save");
	const values = dialog.get_values();
	assert.equal(values.apply_for[0].apply_for, "000100427");
	assert.equal(values.apply_for[1].apply_for, "Cement ស៊ីម៉ង់");
	assert.equal(values.product_discount_slabs[0].free_product, "FREE-ITEM");
	await dialog.primary_action();
	const [saved] = h.rules();
	assert.match(saved.id, /^[0-9a-f-]{36}$/);
	const { id, ...payload } = saved;
	assert.deepEqual(payload, example);
	assert.deepEqual(h.frm.doc.apply_for, [{ apply_for: "existing-child" }]);
	const reopened = harness(h.frm.doc.promotion_rules);
	await (await reopened.open(0)).primary_action();
	assert.deepEqual(reopened.rules(), [saved]);
	assert.equal(h.messages.length, 0);
});

test("all discount types map their value exclusively and clear empty maximums", async () => {
	const h = harness();
	const dialog = await h.open();
	dialog.get_values().price_discount_slabs.push(...["Rate", "Discount Amount", "Discount Percentage"].map((type) => ({
		rate_or_discount: type, price_or_discount_value: "12.5", min_qty: "1", max_qty: "", max_amount: 0,
		doctype: "child", name: "temporary", idx: 1, parent: "promotion", discount_amount: 999,
	})));
	await dialog.primary_action();
	const slabs = h.rules()[0].price_discount_slabs;
	assert.deepEqual(slabs.map((row) => [row.rate, row.discount_amount, row.discount_percentage]), [[12.5, 0, 0], [0, 12.5, 0], [0, 0, 12.5]]);
	for (const row of slabs) {
		assert.equal(row.max_qty, null);
		assert.equal(row.max_amount, null);
		assert.equal(row.min_amount, 0);
		for (const key of ["doctype", "name", "idx", "parent", "price_or_discount_value"]) assert.equal(key in row, false);
	}
});

test("dialog metadata stays independent and dynamic links use their own row type", async () => {
	const h = harness(JSON.stringify([example]));
	const before = clone(h.meta);
	const dialog = await h.open(0);
	const table = dialog.fields_dict.apply_for.df;
	assert.equal(table.options, undefined);
	const type = table.fields.find((field) => field.fieldname === "apply_for_type");
	const target = table.fields.find((field) => field.fieldname === "apply_for");
	assert.deepEqual(plain(type.get_query().filters.name), ["in", ["Item", "Item Group"]]);
	assert.equal(target.get_options({ doc: table.data[0] }), "Item");
	assert.equal(target.get_options({ layout: { grid_row: { doc: table.data[1] } } }), "Item Group");
	type.change.call({ doc: table.data[1] });
	assert.equal(table.data[1].apply_for, "");
	assert.equal(table.data[0].apply_for, "000100427");
	assert.deepEqual(h.meta, before);
	assert.equal(dialog.fields_dict.price_discount_slabs.df.fields.find((field) => field.fieldname === "rate_or_discount").reqd, 1);
});

test("gift UOM defaults are awaited, user UOM overrides survive, and recursion stays boolean", async () => {
	const h = harness();
	const dialog = await h.open();
	const table = dialog.fields_dict.product_discount_slabs.df;
	const field = table.fields.find((field) => field.fieldname === "free_product");
	const row = { free_product: "FREE-ITEM", free_product_qty: 2, is_recursive: 1, recurse_for: 5, apply_recursion_over: 10 };
	table.data.push(row);
	field.change.call({ doc: row });
	await dialog.primary_action();
	assert.equal(h.rules()[0].product_discount_slabs[0].free_product_unit, "Ton តោន");
	assert.equal(h.rules()[0].product_discount_slabs[0].free_is_recursive, true);
	const edited = await h.open(0);
	const editedRow = edited.get_values().product_discount_slabs[0];
	editedRow.unit = "Bag";
	editedRow.is_recursive = "0";
	await edited.primary_action();
	assert.equal(h.rules()[0].product_discount_slabs[0].free_product_unit, "Bag");
	assert.equal(h.rules()[0].product_discount_slabs[0].free_is_recursive, false);
});

test("a delayed stock UOM cannot override a manual unit or a newer product selection", async () => {
	const h = harness();
	const dialog = await h.open();
	const field = dialog.fields_dict.product_discount_slabs.df.fields.find((entry) => entry.fieldname === "free_product");
	let complete;
	h.frappe.db.get_value = () => new Promise((resolve) => { complete = resolve; });
	const row = { free_product: "FREE-ITEM", unit: "Old unit" };
	field.change.call({ doc: row });
	assert.equal(row.unit, "");
	row.unit = "Manual unit";
	complete({ message: { stock_uom: "Ton" } });
	await new Promise((resolve) => setImmediate(resolve));
	assert.equal(row.unit, "Manual unit");
	field.change.call({ doc: row });
	row.free_product = "000100427";
	complete({ message: { stock_uom: "Ton" } });
	await new Promise((resolve) => setImmediate(resolve));
	assert.equal(row.unit, "");
});

test("adding and editing keep other rules, IDs, and order; canceling makes no changes", async () => {
	const h = harness([clone(example), { ...clone(example), id: "keep-this-id" }]);
	const original = clone(h.frm.doc.promotion_rules);
	const canceled = await h.open(0);
	canceled.get_values().price_discount_slabs[0].price_or_discount_value = 99;
	canceled.hide();
	assert.deepEqual(h.frm.doc.promotion_rules, original);
	assert.equal(h.frm.writes, 0);
	await (await h.open()).primary_action();
	const before = h.rules();
	assert.equal(before.length, 3);
	assert.equal(before[1].id, "keep-this-id");
	assert.notEqual(before[0].id, before[2].id);
	assert.deepEqual(before[2].apply_for, []);
	const edit = await h.open(1);
	edit.get_values().price_discount_slabs[0].price_or_discount_value = 30;
	await edit.primary_action();
	const after = h.rules();
	assert.equal(after[1].id, "keep-this-id");
	assert.equal(after[1].price_discount_slabs[0].discount_percentage, 30);
	assert.deepEqual(after[0], before[0]);
	assert.deepEqual(after[2], before[2]);
});

test("delete requires confirmation and removes only the selected rule, including the last rule", async () => {
	const h = harness(JSON.stringify([{ ...example, id: "first" }, { ...example, id: "second" }]));
	await h.handlers.promotion_rules(h.frm);
	h.wrapper.click("delete", 0);
	assert.equal(h.frm.writes, 0);
	assert.match(h.confirmations[0].message, /rule 1/);
	await h.confirmations[0].callback();
	assert.deepEqual(h.rules().map((rule) => rule.id), ["second"]);
	h.wrapper.click("delete", 0);
	await h.confirmations[1].callback();
	assert.deepEqual(h.rules(), []);
	assert.match(h.wrapper.content, /No promotion rules added/);
});

test("missing UUIDs and required fields block saving with row errors and allow a clean retry", async () => {
	const h = harness();
	const dialog = await h.open();
	dialog.get_values().apply_for.push({ apply_for_type: "Item", apply_for: "UNMAPPED", uom: "Bag" });
	await dialog.primary_action();
	assert.equal(h.frm.writes, 0);
	assert.equal(dialog.is_visible, true);
	assert.match(h.messages.at(-1).message, /Apply For row 1.*UNMAPPED.*UUID/);
	dialog.get_values().apply_for[0].apply_for = "000100427";
	dialog.get_values().product_discount_slabs.push({ free_product_qty: 1 });
	await dialog.primary_action();
	assert.match(h.messages.at(-1).message, /Product Discount Slabs row 1.*Free Product.*required/);
	dialog.get_values().product_discount_slabs[0].free_product = "FREE-ITEM";
	await dialog.primary_action();
	assert.equal(h.rules().length, 1);
});

test("unresolved UUIDs remain visible and editing requires reselecting the missing reference", async () => {
	const h = harness(JSON.stringify([example]));
	h.records.Item.splice(0, 1);
	await h.handlers.promotion_rules(h.frm);
	assert.match(h.wrapper.content, new RegExp(ids.item));
	const dialog = await h.open(0);
	assert.match(dialog.fields_dict.unresolved_references.df.options, /cannot resolve/);
	assert.equal(dialog.get_values().apply_for[0].apply_for, "");
	await dialog.primary_action();
	assert.equal(h.frm.writes, 0);
	assert.match(h.messages.at(-1).message, /Apply For row 1/);
	assert.deepEqual(h.rules(), [example]);
});

test("invalid JSON and invalid array shapes never overwrite data or leave stale cards", async () => {
	for (const value of ["{", "{}", "null", "false", "0", "[null]", "[1]", '[{"apply_for":{}}]', '[{"product_discount_slabs":[null]}]']) {
		const h = harness(value);
		h.wrapper.content = "old card";
		await h.handlers.promotion_rules(h.frm);
		assert.match(h.wrapper.content, /text-danger/);
		assert.doesNotMatch(h.wrapper.content, /old card/);
		await h.open();
		assert.equal(h.dialogs.length, 0);
		assert.equal(h.frm.writes, 0);
		assert.equal(h.frm.doc.promotion_rules, value);
	}
	assert.deepEqual(plain(harness().context.read_promotion_rules("   ")), []);
});

test("external JSON edits while a dialog or confirmation is open cannot be overwritten", async () => {
	const h = harness(JSON.stringify([example]));
	const dialog = await h.open(0);
	h.frm.doc.promotion_rules = "[]";
	await dialog.primary_action();
	assert.equal(h.frm.writes, 0);
	assert.match(h.messages.at(-1).message, /changed while this action was open/);
	dialog.hide();
	h.frm.doc.promotion_rules = JSON.stringify([example]);
	h.context.delete_promotion_rule(h.frm, 0);
	h.frm.doc.promotion_rules = "[]";
	await h.confirmations[0].callback();
	assert.equal(h.frm.writes, 0);
});

test("submitted, canceled, workflow-read-only, and permission-read-only forms only display rules", async () => {
	for (const state of [{ docstatus: 1 }, { docstatus: 2 }, { writable: false }, { read_only: true }]) {
		const h = harness(JSON.stringify([example]));
		if (state.docstatus) h.frm.doc.docstatus = state.docstatus;
		else Object.assign(h.frm, state);
		await h.handlers.promotion_rules(h.frm);
		assert.equal(h.frm.add_button_visible, false);
		assert.match(h.wrapper.content, /Cement/);
		assert.doesNotMatch(h.wrapper.content, /data-rule-action/);
		await h.open();
		h.context.delete_promotion_rule(h.frm, 0);
		assert.equal(h.dialogs.length, 0);
		assert.equal(h.confirmations.length, 0);
		assert.equal(h.frm.writes, 0);
	}
});

test("names, units, warnings, and JSON-controlled values are HTML escaped", async () => {
	const value = clone(example);
	value.product_discount_slabs[0].free_product_unit = '<img src=x onerror="bad()">';
	const h = harness(JSON.stringify([value]));
	h.records.Item[0].item_name = "<script>bad()</script>";
	await h.handlers.promotion_rules(h.frm);
	assert.doesNotMatch(h.wrapper.content, /<script>|<img/);
	assert.match(h.wrapper.content, /&lt;script&gt;/);
	assert.match(h.wrapper.content, /&lt;img/);
});

test("refresh renders before sync early returns and does not accumulate click handlers or write IDs", async () => {
	const h = harness(JSON.stringify([example]));
	h.handlers.refresh(h.frm);
	await h.handlers.promotion_rules(h.frm);
	assert.match(h.wrapper.content, /Promotion Rule 1/);
	assert.equal(h.wrapper.handlers.size, 1);
	assert.equal(h.frm.writes, 0);
	assert.equal(h.rules()[0].id, undefined);
	await h.handlers.add_promotion_rule(h.frm);
	assert.equal(h.dialogs.length, 1);
});

test("repeated open and Save clicks create one dialog and append one rule", async () => {
	const h = harness();
	await Promise.all([h.open(), h.open()]);
	assert.equal(h.dialogs.length, 1);
	await h.open();
	assert.equal(h.dialogs.length, 1);
	const dialog = h.dialogs[0];
	dialog.get_values().apply_for.push({ apply_for_type: "Item", apply_for: "000100427", uom: "Bag" });
	let complete;
	h.frappe.db.get_value = () => new Promise((resolve) => { complete = resolve; });
	const saving = dialog.primary_action();
	await Promise.resolve();
	assert.equal(dialog.disabled, true);
	await dialog.primary_action();
	complete({ message: { custom_supabase_id: ids.item } });
	await saving;
	assert.equal(h.rules().length, 1);
	assert.equal(h.frm.writes, 1);
});

test("late display lookups cannot replace a newer render", async () => {
	const h = harness(JSON.stringify([example]));
	const pending = [];
	h.frappe.xcall = () => new Promise((resolve) => pending.push(resolve));
	const first = h.handlers.promotion_rules(h.frm);
	h.frm.doc.promotion_rules = "[]";
	await h.handlers.promotion_rules(h.frm);
	pending.forEach((resolve) => resolve([]));
	await first;
	assert.match(h.wrapper.content, /No promotion rules added/);
	assert.doesNotMatch(h.wrapper.content, /Promotion Rule 1/);
});

test("dismissing the modal during a lookup cancels saving and permits reopening", async () => {
	const h = harness();
	const dialog = await h.open();
	dialog.get_values().apply_for.push({ apply_for_type: "Item", apply_for: "000100427", uom: "Bag" });
	let complete;
	h.frappe.db.get_value = () => new Promise((resolve) => { complete = resolve; });
	const saving = dialog.primary_action();
	await Promise.resolve();
	// Bootstrap's close button fires onhide without calling Dialog.hide().
	dialog.onhide();
	await h.open();
	assert.equal(h.dialogs.length, 2);
	complete({ message: { custom_supabase_id: ids.item } });
	await saving;
	assert.equal(h.frm.writes, 0);
});

test("legacy duplicate IDs become unique, including browsers without crypto.randomUUID", async () => {
	const h = harness(JSON.stringify([{ ...example, id: "duplicate" }, { ...example, id: "duplicate" }]));
	h.context.crypto = { getRandomValues: (array) => webcrypto.getRandomValues(array) };
	await (await h.open()).primary_action();
	const rules = h.rules();
	assert.equal(new Set(rules.map((rule) => rule.id)).size, 3);
	assert.equal(rules[0].id, "duplicate");
	for (const rule of rules.slice(1)) {
		assert.match(rule.id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
	}
});

test("selecting an Apply For item defaults its stock UOM and Save waits for that lookup", async () => {
	const h = harness();
	// A running site may still have the previous child DocType metadata cached.
	h.meta["App Promotion Apply For"].fields = h.meta["App Promotion Apply For"].fields.filter((field) => field.fieldname !== "uom");
	const dialog = await h.open();
	const table = dialog.fields_dict.apply_for.df;
	assert.deepEqual(plain(table.fields.slice(0, 3).map((field) => field.fieldname)), ["apply_for_type", "apply_for", "uom"]);
	const row = { apply_for_type: "Item", apply_for: "000100427", uom: "Old UOM" };
	table.data.push(row);
	table.fields.find((field) => field.fieldname === "apply_for").change.call({ doc: row });
	assert.equal(row.uom, "");
	await dialog.primary_action();
	assert.equal(h.rules()[0].apply_for[0].uom, "Bag");
	assert.equal(h.messages.length, 0);
	assert.ok(h.reads.some((read) => read.doctype === "Item" && read.name === "000100427" && read.fields === "stock_uom"));
});

test("UOM is required for Item rows only, regardless of shared grid required flags", async () => {
	const h = harness();
	const dialog = await h.open();
	const table = dialog.fields_dict.apply_for.df;
	table.data.push(
		{ apply_for_type: "Item", apply_for: "000100427", uom: "  " },
		{ apply_for_type: "Item Group", apply_for: "Cement ស៊ីម៉ង់", uom: "" },
	);
	const uom = table.fields.find((field) => field.fieldname === "uom");
	assert.equal(uom.fieldtype, "Link");
	assert.equal(uom.options, "UOM");
	uom.reqd = 0;
	await dialog.primary_action();
	assert.equal(h.frm.writes, 0);
	assert.match(h.messages.at(-1).message, /Apply For row 1: UOM is required/);
	table.data[0].uom = " Case ";
	table.data[1].uom = "Stale UOM";
	uom.reqd = 1;
	await dialog.primary_action();
	assert.deepEqual(h.rules()[0].apply_for.map((row) => row.uom), ["Case", ""]);
	assert.match(h.wrapper.content, /<th>UOM<\/th>/);
	assert.match(h.wrapper.content, /<td>Case<\/td>/);
});

test("changing to Item Group clears the target and UOM and ignores a pending Item lookup", async () => {
	const h = harness();
	const dialog = await h.open();
	const table = dialog.fields_dict.apply_for.df;
	const type = table.fields.find((field) => field.fieldname === "apply_for_type");
	const target = table.fields.find((field) => field.fieldname === "apply_for");
	const row = { apply_for_type: "Item", apply_for: "000100427", uom: "Bag" };
	table.data.push(row);
	const get_value = h.frappe.db.get_value;
	let complete;
	let reads = 0;
	h.frappe.db.get_value = () => {
		reads++;
		return new Promise((resolve) => { complete = resolve; });
	};
	target.change.call({ doc: row });
	row.apply_for_type = "Item Group";
	type.change.call({ doc: row });
	assert.equal(row.apply_for, "");
	assert.equal(row.uom, "");
	row.apply_for = "Cement ស៊ីម៉ង់";
	target.change.call({ doc: row });
	assert.equal(reads, 1);
	complete({ message: { stock_uom: "Bag" } });
	await new Promise((resolve) => setImmediate(resolve));
	assert.equal(row.uom, "");
	h.frappe.db.get_value = get_value;
	await dialog.primary_action();
	assert.equal(h.rules()[0].apply_for[0].uom, "");
	assert.equal(h.rules()[0].apply_for[0].apply_for_type, "Item Group");
});

test("Apply For stock UOM lookup respects a newer product and a manually selected UOM", async () => {
	const h = harness();
	const dialog = await h.open();
	const table = dialog.fields_dict.apply_for.df;
	const target = table.fields.find((field) => field.fieldname === "apply_for");
	const row = { apply_for_type: "Item", apply_for: "000100427", uom: "Bag" };
	table.data.push(row);
	const pending = [];
	h.frappe.db.get_value = () => new Promise((resolve) => pending.push(resolve));
	target.change.call({ doc: row });
	row.apply_for = "FREE-ITEM";
	target.change.call({ doc: row });
	pending[0]({ message: { stock_uom: "Bag" } });
	await new Promise((resolve) => setImmediate(resolve));
	assert.equal(row.uom, "");
	row.uom = "Case";
	pending[1]({ message: { stock_uom: "Ton តោន" } });
	await new Promise((resolve) => setImmediate(resolve));
	assert.equal(row.uom, "Case");
});

test("older rules default missing item UOM on edit and preserve an explicitly selected UOM", async () => {
	const legacy = clone(example);
	delete legacy.apply_for[0].uom;
	legacy.apply_for[1].uom = "Stale group UOM";
	const h = harness(JSON.stringify([legacy]));
	const dialog = await h.open(0);
	assert.equal(dialog.get_values().apply_for[0].uom, "Bag");
	assert.equal(dialog.get_values().apply_for[1].uom, "");
	assert.equal(h.frm.writes, 0);
	await dialog.primary_action();
	const edit = await h.open(0);
	edit.get_values().apply_for[0].uom = "Case";
	await edit.primary_action();
	const reopened = await h.open(0);
	assert.equal(reopened.get_values().apply_for[0].uom, "Case");
});

test("a hidden JSON storage field does not prevent editing rules on a writable draft", async () => {
	const h = harness(JSON.stringify([example]));
	h.frm.field_status = "None";
	const dialog = await h.open(0);
	assert.ok(dialog);
	dialog.get_values().apply_for[0].uom = "Case";
	await dialog.primary_action();
	assert.equal(h.rules()[0].apply_for[0].uom, "Case");
});
