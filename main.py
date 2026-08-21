import os
import sqlite3
import json
import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import contextmanager
from datetime import datetime

MAIN_TOKEN = os.getenv("RUBIKA_TOKEN")
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
DB_PATH = "/data/bots.db"

if not MAIN_TOKEN:
    raise ValueError("RUBIKA_TOKEN تنظیم نشده!")

app = FastAPI()

# ====================== دیتابیس ======================
def init_db():
    os.makedirs("/data", exist_ok=True)
    with get_db() as conn:
        conn.execute("DROP TABLE IF EXISTS bots")
        conn.execute("DROP TABLE IF EXISTS states")
        conn.execute("""
            CREATE TABLE bots (
                owner_id TEXT PRIMARY KEY,
                token TEXT NOT NULL,
                bot_username TEXT,
                path TEXT UNIQUE,
                welcome_text TEXT DEFAULT 'سلام! به ربات خوش آمدید.',
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE states (
                user_id TEXT PRIMARY KEY,
                state TEXT,
                data TEXT
            )
        """)
        conn.commit()
        print("✅ Database initialized successfully")

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# ====================== توابع کمکی ======================
def api(token: str, method: str, data: dict = None):
    url = f"https://botapi.rubika.ir/v3/{token}/{method}"
    try:
        r = requests.post(url, json=data or {}, timeout=20)
        return r.json()
    except Exception as e:
        print(f"API Error: {e}")
        return {"status": "ERROR", "error": str(e)}

def send_message(token: str, chat_id: str, text: str, inline_keypad=None):
    payload = {"chat_id": chat_id, "text": text}
    if inline_keypad:
        payload["inline_keypad"] = inline_keypad
    return api(token, "sendMessage", payload)

def edit_message(token: str, chat_id: str, message_id: str, text: str, inline_keypad=None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text
    }
    if inline_keypad:
        payload["inline_keypad"] = inline_keypad
    return api(token, "editMessageText", payload)

def make_glass(rows):
    return {
        "rows": [
            {"buttons": [{"id": b["id"], "type": "Simple", "button_text": b["text"]} for b in row]}
            for row in rows
        ]
    }

def get_next_path():
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM bots").fetchone()
        number = (row["cnt"] or 0) + 1
        return f"main{number}"

# ====================== State ======================
def set_state(user_id: str, state: str, data: dict = None):
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO states (user_id, state, data) VALUES (?, ?, ?)",
            (user_id, state, json.dumps(data or {}))
        )
        conn.commit()

def get_state(user_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT state, data FROM states WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            return row["state"], json.loads(row["data"] or "{}")
        return None, {}

def clear_state(user_id: str):
    with get_db() as conn:
        conn.execute("DELETE FROM states WHERE user_id = ?", (user_id,))
        conn.commit()

# ====================== منوها ======================
def main_menu():
    return make_glass([
        [{"id": "connect_bot", "text": "🔗 وصل کردن ربات"}],
        [{"id": "my_bots", "text": "📋 لیست ربات‌های من"}],
        [{"id": "set_welcome", "text": "📝 تنظیم متن خوش‌آمدگویی"}],
        [{"id": "premium", "text": "⭐ اشتراک ویژه"}]
    ])

# ====================== Webhook اصلی ======================
@app.api_route("/webhook/main", methods=["POST", "HEAD", "GET"])
async def main_webhook(request: Request):
    if request.method in ["HEAD", "GET"]:
        return JSONResponse({"status": "OK"})

    data = await request.json()
    print("MAIN:", data)

    if "inline_message" in data:
        im = data["inline_message"]
        chat_id = im.get("chat_id")
        user_id = im.get("sender_id")
        message_id = im.get("message_id")
        button_id = im.get("aux_data", {}).get("button_id")

        if button_id == "premium":
            edit_message(MAIN_TOKEN, chat_id, message_id,
                         "کاربر گرامی این دکمه فعلاً غیرفعال است.",
                         inline_keypad=main_menu())

        elif button_id == "connect_bot":
            set_state(user_id, "waiting_token")
            edit_message(MAIN_TOKEN, chat_id, message_id,
                "توکن ربات خود را از @BotFather بگیرید و همینجا بدون هیچ تغییری بفرستید:")

        elif button_id == "my_bots":
            with get_db() as conn:
                bots = conn.execute(
                    "SELECT bot_username, path FROM bots WHERE owner_id = ?", (user_id,)
                ).fetchall()
            if not bots:
                text = "شما هنوز هیچ رباتی وصل نکرده‌اید."
            else:
                text = "ربات‌های شما:\n\n"
                for b in bots:
                    text += f"• @{b['bot_username'] or 'بدون یوزرنیم'}\n  مسیر: /webhook/{b['path']}\n\n"
            edit_message(MAIN_TOKEN, chat_id, message_id, text, inline_keypad=main_menu())

        elif button_id == "set_welcome":
            set_state(user_id, "waiting_welcome")
            edit_message(MAIN_TOKEN, chat_id, message_id,
                         "متن خوش‌آمدگویی جدید ربات خود را بنویسید:")

        return JSONResponse({"status": "OK"})

    if "update" in data:
        update = data["update"]
        if update.get("type") == "NewMessage":
            msg = update.get("new_message", {})
            chat_id = update.get("chat_id")
            user_id = msg.get("sender_id")
            text = (msg.get("text") or "").strip()

            if not chat_id.startswith("b0"):
                return JSONResponse({"status": "OK"})

            state, _ = get_state(user_id)

            if state == "waiting_token":
                token = text
                me = api(token, "getMe")
                if me.get("status") != "OK":
                    send_message(MAIN_TOKEN, chat_id, "❌ توکن نامعتبر است. دوباره تلاش کنید.")
                    return JSONResponse({"status": "OK"})

                bot_info = me.get("data", {}).get("bot", {})
                bot_username = bot_info.get("username")
                path = get_next_path()

                with get_db() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO bots (owner_id, token, bot_username, path, created_at) VALUES (?, ?, ?, ?, ?)",
                        (user_id, token, bot_username, path, datetime.now().isoformat())
                    )
                    conn.commit()

                webhook_url = f"{BASE_URL}/webhook/{path}"
                print("==== WEBHOOK URL BEING SET ====")
                print(webhook_url)
                print("===============================")

                for ep in ["ReceiveUpdate", "ReceiveInlineMessage"]:
                    res = api(token, "updateBotEndpoints", {"url": webhook_url, "type": ep})
                    print(f"User bot {ep}: {res}")

                clear_state(user_id)
                send_message(MAIN_TOKEN, chat_id,
                    f"✅ ربات شما وصل شد!\n"
                    f"یوزرنیم: @{bot_username or 'نامشخص'}\n"
                    f"مسیر: /webhook/{path}",
                    inline_keypad=main_menu())
                return JSONResponse({"status": "OK"})

            if state == "waiting_welcome":
                with get_db() as conn:
                    conn.execute("UPDATE bots SET welcome_text = ? WHERE owner_id = ?", (text, user_id))
                    conn.commit()
                clear_state(user_id)
                send_message(MAIN_TOKEN, chat_id, f"✅ متن خوش‌آمدگویی ذخیره شد:\n\n{text}", inline_keypad=main_menu())
                return JSONResponse({"status": "OK"})

            if text.lower() in ["/start", "start", "شروع"]:
                send_message(MAIN_TOKEN, chat_id,
                    "به ربات‌ساز مریکوبات خوش آمدید\nبا دکمه‌های زیر ربات خود را بسازید و مدیریت کنید.",
                    inline_keypad=main_menu())

    return JSONResponse({"status": "OK"})


# ====================== Webhook ربات‌های کاربر (با پشتیبانی GET) ======================
@app.api_route("/webhook/{path}", methods=["POST", "HEAD", "GET"])
async def user_bot_webhook(path: str, request: Request):
    # دقیقاً مثل ربات اصلی
    if request.method in ["HEAD", "GET"]:
        return JSONResponse({"status": "OK"})

    with get_db() as conn:
        bot = conn.execute("SELECT * FROM bots WHERE path = ?", (path,)).fetchone()

    if not bot:
        return JSONResponse({"status": "OK"})

    token = bot["token"]
    data = await request.json()
    print(f"USER BOT ({path}):", data)

    if "update" in data:
        update = data["update"]
        if update.get("type") == "NewMessage":
            msg = update.get("new_message", {})
            chat_id = update.get("chat_id")
            text = (msg.get("text") or "").strip()

            if text.lower() in ["/start", "start", "شروع"]:
                welcome = bot["welcome_text"] or "سلام! به ربات خوش آمدید."
                send_message(token, chat_id, welcome)

    return JSONResponse({"status": "OK"})


@app.get("/")
async def home():
    return {
        "status": "ربات‌ساز مریکوبات فعال است",
        "token_set": bool(MAIN_TOKEN),
        "base_url": BASE_URL
    }


@app.on_event("startup")
def startup():
    init_db()
    if BASE_URL:
        webhook_url = f"{BASE_URL}/webhook/main"
        for ep in ["ReceiveUpdate", "ReceiveInlineMessage"]:
            res = api(MAIN_TOKEN, "updateBotEndpoints", {"url": webhook_url, "type": ep})
            print(f"Main {ep}: {res}")
