import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { isNearBottom } from './state.mjs';

// Template refs and layout effects belong to the mounted view, not Pinia state.
export function useChatView(store) {
	const chatRoot = ref(null);
	const scrollbox = ref(null);
	const input = ref(null);
	const photoInput = ref(null);
	const preview = ref(null);
	let layoutObserver, pageObserver, navigationElement;
	function fitHeight() {
		if (!chatRoot.value) return;
		const viewport = window.visualViewport;
		let bottom = viewport ? viewport.height + viewport.offsetTop : window.innerHeight;
		const navigation = document.querySelector('frappe-mobile-nav.desk-mobile-nav')?.getBoundingClientRect();
		if (navigation?.height) bottom = Math.min(bottom, navigation.top);
		// Desk scrolls an ancestor on focus. Measure the unscrolled layout position
		// so that resizing the panel cannot feed back into that scroll position.
		let top = chatRoot.value.getBoundingClientRect().top + window.scrollY;
		for (let parent = chatRoot.value.parentElement; parent; parent = parent.parentElement) {
			if (parent !== document.scrollingElement) top += parent.scrollTop;
		}
		const height = Math.max(0, Math.floor(bottom - Math.max(0, top)));
		const value = `${height}px`;
		if (chatRoot.value.style.getPropertyValue('--chat-height') !== value) {
			chatRoot.value.style.setProperty('--chat-height', value);
		}
	}
	function observeNavigation() {
		const navigation = document.querySelector('frappe-mobile-nav.desk-mobile-nav');
		if (navigation !== navigationElement) {
			if (navigationElement) layoutObserver.unobserve(navigationElement);
			navigationElement = navigation;
			if (navigationElement) layoutObserver.observe(navigationElement);
		}
		fitHeight();
	}
	onMounted(() => {
		fitHeight();
		layoutObserver = new ResizeObserver(fitHeight);
		if (chatRoot.value?.parentElement) layoutObserver.observe(chatRoot.value.parentElement);
		const header = chatRoot.value?.closest('.page-container')?.querySelector('.page-head');
		if (header) layoutObserver.observe(header);
		// Desk loads the phone navigation lazily, even after this page has mounted.
		pageObserver = new MutationObserver(observeNavigation);
		pageObserver.observe(document.body, { childList: true, attributes: true, attributeFilter: ['class'] });
		observeNavigation();
		window.addEventListener('resize', fitHeight);
		window.visualViewport?.addEventListener('resize', fitHeight);
	});
	const detachView = store.bindView({
		nearBottom: () => isNearBottom(scrollbox.value),
		async scrollToBottom() {
			await nextTick();
			if (scrollbox.value) scrollbox.value.scrollTop = scrollbox.value.scrollHeight;
		},
	});

	function grow() {
		nextTick(() => {
			const textarea = input.value?.$el?.querySelector('textarea') || input.value;
			if (!textarea?.style) return;
			textarea.style.height = 'auto';
			textarea.style.height = Math.min(textarea.scrollHeight, 144) + 'px';
		});
	}
	watch(() => store.draft, grow);

	function scrollChanged() {
		if (!isNearBottom(scrollbox.value)) return;
		store.showNew = false;
		store.markVisible();
	}

	async function older() {
		const id = store.selected?.id;
		const oldHeight = scrollbox.value?.scrollHeight || 0;
		if (!await store.older()) return;
		await nextTick();
		if (scrollbox.value && store.selected?.id === id) {
			scrollbox.value.scrollTop += scrollbox.value.scrollHeight - oldHeight;
		}
	}

	function upload(event) {
		const file = event.target.files[0];
		event.target.value = '';
		return store.upload(file);
	}

	function keydown(event) {
		if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
		event.preventDefault();
		store.send();
	}

	function imageLoaded() {
		if (isNearBottom(scrollbox.value)) store.bottom();
	}

	onBeforeUnmount(() => {
		detachView();
		layoutObserver?.disconnect();
		pageObserver?.disconnect();
		window.removeEventListener('resize', fitHeight);
		window.visualViewport?.removeEventListener('resize', fitHeight);
	});
	return { chatRoot, scrollbox, input, photoInput, preview, scrollChanged, older, upload, keydown, imageLoaded };
}
