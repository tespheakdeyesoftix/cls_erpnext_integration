<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { storeToRefs } from 'pinia';
import { useChatStore } from './chatStore.js';
import { useChatView } from './useChatView.js';
import { appLabel, day, inboxTime, time, title } from './formatters.js';
import { safeImage, staffDisplayName } from './state.mjs';
import ContextDetails from './ContextDetails.vue';
import ChatAvatar from './ChatAvatar.vue';
import ChatDialog from './ChatDialog.vue';
import { Badge, Button, FeatherIcon, Input, LoadingIndicator, TextInput } from './frappeUi.js';

const store = useChatStore();
const {
	inbox, totalUnread, search, unreadOnly, selected, mobileThread,
	loadingInbox, loadingThread, inboxError, threadError, actionError, setupNotice,
	canSend, inboxMore, loadingMore, showNew, sendingPhoto, active, draft, connection,
	pinned, snapshot, contextType, contextPrice, contextCurrency, orderTotal, orderSummary, maySend,
} = storeToRefs(store);
const { chatRoot, scrollbox, input, photoInput, preview, scrollChanged, older, upload, keydown, imageLoaded } = useChatView(store);
const contextDetails = ref(null);
const previewOpen = computed({ get: () => Boolean(preview.value), set: (open) => { if (!open) preview.value = null; } });
const { loadInbox, moreInbox, openConversation, send, transmit, back, bottom, markVisible } = store;
const sender = (message) => message.sender_role === 'admin' ? staffDisplayName(message) : title(store.selected);
defineExpose({ refresh: () => store.loadInbox(false) });

onMounted(() => store.start());
onBeforeUnmount(() => store.$dispose());
</script>

<template>
	<div ref="chatRoot" class="homeall-chat" :class="{ 'thread-open': mobileThread }">
		<aside class="chat-inbox" aria-label="Chat inbox">
			<div class="inbox-heading"><h2>Chats <Badge v-if="totalUnread" class="chat-ui-badge total-unread" variant="solid" :label="totalUnread" /></h2>
				<span class="connection" :class="connection.toLowerCase()" role="status"><i></i>{{ connection }}</span></div>
			<div class="inbox-tools"><label class="sr-only" for="chat-search">Search customer or business</label>
				<TextInput id="chat-search" v-model="search" class="chat-search" type="search" size="md" variant="subtle" placeholder="Search customer or business">
					<template #prefix><FeatherIcon class="chat-search-icon" name="search" /></template>
				</TextInput>
				<div class="chat-tabs" role="group" aria-label="Filter conversations">
					<Button class="chat-ui-button" :aria-pressed="!unreadOnly" :class="{ chosen: !unreadOnly }" :variant="unreadOnly ? 'ghost' : 'subtle'" @click="unreadOnly = false">All</Button>
					<Button class="chat-ui-button" :aria-pressed="unreadOnly" :class="{ chosen: unreadOnly }" :variant="unreadOnly ? 'subtle' : 'ghost'" @click="unreadOnly = true">Unread</Button>
				</div></div>
			<div class="inbox-list">
				<div v-if="inboxError" class="chat-error" role="alert">{{ inboxError }} <Button class="chat-ui-button" variant="ghost" @click="loadInbox()">Retry</Button></div>
				<div v-if="loadingInbox" class="chat-empty" role="status"><LoadingIndicator class="chat-loading" />Loading conversations…</div>
				<div v-else-if="!inbox.length && !inboxError" class="chat-empty">{{ search ? 'No matching conversations' : unreadOnly ? 'You’re all caught up' : 'No conversations yet' }}</div>
				<button v-for="item in inbox" :key="item.id" class="conversation-row" :class="{ selected: selected?.id === item.id }" @click="openConversation(item)">
					<ChatAvatar :conversation="item" />
					<span class="conversation-details"><span class="row-title"><strong>{{ title(item) }}</strong><time>{{ inboxTime(item.last_message_at) }}</time></span>
						<span v-if="item.customer?.username" class="username">@{{ item.customer.username }}</span>
						<span class="business-line"><Badge class="chat-ui-badge app-label" size="sm" :label="appLabel(item)" /> {{ item.kind || 'general' }}<span v-if="item.business?.name"> · {{ item.business.name }}</span></span>
						<span class="preview-line"><span>{{ item.last_message_preview || 'No messages yet' }}</span><Badge v-if="item.unread_count" class="chat-ui-badge unread-badge" size="sm" variant="solid" :label="item.unread_count" /></span>
					</span>
				</button>
				<Button v-if="inboxMore" class="chat-ui-button load-more" variant="outline" :loading="loadingMore" loading-text="Loading…" @click="moreInbox">Load more conversations</Button>
			</div>
		</aside>
		<section class="chat-thread" aria-label="Conversation">
			<div v-if="!selected" class="thread-placeholder"><span class="placeholder-icon"><FeatherIcon name="message-circle" /></span><h3>Select a conversation</h3><p>Your customers’ messages, all in one place.</p></div>
			<template v-else>
				<header class="thread-header"><Button class="chat-ui-button chat-icon-button chat-back" variant="ghost" label="Back to inbox" aria-label="Back to inbox" @click="back">
						<template #icon><FeatherIcon name="arrow-left" aria-hidden="true" /></template>
					</Button>
					<ChatAvatar :conversation="selected" />
					<div class="thread-identity"><h3>{{ title(selected) }} <Badge class="chat-ui-badge app-label" size="sm" :label="appLabel(selected)" /></h3>
						<p><span v-if="selected.customer?.username">@{{ selected.customer.username }} · </span>{{ selected.business?.name || 'Customer support' }}</p>
						<p class="contact-details"><span v-if="selected.customer?.email">{{ selected.customer.email }}</span><span v-if="selected.customer?.phone">{{ selected.customer.phone }}</span></p></div>
				</header>
				<div v-if="pinned" class="context-card">
					<span v-if="contextType === 'order'" class="context-icon"><FeatherIcon name="shopping-bag" /></span>
					<img v-if="contextType === 'product' && safeImage(snapshot.image_url || snapshot.image || snapshot.product?.image_url)" :src="safeImage(snapshot.image_url || snapshot.image || snapshot.product?.image_url)" alt="Product" />
					<div class="context-summary"><span class="context-label">{{ contextType === 'order' ? 'Order' : 'Product' }} context</span>
						<strong>{{ contextType === 'order' ? (snapshot.display_number || snapshot.order_number || snapshot.order?.display_number || 'Order') : (snapshot.name || snapshot.product_name || snapshot.product?.name || 'Product') }}</strong>
						<p v-if="contextType === 'product'">{{ snapshot.item_code || snapshot.product?.item_code }} <span v-if="contextPrice != null"> · {{ contextCurrency }} {{ contextPrice }}</span></p>
						<p v-else>{{ orderSummary }}<span v-if="orderTotal != null"> · {{ contextCurrency }} {{ orderTotal }}</span></p>
					</div>
					<Button type="button" class="chat-ui-button context-details-button" variant="subtle" icon-right="chevron-right" @click="contextDetails.open()">View details</Button>
				</div>
				<div v-if="threadError" class="chat-error" role="alert">{{ threadError }} <Button class="chat-ui-button" variant="ghost" @click="openConversation(selected)">Retry</Button></div>
				<div ref="scrollbox" class="message-scroll" @scroll.passive="scrollChanged">
					<div v-if="loadingThread" class="chat-empty" role="status"><LoadingIndicator class="chat-loading" />Loading messages…</div>
					<Button v-if="active?.hasMore" class="chat-ui-button load-more" variant="outline" :loading="active.loadingOlder" loading-text="Loading…" @click="older">Load older messages</Button>
					<div v-if="!loadingThread && !active?.items.length" class="chat-empty">Start the conversation with a reply.</div>
					<template v-for="(message, index) in active?.items || []" :key="message.id">
						<div v-if="index === 0 || day(message.created_at) !== day(active.items[index - 1].created_at)" class="date-separator"><span>{{ day(message.created_at) }}</span></div>
						<div class="message-row" :class="{ admin: message.sender_role === 'admin' }"><div class="message-bubble" :class="{ failed: message._status === 'failed' }">
							<strong class="sender-name">{{ sender(message) }}</strong>
							<button v-if="message.kind === 'photo'" class="photo-message" aria-label="Enlarge photo" @click="preview = message.media_url"><img :src="message.media_url" alt="Chat photo" loading="lazy" @load="imageLoaded" /><span>View photo</span></button>
							<p v-else class="message-text">{{ message.body }}</p>
							<div class="message-meta"><time :datetime="message.created_at">{{ time(message.created_at) }}</time><span v-if="message._status === 'sending'">Sending…</span>
								<Button v-else-if="message._status === 'failed'" class="chat-ui-button retry-message" variant="ghost" :disabled="!maySend" @click="transmit(message)">Failed · Retry</Button></div>
						</div></div>
					</template>
				</div>
				<Button v-if="showNew" class="chat-ui-button new-messages" variant="outline" @click="bottom().then(markVisible)">New messages ↓</Button>
				<div v-if="setupNotice || actionError" class="composer-notice" role="status">{{ actionError || setupNotice }}</div>
				<form class="chat-composer" @submit.prevent="send">
					<input ref="photoInput" type="file" accept="image/jpeg,image/png,image/webp" hidden @change="upload" />
					<Button type="button" class="chat-ui-button chat-icon-button attach-button" variant="ghost" label="Attach photo" aria-label="Attach photo" title="Attach photo" :disabled="!maySend" :loading="sendingPhoto" @click="photoInput.click()">
						<template #icon><FeatherIcon name="image" aria-hidden="true" /></template>
					</Button>
					<div class="composer-input"><label class="sr-only" for="chat-message">Reply</label><Input id="chat-message" ref="input" class="chat-reply-field" type="textarea" :model-value="draft" :rows="1" :disabled="!canSend" :placeholder="canSend ? 'Write a reply…' : 'Replies are unavailable for this account'" @input="draft = $event" @keydown="keydown" /><span v-if="draft.length > 3600" :class="{ 'over-limit': [...draft].length > 4000 }">{{ [...draft].length }}/4000</span></div>
					<Button type="submit" class="chat-ui-button send-button" variant="solid" icon-right="arrow-up" :disabled="!maySend || !draft.trim() || [...draft].length > 4000">Send</Button>
				</form>
			</template>
		</section>
		<ContextDetails ref="contextDetails" :conversation-id="selected?.id" :snapshot="snapshot" :context-type="contextType" :currency="contextCurrency" :price="contextPrice" :total="orderTotal" :summary="orderSummary" />
		<ChatDialog v-model="previewOpen" title="Photo preview" close-label="Close photo preview" wide>
			<img v-if="preview" class="chat-photo-preview" :src="preview" alt="Enlarged chat photo" />
		</ChatDialog>
	</div>
</template>
