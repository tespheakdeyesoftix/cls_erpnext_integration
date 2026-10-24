"""Optional real-browser checks against built assets and mocked services.

Run after bench build with Playwright installed and its Chromium browser available:
  python -m homeall_ecommerce_integration.homeall_ecommerce_integration.page.chat.browser_checks
No Frappe server, customer messages, or external network requests are used.
"""

from pathlib import Path

HARNESS = r"""
const A = '10000000-0000-4000-8000-000000000001', B = '10000000-0000-4000-8000-000000000002';
window.calls = []; window.handlers = {}; window.socketHandlers = {}; window.failNext = false;
window.staffName = 'Test Agent'; window.failAfterCommit = false;
window.holdReads = false; window.holdInbox = false; window.holdNextHistory = false; window.failMessages = 0; window.failAfterEcho = false;
window.socketConnectCalls = 0; window.acceptSocketReconnect = false;
window.rows = [
 {id:A,app_key:'csl',title:'Alice',kind:'product',customer:{full_name:'Alice Customer',username:'alice'},business:{name:'Green Market'},last_message_at:'2026-10-23T10:00:00Z',last_message_preview:'Hello',unread_count:2},
 {id:B,app_key:'dsku-wholesale',title:'Bob',kind:'order',customer:{full_name:'Bob Customer',username:'bob',email:'bob@example.test'},business:{name:'City Store'},last_message_at:'2026-10-22T10:00:00Z',last_message_preview:'Order question',unread_count:1}
];
window.historyRows = Object.fromEntries([A,B].map((id) => [id, [
 {id:id+'-1',conversation_id:id,sender_role:'customer',kind:'text',body:'Hello <b>plain text</b>\nSecond line',created_at:'2026-10-23T09:00:00Z',client_message_id:id+'-c1'},
 {id:id+'-2',conversation_id:id,sender_role:'admin',sender_display_name:'   ',kind:'text',body:'How can we help?',created_at:'2026-10-23T10:00:00Z',client_message_id:id+'-c2'}
]]));
window.emit = (data) => (handlers.homeall_chat || []).forEach(fn => fn(data));
window.frappe = {
 dom:{set_style(){}},
 ui:{}, csrf_token:'test', route_options:{},
 provide(name){name.split('.').reduce((object,key) => object[key] ||= {},window)},
 realtime:{
  on(name,fn){(handlers[name] ||= []).push(fn)}, off(name,fn){handlers[name]=(handlers[name]||[]).filter(x=>x!==fn)},
  socket:{connected:true,on(name,fn){(socketHandlers[name] ||= []).push(fn)},off(name,fn){socketHandlers[name]=(socketHandlers[name]||[]).filter(x=>x!==fn)},connect(){socketConnectCalls++;if(acceptSocketReconnect){this.connected=true;(socketHandlers.connect||[]).forEach(fn=>fn())}}}
 },
 async call({method,args}){
  const operation=method.split('.').at(-1); calls.push({operation,args:JSON.parse(JSON.stringify(args))});
  if(operation==='bootstrap') {
   const message={can_send:true,display_name:staffName,health:{status:'Live'}};
   if(args.include_inbox)message.inbox={items:rows,has_more:false,next_cursor:null,total_unread:rows.reduce((sum,row)=>sum+row.unread_count,0)};
   return {message};
  }
  if(operation==='conversations') {
   if(window.holdInbox)await new Promise(resolve=>window.releaseInbox=resolve);
   let items=rows.filter(row=>(!args.unread||row.unread_count>0)&&JSON.stringify(row).toLowerCase().includes((args.search||'').toLowerCase()));
   return {message:{items,has_more:false,next_cursor:null,total_unread:rows.reduce((sum,row)=>sum+row.unread_count,0)}};
  }
  if(operation==='messages') {
   if(window.failMessages>0){window.failMessages--;throw new Error('Simulated history failure')}
   const id=args.conversation_id;
   if(window.slowA && id===A) await new Promise(resolve=>setTimeout(resolve,220));
   const row=rows.find(row=>row.id===id);
   const context = id===A ? {type:'product',name:'Green tea',item_code:'TEA-01',pricing:{unit_price:12,currency:'USD'}} : {type:'order',display_number:'ORD-100',total_amount:42,currency:'USD',items:[{name:'Tea',quantity:3}]};
   const ordered=[...historyRows[id]].sort((a,b)=>b.created_at.localeCompare(a.created_at));
   const start=args.cursor ? ordered.findIndex(m=>m.id===args.cursor.id)+1 : 0;
   const items=ordered.slice(start,start+100), last=items.at(-1), hasMore=start+100<ordered.length;
   const message={conversation_id:id,...row,context,items,has_more:hasMore,next_cursor:hasMore?{created_at:last.created_at,id:last.id}:null};
   if(window.holdNextHistory){window.holdNextHistory=false;await new Promise(resolve=>window.releaseHistory=resolve)}
   return {message};
  }
  if(operation==='mark_read'){
   if(window.holdReads){window.readWaiting=true;await new Promise(resolve=>window.releaseRead=resolve);window.readWaiting=false;}
   rows.find(row=>row.id===args.conversation_id).unread_count=0;return {message:{}};
  }
  if(operation==='send_text'){
   if(window.failNext){window.failNext=false;throw new Error('Simulated offline')}
   const saved=historyRows[args.conversation_id].find(m=>m.id===args.client_message_id)||{id:args.client_message_id,conversation_id:args.conversation_id,client_message_id:args.client_message_id,sender_role:'admin',sender_display_name:staffName,body:args.body,kind:'text',created_at:'2026-10-23T11:00:00Z'};
   if(!historyRows[args.conversation_id].some(m=>m.id===saved.id))historyRows[args.conversation_id].push(saved);
   if(window.failAfterCommit){window.failAfterCommit=false;throw new Error('Simulated uncertain outcome')}
   emit({event:'message_created',conversation_id:args.conversation_id,message_id:saved.id});
   if(window.failAfterEcho){window.failAfterEcho=false;await new Promise(resolve=>setTimeout(resolve,450));window.httpFailed=true;throw new Error('HTTP failed after realtime confirmation')}
   await new Promise(resolve=>setTimeout(resolve,50));return {message:saved};
  }
  throw new Error('Unexpected method '+operation);
 }
};
"""


def main():
	from playwright.sync_api import expect, sync_playwright

	public = Path(__file__).resolve().parents[3] / "public"
	js = max((public / "dist/js").glob("chat.bundle.*.js"), key=lambda p: p.stat().st_mtime)
	css = max((public / "dist/css").glob("chat.bundle.*.css"), key=lambda p: p.stat().st_mtime)
	desk_assets = Path(__file__).resolve().parents[5] / "frappe/frappe/public/dist/css"
	desk_css = next(desk_assets.glob("desk.bundle.*.css"), None)
	with sync_playwright() as playwright:
		browser = playwright.chromium.launch(headless=True)
		page = browser.new_page(viewport={"width": 1440, "height": 950})
		errors = []
		page.on("pageerror", lambda error: errors.append(str(error)))
		page.route(
			"http://chat.test/**",
			lambda route: route.fulfill(content_type="text/html", body='<div id="app" style="width:100%;min-width:0"></div>'),
		)
		page.goto("http://chat.test/")
		if desk_css:
			page.add_style_tag(content=desk_css.read_text())
		page.add_style_tag(content=css.read_text())
		page.add_script_tag(content=HARNESS)
		page.add_script_tag(content=js.read_text())
		page.evaluate(
			"window.chatPage = new frappe.ui.HomeallChatPage({wrapper:document.getElementById('app')})"
		)
		expect(page.get_by_text("Select a conversation", exact=True)).to_be_visible()
		expect(page.locator(".conversation-row")).to_have_count(2)
		page.locator(".conversation-row").first.click()
		expect(page.locator(".context-card")).to_contain_text("USD 12")
		expect(page.locator(".message-text").first).to_have_text("Hello <b>plain text</b>\nSecond line")
		page.get_by_role("button", name="View details").click()
		context_dialog = page.get_by_role("dialog", name="Product details")
		expect(context_dialog).to_be_visible()
		expect(context_dialog).to_contain_text("Green tea")
		expect(context_dialog).to_contain_text("TEA-01")
		page.get_by_label("Close context details").click()
		expect(context_dialog).not_to_be_visible()
		page.get_by_role("button", name="View details").click()
		page.keyboard.press("Escape")
		expect(context_dialog).not_to_be_visible()
		page.screenshot(path="/tmp/homeall-chat-frappe-desktop.png", full_page=True)
		assert page.locator(".homeall-chat").evaluate("el => Math.abs(el.getBoundingClientRect().width - el.parentElement.getBoundingClientRect().width) < 2")
		light_surface = page.locator(".chat-inbox").evaluate("el => getComputedStyle(el).backgroundColor")
		page.locator("html").evaluate("el => el.dataset.theme = 'dark'")
		page.wait_for_timeout(200)  # Let component color transitions finish before capturing theme colors.
		if desk_css:
			assert page.locator(".chat-inbox").evaluate("el => getComputedStyle(el).backgroundColor") != light_surface
		page.screenshot(path="/tmp/homeall-chat-frappe-dark.png", full_page=True)
		assert page.locator(".total-unread").evaluate("el => getComputedStyle(el).color !== getComputedStyle(el).backgroundColor")
		page.locator("html").evaluate("el => el.dataset.theme = 'light'")
		assert page.locator(".message-text b").count() == 0
		expect(page.locator(".sender-name").last).to_have_text("Support")
		page.locator("textarea").fill("Alice draft")
		page.locator(".conversation-row").nth(1).click()
		expect(page.locator(".thread-identity h3")).to_contain_text("Bob")
		expect(page.locator("textarea")).to_have_value("")
		page.locator("textarea").fill("Bob draft")
		page.locator(".conversation-row").first.click()
		expect(page.locator("textarea")).to_have_value("Alice draft")
		assert page.evaluate("chatPage.pinia.state.value['homeall-chat'].drafts[rows[0].id]") == "Alice draft"
		assert page.evaluate("chatPage.pinia.state.value['homeall-chat'].drafts[rows[1].id]") == "Bob draft"
		page.locator("textarea").fill("Reply with\na line break")
		page.locator("textarea").press("Enter")
		expect(page.get_by_text("Reply with\na line break", exact=True)).to_have_count(1)
		expect(page.locator(".sender-name").last).to_have_text("Test Agent")
		page.evaluate("window.failNext = true")
		page.locator("textarea").fill("Retry me")
		page.locator("textarea").press("Enter")
		expect(page.get_by_text("Failed · Retry", exact=True)).to_be_visible()
		page.get_by_text("Failed · Retry", exact=True).click()
		expect(page.get_by_text("Retry me", exact=True)).to_have_count(1)
		expect(page.get_by_text("Failed · Retry", exact=True)).to_have_count(0)
		uuid_calls = page.evaluate(
			"calls.filter(c=>c.operation==='send_text'&&c.args.body==='Retry me').map(c=>c.args.client_message_id)"
		)
		assert len(uuid_calls) == 2 and uuid_calls[0] == uuid_calls[1]
		page.wait_for_timeout(350)  # Let the preceding send's echo reconcile before the next failure case.
		page.evaluate("window.staffName = 'Original Agent'; window.failAfterCommit = true")
		page.locator("textarea").fill("Uncertain original")
		page.locator("textarea").press("Enter")
		expect(page.get_by_text("Failed · Retry", exact=True)).to_be_visible()
		page.evaluate("window.staffName = 'Renamed Agent'")
		page.get_by_text("Failed · Retry", exact=True).click()
		original_bubble = page.locator(".message-bubble").filter(has_text="Uncertain original")
		expect(original_bubble.locator(".sender-name")).to_have_text("Original Agent")
		expect(original_bubble).to_have_count(1)
		# Recovery must page through a gap larger than one 100-message response.
		page.evaluate("""() => {
		 const id=rows[0].id;
		 for(let i=0;i<140;i++)historyRows[id].push({id:'catchup-'+i,conversation_id:id,sender_role:'customer',kind:'text',body:'Recovered '+i,created_at:new Date(Date.UTC(2026,9,23,12,i)).toISOString(),client_message_id:'catchup-client-'+i});
		 emit({event:'bridge_status',status:'Live'});
		}""")
		expect(page.locator(".message-bubble")).to_have_count(145)
		expect(original_bubble.locator(".sender-name")).to_have_text("Original Agent")
		expect(page.get_by_text("Recovered 139", exact=True)).to_be_visible()
		page.locator(".message-scroll").evaluate("element => element.scrollTop = 0")
		page.evaluate("""() => {
		 const id=rows[0].id;
		 historyRows[id].push({id:'live',conversation_id:id,sender_role:'customer',kind:'text',body:'Live customer message',created_at:'2026-10-24T00:00:00Z',client_message_id:'live-client'});
		 emit({event:'message_created',conversation_id:id,message_id:'live'});
		}""")
		expect(page.get_by_text("New messages ↓", exact=True)).to_be_visible()
		assert page.locator(".message-scroll").evaluate("element => element.scrollTop") == 0
		page.get_by_text("New messages ↓", exact=True).click()
		expect(page.get_by_text("Live customer message", exact=True)).to_be_visible()
		page.evaluate("socketHandlers.disconnect.forEach(fn=>fn())")
		expect(page.locator(".connection")).to_have_text("Offline")
		page.evaluate("socketHandlers.connect.forEach(fn=>fn())")
		expect(page.locator(".connection")).to_have_text("Live")
		page.evaluate("""() => {
		 const id=rows[0].id;
		 historyRows[id].push({id:'photo',conversation_id:id,sender_role:'admin',sender_display_name:'  <b>Photo Agent</b>  ',kind:'photo',media_url:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aCbwAAAAASUVORK5CYII=',created_at:'2026-10-24T01:00:00Z',client_message_id:'photo-client'});
		 emit({event:'message_created',conversation_id:id,message_id:'photo'});
		}""")
		photo_bubble = page.locator(".message-bubble").filter(has=page.locator(".photo-message"))
		expect(photo_bubble.locator(".sender-name")).to_have_text("<b>Photo Agent</b>")
		assert photo_bubble.locator(".sender-name b").count() == 0
		photo_bubble.get_by_label("Enlarge photo").click()
		expect(page.get_by_role("dialog", name="Photo preview")).to_be_visible()
		page.get_by_label("Close photo preview").click()
		page.evaluate("window.slowA = true")
		page.locator(".conversation-row").first.click()
		page.locator(".conversation-row").nth(1).click()
		expect(page.locator(".thread-identity h3")).to_contain_text("Bob")
		expect(page.locator(".context-card")).to_contain_text("USD 42")
		expect(page.locator(".context-card")).to_contain_text("3 \u00d7 Tea")
		page.wait_for_timeout(300)
		expect(page.locator(".thread-identity h3")).to_contain_text("Bob")
		page.locator("#chat-search").fill("Green Market")
		expect(page.locator(".conversation-row")).to_have_count(1)
		page.locator("#chat-search").fill("")
		expect(page.locator(".conversation-row")).to_have_count(2)
		page.set_viewport_size({"width": 390, "height": 844})
		expect(page.locator(".chat-inbox")).not_to_be_visible()
		expect(page.locator(".chat-composer")).to_be_visible()
		page.screenshot(path="/tmp/homeall-chat-frappe-mobile.png", full_page=True)
		assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
		page.get_by_label("Back to inbox").click()
		expect(page.locator(".chat-inbox")).to_be_visible()
		expect(page.locator(".chat-thread")).not_to_be_visible()
		page.evaluate("chatPage.destroy()")
		assert page.evaluate("handlers.homeall_chat.length") == 0
		assert page.evaluate("Object.values(socketHandlers).every(list=>list.length===0)")
		page.evaluate(
			"window.chatPage = new frappe.ui.HomeallChatPage({wrapper:document.getElementById('app')})"
		)
		expect(page.locator(".conversation-row")).to_have_count(2)
		assert page.evaluate("handlers.homeall_chat.length") == 1
		page.locator(".conversation-row").first.click()
		expect(page.get_by_text("Load older messages", exact=True)).to_be_visible()
		page.get_by_text("Load older messages", exact=True).click()
		expect(original_bubble.locator(".sender-name")).to_have_text("Original Agent")
		expect(photo_bubble.locator(".sender-name")).to_have_text("<b>Photo Agent</b>")
		# Disposed Pinia watchers must not issue requests when their retained state changes.
		page.evaluate("""() => {
		 window.retiredState = chatPage.pinia.state.value['homeall-chat'];
		 chatPage.destroy();
		 window.callsAtDispose = calls.length;
		 retiredState.search = 'after disposal';
		}""")
		page.wait_for_timeout(500)
		assert page.evaluate("calls.length === callsAtDispose")
		assert page.evaluate("handlers.homeall_chat.length") == 0
		# Each mount owns a separate Pinia container, including when two are created together.
		page.evaluate("""() => {
		 document.body.insertAdjacentHTML('beforeend', '<div id="other-chat"></div>');
		 window.chatPage = new frappe.ui.HomeallChatPage({wrapper:document.getElementById('app')});
		 window.otherChatPage = new frappe.ui.HomeallChatPage({wrapper:document.getElementById('other-chat')});
		}""")
		expect(page.locator("#app .conversation-row")).to_have_count(2)
		expect(page.locator("#other-chat .conversation-row")).to_have_count(2)
		page.locator("#app input[type=search]").fill("Green Market")
		expect(page.locator("#app .conversation-row")).to_have_count(1)
		expect(page.locator("#other-chat .conversation-row")).to_have_count(2)
		assert page.evaluate("otherChatPage.pinia.state.value['homeall-chat'].search") == ""
		page.evaluate("chatPage.destroy(); otherChatPage.destroy()")
		assert page.evaluate("handlers.homeall_chat.length") == 0
		assert not errors, errors
		page.close()
		page = browser.new_page(viewport={"width": 1440, "height": 950})
		page.on("pageerror", lambda error: errors.append(str(error)))
		page.route(
			"http://chat.test/**",
			lambda route: route.fulfill(content_type="text/html", body='<div id="app" style="width:100%;min-width:0"></div>'),
		)
		page.goto("http://chat.test/")
		page.add_style_tag(content=css.read_text())
		page.add_script_tag(content=HARNESS)
		page.add_script_tag(content=js.read_text())
		page.evaluate("""() => {
		 const id=rows[0].id;
		 historyRows[id].push({id:'unread',conversation_id:id,sender_role:'customer',kind:'text',body:'Unread customer',created_at:'2026-10-23T10:30:00Z',client_message_id:'unread-client'});
		 window.holdReads=true;
		 window.chatPage=new frappe.ui.HomeallChatPage({wrapper:document.getElementById('app')});
		}""")
		expect(page.locator(".conversation-row")).to_have_count(2)
		assert page.evaluate("calls.filter(c=>c.operation==='conversations').length") == 0
		page.locator(".conversation-row").first.click()
		page.wait_for_function("typeof releaseRead === 'function'")
		expect(page.get_by_text("Unread customer", exact=True)).to_be_visible()
		expect(page.get_by_text("Loading messages…", exact=True)).not_to_be_visible()
		page.locator("textarea").fill("Acknowledged immediately")
		page.locator("textarea").press("Enter")
		ack = page.locator(".message-bubble").filter(has_text="Acknowledged immediately")
		expect(ack.locator(".sender-name")).to_have_text("Test Agent")
		expect(ack.get_by_text("Sending…", exact=True)).not_to_be_visible()
		assert page.evaluate("window.readWaiting")
		page.evaluate("window.holdReads=false; releaseRead()")
		page.wait_for_timeout(400)
		page.evaluate(
			"window.messagesBefore = calls.filter(c=>c.operation==='messages').length; window.inboxBefore = calls.filter(c=>c.operation==='conversations').length"
		)
		page.evaluate(
			"for(let i=0;i<5;i++)emit({event:'read_updated',conversation_id:rows[0].id,message_id:historyRows[rows[0].id].at(-1).id})"
		)
		page.wait_for_timeout(350)
		assert page.evaluate("calls.filter(c=>c.operation==='messages').length === messagesBefore")
		assert page.evaluate("calls.filter(c=>c.operation==='conversations').length === inboxBefore + 1")
		page.evaluate(
			"emit({event:'message_created',conversation_id:rows[0].id,message_id:historyRows[rows[0].id].at(-1).id})"
		)
		page.wait_for_timeout(300)
		assert page.evaluate("calls.filter(c=>c.operation==='messages').length === messagesBefore")
		# The thread must update even while its independent inbox refresh is stalled.
		page.evaluate("""() => {
		 const id=rows[0].id; window.holdInbox=true;
		 historyRows[id].push({id:'parallel',conversation_id:id,sender_role:'customer',kind:'text',body:'Thread updates while inbox waits',created_at:'2026-10-23T11:30:00Z',client_message_id:'parallel-client'});
		 emit({event:'message_created',conversation_id:id,message_id:'parallel'});
		}""")
		expect(page.get_by_text("Thread updates while inbox waits", exact=True)).to_be_visible()
		page.wait_for_function("typeof releaseInbox === 'function'")
		page.evaluate("""() => {
		 const id=rows[0].id;
		 historyRows[id].push({id:'parallel-second',conversation_id:id,sender_role:'customer',kind:'text',body:'Second reply while inbox is still stalled',created_at:'2026-10-23T11:31:00Z',client_message_id:'parallel-second-client'});
		 emit({event:'message_created',conversation_id:id,message_id:'parallel-second'});
		}""")
		expect(page.get_by_text("Second reply while inbox is still stalled", exact=True)).to_be_visible()
		page.evaluate("window.holdInbox=false; releaseInbox()")
		page.wait_for_timeout(300)
		# A stale history response started before the event cannot hide the incoming reply.
		page.evaluate("window.holdNextHistory=true")
		page.locator(".conversation-row").first.click()
		page.wait_for_function("typeof releaseHistory === 'function'")
		page.evaluate("""() => {
		 const id=rows[0].id;
		 historyRows[id].push({id:'during-history',conversation_id:id,sender_role:'customer',kind:'text',body:'Reply received during history fetch',created_at:'2026-10-23T11:32:00Z',client_message_id:'during-history-client'});
		 emit({event:'message_created',conversation_id:id,message_id:'during-history'});
		}""")
		page.wait_for_timeout(250)
		page.evaluate("releaseHistory()")
		expect(page.get_by_text("Reply received during history fetch", exact=True)).to_be_visible()
		page.evaluate("window.failMessages=1; emit({event:'context_updated',conversation_id:rows[0].id})")
		expect(page.locator(".chat-thread .chat-error")).to_be_visible()
		page.evaluate("emit({event:'context_updated',conversation_id:rows[0].id})")
		expect(page.locator(".chat-thread .chat-error")).not_to_be_visible()
		page.evaluate("window.failAfterEcho=true")
		page.locator("textarea").fill("Realtime confirmed despite HTTP failure")
		page.locator("textarea").press("Enter")
		page.wait_for_function("window.httpFailed === true")
		confirmed = page.locator(".message-bubble").filter(has_text="Realtime confirmed despite HTTP failure")
		expect(confirmed).to_have_count(1)
		expect(confirmed.get_by_text("Failed · Retry", exact=True)).not_to_be_visible()
		expect(page.locator(".composer-notice")).not_to_be_visible()
		# Exhausted native Socket.IO retries must not leave chat permanently disconnected.
		page.evaluate("""() => {
		 const id=rows[0].id;
		 historyRows[id].push({id:'missed-while-disconnected',conversation_id:id,sender_role:'customer',kind:'text',body:'Reply recovered after socket failure',created_at:'2026-10-23T11:33:00Z',client_message_id:'missed-while-disconnected-client'});
		 frappe.realtime.socket.connected=false;
		 window.acceptSocketReconnect=true;
		 (socketHandlers.connect_error||[]).forEach(fn=>fn());
		}""")
		expect(page.locator(".connection")).to_have_text("Offline")
		page.wait_for_function("socketConnectCalls > 0")
		expect(page.locator(".connection")).to_have_text("Live")
		expect(page.get_by_text("Reply recovered after socket failure", exact=True)).to_be_visible()
		page.evaluate("chatPage.destroy()")
		assert page.evaluate("handlers.homeall_chat.length") == 0
		assert not errors, errors
		page.close()
		# A standalone LAN development web server does not proxy /socket.io itself.
		page = browser.new_page(viewport={"width": 1440, "height": 950})
		page.on("pageerror", lambda error: errors.append(str(error)))
		page.route(
			"http://chat.test:8887/**",
			lambda route: route.fulfill(content_type="text/html", body='<div id="app" style="width:100%;min-width:0"></div>'),
		)
		page.goto("http://chat.test:8887/")
		if desk_css:
			page.add_style_tag(content=desk_css.read_text())
		page.add_style_tag(content=css.read_text())
		page.add_script_tag(content=HARNESS)
		page.evaluate("""() => {
		 frappe.boot={sitename:'homeall.dev',developer_mode:1,socketio_port:9002};
		 frappe.realtime.socket.connected=false; window.acceptSocketReconnect=true; window.transportCloses=0;
		 frappe.realtime.socket.io={uri:'http://chat.test:8887/homeall.dev',opts:{},engine:{close(){transportCloses++}}};
		}""")
		page.add_script_tag(content=js.read_text())
		page.evaluate(
			"window.chatPage=new frappe.ui.HomeallChatPage({wrapper:document.getElementById('app')})"
		)
		expect(page.locator(".conversation-row")).to_have_count(2)
		page.wait_for_function("socketConnectCalls > 0")
		expect(page.locator(".connection")).to_have_text("Live")
		assert page.evaluate("frappe.realtime.socket.io.uri") == "http://chat.test:9002"
		assert (
			page.evaluate("frappe.realtime.socket.io.opts.extraHeaders['X-Frappe-Site-Name']")
			== "homeall.dev"
		)
		assert page.evaluate("transportCloses") == 1
		page.evaluate("""() => {
		 chatPage.destroy();
		 frappe.realtime.socket.io.uri='http://chat.test:8887';
		 window.chatPage=new frappe.ui.HomeallChatPage({wrapper:document.getElementById('app')});
		}""")
		expect(page.locator(".conversation-row")).to_have_count(2)
		assert page.evaluate("frappe.realtime.socket.io.uri") == "http://chat.test:8887"
		page.evaluate("chatPage.destroy()")
		assert not errors, errors
		browser.close()
	print(
		"Browser checks passed: Pinia state isolation, per-thread drafts, watcher/listener disposal, saved names, retries, Frappe UI controls/dialogs, light/dark themes, photo previews, pagination, realtime/catch-up, mobile, selection races, bundled startup, nonblocking read receipts, independent refreshes during stalled inbox requests, replies during in-flight history fetches, coalesced read events, transient-error recovery, realtime-confirmed sends after HTTP failure, reconnect/catch-up after Socket.IO connection errors, development port/site routing, and preserving healthy proxy connections."
	)


if __name__ == "__main__":
	main()
