const statusLabels = {
	order_placed: "បានដាក់ការបញ្ជាទិញ",
	pending: "កំពុងរង់ចាំ",
	accepted: "ទទួលការកុម្ម៉ង",
	rejected: "បដិសេធការកុម្ម៉ង",
	processing: "កំពុងរៀបចំ",
	out_for_delivery: "កំពុងដឹកជញ្ជូន",
	delivered: "បានប្រគល់",
	completed: "បានបញ្ចប់",
	cancelled: "បានលុបចោល",
	paid: "បានបង់ប្រាក់",
	unpaid: "មិនទាន់បង់",
	failed: "បរាជ័យ",
	expired: "ផុតកំណត់",
	refunded: "បានសងប្រាក់",
	pay_on_delivery: "បង់ពេលទទួលទំនិញ",
	synced: "បានធ្វើសមកាលកម្ម",
};

export const ORDER_STATUS_OPTIONS = [
	"pending",
	"accepted",
	"rejected",
	"processing",
	"out_for_delivery",
	"delivered",
	"completed",
	"cancelled",
].map((value) => ({
	value,
	label: statusLabels[value],
}));

const paymentLabels = {
	cash_on_delivery: "សាច់ប្រាក់ពេលទទួលទំនិញ",
	aba_qr_pay: "ABA QR Pay",
	bank_transfer: "ផ្ទេរប្រាក់តាមធនាគារ",
	qr: "ស្កេន QR",
	card: "កាត",
};

export function formatDate(value) {
	if (!value) return "—";
	return new Intl.DateTimeFormat("km-KH", {
		dateStyle: "medium",
		timeStyle: "short",
	}).format(new Date(value));
}

export function formatMoney(value, currency = "USD") {
	const amount = Number(value || 0);
	try {
		return new Intl.NumberFormat("km-KH", {
			style: "currency",
			currency: currency || "USD",
			minimumFractionDigits: 2,
		}).format(amount);
	} catch {
		return `${amount.toFixed(2)} ${currency || ""}`.trim();
	}
}

export function statusLabel(value) {
	return statusLabels[value] || value || "មិនបានកំណត់";
}

export function paymentMethodLabel(value) {
	return paymentLabels[value] || statusLabels[value] || value || "មិនបានកំណត់";
}

export function statusTone(value) {
	if (["delivered", "completed", "paid", "synced"].includes(value)) return "green";
	if (["rejected", "cancelled", "failed"].includes(value)) return "red";
	if (value === "order_placed") return "blue";
	if (["accepted", "processing", "out_for_delivery"].includes(value)) return "blue";
	return "amber";
}

export function shortId(value) {
	return value ? String(value).slice(0, 8).toUpperCase() : "—";
}

export function productName(item) {
	return item?.product_name || item?.product?.name || item?.erp_item_code || item?.product?.erp_item_code || shortId(item?.product_id);
}

export function itemUnitPrice(item) {
	return Number(item?.unit_price ?? item?.price ?? item?.product?.price ?? 0);
}

export function itemTotal(item) {
	return Number(item?.line_total ?? item?.total ?? item?.amount ?? itemUnitPrice(item) * Number(item?.quantity || 0));
}

export function formatQuantity(value) {
	return new Intl.NumberFormat("km-KH", { maximumFractionDigits: 6 }).format(Number(value || 0));
}

export function isFreeItem(item) {
	return item?.line_type === "free";
}

export function itemDiscountLabel(item, currency = "USD") {
	switch (item.discount_type) {
		case "percentage": return `បញ្ចុះតម្លៃ ${formatQuantity(item.discount_value)}%`;
		case "fixed_amount": return `បញ្ចុះតម្លៃ ${formatMoney(item.discount_value, currency)} / ${item.uom || "ឯកតា"}`;
		case "rate": return `តម្លៃពិសេស ${formatMoney(item.discount_value, currency)} / ${item.uom || "ឯកតា"}`;
		case "free_product": return "ទំនិញឥតគិតថ្លៃ";
		default: return "";
	}
}

export function giftSource(item, items) {
	const sourceId = item.source_product_id || item.pricing_snapshot?.source_product_id;
	if (!sourceId) return "";
	const sourceUom = item.source_uom || item.pricing_snapshot?.source_uom;
	const source = items.find((line) => !isFreeItem(line) && line.product_id === sourceId && (!sourceUom || line.uom === sourceUom));
	return [source ? productName(source) : sourceId, sourceUom].filter(Boolean).join(" · ");
}

export function giftQuantities(items) {
	const quantities = new Map();
	for (const item of items.filter(isFreeItem)) {
		const uom = item.uom || "";
		quantities.set(uom, (quantities.get(uom) || 0) + Number(item.quantity || 0));
	}
	return [...quantities].map(([uom, quantity]) => `${formatQuantity(quantity)} ${uom}`.trim()).join(" + ");
}
