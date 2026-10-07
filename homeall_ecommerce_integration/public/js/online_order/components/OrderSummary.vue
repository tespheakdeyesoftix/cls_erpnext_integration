<script setup>
import OrderStatusBadge from "./OrderStatusBadge.vue";
import { formatDate, paymentMethodLabel, shortId, statusLabel } from "../utils";

defineProps({
	order: { type: Object, required: true },
});
</script>

<template>
	<div class="detail-grid">
		<div class="detail-field">
			<span>លេខបញ្ជាទិញ</span>
			<strong>#{{ shortId(order.id) }}</strong>
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
	</div>
</template>
