<script setup>
import { formatMoney, formatQuantity, giftSource, isFreeItem, itemDiscountLabel, itemTotal, itemUnitPrice, productName } from "../utils";

defineProps({
	items: { type: Array, default: () => [] },
	currency: { type: String, default: "USD" },
});
</script>

<template>
	<section class="detail-section">
		<h4>ទំនិញក្នុងការបញ្ជាទិញ</h4>
		<div v-if="items.length" class="order-items">
			<article v-for="(item, index) in items" :key="item.id || `${item.product_id}-${item.uom}-${item.line_type}-${index}`" class="order-item" :class="{ 'order-item--free': isFreeItem(item) }">
				<div class="product-image">
					<img
						v-if="item.image_url || item.product?.default_image_url"
						:src="item.image_url || item.product.default_image_url"
						:alt="productName(item)"
					/>
					<span v-else>គ្មានរូប</span>
				</div>
				<div class="product-info">
					<div class="item-heading">
						<strong>{{ productName(item) }}</strong>
						<span v-if="isFreeItem(item)" class="order-status order-status--green">ទំនិញឥតគិតថ្លៃ</span>
					</div>
					<small v-if="item.erp_item_code || item.product?.erp_item_code">
						កូដ៖ {{ item.erp_item_code || item.product.erp_item_code }}
					</small>
					<small>
						ចំនួន៖ {{ formatQuantity(item.quantity) }} {{ item.uom || item.product?.uom }}
					</small>
					<small v-if="item.base_uom && (item.base_uom !== item.uom || Number(item.conversion_factor) !== 1)">
						ចំនួនឯកតាមូលដ្ឋាន៖ {{ formatQuantity(item.base_quantity) }} {{ item.base_uom }}
						(× {{ formatQuantity(item.conversion_factor) }})
					</small>
					<small>
						តម្លៃ/ឯកតា៖
						<del v-if="item.base_unit_price != null && Number(item.base_unit_price) !== itemUnitPrice(item)">{{ formatMoney(item.base_unit_price, currency) }}</del>
						{{ formatMoney(itemUnitPrice(item), currency) }}
					</small>
					<small v-if="itemDiscountLabel(item, currency) && !isFreeItem(item)" class="discount-text">{{ itemDiscountLabel(item, currency) }}</small>
					<small v-if="item.pricing_snapshot?.promotion_name">ប្រូម៉ូសិន៖ {{ item.pricing_snapshot.promotion_name }}</small>
					<small v-if="isFreeItem(item) && giftSource(item, items)">ទទួលបានពី៖ {{ giftSource(item, items) }}</small>
					<small v-if="Number(item.product_discount_amount) > 0" class="discount-text">
						{{ isFreeItem(item) ? "តម្លៃទំនិញឥតគិតថ្លៃ" : "បញ្ចុះតម្លៃទំនិញ" }}៖ −{{ formatMoney(item.product_discount_amount, currency) }}
					</small>
					<small v-if="Number(item.cart_discount_amount) > 0" class="discount-text">
						បញ្ចុះតម្លៃលើការបញ្ជាទិញ៖ −{{ formatMoney(item.cart_discount_amount, currency) }}
					</small>
					<small v-if="Number(item.tax_amount) > 0">
						ពន្ធ៖ {{ formatMoney(item.tax_amount, currency) }}
					</small>
				</div>
				<div class="item-total">
					<small class="muted">សរុប</small>
					<strong>{{ formatMoney(itemTotal(item), currency) }}</strong>
				</div>
			</article>
		</div>
		<p v-else class="muted">មិនមានព័ត៌មានទំនិញ</p>
	</section>
</template>
