<script setup>
import { onMounted } from "vue";
import { Button } from "./frappeUi";
import OrderDetailDialog from "./components/OrderDetailDialog.vue";
import OrderFilters from "./components/OrderFilters.vue";
import OrderPagination from "./components/OrderPagination.vue";
import OrderTable from "./components/OrderTable.vue";
import { useOrders } from "./composables/useOrders";

const store = useOrders();
onMounted(store.fetchOrders);
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
			v-model="store.state.detailOpen"
			:order="store.state.selectedOrder"
			:history-loading="store.state.detailLoading"
			:history-error="store.state.detailError"
			:status-updating="store.state.statusUpdating"
			@refresh-history="store.fetchOrderStatusHistory"
			@update-status="store.updateOrderStatus"
		/>
	</section>
</template>
