import os
import time
import json
import threading
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"
DB = "https://esquad-warzone-default-rtdb.europe-west1.firebasedatabase.app"

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
            [
                {"text": L["5"], "callback_data": "ans:5"},
                {"text": L["15"], "callback_data": "ans:15"},
            ],
            [
                {"text": L["30"], "callback_data": "ans:30"},
                {"text": L["60"], "callback_data": "ans:60"},
            ],
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


def notify_new_request(lobby, old):
    if not lobby or not lobby.get("hostId"):
        return
    if (old or {}).get("hostId") == lobby.get("hostId") and (old or {}).get("startIso") == lobby.get("startIso"):
        return
    members = db_get("members") or {}
    text = (
        f"{lobby.get('hostName', 'یکی')} پرسیده: کسی هست برای بازی؟\n"
        f"شروع: {lobby.get('startLabel')}\n"
        f"حدوداً تا {lobby.get('endLabel')}"
    )
    host = str(lobby.get("hostId"))
    kb = keyboard_for(lobby)
    for uid in members:
        if str(uid) == host:
            continue
        try:
            tg("sendMessage", {"chat_id": int(uid), "text": text, "reply_markup": kb})
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
    for a in lobby.get("answers") or []:
        if not a:
            continue
        oid = str(a.get("id"))
        prev_a = prev.get(oid)
        if prev_a is None or prev_a.get("code") != a.get("code"):
            try:
                tg(
                    "sendMessage",
                    {
                        "chat_id": int(lobby["hostId"]),
                        "text": f"{a.get('name', 'بازیکن')}: {L.get(a.get('code'), a.get('code'))}",
                    },
                )
            except Exception as e:
                print("host notify fail", e)


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
                    notify_new_request(cur, last)
                    notify_new_answers(cur, last)
                    last = cur
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
