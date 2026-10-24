import test from 'node:test';
import assert from 'node:assert/strict';
import { clientMessageId, mergeMessages, sortConversations, isNearBottom, normalizeMessage, staffDisplayName } from './state.mjs';
const base = { sender_display_name: null, conversation_id: 'thread', sender_role: 'admin', client_message_id: 'client', created_at: '2026-10-23T10:00:00Z' };
const pending = { ...base, id: 'pending', _status: 'sending' };
const saved = { ...base, id: 'saved', sender_display_name: 'Alice' };

test('realtime echo before send response replaces optimistic bubble once', () => {
	const echo = mergeMessages([pending], [saved]);
	assert.deepEqual(mergeMessages(echo, [saved]), [saved]);
});
test('send response followed by realtime echo produces one saved bubble', () => {
	assert.deepEqual(mergeMessages(mergeMessages([pending], [saved]), [saved]), [saved]);
});
test('failed retry retains client identity and a later echo wins', () => {
	assert.deepEqual(mergeMessages([{ ...pending, _status: 'failed' }], [saved]), [saved]);
});
test('late failure or optimistic state cannot overwrite an acknowledged message', () => {
	assert.deepEqual(mergeMessages([saved], [{ ...pending, _status: 'failed' }]), [saved]);
});
test('catch-up preserves older loaded history, pending sends and chronological order', () => {
	const old = { ...base, id: 'old', client_message_id: 'old-client', created_at: '2026-10-22T00:00:00Z' };
	const another = { ...pending, id: 'pending2', client_message_id: 'another', created_at: '2026-10-24T00:00:00Z' };
	assert.deepEqual(mergeMessages([old, another], [saved, saved]), [old, saved, another]);
});
test('same client UUID in another thread or sender role is a different message', () => {
	assert.equal(mergeMessages([saved], [{ ...saved, id: 'other', conversation_id: 'other' }, { ...saved, id: 'customer', sender_role: 'customer' }]).length, 3);
});
test('inbox sorts by latest activity and deduplicates updated rows', () => {
	assert.deepEqual(sortConversations([{ id: 'a', last_message_at: '2026-10-22' }, { id: 'b', last_message_at: '2026-10-23' }, { id: 'a', last_message_at: '2026-10-24', unread_count: 0 }]).map((m) => m.id), ['a', 'b']);
});
test('reader position determines autoscroll threshold', () => {
	assert.equal(isNearBottom({ scrollHeight: 1000, scrollTop: 100, clientHeight: 400 }), false);
	assert.equal(isNearBottom({ scrollHeight: 1000, scrollTop: 550, clientHeight: 400 }), true);
});
test('client message IDs have UUID v4 identity for sends and retry storage', () => {
	const first = clientMessageId(), second = clientMessageId();
	assert.match(first, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
	assert.notEqual(first, second);
});

test('normalization retains saved aliases and accepts absent or invalid legacy fields', () => {
	assert.equal(normalizeMessage(saved).sender_display_name, 'Alice');
	assert.equal(normalizeMessage({ id: 'legacy' }).sender_display_name, null);
	assert.equal(normalizeMessage({ sender_display_name: 42 }).sender_display_name, null);
});
test('staff labels trim names and show Support for missing, null or whitespace aliases', () => {
	for (const name of [undefined, null, '', '   ']) assert.equal(staffDisplayName({ sender_display_name: name }), 'Support');
	assert.equal(staffDisplayName({ sender_display_name: '  Alice  ' }), 'Alice');
	assert.equal(staffDisplayName({ sender_display_name: '<b>Alice</b>' }), '<b>Alice</b>');
});
test('a later legacy response cannot erase a saved alias during realtime or catch-up', () => {
	for (const name of [undefined, null, '', '   ']) {
		const legacy = { ...saved, sender_display_name: name };
		assert.equal(mergeMessages([saved], [legacy])[0].sender_display_name, 'Alice');
	}
});
test('authoritative legacy save never borrows the optimistic current staff name', () => {
	const optimistic = { ...pending, sender_display_name: 'Current Staff' };
	const canonical = { ...saved, sender_display_name: null };
	assert.equal(mergeMessages([optimistic], [canonical])[0].sender_display_name, null);
	assert.equal(staffDisplayName(mergeMessages([optimistic], [canonical])[0]), 'Support');
});
test('saved original alias wins over a renamed staff optimistic bubble in either arrival order', () => {
	const optimistic = { ...pending, sender_display_name: 'Renamed Staff' };
	assert.equal(mergeMessages(mergeMessages([optimistic], [saved]), [saved])[0].sender_display_name, 'Alice');
	assert.equal(mergeMessages([saved], [optimistic])[0].sender_display_name, 'Alice');
});
test('text and photo aliases survive older-page prepends and reconnect catch-up', () => {
	const photo = { ...saved, id: 'photo', client_message_id: 'photo-client', kind: 'photo', sender_display_name: 'Bob', created_at: '2026-10-22T00:00:00Z' };
	const history = mergeMessages([saved], [photo]);
	const catchup = mergeMessages(history, [{ ...photo, sender_display_name: undefined }, { ...saved }]);
	assert.deepEqual(catchup.map(m => m.sender_display_name), ['Bob', 'Alice']);
});
