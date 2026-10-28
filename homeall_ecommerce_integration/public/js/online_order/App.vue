<script setup>
import { onMounted, onUnmounted } from "vue";
import { destination, listenForRoutes } from '../notifications/policy.mjs';
import { Button } from "./frappeUi";
import OrderDetailDialog from "./components/OrderDetailDialog.vue";
import OrderFilters from "./components/OrderFilters.vue";
import OrderPagination from "./components/OrderPagination.vue";
import OrderTable from "./components/OrderTable.vue";
import { useOrders } from "./composables/useOrders";

const store = useOrders();
let lastLink = '';
let stopRoutes = () => {};
function updateDetailOpen(open) {
	store.state.detailOpen = open;
	if (open) return;
	const url = new URL(window.location.href);
	if (url.pathname !== '/desk/online-order') return;
	url.searchParams.delete('order');
	url.searchParams.delete('homeall_event');
	window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash);
	if (frappe.route_options) {
		delete frappe.route_options.order;
		delete frappe.route_options.homeall_event;
	}
	lastLink = '';
}

async function openLinkedOrder() {
	const query = new URLSearchParams(window.location.search);
	for (const key of ['order', 'homeall_event']) {
		if (frappe.route_options?.[key]) query.set(key, frappe.route_options[key]);
	}
	const url = destination('/desk/online-order?' + query.toString(), location.origin);
	if (!url || url.href === lastLink) return;
	lastLink = url.href;
	if (await store.openOrderById(url.searchParams.get('order'))) {
		const eventId = url.searchParams.get('homeall_event');
		if (eventId) frappe.call({ method: 'homeall_ecommerce_integration.notifications.api.mark_opened', args: { event_id: eventId } });
	} else if (lastLink === url.href) lastLink = '';
}
onMounted(() => {
	void store.fetchOrders();
	void openLinkedOrder();
	stopRoutes = listenForRoutes(frappe.router, openLinkedOrder, 'orders');
});
onUnmounted(() => {
	stopRoutes();
	store.cancelDetailRequest();
});
</script>

<template>
	<section class="online-order-page" lang="km">
		<div class="order-toolbar">
			<div>
				<h2>បញ្ជីការបញ្ជាទិញ</h2>
				<p>តាមដានការបញ្ជាទិញដែលទទួលបានពីហាងអនឡាញ</p>
			</div>
			<Button
				:loading="store.state.loading"
				loading-text="កំពុងផ្ទុក..."
				@click="store.fetchOrders"
			>
				ផ្ទុកឡើងវិញ
			</Button>
		</div>

		<OrderFilters
			:state="store.state"
			@apply="store.applyFilters"
			@clear="store.clearFilters"
		/>

		<div v-if="store.state.error" class="order-error">{{ store.state.error }}</div>

		<OrderTable
			:orders="store.state.orders"
			:loading="store.state.loading"
			@select="store.openOrder"
		/>

		<OrderPagination :store="store" />
		<OrderDetailDialog
			:model-value="store.state.detailOpen"
			:order="store.state.selectedOrder"
			:history-loading="store.state.detailLoading"
			:history-error="store.state.detailError"
			:status-updating="store.state.statusUpdating"
			@update:model-value="updateDetailOpen"
			@refresh-history="store.fetchOrderStatusHistory"
			@update-status="store.updateOrderStatus"
		/>
	</section>
</template>
