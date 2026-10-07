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
	return item?.product?.name || item?.product?.erp_item_code || shortId(item?.product_id);
}

export function itemUnitPrice(item) {
	return Number(item?.unit_price ?? item?.price ?? item?.product?.price ?? 0);
}

export function itemTotal(item) {
	return Number(item?.total ?? item?.amount ?? itemUnitPrice(item) * Number(item?.quantity || 0));
}
