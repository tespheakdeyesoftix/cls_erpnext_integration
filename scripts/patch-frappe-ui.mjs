import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const componentsDir = path.join(projectRoot, "node_modules", "frappe-ui", "src", "components");

if (!fs.existsSync(componentsDir)) {
	console.log("frappe-ui is not installed; compatibility patch skipped.");
	process.exit(0);
}

const featherModule = `import { h, mergeProps } from "vue";
import feather from "feather-icons";

const validIcons = Object.keys(feather.icons);

export default {
	name: "FeatherIcon",
	props: {
		name: {
			type: String,
			required: true,
			validator: (value) => validIcons.includes(value),
		},
		color: { type: String, default: null },
		strokeWidth: { type: Number, default: 1.5 },
	},
	render() {
		const icon = feather.icons[this.name] || feather.icons.circle;
		return h(
			"svg",
			mergeProps(
				icon.attrs,
				{
					fill: "none",
					stroke: "currentColor",
					color: this.color,
					"stroke-linecap": "round",
					"stroke-linejoin": "round",
					"stroke-width": this.strokeWidth,
					width: null,
					height: null,
					class: [icon.attrs.class, "shrink-0"],
					innerHTML: icon.contents,
				},
				this.$attrs,
			),
		);
	},
};
`;

fs.writeFileSync(path.join(componentsDir, "FeatherIcon.js"), featherModule);

for (const filename of fs.readdirSync(componentsDir)) {
	if (!filename.endsWith(".vue")) continue;

	const componentPath = path.join(componentsDir, filename);
	const source = fs.readFileSync(componentPath, "utf8");
	const patched = source.replaceAll("./FeatherIcon.vue", "./FeatherIcon.js");
	if (patched !== source) fs.writeFileSync(componentPath, patched);
}

const popoverPath = path.join(componentsDir, "Popover.vue");
const popover = fs
	.readFileSync(popoverPath, "utf8")
	.replace("beforeDestroy() {", "beforeUnmount() {");
fs.writeFileSync(popoverPath, popover);

const datePickerPath = path.join(componentsDir, "DatePicker.vue");
let datePicker = fs.readFileSync(datePickerPath, "utf8");
datePicker = datePicker
	.replace("['S', 'M', 'T', 'W', 'T', 'F', 'S']", "['អា', 'ច', 'អ', 'ព', 'ព្រ', 'សុ', 'ស']")
	.replace(">\n            Clear\n          <", ">\n            សម្អាត\n          <")
	.replace("toLocaleString('en-US'", "toLocaleString('km-KH'");
fs.writeFileSync(datePickerPath, datePicker);

console.log("Applied Frappe 16 compatibility and Khmer labels to frappe-ui.");
