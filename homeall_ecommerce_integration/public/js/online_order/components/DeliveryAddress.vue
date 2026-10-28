<script setup>
defineProps({
	address: { type: Object, default: () => ({}) },
});
</script>

<template>
	<section class="detail-section">
		<h4>អាសយដ្ឋានដឹកជញ្ជូន</h4>
		<div v-if="Object.keys(address || {}).length" class="address-card">
			<small v-if="address.label" class="muted">{{ address.label }}</small>
			<strong>{{ address.recipient_name || "មិនមានឈ្មោះអ្នកទទួល" }}</strong>
			<span v-if="address.phone">{{ address.phone }}</span>
			<p>
				{{ [address.address_line1, address.address_line2].filter(Boolean).join(", ") }}
				<br v-if="address.city || address.state_province" />
				{{ [address.city, address.state_province, address.postal_code].filter(Boolean).join(", ") }}
				<br v-if="address.country_code" />
				{{ address.country_code }}
			</p>
			<p v-if="address.delivery_note">កំណត់សម្គាល់ដឹកជញ្ជូន៖ {{ address.delivery_note }}</p>
			<small v-if="address.latitude != null && address.longitude != null" class="muted">
				ទីតាំង៖ {{ address.latitude }}, {{ address.longitude }}
			</small>
		</div>
		<p v-else class="muted">មិនមានអាសយដ្ឋានដឹកជញ្ជូន</p>
	</section>
</template>
