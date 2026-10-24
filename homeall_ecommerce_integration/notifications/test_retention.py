"""Offline retention checks; no live notification history is deleted."""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import frappe

from homeall_ecommerce_integration.homeall_ecommerce_integration.doctype.homeall_notification_event.homeall_notification_event import (
	HomeallNotificationEvent,
)

from . import retention


class RetentionTests(unittest.TestCase):
	def setUp(self):
		self.cutoff = datetime(2026, 7, 26)
		self.old = self.cutoff - timedelta(days=1)
		self.event = frappe._dict(status="Ready", payload='{"order_id":"private"}', modified=self.old)
		self.row = frappe._dict(status="Sent", modified=self.old, notification_log=None)
		self.db = MagicMock()
		self.db.sql.return_value = [self.row]
		self.db.exists.return_value = False
		for obj, attr, value in [
			(frappe, "db", self.db),
			(frappe, "get_doc", MagicMock(return_value=self.event)),
			(retention, "now_datetime", lambda: self.cutoff + timedelta(days=90)),
		]:
			p = patch.object(obj, attr, value)
			p.start()
			self.addCleanup(p.stop)

	def test_controller_exposes_log_settings_interface(self):
		with patch.object(retention, "clear_old_events") as clear:
			HomeallNotificationEvent.clear_old_logs(days=90)
		clear.assert_called_once_with(90)

	def test_cleanup_retains_identity_and_does_not_delete_bell_or_event(self):
		self.assertTrue(retention.compact_event("event", self.cutoff))
		frappe.get_doc.assert_called_once_with(retention.EVENT, "event", for_update=True)
		self.assertIn("for update", self.db.sql.call_args.args[0])
		self.db.delete.assert_called_once_with(
			retention.DELIVERY, {"parent": "event", "parenttype": retention.EVENT}
		)
		self.db.set_value.assert_called_once_with(
			retention.EVENT, "event", {"payload": None, "destination": None}, update_modified=False
		)

	def test_pending_recent_and_already_compacted_events_are_preserved(self):
		for change in [{"status": "Pending"}, {"modified": self.cutoff}, {"payload": None}]:
			self.event.update(status="Ready", payload="{}", modified=self.old)
			self.event.update(change)
			self.assertFalse(retention.compact_event("event", self.cutoff))
		self.db.delete.assert_not_called()

	def test_active_failed_unknown_and_recent_deliveries_are_preserved(self):
		for status in ["Pending", "Sending", "Failed", None]:
			self.row.status = status
			self.assertFalse(retention.compact_event("event", self.cutoff))
		self.row.update(status="Skipped", modified=self.cutoff)
		self.assertFalse(retention.compact_event("event", self.cutoff))
		self.db.delete.assert_not_called()

	def test_existing_bell_mapping_is_preserved_for_mark_opened(self):
		self.row.notification_log = "bell"
		self.db.exists.return_value = True
		self.assertFalse(retention.compact_event("event", self.cutoff))
		self.db.delete.assert_not_called()
		self.db.exists.assert_called_once_with("Notification Log", {"name": ["in", ["bell"]]})

	def test_skipped_delivery_can_be_cleaned_after_bell_expires(self):
		self.row.update(status="Skipped", notification_log="expired-bell")
		self.assertTrue(retention.compact_event("event", self.cutoff))

	def test_nonpositive_retention_disables_cleanup(self):
		for days in [0, -1, "0"]:
			retention.clear_old_events(days)
		self.db.sql.assert_not_called()

	def test_cleanup_is_bounded_and_commits_batches(self):
		self.db.sql.return_value = [frappe._dict(name="event")]
		with patch.object(retention, "compact_event", return_value=True) as compact:
			retention.clear_old_events(90)
		self.assertEqual(compact.call_count, retention.MAX_BATCHES)
		self.assertEqual(self.db.commit.call_count, retention.MAX_BATCHES)
		self.assertEqual(self.db.sql.call_args.args[1]["limit"], retention.BATCH_SIZE)

	def test_concurrent_change_stops_cleanup_without_spinning(self):
		self.db.sql.return_value = [frappe._dict(name="event")]
		with patch.object(retention, "compact_event", return_value=False) as compact:
			retention.clear_old_events(90)
		compact.assert_called_once()
		self.db.commit.assert_called_once()
