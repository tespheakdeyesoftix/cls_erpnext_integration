import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

// Load the bundle's ES module without changing the app's CommonJS package type.
const source = await readFile(new URL("./utils.js", import.meta.url), "utf8");
const { productName, itemUnitPrice, itemTotal, isFreeItem, giftSource, giftQuantities, itemDiscountLabel, formatMoney, formatQuantity } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const samples = JSON.parse(await readFile(new URL("../../../homeall_ecommerce_integration/page/online_order/order_schema/orders.samples.json", import.meta.url), "utf8"));

test("all schema scenarios use stored line totals, names, and prices over current catalog data", () => {
	for (const scenario of samples.scenarios) {
		for (const saved of scenario.data.order_items) {
			const item = { ...saved, product: { name: "Renamed product", price: 999, currency: "KHR" }, total: 999 };
			assert.equal(productName(item), saved.product_name, scenario.name);
			assert.equal(itemUnitPrice(item), saved.unit_price, scenario.name);
			assert.equal(itemTotal(item), saved.line_total, scenario.name);
			assert.equal(isFreeItem(item), saved.line_type === "free", scenario.name);
		}
	}
});

test("same-product and different-product gifts retain zero payable totals and their source UOM", () => {
	for (const scenario of samples.scenarios.filter((scenario) => scenario.data.order_items.some(isFreeItem))) {
		const lines = scenario.data.order_items;
		for (const gift of lines.filter(isFreeItem)) {
			assert.equal(itemTotal(gift), 0, scenario.name);
			assert.match(giftSource(gift, lines), /Sample product 1 · Unit/, scenario.name);
		}
		assert.ok(giftQuantities(lines), scenario.name);
	}
});

test("gift quantities preserve mixed units and fractional quantities without adding purchased lines", () => {
	assert.equal(giftQuantities([
		{ line_type: "purchased", quantity: 100, uom: "Box" },
		{ line_type: "free", quantity: "1.25", uom: "Box" },
		{ line_type: "free", quantity: 0.25, uom: "Box" },
		{ line_type: "free", quantity: 2, uom: "Unit" },
	]), `${formatQuantity(1.5)} Box + ${formatQuantity(2)} Unit`);
});

test("fixed item discounts are per unit and rate discounts describe the final rate", () => {
	assert.equal(itemDiscountLabel({ discount_type: "fixed_amount", discount_value: 2, uom: "Box" }, "USD"), `បញ្ចុះតម្លៃ ${formatMoney(2, "USD")} / Box`);
	assert.equal(itemDiscountLabel({ discount_type: "rate", discount_value: 7.5, uom: "Unit" }, "USD"), `តម្លៃពិសេស ${formatMoney(7.5, "USD")} / Unit`);
	assert.equal(itemDiscountLabel({ discount_type: "none" }), "");
});

test("gift source matches the purchased UOM when a product repeats", () => {
	assert.equal(giftSource({ source_product_id: "same", source_uom: "Box" }, [
		{ product_id: "same", uom: "Unit", product_name: "Single unit" },
		{ product_id: "same", uom: "Box", product_name: "Purchased box" },
	]), "Purchased box · Box");
});
