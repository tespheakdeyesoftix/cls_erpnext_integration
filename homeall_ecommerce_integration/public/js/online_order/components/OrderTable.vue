<script setup>
import { LoadingIndicator } from "../frappeUi";
import OrderStatusBadge from "./OrderStatusBadge.vue";
import { formatDate, formatMoney, paymentMethodLabel, shortId, statusLabel } from "../utils";

defineProps({
	orders: { type: Array, default: () => [] },
	loading: { type: Boolean, default: false },
});
defineEmits(["select"]);
</script>

<template>
	<div class="order-table-card">
		<div v-if="loading" class="order-state">
			<LoadingIndicator class="order-spinner" />
			<span>កំពុងទាញយកការបញ្ជាទិញ...</span>
		</div>
		<div v-else-if="!orders.length" class="order-state">
			<strong>មិនមានការបញ្ជាទិញ</strong>
			<span>សូមប្តូរកាលបរិច្ឆេទ ឬផ្ទុកទិន្នន័យឡើងវិញ</span>
		</div>
		<div v-else class="table-responsive">
			<table class="order-table">
				<thead>
					<tr>
						<th>លេខបញ្ជាទិញ</th>
						<th>កាលបរិច្ឆេទ</th>
						<th>ស្ថានភាព</th>
						<th>ការទូទាត់</th>
						<th class="numeric">ចំនួន</th>
						<th class="numeric">ទឹកប្រាក់សរុប</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="order in orders"
						:key="order.id"
						tabindex="0"
						@click="$emit('select', order)"
						@keydown.enter="$emit('select', order)"
					>
						<td>
							<strong>#{{ shortId(order.id) }}</strong>
							<small v-if="order.erp_order_number">{{ order.erp_order_number }}</small>
						</td>
						<td>{{ formatDate(order.created_at) }}</td>
						<td><OrderStatusBadge :status="order.status" /></td>
						<td>
							<div>{{ paymentMethodLabel(order.payment_method) }}</div>
							<small>{{ statusLabel(order.payment_status) }}</small>
						</td>
						<td class="numeric">{{ order.total_quantity || 0 }}</td>
						<td class="numeric amount">{{ formatMoney(order.total_amount, order.currency) }}</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
