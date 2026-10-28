<script setup>
import { formatMoney } from "../utils";

defineProps({
	order: { type: Object, required: true },
});
</script>

<template>
	<div class="order-totals">
		<div><span>សរុបរង (តម្លៃដើម រួមទំនិញឥតគិតថ្លៃ)</span><strong>{{ formatMoney(order.subtotal, order.currency) }}</strong></div>
		<div v-if="Number(order.product_discount_amount) > 0" class="discount-text">
			<span>បញ្ចុះតម្លៃទំនិញ (រួមទំនិញឥតគិតថ្លៃ)</span><strong>−{{ formatMoney(order.product_discount_amount, order.currency) }}</strong>
		</div>
		<div v-if="Number(order.cart_discount_amount) > 0" class="discount-text">
			<span>បញ្ចុះតម្លៃលើការបញ្ជាទិញ</span><strong>−{{ formatMoney(order.cart_discount_amount, order.currency) }}</strong>
		</div>
		<div class="discount-total"><span>បញ្ចុះតម្លៃសរុប</span><strong>−{{ formatMoney(order.discount_amount, order.currency) }}</strong></div>
		<div><span>ពន្ធ</span><strong>{{ formatMoney(order.tax_amount, order.currency) }}</strong></div>
		<div class="grand-total">
			<span>ទឹកប្រាក់សរុប</span>
			<strong>{{ formatMoney(order.total_amount, order.currency) }}</strong>
		</div>
	</div>
</template>
