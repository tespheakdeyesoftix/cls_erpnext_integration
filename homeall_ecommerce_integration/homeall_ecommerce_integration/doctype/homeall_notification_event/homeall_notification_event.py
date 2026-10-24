from frappe.model.document import Document


class HomeallNotificationEvent(Document):
	@staticmethod
	def clear_old_logs(days=90):
		from homeall_ecommerce_integration.notifications.retention import clear_old_events

		clear_old_events(days)
