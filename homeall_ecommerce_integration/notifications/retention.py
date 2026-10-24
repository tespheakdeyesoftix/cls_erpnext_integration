"""Bounded Log Settings cleanup that retains event identities for deduplication."""

import frappe
from frappe.utils import add_days, cint, get_datetime, now_datetime

from .worker import DELIVERY, EVENT

BATCH_SIZE = 250
MAX_BATCHES = 20
COMPLETED = {"Sent", "Skipped"}


def clear_old_events(days=90):
	# Treat zero as disabled, rather than removing today's delivery history.
	if cint(days) <= 0:
		return
	cutoff = add_days(now_datetime(), -cint(days))
	for _ in range(MAX_BATCHES):
		candidates = frappe.db.sql(
			"""select e.name from `tabHomeall Notification Event` e
			where e.status = 'Ready' and e.modified < %(cutoff)s and e.payload is not null
			and not exists (
				select 1 from `tabHomeall Notification Delivery` d
				where d.parent = e.name and d.parenttype = %(parenttype)s
				and (d.status not in ('Sent', 'Skipped') or d.modified >= %(cutoff)s
					or exists (select 1 from `tabNotification Log` n where n.name = d.notification_log))
			)
			order by e.modified, e.name limit %(limit)s""",
			{"cutoff": cutoff, "parenttype": EVENT, "limit": BATCH_SIZE},
			as_dict=True,
		)
		if not candidates:
			break
		compacted = sum(compact_event(row.name, cutoff) for row in candidates)
		# Release locks and keep each cleanup transaction small. Log Settings also
		# commits after the controller returns; partial progress is safe to resume.
		frappe.db.commit()
		if not compacted:
			break


def compact_event(name, cutoff):
	# Match fanout's event lock, then lock deliveries and recheck after selection.
	event = frappe.get_doc(EVENT, name, for_update=True)
	if event.status != "Ready" or event.payload is None or get_datetime(event.modified) >= cutoff:
		return False
	rows = frappe.db.sql(
		"""select status, modified, notification_log from `tabHomeall Notification Delivery`
		where parent = %s and parenttype = %s for update""",
		(name, EVENT),
		as_dict=True,
	)
	if any(row.status not in COMPLETED or get_datetime(row.modified) >= cutoff for row in rows):
		return False
	logs = [row.notification_log for row in rows if row.notification_log]
	if logs and frappe.db.exists("Notification Log", {"name": ["in", logs]}):
		# mark_opened() still needs these mappings while bell entries exist.
		return False
	frappe.db.delete(DELIVERY, {"parent": name, "parenttype": EVENT})
	# INSERT IGNORE and status Ready make a replay of this UUID harmless, even
	# after the order/chat identifiers and delivery history have been removed.
	frappe.db.set_value(EVENT, name, {"payload": None, "destination": None}, update_modified=False)
	return True
