<script setup>
import { computed, ref, watch } from "vue";
import { Button, Dialog } from "../frappeUi";
import DeliveryAddress from "./DeliveryAddress.vue";
import OrderItems from "./OrderItems.vue";
import OrderStatusHistory from "./OrderStatusHistory.vue";
import OrderSummary from "./OrderSummary.vue";
import OrderTotals from "./OrderTotals.vue";
import { ORDER_STATUS_OPTIONS, shortId } from "../utils";

const props = defineProps({
	modelValue: { type: Boolean, required: true },
	order: { type: Object, default: null },
	historyLoading: { type: Boolean, default: false },
	historyError: { type: String, default: "" },
	statusUpdating: { type: Boolean, default: false },
});
const emit = defineEmits(["update:modelValue", "refresh-history", "update-status"]);

const selectedStatus = ref("");
const reason = ref("");

const title = computed(() =>
	props.order ? `ព័ត៌មានការបញ្ជាទិញ #${shortId(props.order.id)}` : "ព័ត៌មានការបញ្ជាទិញ",
);
const dialogOptions = computed(() => ({ title: title.value, size: "4xl" }));
const statusChanged = computed(
	() => Boolean(selectedStatus.value) && selectedStatus.value !== props.order?.status,
);

watch(
	() => [props.modelValue, props.order?.id],
	() => {
		selectedStatus.value = props.order?.status || "";
		reason.value = "";
	},
	{ immediate: true },
);

watch(
	() => props.order?.status,
	(status, previousStatus) => {
		selectedStatus.value = status || "";
		if (status && status !== previousStatus) reason.value = "";
	},
);

function submitStatus() {
	if (!statusChanged.value || props.statusUpdating) return;
	emit("update-status", {
		status: selectedStatus.value,
		reason: reason.value.trim(),
	});
}

function submitQuickStatus(status) {
	if (props.statusUpdating || props.order?.status !== "pending") return;
	selectedStatus.value = status;
	emit("update-status", {
		status,
		reason: "",
	});
}

function close() {
	emit("update:modelValue", false);
}
</script>

<template>
	<Dialog
		:model-value="modelValue"
		:options="dialogOptions"
		@update:model-value="$emit('update:modelValue', $event)"
	>
		<template #body>
			<div v-if="order" class="order-dialog" lang="km">
				<header class="dialog-header">
					<div>
						<h3>{{ title }}</h3>
						<p>ព័ត៌មានលម្អិតពីការបញ្ជាទិញអនឡាញ</p>
					</div>
					<Button variant="ghost" aria-label="បិទ" @click="close">បិទ</Button>
				</header>
				<div class="dialog-scroll">
					<OrderSummary :order="order" />
					<div class="status-management-grid">
						<section class="detail-section status-editor">
							<h4>ប្តូរស្ថានភាព</h4>
							<div v-if="order.status === 'pending'" class="quick-status">
								<span>សកម្មភាពរហ័ស</span>
								<div class="quick-status-actions">
									<Button
										class="quick-accept"
										:loading="statusUpdating && selectedStatus === 'accepted'"
										:disabled="statusUpdating"
										type="button"
										@click="submitQuickStatus('accepted')"
									>
										ទទួលការកុម្ម៉ង
									</Button>
									<Button
										class="quick-reject"
										:loading="statusUpdating && selectedStatus === 'rejected'"
										:disabled="statusUpdating"
										type="button"
										@click="submitQuickStatus('rejected')"
									>
										បដិសេធការកុម្ម៉ង
									</Button>
								</div>
							</div>
							<form class="status-form" @submit.prevent="submitStatus">
								<label class="status-field">
									<span>ស្ថានភាពថ្មី</span>
									<select v-model="selectedStatus" :disabled="statusUpdating">
										<option v-for="option in ORDER_STATUS_OPTIONS" :key="option.value" :value="option.value">
											{{ option.label }}
										</option>
									</select>
								</label>
								<label class="status-field">
									<span>មូលហេតុ</span>
									<textarea
										v-model="reason"
										rows="3"
										:disabled="statusUpdating"
										maxlength="2000"
										placeholder="បញ្ចូលមូលហេតុនៃការផ្លាស់ប្តូរ"
									></textarea>
								</label>
								<div class="status-actions">
									<Button
										theme="blue"
										variant="solid"
										:loading="statusUpdating"
										loading-text="កំពុងរក្សាទុក..."
										:disabled="!statusChanged || statusUpdating"
										type="submit"
									>
										រក្សាទុកស្ថានភាព
									</Button>
								</div>
							</form>
						</section>
						<OrderStatusHistory
							:history="order.status_history || []"
							:created-at="order.created_at"
							:loading="historyLoading"
						/>
					</div>
					<div v-if="historyError" class="detail-error">
						<span>{{ historyError }}</span>
						<Button variant="ghost" @click="$emit('refresh-history')">
							ព្យាយាមម្តងទៀត
						</Button>
					</div>
					<OrderItems :items="order.items || []" :currency="order.currency" />
					<div class="dialog-columns">
						<DeliveryAddress :address="order.delivery_address_snapshot" />
						<section class="detail-section">
							<h4>កំណត់សម្គាល់</h4>
							<p>{{ order.note || order.request_items?.note || "មិនមានកំណត់សម្គាល់" }}</p>
						</section>
					</div>
					<OrderTotals :order="order" />
				</div>
			</div>
		</template>
	</Dialog>
</template>
