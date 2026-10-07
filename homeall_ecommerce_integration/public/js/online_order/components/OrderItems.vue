<script setup>
import { formatMoney, itemTotal, itemUnitPrice, productName } from "../utils";

defineProps({
	items: { type: Array, default: () => [] },
	currency: { type: String, default: "USD" },
});
</script>

<template>
	<section class="detail-section">
		<h4>ទំនិញក្នុងការបញ្ជាទិញ</h4>
		<div v-if="items.length" class="order-items">
			<article v-for="item in items" :key="item.product_id" class="order-item">
				<div class="product-image">
					<img
						v-if="item.product?.default_image_url"
						:src="item.product.default_image_url"
						:alt="productName(item)"
					/>
					<span v-else>គ្មានរូប</span>
				</div>
				<div class="product-info">
					<strong>{{ productName(item) }}</strong>
					<small v-if="item.product?.erp_item_code">
						កូដ៖ {{ item.product.erp_item_code }}
					</small>
					<small>
						{{ formatMoney(itemUnitPrice(item), item.product?.currency || currency) }}
						× {{ item.quantity || 0 }}
						<span v-if="item.product?.uom">{{ item.product.uom }}</span>
					</small>
				</div>
				<strong class="item-total">{{ formatMoney(itemTotal(item), currency) }}</strong>
			</article>
		</div>
		<p v-else class="muted">មិនមានព័ត៌មានទំនិញ</p>
	</section>
</template>
