<script setup>
import OrderStatusBadge from "./OrderStatusBadge.vue";
import { formatDate, formatQuantity, giftQuantities, paymentMethodLabel, statusLabel } from "../utils";

defineProps({
	order: { type: Object, required: true },
});
</script>

<template>
	<div class="detail-grid order-summary">
		<div class="detail-field">
			<span>លេខបញ្ជាទិញ</span>
			<strong class="order-reference">{{ order.id }}</strong>
		</div>
		<div class="detail-field">
			<span>កាលបរិច្ឆេទ</span>
			<strong>{{ formatDate(order.created_at) }}</strong>
		</div>
		<div class="detail-field">
			<span>ស្ថានភាព</span>
			<OrderStatusBadge :status="order.status" />
		</div>
		<div class="detail-field">
			<span>ការធ្វើសមកាលកម្ម ERP</span>
			<strong>{{ statusLabel(order.erp_sync_status) }}</strong>
		</div>
		<div class="detail-field">
			<span>វិធីទូទាត់</span>
			<strong>{{ paymentMethodLabel(order.payment_method) }}</strong>
		</div>
		<div class="detail-field">
			<span>ស្ថានភាពទូទាត់</span>
			<strong>{{ statusLabel(order.payment_status) }}</strong>
		</div>
		<div v-if="order.erp_order_number" class="detail-field">
			<span>លេខបញ្ជាទិញ ERP</span>
			<strong>{{ order.erp_order_number }}</strong>
		</div>
		<div v-if="order.erp_customer" class="detail-field">
			<span>អតិថិជន ERP</span>
			<strong>{{ order.erp_customer }}</strong>
		</div>
		<div v-if="order.pricing_user_type_name" class="detail-field">
			<span>ប្រភេទតម្លៃអតិថិជន</span>
			<strong>{{ order.pricing_user_type_name }}</strong>
		</div>
		<div class="detail-field">
			<span>ចំនួនទំនិញទិញ (មិនរួមទំនិញឥតគិតថ្លៃ)</span>
			<strong>{{ formatQuantity(order.total_quantity) }}</strong>
		</div>
		<div v-if="giftQuantities(order.items || [])" class="detail-field">
			<span>ចំនួនទំនិញឥតគិតថ្លៃ</span>
			<strong>{{ giftQuantities(order.items || []) }}</strong>
		</div>
		<div v-if="order.updated_at" class="detail-field">
			<span>កែប្រែចុងក្រោយ</span>
			<strong>{{ formatDate(order.updated_at) }}</strong>
		</div>
	</div>
</template>
