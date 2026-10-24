"""Browser checks using real application sources and mocked Firebase/network services.

Run with Playwright installed after building app assets. No real push is sent.
"""

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "homeall_ecommerce_integration/public/js/notifications"
MOCK = """
export function initializeApp(){return {}};
export function getApp(){return {}};
export function getMessaging(){return {}};
export async function isSupported(){return true};
export async function getToken(){window.trace.push('token');if(window.failToken)throw new Error('Registration failed');return 'valid-firebase-token-1234567890'};
export async function deleteToken(){window.trace.push('deleteToken')};
export function onMessage(fn, callback){window.foreground=callback};
export function onBackgroundMessage(fn, callback){window.background=callback};
"""
HARNESS = """
window.trace=[];window.calls=[];window.notices=[];window.handlers={};window.routeHandlers={};
window.cfg={enabled:true,push_enabled:true,configured:true,firebase:{},vapid_key:'public'};
window.$=(callback)=>callback();window.__=(text)=>text;
Object.defineProperty(window,'Notification',{value:class {
 static permission='default';
 static requestPermission(){trace.push(navigator.userActivation.isActive?'permission-click':'permission-no-click');this.permission=window.denyPermission?'denied':'granted';return Promise.resolve(this.permission)}
}});
Object.defineProperty(navigator,'serviceWorker',{value:{async register(){trace.push('worker');return {}}}});
window.frappe={session:{user:'alice'},boot:{},realtime:{on(name,fn){handlers[name]=fn}},
 router:{jq:{on(name,fn){routeHandlers[name]=fn},off(name){delete routeHandlers[name]}}},
 show_alert(value){notices.push(value)},msgprint(text){notices.push(text)},
 async call({method,args}){const operation=method.split('.').at(-1);calls.push({operation,args});
  if(operation==='get_config')return {message:cfg};
  if(operation==='register')trace.push('register');
  return {message:{enabled:operation==='register'}};
 },ui:{Dialog:class {
 constructor(options){this.options=options;this.el=document.createElement('section');this.el.className='dialog';
 this.el.innerHTML=options.fields[0].options;
 this.primary=document.createElement('button');this.primary.textContent=options.primary_action_label;
 this.primary.onclick=options.primary_action;this.el.append(this.primary);
 this.later=document.createElement('button');this.later.textContent='Later';this.later.onclick=options.secondary_action;this.el.append(this.later);}
 show(){document.body.append(this.el)} hide(){this.el.remove();this.onhide?.()}
 get_primary_btn(){return {hide:()=>this.primary.hidden=true}}
 }}};
"""


def main():
	from playwright.sync_api import expect, sync_playwright

	with tempfile.TemporaryDirectory(prefix="homeall-notification-browser-") as folder:
		target = Path(folder)
		mock = target / "firebase.mjs"
		mock.write_text(MOCK)
		for entry, output in [
			("homeall_notifications.bundle.js", "client.js"),
			("homeall_push_worker.bundle.js", "worker.js"),
		]:
			script = """const esbuild=require(process.argv[1]);esbuild.buildSync({entryPoints:[process.argv[2]],
             outfile:process.argv[3],bundle:true,format:'iife',alias:{'firebase/app':process.argv[4],
             'firebase/messaging/sw':process.argv[4],'firebase/messaging':process.argv[4]}})"""
			subprocess.run(
				[
					"node",
					"-e",
					script,
					str(ROOT.parent / "frappe/node_modules/esbuild"),
					str(PUBLIC / entry),
					str(target / output),
					str(mock),
				],
				check=True,
			)
		with sync_playwright() as p:
			browser = p.chromium.launch(headless=True)
			page = browser.new_page()
			errors = []
			page.on("pageerror", lambda error: errors.append(str(error)))
			page.route(
				"https://homeall.test/**",
				lambda route: route.fulfill(content_type="text/html", body='<nav class="navbar"></nav>'),
			)

			def load(change=""):
				page.goto("https://homeall.test/")
				page.add_script_tag(content=HARNESS + change)
				page.add_script_tag(content=(target / "client.js").read_text())
				page.wait_for_function("calls.some(c=>c.operation==='get_config')")
				expect(page.locator("#homeall-notification-preferences")).to_have_count(0)

			load(
				"document.body.insertAdjacentHTML('beforeend','<button id=\"homeall-notification-preferences\">Browser notifications</button>');"
			)
			expect(page.get_by_role("button", name="Enable notifications", exact=True)).to_be_visible()
			page.get_by_role("button", name="Enable notifications", exact=True).click()
			page.wait_for_function("trace.includes('register')")
			assert page.evaluate("trace") == ["permission-click", "worker", "token", "register"]
			expect(page.locator(".dialog")).to_have_count(0)
			page.evaluate("homeallNotifications.preferences()")
			page.get_by_role("button", name="Disable notifications", exact=True).click()
			page.wait_for_function("trace.includes('deleteToken')")
			load()
			expect(page.locator(".dialog")).to_have_count(1)  # Opting out asks again on the next visit.
			page.evaluate("localStorage.clear()")
			load()
			page.get_by_role("button", name="Later", exact=True).click()
			expect(page.locator(".dialog")).to_have_count(0)
			page.evaluate("Object.values(routeHandlers).forEach(fn=>fn())")
			expect(page.locator(".dialog")).to_have_count(1)  # Next route asks again without stacking.
			page.evaluate("Object.values(routeHandlers).forEach(fn=>fn())")
			expect(page.locator(".dialog")).to_have_count(1)
			page.get_by_role("button", name="Later", exact=True).click()
			load()
			expect(page.locator(".dialog")).to_have_count(1)  # Reload also asks again.
			page.evaluate("localStorage.setItem('homeall-push:alice:snooze',String(Number.MAX_SAFE_INTEGER))")
			load()
			expect(page.locator(".dialog")).to_have_count(1)  # Older saved snoozes are ignored.
			page.evaluate("localStorage.clear()")
			load("Notification.permission='denied';")
			expect(page.locator(".dialog")).to_have_count(1)
			expect(page.get_by_text("Notifications are blocked.", exact=False)).to_be_visible()
			expect(page.get_by_role("button", name="Enable notifications", exact=True)).not_to_be_visible()
			page.evaluate("localStorage.clear()")
			load("Notification.permission='granted';")
			page.wait_for_function("trace.includes('register')")
			assert "permission-click" not in page.evaluate("trace")
			page.evaluate("localStorage.setItem('homeall-push:bob:disabled','true')")
			load("frappe.session.user='bob';")
			assert not page.evaluate("calls.some(c=>c.operation==='register')")
			expect(page.locator(".dialog")).to_have_count(1)
			page.evaluate("localStorage.clear()")
			load("window.failToken=true;")
			page.get_by_role("button", name="Enable notifications", exact=True).click()
			page.wait_for_function("trace.includes('token')")
			expect(page.locator(".dialog")).to_have_count(1)
			assert page.evaluate("localStorage.getItem('homeall-push:alice:enabled')") == "false"
			page.evaluate("localStorage.clear()")
			load("window.denyPermission=true;")
			page.get_by_role("button", name="Enable notifications", exact=True).click()
			expect(page.get_by_text("Notifications are blocked.", exact=False)).to_be_visible()
			assert page.evaluate("trace.filter(v=>v==='permission-click').length") == 1
			page.evaluate("Object.values(routeHandlers).forEach(fn=>fn())")
			assert page.evaluate("trace.filter(v=>v==='permission-click').length") == 1
			page.evaluate("localStorage.clear()")
			load("cfg.configured=false;")
			expect(page.get_by_text("Browser notifications are not configured", exact=False)).to_be_visible()
			page.evaluate("localStorage.clear()")
			load("Object.defineProperty(navigator,'userAgent',{value:'iPhone'});")
			expect(page.get_by_text("On iPhone or iPad,", exact=False)).to_be_visible()
			expect(page.get_by_role("button", name="Enable notifications", exact=True)).not_to_be_visible()

			# Production order bundle: the linked order need not appear in the list.
			order = "20000000-0000-4000-8000-000000000002"
			other = "30000000-0000-4000-8000-000000000003"
			event_id = "10000000-0000-4000-8000-000000000001"
			page.goto(f"https://homeall.test/desk/online-order?order={order}&homeall_event={event_id}")
			page.add_script_tag(
				content=HARNESS
				+ """
             document.body.innerHTML='<div id="app"></div>';
             window.orderCalls=[];window.failOrder=false;
             frappe.route_options={};frappe.provide=()=>{};frappe.dom={set_style(){}};
             frappe.router={jq:{on(name,fn){handlers[name]=fn},off(name,fn){if(handlers[name]===fn)delete handlers[name]}}};
             frappe.call=async({method,args})=>{
              const operation=method.split('.').at(-1);orderCalls.push({operation,args});
              if(operation==='get_orders')return {message:{orders:[],total:0,page:1,total_pages:1}};
              if(operation==='get_order'){
               if(failOrder)throw new Error('Not found');
               return {message:{id:args.order_id,status:'pending',currency:'USD',created_at:'2026-01-01T00:00:00Z',
                subtotal:10,tax_amount:0,total_amount:10,items:[],status_history:[],note:'linked-order-'+args.order_id}};
              }
              return {message:{}};
             };
            """
			)
			order_bundle = max(
				(ROOT / "homeall_ecommerce_integration/public/dist/js").glob("online_order.bundle.*.js"),
				key=lambda f: f.stat().st_mtime,
			)
			page.add_script_tag(content=order_bundle.read_text())
			assert page.evaluate("typeof frappe.ui.OnlineOrderPage") == "function", errors
			page.evaluate(
				"window.ordersPage=new frappe.ui.OnlineOrderPage({wrapper:document.getElementById('app')})"
			)
			expect(page.get_by_text("linked-order-" + order, exact=True)).to_be_visible()
			page.wait_for_function("orderCalls.some(c=>c.operation==='mark_opened')")
			page.evaluate(
				"""(url)=>{history.pushState({},'',url);handlers['change.homeall-orders']()}""",
				f"/desk/online-order?order={other}",
			)
			expect(page.get_by_text("linked-order-" + other, exact=True)).to_be_visible()
			page.evaluate(
				"""(url)=>{failOrder=true;history.pushState({},'',url);handlers['change.homeall-orders']()}""",
				f"/desk/online-order?order={order}",
			)
			expect(page.get_by_text("Unable to open this order.", exact=False)).to_be_visible()
			expect(page.get_by_text("linked-order-" + other, exact=True)).to_have_count(0)
			page.evaluate("ordersPage.destroy()")
			assert not page.evaluate("Boolean(handlers['change.homeall-orders'])")

			page.goto("https://homeall.test/")
			page.add_script_tag(
				content="""
             window.HOMEALL_FIREBASE_CONFIG={};window.systemNotices=[];window.navigationCalls=[];
             window.registration={async showNotification(title,options){systemNotices.push({title,options})}};
             window.clients = {
              async matchAll() {
               return [{
                url: 'https://homeall.test/desk',
                async navigate(url) {
                 navigationCalls.push(url);
                 return { async focus() { navigationCalls.push('focus'); } };
                }
               }];
              },
              async openWindow(url) { navigationCalls.push(url); }
             };
            """
			)
			page.add_script_tag(content=(target / "worker.js").read_text())
			notice = dict(
				event_id="10000000-0000-4000-8000-000000000001",
				type="order_created",
				destination="/desk/online-order?order=20000000-0000-4000-8000-000000000002&homeall_event=10000000-0000-4000-8000-000000000001",
				expires_at="9999999999",
				title="<script>private customer</script>",
			)
			assert page.evaluate("!!self.registration"), (
				errors,
				page.evaluate("Object.keys(window).filter(k=>k.includes('registration'))"),
			)
			page.evaluate("(data)=>window.background({data})", notice)
			assert page.evaluate("systemNotices[0].title") == "New online order"
			page.evaluate("""async ()=>{const e=new Event('notificationclick');e.notification={
             data:{url:systemNotices[0].options.data.url},close(){}};
             e.waitUntil=(promise)=>window.clickDone=promise;dispatchEvent(e);await clickDone;}""")
			assert page.evaluate("navigationCalls.at(-1)") == "focus"
			assert "/desk/online-order?order=" in page.evaluate("navigationCalls[0]")
			assert errors == [], json.dumps(errors)
			browser.close()
	print(
		"Notification browser checks passed: modal on every unsubscribed visit, no standalone button, dismissal/reload/navigation, ignored legacy snoozes, registration failure, permission denial, user gesture, account isolation, iPhone guidance, direct order links, background display and clicks."
	)


if __name__ == "__main__":
	main()
