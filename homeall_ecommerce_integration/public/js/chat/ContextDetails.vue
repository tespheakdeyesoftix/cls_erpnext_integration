<script setup>
import { computed, ref, watch } from 'vue';
import { safeImage } from './state.mjs';
import ChatDialog from './ChatDialog.vue';

const props = defineProps(['conversationId', 'snapshot', 'contextType', 'currency', 'price', 'total', 'summary']);
const visible = ref(false);
const isOrder = computed(() => props.contextType === 'order');
const name = computed(() => isOrder.value
	? props.snapshot.display_number || props.snapshot.order_number || props.snapshot.order?.display_number || 'Order'
	: props.snapshot.name || props.snapshot.product_name || props.snapshot.product?.name || 'Product');
const image = computed(() => safeImage(props.snapshot.image_url || props.snapshot.image || props.snapshot.product?.image_url));
const code = computed(() => props.snapshot.item_code || props.snapshot.product?.item_code);
const status = computed(() => props.snapshot.status || props.snapshot.order?.status);
const items = computed(() => props.snapshot.items || props.snapshot.order?.items || []);
const basePrice = computed(() => props.snapshot.pricing?.base_unit_price);
function close() { visible.value = false; }
function open() { if (props.conversationId) visible.value = true; }
watch(() => props.conversationId, close);
defineExpose({ open });
</script>

<template>
	<ChatDialog v-model="visible" :title="isOrder ? 'Order details' : 'Product details'" close-label="Close context details">
		<img v-if="image && !isOrder" class="context-product-image" :src="image" :alt="name" />
		<h4>{{ name }}</h4>
		<dl class="context-facts">
			<template v-if="!isOrder && code"><dt>Item code</dt><dd>{{ code }}</dd></template>
			<template v-if="isOrder && status"><dt>Status</dt><dd>{{ status }}</dd></template>
			<template v-if="!isOrder && price != null"><dt>Unit price</dt><dd>{{ currency }} {{ price }}</dd></template>
			<template v-if="!isOrder && basePrice != null && basePrice !== price"><dt>Base unit price</dt><dd>{{ currency }} {{ basePrice }}</dd></template>
			<template v-if="isOrder && total != null"><dt>Total</dt><dd>{{ currency }} {{ total }}</dd></template>
		</dl>
		<template v-if="isOrder">
			<h5>Items</h5>
			<ul v-if="items.length" class="context-items">
				<li v-for="(item, index) in items" :key="index">
					<img v-if="safeImage(item.image_url)" :src="safeImage(item.image_url)" alt="" loading="lazy" />
					<div><strong>{{ item.name || item.item_name || item.product_name || 'Item' }}</strong><span v-if="item.item_code || item.erp_item_code">{{ item.item_code || item.erp_item_code }}</span></div>
					<span class="context-item-quantity">{{ item.quantity ?? 1 }} {{ item.unit || item.uom || '' }}</span>
				</li>
			</ul>
			<p v-else>{{ summary || 'No item details available.' }}</p>
		</template>
	</ChatDialog>
</template>
