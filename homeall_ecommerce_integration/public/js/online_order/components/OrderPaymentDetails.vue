<script setup>
import { computed } from "vue";
import { formatDate } from "../utils";

const props = defineProps({ order: { type: Object, required: true } });
const qrUrl = computed(() => /^https:\/\/[^\s]+$/.test(props.order.payment_qr_image_url || "") ? props.order.payment_qr_image_url : "");
</script>

<template>
	<section v-if="order.payment_reference || order.payment_transaction_id || order.payment_expires_at || qrUrl" class="detail-section">
		<h4>ព័ត៌មានលម្អិតការទូទាត់</h4>
		<div class="detail-grid payment-details">
			<div v-if="order.payment_reference" class="detail-field">
				<span>លេខយោងការទូទាត់</span>
				<strong>{{ order.payment_reference }}</strong>
			</div>
			<div v-if="order.payment_transaction_id" class="detail-field">
				<span>លេខប្រតិបត្តិការ</span>
				<strong>{{ order.payment_transaction_id }}</strong>
			</div>
			<div v-if="order.payment_expires_at" class="detail-field">
				<span>ពេលផុតកំណត់ការទូទាត់</span>
				<strong>{{ formatDate(order.payment_expires_at) }}</strong>
			</div>
		</div>
		<a v-if="qrUrl" :href="qrUrl" target="_blank" rel="noopener noreferrer" class="payment-qr-link">មើល QR ទូទាត់</a>
	</section>
</template>
