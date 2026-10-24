<script setup>
import { Button, Dialog, FeatherIcon } from './frappeUi.js';

defineProps({
	modelValue: Boolean,
	title: { type: String, required: true },
	closeLabel: { type: String, default: 'Close details' },
	wide: Boolean,
});
const emit = defineEmits(['update:modelValue']);
const close = () => emit('update:modelValue', false);
</script>

<template>
	<Dialog :model-value="modelValue" :options="{ title, size: wide ? '5xl' : '2xl' }"
		class="homeall-chat-modal" :class="{ 'chat-photo-modal': wide }" :aria-label="title"
		@update:model-value="emit('update:modelValue', $event)">
		<template #body>
			<div class="homeall-chat-dialog">
				<header class="context-dialog-header">
					<h3>{{ title }}</h3>
					<Button class="chat-ui-button chat-icon-button" variant="ghost"
						:label="closeLabel" :aria-label="closeLabel" @click="close">
						<template #icon><FeatherIcon name="x" aria-hidden="true" /></template>
					</Button>
				</header>
				<div class="context-dialog-body"><slot /></div>
				<footer class="context-dialog-footer">
					<Button class="chat-ui-button" variant="subtle" @click="close">Close</Button>
				</footer>
			</div>
		</template>
	</Dialog>
</template>
