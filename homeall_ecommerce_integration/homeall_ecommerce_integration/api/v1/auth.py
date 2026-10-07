import frappe
from frappe.auth import LoginManager


@frappe.whitelist(allow_guest=True, methods=["POST"])
def login(usr: str, pwd: str) -> dict[str, str | None] | None:
	"""Authenticate a user and return the profile required by the mobile app."""
	login_manager = LoginManager()

	# LoginManager reads the standard ``usr`` and ``pwd`` request parameters and
	# applies Frappe's normal login hooks, password-reset rules, and 2FA flow.
	if login_manager.login() is False:
		return None

	return {
		"name": login_manager.user,
		"full_name": login_manager.full_name,
		"photo": login_manager.info.user_image,
	}

def login_with_phone():
	pass


def verify_otp():
	pass