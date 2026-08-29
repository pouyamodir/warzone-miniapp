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

STATS_HIDE_IDS = set()
STATS_HIDE_USERNAMES = {"pouya_modir"}
REPLY_WINDOW = 100 * 60

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


LABELS_NOW = {
    "5": "تا ۵ دقیقه",
    "15": "تا ۱۵ دقیقه",
    "30": "حدود ۳۰ دقیقه",
    "60": "یک ساعت به بالا",
    "no": "نیستم",
}
LABELS_LATER = {
    "5": "هستم",
    "15": "با ۱۵ دقیقه تأخیر",
    "30": "با نیم ساعت تأخیر",
    "60": "با یک ساعت تأخیر",
    "no": "نیستم",
}


def is_later(lobby):
    return (lobby or {}).get("startMode") == "clock"


def labels_for(lobby):
    return LABELS_LATER if is_later(lobby) else LABELS_NOW


def keyboard_for(lobby):
    L = labels_for(lobby)
    return {
        "inline_keyboard": [
            [{"text": L["5"], "callback_data": "ans:5"}, {"text": L["15"], "callback_data": "ans:15"}],
            [{"text": L["30"], "callback_data": "ans:30"}, {"text": L["60"], "callback_data": "ans:60"}],
            [{"text": L["no"], "callback_data": "ans:no"}],
            [{"text": "باز کردن تابلو", "url": "https://t.me/warzonesquad_bot/squad"}],
        ]
    }


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


def hidden(uid, info=None):
    uid = str(uid)
    if uid in STATS_HIDE_IDS:
        return True
    un = str((info or {}).get("username") or "").lstrip("@").lower()
    return un in STATS_HIDE_USERNAMES


def save_member(user):
    if not user or "id" not in user:
        return
    db_put(
        f"members/{user['id']}",
        {
            "name": " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x),
            "username": user.get("username") or "",
            "ts": int(time.time() * 1000),
        },
    )


def members_map():
    return db_get("members") or {}


def member_ids():
    return [str(uid) for uid in members_map().keys()]


def card_text(lobby):
    L = labels_for(lobby)
    answers = lobby.get("answers") or []
    ready = {"5", "15"} if not is_later(lobby) else {"5"}
    n = 1 + len({str(a.get("id")) for a in answers if a.get("code") in ready})
    n = min(4, n)
    lines = [
        f"{lobby.get('hostName', 'یکی')} پرسیده: کسی هست برای بازی؟",
        f"شروع: {lobby.get('startLabel')} — حدوداً تا {lobby.get('endLabel')}",
        f"{n} از ۴",
        "",
        f"{lobby.get('hostName', 'میزبان')}: درخواست‌کننده",
    ]
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
    if (old or {}).get("hostId") == lobby.get("hostId") and (old or {}).get("startIso") == lobby.get("startIso"):
        return
    host = str(lobby.get("hostId"))
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
    if str(lobby.get("hostId") or "") != str(old.get("hostId") or ""):
        return
    if lobby.get("startIso") != old.get("startIso"):
        return
    L = labels_for(lobby)
    prev = {str(a.get("id")): a for a in (old.get("answers") or []) if a}
    members = member_ids()
    host = str(lobby.get("hostId") or "")
    if host and host not in members:
        members.append(host)
    changed = False
    for a in lobby.get("answers") or []:
        if not a:
            continue
        oid = str(a.get("id"))
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


def tally_noreply(old, new):
    if not old or not old.get("hostId"):
        return
    if new and str(new.get("hostId")) == str(old.get("hostId")) and new.get("startIso") == old.get("startIso"):
        return
    opened = opened_ts(old)
    if opened is None or (time.time() - opened) < REPLY_WINDOW:
        return
    answered = {str(a.get("id")) for a in (old.get("answers") or [])}
    host = str(old.get("hostId"))
    members = members_map()
    for uid, info in members.items():
        uid = str(uid)
        info = info or {}
        if uid == host or uid in answered or hidden(uid, info):
            continue
        row = db_get(f"stats/noreply/{uid}") or {}
        db_put(
            f"stats/noreply/{uid}",
            {
                "name": info.get("name") or row.get("name") or "بازیکن",
                "username": info.get("username") or row.get("username") or "",
                "count": int(row.get("count") or 0) + 1,
            },
        )


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
    skip = {str(a.get("id")) for a in (lobby.get("answers") or []) if a.get("code") == "no"}
    text = f"۱۰ دقیقه تا شروع — {lobby.get('hostName', 'یکی')} درخواست داده بود."
    for uid in member_ids() + [str(lobby.get("hostId"))]:
        if str(uid) in skip:
            continue
        try:
            tg("sendMessage", {"chat_id": int(uid), "text": text})
        except Exception as e:
            print("remind fail", uid, e)
    lobby["reminded"] = True
    db_put("lobby", lobby)


def handle_update(upd):
    if "message" in upd and str(upd["message"].get("text") or "").startswith("/start"):
        save_member(upd["message"].get("from"))
        tg(
            "sendMessage",
            {
                "chat_id": upd["message"]["chat"]["id"],
                "text": "عضو اسکواد شدی. از دکمه Open درخواست بده.",
            },
        )
        return

    q = upd.get("callback_query")
    if not q:
        return

    tg("answerCallbackQuery", {"callback_query_id": q["id"]})
    data = q.get("data") or ""
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

    if str(user.get("id")) == str(lobby.get("hostId")):
        tg("sendMessage", {"chat_id": chat_id, "text": "این درخواست خودته."})
        return

    answers = [a for a in (lobby.get("answers") or []) if str(a.get("id")) != str(user.get("id"))]
    answers.append(
        {
            "id": str(user.get("id")),
            "name": " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x) or "بازیکن",
            "code": code,
            "at": int(time.time() * 1000),
        }
    )
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
                    last = cur
                if cur:
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
