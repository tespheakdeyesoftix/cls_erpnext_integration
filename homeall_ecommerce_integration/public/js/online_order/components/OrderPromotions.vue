<script setup>
import { formatMoney, formatQuantity } from "../utils";

defineProps({
	promotions: { type: Array, default: () => [] },
	currency: { type: String, default: "USD" },
});
</script>

<template>
	<section v-if="promotions.length" class="detail-section">
		<h4>ប្រូម៉ូសិនលើការបញ្ជាទិញ</h4>
		<div class="order-promotions">
			<article v-for="(promotion, index) in promotions" :key="promotion.id || promotion.promotion_id || index" class="promotion-card">
				<div class="promotion-heading">
					<strong>{{ promotion.promotion_name }}</strong>
					<strong class="discount-text">−{{ formatMoney(promotion.discount_amount, promotion.currency || currency) }}</strong>
				</div>
				<p class="muted">
					{{ promotion.application_scope === 'entire_cart' ? 'ការបញ្ជាទិញទាំងមូល' : 'ទំនិញដែលមានសិទ្ធិ' }} ·
					{{ promotion.discount_type === 'percentage' ? `${formatQuantity(promotion.discount_value)}%` : formatMoney(promotion.discount_value, promotion.currency || currency) }}
				</p>
				<p class="muted">
					មូលដ្ឋានបញ្ចុះតម្លៃ៖ {{ formatMoney(promotion.benefit_base_amount, promotion.currency || currency) }}
				</p>
				<p v-if="promotion.eligibility_basis === 'quantity' && promotion.qualifying_quantity != null" class="muted">
					ចំនួនមានសិទ្ធិ៖ {{ formatQuantity(promotion.qualifying_quantity) }} {{ promotion.pricing_snapshot?.qualification_uom || '' }}
				</p>
				<p v-else-if="promotion.qualifying_amount != null" class="muted">
					ទឹកប្រាក់មានសិទ្ធិ៖ {{ formatMoney(promotion.qualifying_amount, promotion.currency || currency) }}
				</p>
			</article>
		</div>
	</section>
</template>
