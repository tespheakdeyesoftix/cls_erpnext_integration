<script setup>
import { computed } from "vue";
import { Badge } from "../frappeUi";
import { statusLabel, statusTone } from "../utils";

const props = defineProps({
	status: { type: String, default: "" },
});
const tone = computed(() => statusTone(props.status));
</script>

<template>
	<Badge
		class="order-status"
		:class="`order-status--${tone}`"
		:theme="tone === 'amber' ? 'orange' : tone"
		:label="statusLabel(status)"
	/>
</template>
