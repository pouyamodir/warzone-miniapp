import os
import time
import json
import threading
from datetime import datetime, timezone
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"
DB = "https://esquad-warzone-default-rtdb.europe-west1.firebasedatabase.app"

STATS_HIDE_IDS = {"6812317446"}
STATS_HIDE_USERNAMES = {"pouya_modir"}
ADMIN_IDS = {"59293747"}
REPLY_WINDOW = 90 * 60
LATE_AUTO_HOURS = 24

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *a):
        pass

def serve():
    port = int(os.environ.get("PORT", "10000"))
    HTTPServer(("0.0.0.0", port), H).serve_forever()

LABELS_NOW = {"5": "تا ۵ دقیقه", "15": "تا ۱۵ دقیقه", "30": "حدود ۳۰ دقیقه", "60": "یک ساعت به بالا", "no": "نیستم"}
LABELS_LATER = {"5": "هستم", "15": "با ۱۵ دقیقه تأخیر", "30": "با نیم ساعت تأخیر", "60": "با یک ساعت تأخیر", "no": "نیستم"}

def is_later(lobby):
    return (lobby or {}).get("startMode") == "clock"

def labels_for(lobby):
    return LABELS_LATER if is_later(lobby) else LABELS_NOW

def keyboard_for(lobby):
    L = labels_for(lobby)
    return {"inline_keyboard": [[{"text": L["5"], "callback_data": "ans:5"}, {"text": L["15"], "callback_data": "ans:15"}], [{"text": L["30"], "callback_data": "ans:30"}, {"text": L["60"], "callback_data": "ans:60"}], [{"text": L["no"], "callback_data": "ans:no"}], [{"text": "باز کردن تابلو", "url": "https://t.me/warzonesquad_bot/squad"}]]}

def db_get(path):
    r = requests.get(f"{DB}/{path}.json", timeout=15)
    r.raise_for_status()
    return r.json()

def db_put(path, data):
    requests.put(f"{DB}/{path}.json", json=data, timeout=15).raise_for_status()

def tg(method, payload):
    return requests.post(f"{API}/{method}", json=payload, timeout=30).json()

def notice_key(lobby):
    return str((lobby or {}).get("startIso") or "x").replace(".", "_").replace(":", "-")

def sid(v):
    return str(v or "").strip()

def hidden(uid, info=None):
    uid = sid(uid)
    if uid in STATS_HIDE_IDS:
        return True
    un = sid((info or {}).get("username")).lstrip("@").lower()
    return un == "pouya_modir"

def save_member(user):
    if not user or "id" not in user:
        return
    db_put(f"members/{user['id']}", {"name": " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x), "username": user.get("username") or "", "ts": int(time.time() * 1000)})

def members_map():
    return db_get("members") or {}

def member_ids():
    return [sid(uid) for uid in members_map().keys()]

def bump_stat(kind, uid, name="", username="", delta=1):
    uid = sid(uid)
    if not uid:
        return
    row = db_get(f"stats/{kind}/{uid}") or {}
    count = max(0, int(row.get("count") or 0) + int(delta))
    db_put(f"stats/{kind}/{uid}", {"name": name or row.get("name") or "بازیکن", "username": username or row.get("username") or "", "count": count})

def card_text(lobby):
    L = labels_for(lobby)
    answers = lobby.get("answers") or []
    ready = {"5", "15"} if not is_later(lobby) else {"5"}
    n = min(4, 1 + len({sid(a.get("id")) for a in answers if a.get("code") in ready}))
    lines = [f"{lobby.get('hostName', 'یکی')} پرسیده: کسی هست برای بازی؟", f"شروع: {lobby.get('startLabel')} — حدوداً تا {lobby.get('endLabel')}", f"{n} از ۴", "", f"{lobby.get('hostName', 'میزبان')}: درخواست‌کننده"]
    for a in answers:
        lines.append(f"{a.get('name', 'بازیکن')}: {L.get(a.get('code'), a.get('code'))}")
    return "\n".join(lines)

def send_or_edit_card(uid, lobby):
    key = notice_key(lobby)
    mid = db_get(f"notices/{key}/{uid}")
    payload = {"chat_id": int(uid), "text": card_text(lobby), "reply_markup": keyboard_for(lobby)}
    if mid:
        r = tg("editMessageText", {"chat_id": int(uid), "message_id": int(mid), "text": payload["text"], "reply_markup": payload["reply_markup"]})
        if r.get("ok"):
            return
    r = tg("sendMessage", payload)
    if r.get("ok"):
        db_put(f"notices/{key}/{uid}", r["result"]["message_id"])

def notify_new_request(lobby, old):
    if not lobby or not lobby.get("hostId"):
        return
    if sid((old or {}).get("hostId")) == sid(lobby.get("hostId")) and (old or {}).get("startIso") == lobby.get("startIso"):
        return
    host = sid(lobby.get("hostId"))
    for uid in member_ids():
        if uid == host:
            continue
        try:
            send_or_edit_card(uid, lobby)
        except Exception as e:
            print("send fail", uid, e)

def notify_new_answers(lobby, old):
    if not lobby or not old:
        return
    if sid(lobby.get("hostId")) != sid(old.get("hostId")) or lobby.get("startIso") != old.get("startIso"):
        return
    L = labels_for(lobby)
    prev = {sid(a.get("id")): a for a in (old.get("answers") or []) if a}
    members = member_ids()
    host = sid(lobby.get("hostId"))
    if host and host not in members:
        members.append(host)
    changed = False
    for a in lobby.get("answers") or []:
        if not a:
            continue
        oid = sid(a.get("id"))
        prev_a = prev.get(oid)
        if prev_a is None or prev_a.get("code") != a.get("code"):
            changed = True
            text = f"{a.get('name', 'بازیکن')}: {L.get(a.get('code'), a.get('code'))}"
            for uid in members:
                if uid == oid:
                    continue
                try:
                    tg("sendMessage", {"chat_id": int(uid), "text": text})
                except Exception as e:
                    print("answer notify fail", uid, e)
    if changed:
        for uid in members:
            if uid == host:
                continue
            try:
                send_or_edit_card(uid, lobby)
            except Exception as e:
                print("edit card fail", uid, e)

def opened_ts(lobby):
    raw = (lobby or {}).get("openedAt")
    if raw:
        n = float(raw)
        return n / 1000 if n > 1e12 else n
    iso = (lobby or {}).get("startIso")
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None

def increment_noreply(lobby):
    answered = {sid(a.get("id")) for a in (lobby.get("answers") or [])}
    host = sid(lobby.get("hostId"))
    members = members_map()
    for uid, info in members.items():
        uid = sid(uid)
        info = info or {}
        if not uid or uid == host or uid in answered or hidden(uid, info) or uid in ("local", "undefined", "null"):
            continue
        bump_stat("noreply", uid, info.get("name") or "", info.get("username") or "")

def maybe_tally_open(lobby):
    if not lobby or not lobby.get("hostId") or lobby.get("noreplyTallied"):
        return lobby
    opened = opened_ts(lobby)
    if opened is None or (time.time() - opened) < REPLY_WINDOW:
        return lobby
    increment_noreply(lobby)
    lobby = dict(lobby)
    lobby["noreplyTallied"] = True
    db_put("lobby", lobby)
    return lobby

def notify_new_lates(lobby, old):
    if not lobby or not old:
        return
    if sid(lobby.get("hostId")) != sid(old.get("hostId")) or lobby.get("startIso") != old.get("startIso"):
        return
    prev = {sid(x.get("id")): x for x in (old.get("lates") or []) if x}
    host = sid(lobby.get("hostId"))
    host_name = lobby.get("hostName") or "درخواست‌کننده"
    for item in lobby.get("lates") or []:
        uid = sid(item.get("id"))
        if not uid or uid in prev or item.get("status") != "pending":
            continue
        try:
            tg("sendMessage", {"chat_id": int(uid), "text": f"{host_name} برات تأخیر ثبت کرده.\nقبول می‌کنی یا اعتراض داری؟\nاگه عکس لابی داری بعد از اعتراض همین‌جا بفرست.", "reply_markup": {"inline_keyboard": [[{"text": "قبول می‌کنم", "callback_data": f"late:ok:{uid}"}], [{"text": "اعتراض دارم", "callback_data": f"late:no:{uid}"}]]}})
            if host:
                tg("sendMessage", {"chat_id": int(host), "text": f"تأخیر برای {item.get('name', 'بازیکن')} ثبت شد."})
        except Exception as e:
            print("late notify fail", uid, e)

def set_late_status(target, status):
    lobby = db_get("lobby") or {}
    lates = lobby.get("lates") or []
    found = False
    for item in lates:
        if sid(item.get("id")) == sid(target):
            item["status"] = status
            found = True
    if found:
        lobby["lates"] = lates
        db_put("lobby", lobby)
    return found

def accept_late(target, name=""):
    members = members_map()
    info = members.get(sid(target)) or {}
    bump_stat("late", target, name or info.get("name") or "", info.get("username") or "")
    set_late_status(target, "accepted")

def auto_accept_lates(lobby):
    if not lobby:
        return
    changed = False
    lates = list(lobby.get("lates") or [])
    now = time.time()
    for item in lates:
        if item.get("status") != "pending":
            continue
        at = float(item.get("at") or 0)
        at = at / 1000 if at > 1e12 else at
        if at and now - at >= LATE_AUTO_HOURS * 3600:
            accept_late(item.get("id"), item.get("name") or "")
            item["status"] = "accepted"
            changed = True
            try:
                tg("sendMessage", {"chat_id": int(item["id"]), "text": "تأخیر چون جواب ندادی خودکار تأیید شد."})
            except Exception:
                pass
    if changed:
        lobby["lates"] = lates
        db_put("lobby", lobby)

def tally_noreply(old, new):
    if not old or not old.get("hostId") or old.get("noreplyTallied"):
        return
    if new and sid(new.get("hostId")) == sid(old.get("hostId")) and new.get("startIso") == old.get("startIso"):
        return
    opened = opened_ts(old)
    if opened is None or (time.time() - opened) < REPLY_WINDOW:
        return
    increment_noreply(old)

def maybe_remind(lobby):
    if not lobby or lobby.get("startMode") != "clock" or lobby.get("reminded") or not lobby.get("startIso"):
        return
    try:
        start = datetime.fromisoformat(lobby["startIso"].replace("Z", "+00:00"))
    except Exception:
        return
    now = datetime.now(timezone.utc)
    left = (start - now).total_seconds()
    if left > 10 * 60 or left < 0:
        return
    skip = {sid(a.get("id")) for a in (lobby.get("answers") or []) if a.get("code") == "no"}
    text = f"۱۰ دقیقه تا شروع — {lobby.get('hostName', 'یکی')} درخواست داده بود."
    for uid in member_ids() + [sid(lobby.get("hostId"))]:
        if sid(uid) in skip or not uid:
            continue
        try:
            tg("sendMessage", {"chat_id": int(uid), "text": text})
        except Exception as e:
            print("remind fail", uid, e)
    lobby["reminded"] = True
    db_put("lobby", lobby)

def handle_photo(upd):
    msg = upd.get("message") or {}
    photos = msg.get("photo") or []
    if not photos:
        return False
    user = msg.get("from") or {}
    uid = sid(user.get("id"))
    if not db_get(f"latePhotoWait/{uid}"):
        return False
    file_id = photos[-1]["file_id"]
    db_put(f"latePhotos/{uid}", {"file_id": file_id, "ts": int(time.time() * 1000)})
    db_put(f"latePhotoWait/{uid}", None)
    tg("sendMessage", {"chat_id": msg["chat"]["id"], "text": "عکس رسید. ادمین می‌بینه."})
    for admin in ADMIN_IDS:
        try:
            tg("sendPhoto", {"chat_id": int(admin), "photo": file_id, "caption": f"عکس اعتراض تأخیر از {user.get('first_name', '')}"})
        except Exception as e:
            print("admin photo fail", e)
    return True

def handle_update(upd):
    if handle_photo(upd):
        return
    if "message" in upd and str(upd["message"].get("text") or "").startswith("/start"):
        save_member(upd["message"].get("from"))
        tg("sendMessage", {"chat_id": upd["message"]["chat"]["id"], "text": "عضو اسکواد شدی. از دکمه Open درخواست بده."})
        return
    q = upd.get("callback_query")
    if not q:
        return
    tg("answerCallbackQuery", {"callback_query_id": q["id"]})
    data = q.get("data") or ""
    if data.startswith("lateadm:") or data.startswith("late:"):
        user = q.get("from") or {}
        chat_id = q["message"]["chat"]["id"]
        parts = data.split(":")
        if len(parts) < 3:
            return
        kind, action, target = parts[0], parts[1], parts[2]
        uid = sid(user.get("id"))
        if kind == "lateadm" and uid not in ADMIN_IDS:
            tg("sendMessage", {"chat_id": chat_id, "text": "فقط ادمین."})
            return
        if kind == "late" and uid != sid(target) and uid not in ADMIN_IDS:
            tg("sendMessage", {"chat_id": chat_id, "text": "این دکمه مال تو نیست."})
            return
        if action == "ok":
            accept_late(target)
            tg("sendMessage", {"chat_id": chat_id, "text": "تأخیر تأیید شد."})
            if kind == "lateadm":
                try:
                    tg("sendMessage", {"chat_id": int(target), "text": "ادمین تأخیر را تأیید کرد."})
                except Exception:
                    pass
            return
        set_late_status(target, "disputed" if kind == "late" else "rejected")
        if kind == "late":
            db_put(f"latePhotoWait/{target}", True)
            tg("sendMessage", {"chat_id": chat_id, "text": "اعتراض ثبت شد. اگه عکس لابی داری همین‌جا بفرست."})
            name = next((x.get("name") for x in ((db_get("lobby") or {}).get("lates") or []) if sid(x.get("id")) == sid(target)), "بازیکن")
            for admin in ADMIN_IDS:
                try:
                    tg("sendMessage", {"chat_id": int(admin), "text": f"{name} به تأخیر اعتراض کرد.", "reply_markup": {"inline_keyboard": [[{"text": "تأیید تأخیر", "callback_data": f"lateadm:ok:{target}"}], [{"text": "رد تأخیر", "callback_data": f"lateadm:no:{target}"}]]}})
                except Exception as e:
                    print("admin late fail", e)
        else:
            tg("sendMessage", {"chat_id": chat_id, "text": "تأخیر رد شد."})
            try:
                tg("sendMessage", {"chat_id": int(target), "text": "ادمین اعتراض را پذیرفت. تأخیر ثبت نشد."})
            except Exception:
                pass
        return
    if not data.startswith("ans:"):
        return
    code = data.split(":", 1)[1]
    user = q.get("from") or {}
    save_member(user)
    chat_id = q["message"]["chat"]["id"]
    lobby = db_get("lobby") or {}
    L = labels_for(lobby)
    if not lobby or not lobby.get("hostId"):
        tg("sendMessage", {"chat_id": chat_id, "text": "این درخواست بسته شده."})
        return
    if sid(user.get("id")) == sid(lobby.get("hostId")):
        tg("sendMessage", {"chat_id": chat_id, "text": "این درخواست خودته."})
        return
    answers = [a for a in (lobby.get("answers") or []) if sid(a.get("id")) != sid(user.get("id"))]
    answers.append({"id": sid(user.get("id")), "name": " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x) or "بازیکن", "code": code, "at": int(time.time() * 1000)})
    lobby["answers"] = answers
    db_put("lobby", lobby)
    tg("sendMessage", {"chat_id": chat_id, "text": "ثبت شد: " + L.get(code, code)})

def main():
    threading.Thread(target=serve, daemon=True).start()
    print("bot running")
    offset = None
    last = None
    last_check = 0
    while True:
        try:
            now = time.time()
            if now - last_check >= 3:
                cur = db_get("lobby")
                if json.dumps(cur, sort_keys=True) != json.dumps(last, sort_keys=True):
                    tally_noreply(last, cur)
                    notify_new_request(cur, last)
                    notify_new_answers(cur, last)
                    notify_new_lates(cur, last)
                    last = cur
                if cur:
                    cur = maybe_tally_open(cur)
                    auto_accept_lates(cur)
                    maybe_remind(cur)
                    last = db_get("lobby")
                last_check = now
            payload = {"timeout": 2}
            if offset is not None:
                payload["offset"] = offset
            data = tg("getUpdates", payload)
            for upd in data.get("result") or []:
                offset = upd["update_id"] + 1
                handle_update(upd)
        except Exception as e:
            print("loop error", e)
            time.sleep(2)

if __name__ == "__main__":
    main()
