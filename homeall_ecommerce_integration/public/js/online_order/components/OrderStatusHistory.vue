<script setup>
import { computed } from "vue";
import { LoadingIndicator } from "../frappeUi";
import { formatDate } from "../utils";
import OrderStatusBadge from "./OrderStatusBadge.vue";

const props = defineProps({
	history: { type: Array, default: () => [] },
	createdAt: { type: String, default: "" },
	loading: { type: Boolean, default: false },
});

const timeline = computed(() => {
	const placedEntry = props.createdAt
		? [{
			id: `order-placed-${props.createdAt}`,
			from_status: null,
			to_status: "order_placed",
			changed_at: props.createdAt,
		}]
		: [];
	const uniqueHistory = props.history.filter((item, index, entries) => {
		if (index === 0) return true;
		const previous = entries[index - 1];
		return !(
			item.from_status === previous.from_status && item.to_status === previous.to_status
		);
	});

	return [...uniqueHistory, ...placedEntry];
});
</script>

<template>
	<section class="detail-section status-history">
		<div class="status-section-heading">
			<h4>ប្រវត្តិស្ថានភាព</h4>
			<span v-if="timeline.length" class="muted">{{ timeline.length }} ដង</span>
		</div>

		<div v-if="loading" class="status-history-state">
			<LoadingIndicator class="order-spinner" />
			<span>កំពុងទាញយកប្រវត្តិ...</span>
		</div>
		<p v-else-if="!timeline.length" class="status-history-state">
			មិនទាន់មានប្រវត្តិផ្លាស់ប្តូរស្ថានភាពទេ
		</p>
		<ol v-else class="status-timeline">
			<li v-for="item in timeline" :key="item.id" class="status-history-item">
				<span class="status-history-dot" aria-hidden="true"></span>
				<div class="status-history-content">
					<div class="status-history-transition">
						<OrderStatusBadge v-if="item.from_status" :status="item.from_status" />
						<span v-if="item.from_status" class="status-arrow" aria-hidden="true">→</span>
						<OrderStatusBadge :status="item.to_status" />
					</div>
					<time class="status-history-meta" :datetime="item.changed_at">
						{{ formatDate(item.changed_at) }}
					</time>
					<p v-if="item.reason" class="status-history-reason">{{ item.reason }}</p>
					<small v-if="item.changed_by" class="status-history-meta">
						អ្នកផ្លាស់ប្តូរ៖ {{ item.changed_by }}
					</small>
				</div>
			</li>
		</ol>
	</section>
</template>
