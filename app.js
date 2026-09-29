const ADMIN_IDS = ["59293747"];
const STATS_HIDE_IDS = ["6812317446"];
const STATS_HIDE_USERNAMES = ["pouya_modir"];
const tg = window.Telegram && window.Telegram.WebApp;
if (tg) { tg.ready(); tg.expand(); try { tg.setHeaderColor("#0b0c0e"); tg.setBackgroundColor("#0b0c0e"); } catch(e) {} }
const user = (tg && tg.initDataUnsafe && tg.initDataUnsafe.user) || {};
const me = { id: String(user.id || "local"), name: [user.first_name, user.last_name].filter(Boolean).join(" ") || "بازیکن" };
const isAdmin = ADMIN_IDS.includes(me.id);
if (isAdmin) { const m=document.getElementById("btnMembers"); if(m) m.hidden=false; }
document.getElementById("hello").innerHTML = me.name + '<span>تابلو اسکواد — وقت ایران</span>';
document.getElementById("meChip").textContent = user.username ? "@"+user.username : "عضو";
firebase.initializeApp({
apiKey: "AIzaSyAyIDyPMx1eKgryRSvHpDcQ5G-rh8f_qPQ",
authDomain: "esquad-warzone.firebaseapp.com",
databaseURL: "https://esquad-warzone-default-rtdb.europe-west1.firebasedatabase.app",
projectId: "esquad-warzone",
storageBucket: "esquad-warzone.firebasestorage.app",
messagingSenderId: "429017395304",
appId: "1:429017395304:web:d3bd45d06b10ca306f8bdd"
});
const db = firebase.database();
const lobbiesRef = db.ref("lobbies");
const statsRef = db.ref("stats/noreply");
const lateRef = db.ref("stats/late");
const membersRef = db.ref("members");
const bannedRef = db.ref("banned");
const iranNow = () => new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Tehran" }));
const pad = (n) => String(n).padStart(2,"0");
const fmt = (d) => pad(d.getHours()) + ":" + pad(d.getMinutes());
const MODE_LABELS = {br:"بتل رویال", casual:"کژوال", resurgence:"ریسرجنس", ranked:"رنک"};
const modeText = (s) => ((s && s.modes) || []).map(m => MODE_LABELS[m] || m).join(" / ") || "نامشخص";
const saveLobby = (s) => { if (!s || !s.id) return; lobbiesRef.child(s.id).set(s); };
const dropLobby = (id) => { if (id) lobbiesRef.child(id).set(null); };
let startMode = "now", duration = 120, selectedModes = [], lobbies = {}, activeId = null, state = null, ready = false, statsData = {}, lateData = {}, membersData = {}, bannedData = {}, statsEdit = false;
const $ = (id) => document.getElementById(id);
const show = (id) => ["viewIdle","viewCreate","viewBoard"].forEach(v => $(v).hidden = v !== id);
function parseHHMM(str) { const [h,m] = str.split(":").map(Number); const d = iranNow(); d.setHours(h,m,0,0); return d; }
function computePhase(s) {
const now = iranNow(), start = new Date(s.startIso), end = new Date(s.endIso);
if (now >= end) return "closed"; if (now >= start) return "live"; return "wait";
}
function isLater(s) { return s && s.startMode === "clock"; }
function counted(s) {
const list = s.answers || [];
const readyCodes = isLater(s) ? ["5"] : ["5","15"];
return [...new Set([s.hostId, ...list.filter(a => readyCodes.includes(a.code)).map(a => a.id)])];
}
function label(code, s) {
if (code === "host") return "درخواست‌کننده";
if (isLater(s)) return {"5":"هستم","15":"با ۱۵ دقیقه تأخیر","30":"با نیم ساعت تأخیر","60":"با یک ساعت تأخیر",no:"نیستم"}[code] || code;
return {"5":"تا ۵ دقیقه","15":"تا ۱۵ دقیقه","30":"حدود ۳۰ دقیقه — رزرو","60":"یک ساعت به بالا — رزرو",no:"نیستم"}[code] || code;
}
function tagClass(code) {
if (code==="no") return "no"; if (code==="15"||code==="30"||code==="60") return "wait"; if (code==="host") return "host"; return "ok";
}
function choiceButtons(s, selected) {
const items = isLater(s) ? [["5","هستم"],["15","با ۱۵ دقیقه تأخیر"],["30","با نیم ساعت تأخیر"],["60","با یک ساعت تأخیر"],["no","نیستم"]] : [["5","تا ۵ دقیقه"],["15","تا ۱۵ دقیقه"],["30","حدود ۳۰ دقیقه"],["60","یک ساعت به بالا"],["no","نیستم"]];
return `<div class="choices">` + items.map(([code, text]) => `<button class="choice${code===selected?" on":""}${code==="no"?" full":""}" data-ans="${code}">${text}</button>`).join("") + `</div>`;
}
function bindAnswers() {
$("boardActions").querySelectorAll("[data-ans]").forEach(b => b.onclick = () => {
state.answers = (state.answers || []).filter(a => a.id !== me.id);
state.answers.push({ id: me.id, name: me.name, code: b.dataset.ans, at: Date.now() });
saveLobby(state);
});
}
function hiddenStat(r) {
if (STATS_HIDE_IDS.includes(String(r.id))) return true;
const u = String(r.username || "").replace("@","").toLowerCase();
return STATS_HIDE_USERNAMES.includes(u);
}
function openLobbies() {
return Object.values(lobbies||{}).filter(Boolean).filter(s => computePhase(s) !== "closed");
}
function renderList() {
const rows = openLobbies();
const box = $("lobbyList");
if (!box) return;
if (!rows.length) { box.innerHTML = ""; return; }
box.innerHTML = rows.map(s => {
const n = Math.min(4, counted(s).length);
return `<div class="person tap" data-open="${s.id}"><div class="n">${s.hostName} · ${modeText(s)}<div class="muted">${s.startLabel} — ${n} از ۴</div></div><div class="tag host">ورود</div></div>`;
}).join("");
box.querySelectorAll("[data-open]").forEach(el => el.onclick = () => { activeId = el.dataset.open; render(); });
}
function render() {
if (!ready) return;
Object.values(lobbies||{}).forEach(s => { if (s && computePhase(s)==="closed") dropLobby(s.id); });
const rows = openLobbies();
if (activeId && !rows.some(s => s.id === activeId)) activeId = null;
if (!activeId && rows.length === 1) activeId = rows[0].id;
state = rows.find(s => s.id === activeId) || null;
if (!state) { renderList(); show("viewIdle"); return; }
state.answers = state.answers || [];
const phase = computePhase(state);
const n = Math.min(4, counted(state).length);
$("num").textContent = n;
$("hostLine").textContent = state.hostName + " · " + modeText(state);
$("phase").textContent = phase==="wait" ? "در انتظار پر شدن اسکواد" : (n>=4 ? "اسکواد کامل شد — بازی شروع شده" : "بازی شروع شد");
$("timeLine").innerHTML = "شروع " + state.startLabel + " — حدوداً تا " + state.endLabel +
"<br/>مود: " + modeText(state) +
(phase==="live" && n<4 ? "<br/>لابی باز می‌مونه. اگر جا خالی ماند می‌توانید منتظر دست جاری بمانید." : "") +
(phase==="wait" ? "<br/>لابی بازه" : "") +
(me.id===state.hostId ? "<br/>روی اسم کسی بزن تا تأخیر ثبت شود." : "");
const people = [{id:state.hostId,name:state.hostName,code:"host"}, ...state.answers];
$("people").innerHTML = people.map(p => {
const marked = (state.lates || []).some(x => String(x.id)===String(p.id));
const canTap = me.id===state.hostId && p.code!=="host" && p.code!=="no";
return `<div class="person${canTap?" tap":""}" data-pid="${p.id}"><div class="n">${p.name}${marked?" · تأخیر":""}</div><div class="tag ${tagClass(p.code)}">${label(p.code, state)}</div></div>`;
}).join("");
if (me.id === state.hostId) {
$("people").querySelectorAll(".tap").forEach(el => el.onclick = () => {
const person = people.find(p => String(p.id)===String(el.dataset.pid));
if (!person) return;
const exists = (state.lates || []).some(x => String(x.id)===String(person.id));
if (exists) { alert("برای این لابی قبلاً ثبت شده."); return; }
if (!confirm("تأخیر برای " + person.name + " ثبت شود؟ فقط اگر بیشتر از ۵ دقیقه از زمان اعلام‌شده گذشته.")) return;
state.lates = (state.lates || []).concat([{id:String(person.id), name:person.name, status:"pending", at:Date.now()}]);
saveLobby(state);
});
}
const actions = $("boardActions");
const mine = state.answers.find(a => a.id === me.id);
const extra = rows.length > 1 ? `<button class="btn btn-soft" id="btnBackList">لابی‌های دیگر</button>` : "";
if (me.id === state.hostId) {
actions.innerHTML = `<button class="btn btn-soft" id="btnCancelReq">لغو درخواست</button>` + extra;
$("btnCancelReq").onclick = () => dropLobby(state.id);
} else {
actions.innerHTML = (mine ? `<div class="muted">جواب فعلی: ${label(mine.code, state)} — می‌توانی عوض کنی</div>` : "") + choiceButtons(state, mine && mine.code) + extra;
bindAnswers();
}
if ($("btnBackList")) $("btnBackList").onclick = () => { activeId = null; render(); };
show("viewBoard");
}
function statsRows() {
const ids = new Set([...Object.keys(statsData||{}), ...Object.keys(lateData||{})]);
return [...ids].map(id => {
const n = statsData[id] || {};
const l = lateData[id] || {};
return {id, name: n.name || l.name || "بازیکن", username: n.username || l.username || "", noreply: Number(n.count||0), late: Number(l.count||0)};
}).map(r => ({...r, total: r.noreply + r.late}))
.filter(r => !hiddenStat(r))
.filter(r => statsEdit || r.total > 0)
.sort((a,b) => b.total - a.total || b.noreply - a.noreply || b.late - a.late);
}
function clearPlayerStats(id) {
if (!id) return;
statsRef.child(id).set(null);
lateRef.child(id).set(null);
}
function renderStats() {
const rows = statsRows();
const edit = isAdmin && statsEdit;
$("statsList").innerHTML = `<div class="table"><div class="row head"><div class="n">اسم</div><div class="c">بی‌جواب</div><div class="c">تأخیر</div><div class="c">جمع</div></div>` +
(rows.length ? rows.map(r => `<div class="row"><div class="n"><span class="nm">${r.name}</span>${edit?`<div class="editbtns"><button class="tiny" data-del="${r.id}">حذف از آمار</button></div>`:""}</div><div class="c">${r.noreply}${edit?`<div class="editbtns"><button class="tiny" data-b="noreply:${r.id}:-1">−</button><button class="tiny" data-b="noreply:${r.id}:1">+</button></div>`:""}</div><div class="c">${r.late}${edit?`<div class="editbtns"><button class="tiny" data-b="late:${r.id}:-1">−</button><button class="tiny" data-b="late:${r.id}:1">+</button></div>`:""}</div><div class="c">${r.total}</div></div>`).join("") : `<div class="muted">هنوز سابقه‌ای نیست.</div>`) + `</div>`;
if (edit) {
$("statsList").querySelectorAll("[data-b]").forEach(btn => btn.onclick = () => {
const [kind,id,d] = btn.dataset.b.split(":");
const row = rows.find(x => String(x.id)===String(id)) || {};
bump(kind, id, row.name||"", row.username||"", Number(d));
});
$("statsList").querySelectorAll("[data-del]").forEach(btn => btn.onclick = () => {
const id = btn.dataset.del;
const row = rows.find(x => String(x.id)===String(id)) || {};
if (!confirm("«" + (row.name||"بازیکن") + "» از آمار حذف شود؟ عضویت و مسدود بودن عوض نمی‌شود.")) return;
clearPlayerStats(id);
});
}
const ed = $("btnEditStats");
if (ed) { ed.hidden = !isAdmin; ed.textContent = statsEdit ? "تمام ویرایش" : "ویرایش"; }
}
function bump(kind, id, name, username, delta) {
const ref = db.ref("stats/"+kind+"/"+id);
ref.once("value").then(snap => {
const row = snap.val() || {};
const count = Math.max(0, Number(row.count||0) + delta);
ref.set({name: name||row.name||"بازیکن", username: username||row.username||"", count});
});
}
function renderMembers() {
if (!isAdmin) return;
const rows = Object.entries(membersData||{}).map(([id,row]) => ({id, ...(row||{})}));
$("membersTitle").textContent = "اعضا · " + rows.length + " نفر";
$("membersList").innerHTML = rows.length ? rows.map(r => {
const banned = !!(bannedData||{})[r.id];
const hide = hiddenStat(r);
return `<div class="person" style="flex-wrap:wrap;gap:8px"><div class="n">${r.name||"بازیکن"}${hide?" · تست":""}<div class="muted">@${r.username||"—"} ${banned?"· مسدود":""}</div></div>${String(r.id)===String(me.id) ? `<div class="muted">مالک</div>` : `<div><button class="tiny" data-ban="${r.id}">${banned?"آزاد":"مسدود"}</button><button class="tiny" data-kick="${r.id}">اخراج</button></div>`}</div>`;
}).join("") : `<div class="muted">عضوی نیست.</div>`;
$("membersList").querySelectorAll("[data-ban]").forEach(btn => btn.onclick = () => {
const id = btn.dataset.ban;
if ((bannedData||{})[id]) bannedRef.child(id).set(null);
else if (confirm("مسدود شود؟ نوتیف نمی‌رود.")) bannedRef.child(id).set(true);
});
$("membersList").querySelectorAll("[data-kick]").forEach(btn => btn.onclick = () => {
const id = btn.dataset.kick;
if (!confirm("اخراج و مسدود شود؟ آمار هم پاک می‌شود.")) return;
membersRef.child(id).set(null);
bannedRef.child(id).set(true);
clearPlayerStats(id);
});
}
$("btnAsk").onclick = () => show("viewCreate");
$("btnCancelCreate").onclick = () => render();
document.querySelectorAll("[data-start]").forEach(b => b.onclick = () => {
startMode = b.dataset.start;
document.querySelectorAll("[data-start]").forEach(x => x.classList.toggle("on", x===b));
$("clockWrap").hidden = startMode !== "clock";
});
document.querySelectorAll("[data-dur]").forEach(b => b.onclick = () => {
duration = Number(b.dataset.dur);
document.querySelectorAll("[data-dur]").forEach(x => x.classList.toggle("on", x===b));
});
document.querySelectorAll("[data-mode]").forEach(b => b.onclick = () => {
const m = b.dataset.mode;
if (selectedModes.includes(m)) selectedModes = selectedModes.filter(x => x !== m);
else selectedModes = selectedModes.concat(m);
if (!selectedModes.length) selectedModes = [m];
document.querySelectorAll("[data-mode]").forEach(x => x.classList.toggle("on", selectedModes.includes(x.dataset.mode)));
});
$("btnPublish").onclick = () => {
if (!selectedModes.length) { alert("حداقل یک مود را انتخاب کن."); return; }
const start = startMode==="now" ? iranNow() : parseHHMM($("clock").value || fmt(iranNow()));
const end = new Date(start.getTime() + duration * 60000);
const id = Date.now().toString(36);
const row = {
id, hostId: me.id, hostName: me.name, startMode: startMode, modes: selectedModes.slice(),
startIso: start.toISOString(), endIso: end.toISOString(),
startLabel: fmt(start), endLabel: fmt(end), answers: [], reminded: false,
openedAt: Date.now(), noreplyTallied: false, lates: []
};
activeId = id;
saveLobby(row);
};
function openSheet(id) { $(id).classList.add("on"); }
function closeSheet(id) { $(id).classList.remove("on"); }
$("btnRules1").onclick = $("btnRules2").onclick = () => openSheet("rules");
$("closeRules").onclick = () => closeSheet("rules");
$("rules").onclick = (e) => { if (e.target.id==="rules") closeSheet("rules"); };
$("btnStats1").onclick = $("btnStats2").onclick = () => { statsEdit=false; renderStats(); openSheet("stats"); };
$("closeStats").onclick = () => closeSheet("stats");
$("stats").onclick = (e) => { if (e.target.id==="stats") closeSheet("stats"); };
$("btnEditStats").onclick = () => { statsEdit = !statsEdit; renderStats(); };
$("btnMembers").onclick = () => { renderMembers(); openSheet("members"); };
$("closeMembers").onclick = () => closeSheet("members");
$("members").onclick = (e) => { if (e.target.id==="members") closeSheet("members"); };
$("clock").value = fmt(iranNow());
lobbiesRef.on("value", (snap) => {
ready = true;
const raw = snap.val() || {};
lobbies = {};
Object.entries(raw).forEach(([id, row]) => { if (row) lobbies[id] = Object.assign({id}, row); });
render();
});
statsRef.on("value", (snap) => { statsData = snap.val() || {}; if ($("stats").classList.contains("on")) renderStats(); });
lateRef.on("value", (snap) => { lateData = snap.val() || {}; if ($("stats").classList.contains("on")) renderStats(); });
membersRef.on("value", (snap) => { membersData = snap.val() || {}; if ($("members").classList.contains("on")) renderMembers(); });
bannedRef.on("value", (snap) => { bannedData = snap.val() || {}; if ($("members").classList.contains("on")) renderMembers(); });
