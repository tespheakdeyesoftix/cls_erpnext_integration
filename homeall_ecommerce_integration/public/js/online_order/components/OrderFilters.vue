<script setup>
import { Button, DatePicker } from "../frappeUi";
import { ORDER_STATUS_OPTIONS } from "../utils";

const props = defineProps({
	state: { type: Object, required: true },
});
const emit = defineEmits(["apply", "clear"]);

function formatDateValue(value) {
	if (!value) return "";
	const [year, month, day] = value.split("-").map(Number);
	return new Intl.DateTimeFormat("km-KH", { dateStyle: "medium" }).format(
		new Date(year, month - 1, day),
	);
}

function submit() {
	if (props.state.startDate && props.state.endDate && props.state.startDate > props.state.endDate) {
		frappe.msgprint("ថ្ងៃចាប់ផ្តើមមិនអាចនៅក្រោយថ្ងៃបញ្ចប់បានទេ");
		return;
	}
	emit("apply");
}
</script>

<template>
	<form class="order-filters" @submit.prevent="submit">
		<div class="filter-field">
			<span>ថ្ងៃចាប់ផ្តើម</span>
			<DatePicker
				v-model="state.startDate"
				input-class="filter-date-input"
				placeholder="ជ្រើសរើសថ្ងៃចាប់ផ្តើម"
				:format-value="formatDateValue"
			/>
		</div>
		<div class="filter-field">
			<span>ថ្ងៃបញ្ចប់</span>
			<DatePicker
				v-model="state.endDate"
				input-class="filter-date-input"
				placeholder="ជ្រើសរើសថ្ងៃបញ្ចប់"
				:format-value="formatDateValue"
			/>
		</div>
		<label class="filter-field">
			<span>ស្ថានភាព</span>
			<select v-model="state.status">
				<option value="">ស្ថានភាពទាំងអស់</option>
				<option v-for="option in ORDER_STATUS_OPTIONS" :key="option.value" :value="option.value">
					{{ option.label }}
				</option>
			</select>
		</label>
		<div class="filter-actions">
			<Button type="submit" theme="blue" variant="solid" :disabled="state.loading">
				ស្វែងរក
			</Button>
			<Button
				type="button"
				variant="outline"
				:disabled="state.loading || (!state.startDate && !state.endDate && !state.status)"
				@click="$emit('clear')"
			>
				សម្អាត
			</Button>
		</div>
	</form>
</template>
