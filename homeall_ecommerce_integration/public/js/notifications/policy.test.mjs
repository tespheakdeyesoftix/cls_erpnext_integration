import { test } from 'node:test';
import assert from 'node:assert/strict';
import { destination, mayPrompt, notificationData, listenForRoutes } from './policy.mjs';

const id = '10000000-0000-4000-8000-000000000001';
const origin = 'https://erp.example.com';
test('route subscriptions remove their exact namespaced callback on disposal', () => {
	const handlers = new Map();
	const router = { jq: { on: (name, fn) => handlers.set(name, fn), off: (name, fn) => {
		assert.equal(handlers.get(name), fn); handlers.delete(name);
	} } };
	const stop = listenForRoutes(router, () => {}, 'test');
	assert.equal(handlers.size, 1); stop(); assert.equal(handlers.size, 0);
});
test('only exact same-origin order/chat links and UUID arguments are allowed', () => {
	assert.ok(destination(`/desk/online-order?order=${id}`, origin));
	assert.ok(destination(`/desk/chat?conversation=${id}&message=${id}`, origin));
	for (const path of [`https://evil.test/desk/online-order?order=${id}`, '//evil.test', '/desk/user',
		`/desk/online-order?order=${id}&redirect=https://evil.test`, '/desk/online-order?order=invalid',
		`/desk/online-order?order=${id}#evil`]) assert.equal(destination(path, origin), null);
});
test('every unsubscribed visit prompts, including blocked permission and legacy snoozes', () => {
	for (const change of [{}, { permission: 'denied' }, { permission: 'granted' }, { supported: false }, { snoozeUntil: Number.MAX_SAFE_INTEGER }]) {
		assert.equal(mayPrompt({ enabled: false, ...change }), true);
	}
	assert.equal(mayPrompt({ enabled: true }), false);
});
test('push display ignores remote copy, rejects expired and mismatched events', () => {
	const data = { event_id: id, type: 'order_created', title: '<script>', expires_at: '100',
		destination: `/desk/online-order?order=${id}&homeall_event=${id}` };
	assert.equal(notificationData(data, origin, 1000).title, 'New online order');
	assert.equal(notificationData(data, origin, 100000), null);
	assert.equal(notificationData({ ...data, expires_at: 'invalid' }, origin, 0), null);
	assert.equal(notificationData({ ...data, event_id: 'invalid' }, origin, 0), null);
});
