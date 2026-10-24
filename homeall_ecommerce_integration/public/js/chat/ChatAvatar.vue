<script setup>
import { computed, ref, watch } from 'vue';
import { Avatar } from './frappeUi.js';
import { initial } from './formatters.js';
import { safeImage } from './state.mjs';

const props = defineProps({ conversation: { type: Object, required: true } });
const failed = ref(false);
const image = computed(() => safeImage(props.conversation.customer?.avatar_url));
watch(image, () => { failed.value = false; });
</script>

<template>
	<Avatar class="chat-avatar" size="2xl" :image="failed ? undefined : image || undefined"
		:label="initial(conversation)" aria-hidden="true" @error.capture="failed = true" />
</template>
