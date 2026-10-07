import { computed, reactive } from "vue";

const state = reactive({
	orders: [],
	page: 1,
	pageSize: 20,
	total: 0,
	totalPages: 1,
	startDate: "",
	endDate: "",
	status: "",
	loading: false,
	error: "",
	selectedOrder: null,
	detailOpen: false,
	detailLoading: false,
	detailError: "",
	statusUpdating: false,
});

let requestId = 0;
let historyRequestId = 0;

export function useOrders() {
	const firstRow = computed(() => (state.total ? (state.page - 1) * state.pageSize + 1 : 0));
	const lastRow = computed(() => Math.min(state.page * state.pageSize, state.total));

	async function fetchOrders() {
		const currentRequest = ++requestId;
		state.loading = true;
		state.error = "";

		try {
			const response = await frappe.call({
				method:
					"homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.orders.get_orders",
				type: "GET",
				args: {
					page: state.page,
					page_size: state.pageSize,
					start_date: state.startDate || null,
					end_date: state.endDate || null,
					status: state.status || null,
				},
			});

			if (currentRequest !== requestId) return;
			const result = response.message || {};
			state.orders = result.orders || [];
			state.page = result.page || 1;
			state.total = result.total || 0;
			state.totalPages = result.total_pages || 1;
		} catch (error) {
			if (currentRequest !== requestId) return;
			state.orders = [];
			state.error =
				error?.messages?.[0] || error?.message || "មិនអាចទាញយកការបញ្ជាទិញបានទេ";
		} finally {
			if (currentRequest === requestId) state.loading = false;
		}
	}

	function applyFilters() {
		state.page = 1;
		return fetchOrders();
	}

	function clearFilters() {
		state.startDate = "";
		state.endDate = "";
		state.status = "";
		return applyFilters();
	}

	function goToPage(page) {
		const target = Math.min(Math.max(page, 1), state.totalPages);
		if (target === state.page) return;
		state.page = target;
		return fetchOrders();
	}

	function applyOrderStatusResult(orderId, result) {
		const listOrder = state.orders.find((order) => order.id === orderId);
		if (listOrder && result.status) listOrder.status = result.status;

		if (state.selectedOrder?.id !== orderId) return;
		if (result.status) state.selectedOrder.status = result.status;
		state.selectedOrder.status_history = result.history || [];
	}

	async function fetchOrderStatusHistory(orderId = state.selectedOrder?.id) {
		if (!orderId) return;

		const currentRequest = ++historyRequestId;
		state.detailLoading = true;
		state.detailError = "";

		try {
			const response = await frappe.call({
				method:
					"homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.orders.get_order_status_history",
				type: "GET",
				args: { order_id: orderId },
			});

			if (currentRequest !== historyRequestId) return;
			applyOrderStatusResult(orderId, response.message || {});
		} catch (error) {
			if (currentRequest !== historyRequestId) return;
			state.detailError =
				error?.messages?.[0] || error?.message || "មិនអាចទាញយកប្រវត្តិស្ថានភាពបានទេ";
		} finally {
			if (currentRequest === historyRequestId) state.detailLoading = false;
		}
	}

	async function updateOrderStatus({ status, reason }) {
		const orderId = state.selectedOrder?.id;
		if (!orderId || !status) return;

		state.statusUpdating = true;
		state.detailError = "";

		try {
			const response = await frappe.call({
				method:
					"homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.orders.update_order_status",
				type: "POST",
				args: {
					order_id: orderId,
					status,
					reason: reason || null,
				},
			});

			const result = response.message || {};
			applyOrderStatusResult(orderId, result);
			return result;
		} catch (error) {
			state.detailError =
				error?.messages?.[0] || error?.message || "មិនអាចប្តូរស្ថានភាពបានទេ";
			return null;
		} finally {
			state.statusUpdating = false;
		}
	}

	function openOrder(order) {
		order.status_history = [];
		state.selectedOrder = order;
		state.detailOpen = true;
		void fetchOrderStatusHistory(order.id);
	}

	return {
		state,
		firstRow,
		lastRow,
		fetchOrders,
		applyFilters,
		clearFilters,
		goToPage,
		fetchOrderStatusHistory,
		updateOrderStatus,
		openOrder,
	};
}
