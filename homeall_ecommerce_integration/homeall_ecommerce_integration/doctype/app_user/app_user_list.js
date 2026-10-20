// Copyright (c) 2026, Tes Pheakdey and contributors
// For license information, please see license.txt

frappe.listview_settings["App User"] = {
	add_fields: ["status"],

	get_indicator(doc) {
		if (doc.status === "Inactive") {
			return [__("Inactive"), "red", "status,=,Inactive"];
		}

		return [__("Active"), "green", "status,=,Active"];
	},
};
