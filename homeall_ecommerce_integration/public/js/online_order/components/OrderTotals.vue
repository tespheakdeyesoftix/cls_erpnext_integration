<script setup>
import { formatMoney } from "../utils";

defineProps({
	order: { type: Object, required: true },
});
</script>

<template>
	<div class="order-totals">
		<div><span>សរុបរង</span><strong>{{ formatMoney(order.subtotal, order.currency) }}</strong></div>
		<div><span>ពន្ធ</span><strong>{{ formatMoney(order.tax_amount, order.currency) }}</strong></div>
		<div class="grand-total">
			<span>ទឹកប្រាក់សរុប</span>
			<strong>{{ formatMoney(order.total_amount, order.currency) }}</strong>
		</div>
	</div>
</template>
