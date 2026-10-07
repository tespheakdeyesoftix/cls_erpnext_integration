<script setup>
import { Button } from "../frappeUi";

defineProps({
	store: { type: Object, required: true },
});
</script>

<template>
	<footer class="order-pagination">
		<div>
			បង្ហាញ {{ store.firstRow.value }} ដល់ {{ store.lastRow.value }}
			ក្នុងចំណោម {{ store.state.total }} ការបញ្ជាទិញ
		</div>
		<div class="pagination-actions">
			<Button
				variant="outline"
				:disabled="store.state.loading || store.state.page <= 1"
				@click="store.goToPage(store.state.page - 1)"
			>
				ទំព័រមុន
			</Button>
			<span>ទំព័រ {{ store.state.page }} / {{ store.state.totalPages }}</span>
			<Button
				variant="outline"
				:disabled="store.state.loading || store.state.page >= store.state.totalPages"
				@click="store.goToPage(store.state.page + 1)"
			>
				ទំព័របន្ទាប់
			</Button>
		</div>
	</footer>
</template>
