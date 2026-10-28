import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const frappeRoot = resolve(appRoot, "../frappe");
const sitesRoot = resolve(appRoot, "../../sites");

// Match bench watch's working directory so content hashes and cleanup agree.
const result = spawnSync(process.execPath, [
	"esbuild",
	"--files",
	"homeall_ecommerce_integration/online_order.bundle.js,homeall_ecommerce_integration/online_order.bundle.css",
], { cwd: frappeRoot, stdio: "inherit" });

if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status || 1);

const assets = JSON.parse(readFileSync(resolve(sitesRoot, "assets/assets.json"), "utf8"));
for (const bundle of ["online_order.bundle.js", "online_order.bundle.css"]) {
	const assetPath = assets[bundle];
	if (!assetPath || !existsSync(resolve(sitesRoot, `.${assetPath}`))) {
		throw new Error(`Built asset is missing: ${bundle} (${assetPath || "no manifest entry"})`);
	}
}

const script = readFileSync(resolve(sitesRoot, `.${assets["online_order.bundle.js"]}`), "utf8");
if (!script.startsWith("frappe.dom.set_style(") || !script.includes(".online-order-page")) {
	throw new Error("The online order JavaScript must include its page styles.");
}
console.log("Online order assets verified; page styles are included in the JavaScript.");
