import os, time, json, threading, requests
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.environ["BOT_TOKEN"]
DB = "https://esquad-warzone-default-rtdb.europe-west1.firebasedatabase.app"

LABELS = {
    "5": "الان تا ۵ دقیقه",
    "15": "تا ۱۵ دقیقه",
    "30": "حدود ۳۰ دقیقه",
    "60": "یک ساعت به بالا",
    "no": "نیستم",
}

def db_get(path):
    r = requests.get(f"{DB}/{path}.json", timeout=15)
    r.raise_for_status()
    return r.json()

def db_put(path, data):
    r = requests.put(f"{DB}/{path}.json", json=data, timeout=15)
    r.raise_for_status()

def save_member(user):
    if not user: return
    db_put(f"members/{user.id}", {
        "name": " ".join(x for x in [user.first_name, user.last_name] if x),
        "username": user.username or "",
        "ts": int(time.time() * 1000),
    })

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_member(update.effective_user)
    await update.message.reply_text("عضو اسکواد شدی. از دکمه ESQUAD درخواست بده.")

async def on_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not q.data or not q.data.startswith("ans:"): return
    code = q.data.split(":", 1)[1]
    user = q.from_user
    save_member(user)
    lobby = db_get("lobby") or {}
    if not lobby or not lobby.get("hostId"):
        await q.message.reply_text("این درخواست بسته شده.")
        return
    if str(user.id) == str(lobby.get("hostId")):
        await q.message.reply_text("این درخواست خودته.")
        return
    answers = [a for a in (lobby.get("answers") or []) if str(a.get("id")) != str(user.id)]
    answers.append({
        "id": str(user.id),
        "name": " ".join(x for x in [user.first_name, user.last_name] if x) or "بازیکن",
        "code": code,
        "at": int(time.time() * 1000),
    })
    lobby["answers"] = answers
    db_put("lobby", lobby)
    await q.message.reply_text("ثبت شد: " + LABELS.get(code, code))

def notify_new_request(lobby, old):
    if not lobby or not lobby.get("hostId"): return
    if (old or {}).get("hostId") == lobby.get("hostId") and (old or {}).get("startIso") == lobby.get("startIso"):
        return
    members = db_get("members") or {}
    text = (
        f"{lobby.get('hostName', 'یکی')} پرسیده: کسی هست برای بازی؟\n"
        f"شروع: {lobby.get('startLabel')}\n"
        f"حدوداً تا {lobby.get('endLabel')}"
    )
    kb = {"inline_keyboard": [
        [{"text": "الان تا ۵ دقیقه", "callback_data": "ans:5"}, {"text": "تا ۱۵ دقیقه", "callback_data": "ans:15"}],
        [{"text": "حدود ۳۰ دقیقه", "callback_data": "ans:30"}, {"text": "یک ساعت به بالا", "callback_data": "ans:60"}],
        [{"text": "نیستم", "callback_data": "ans:no"}],
        [{"text": "باز کردن تابلو", "url": "https://t.me/warzonesquad_bot/squad"}],
    ]}
    host = str(lobby.get("hostId"))
    for uid in members.keys():
        if str(uid) == host: continue
        try:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={"chat_id": int(uid), "text": text, "reply_markup": kb},
                timeout=15,
            )
        except Exception as e:
            print("send fail", uid, e)

def watch_lobby():
    last = None
    while True:
        try:
            cur = db_get("lobby")
            if json.dumps(cur, sort_keys=True) != json.dumps(last, sort_keys=True):
                notify_new_request(cur, last)
                last = cur
        except Exception as e:
            print("watch error", e)
        time.sleep(3)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_answer))
    threading.Thread(target=watch_lobby, daemon=True).start()
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
