import os
import sqlite3
import json
import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import contextmanager
from datetime import datetime

# ====================== تنظیمات ======================
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bots (
                owner_id TEXT PRIMARY KEY,
                token TEXT NOT NULL,
                bot_username TEXT,
                welcome_text TEXT DEFAULT 'سلام! به ربات خوش آمدید.',
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS states (
                user_id TEXT PRIMARY KEY,
                state TEXT,
                data TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS buttons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT,
                button_type TEXT,
                button_text TEXT,
                response_text TEXT
            )
        """)
        conn.commit()

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
        r = requests.post(url, json=data or {}, timeout=15)
        return r.json()
    except Exception as e:
        print(f"API Error: {e}")
        return {"status": "ERROR", "error": str(e)}

def send_message(token: str, chat_id: str, text: str, inline_keypad=None):
    payload = {"chat_id": chat_id, "text": text}
    if inline_keypad:
        payload["inline_keypad"] = inline_keypad
    return api(token, "sendMessage", payload)

def make_glass(rows):
    return {
        "rows": [
            {"buttons": [{"id": b["id"], "type": "Simple", "button_text": b["text"]} for b in row]}
            for row in rows
        ]
    }

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
        [{"id": "premium", "text": "⭐ اشتراک ویژه"}]
    ])

def admin_menu():
    return make_glass([
        [{"id": "set_welcome", "text": "📝 متن خوش‌آمدگویی"}],
        [{"id": "create_panel_btn", "text": "⌨️ ساخت دکمه پنلی"}],
        [{"id": "create_glass_btn", "text": "🪟 ساخت دکمه شیشه‌ای"}],
        [{"id": "test_bot", "text": "🧪 تست ربات"}],
        [{"id": "back_main", "text": "🔙 بازگشت"}]
    ])

# ====================== Webhook ربات اصلی ======================
@app.api_route("/webhook/main", methods=["POST", "HEAD"])
async def main_webhook(request: Request):
    if request.method == "HEAD":
        return JSONResponse({"status": "OK"})

    data = await request.json()
    print("MAIN:", data)

    # ---------- کلیک دکمه ----------
    if "inline_message" in data:
        im = data["inline_message"]
        chat_id = im.get("chat_id")
        user_id = im.get("sender_id")
        button_id = im.get("aux_data", {}).get("button_id")

        if button_id == "premium":
            send_message(MAIN_TOKEN, chat_id, "کاربر گرامی این دکمه فعلا غیرفعال است.", inline_keypad=main_menu())

        elif button_id == "connect_bot":
            set_state(user_id, "waiting_token")
            send_message(MAIN_TOKEN, chat_id,
                "برای وصل کردن ربات خودت این مراحل رو انجام بده:\n\n"
                "۱. برو داخل روبیکا به @BotFather\n"
                "۲. دستور /newbot رو بزن و ربات جدید بساز\n"
                "۳. توکنی که بهت می‌ده رو کپی کن\n\n"
                "حالا توکن ربات خود را در همین چت بدون هیچ تغییری وارد کنید:")

        elif button_id == "my_bots":
            with get_db() as conn:
                bots = conn.execute("SELECT bot_username FROM bots WHERE owner_id = ?", (user_id,)).fetchall()
            if not bots:
                text = "شما هنوز هیچ رباتی وصل نکرده‌اید."
            else:
                text = "ربات‌های شما:\n\n" + "\n".join([f"• @{b['bot_username'] or 'بدون یوزرنیم'}" for b in bots])
            send_message(MAIN_TOKEN, chat_id, text, inline_keypad=main_menu())

        return JSONResponse({"status": "OK"})

    # ---------- پیام جدید ----------
    if "update" in data:
        update = data["update"]
        if update.get("type") == "NewMessage":
            msg = update.get("new_message", {})
            chat_id = update.get("chat_id")
            user_id = msg.get("sender_id")
            text = (msg.get("text") or "").strip()

            # فقط چت خصوصی
            if not chat_id.startswith("b0"):
                return JSONResponse({"status": "OK"})

            state, _ = get_state(user_id)

            # دریافت توکن
            if state == "waiting_token":
                token = text
                me = api(token, "getMe")
                if me.get("status") != "OK":
                    send_message(MAIN_TOKEN, chat_id, "❌ توکن نامعتبر است. لطفاً دوباره تلاش کنید.")
                    return JSONResponse({"status": "OK"})

                bot_info = me.get("data", {}).get("bot", {})
                bot_username = bot_info.get("username")

                with get_db() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO bots (owner_id, token, bot_username, created_at) VALUES (?, ?, ?, ?)",
                        (user_id, token, bot_username, datetime.now().isoformat())
                    )
                    conn.commit()

                # ثبت webhook برای ربات کاربر
                webhook_url = f"{BASE_URL}/webhook/{user_id}"
                print("==== WEBHOOK URL BEING SET ====")
                print(webhook_url)
                print("===============================")
                for ep in ["ReceiveUpdate", "ReceiveInlineMessage"]:
                    res = api(token, "updateBotEndpoints", {"url": webhook_url, "type": ep})
                    print(f"User bot {ep}: {res}")

                clear_state(user_id)
                send_message(MAIN_TOKEN, chat_id,
                    f"✅ ربات شما با موفقیت وصل شد!\n\n"
                    f"یوزرنیم: @{bot_username or 'نامشخص'}\n\n"
                    f"حالا برو داخل ربات خودت و /start بزن تا پنل ادمین باز شود.",
                    inline_keypad=main_menu())
                return JSONResponse({"status": "OK"})

            # /start ربات اصلی
            if text.lower() in ["/start", "start", "شروع"]:
                send_message(MAIN_TOKEN, chat_id,
                    "به ربات ساز مریکوبات خوش آمدید\n"
                    "شما میتوانید با استفاده از دکمه های زیر ربات خود را بسازید.",
                    inline_keypad=main_menu())

    return JSONResponse({"status": "OK"})

# ====================== Webhook ربات‌های کاربر ======================
@app.api_route("/webhook/{owner_id}", methods=["POST", "HEAD"])
async def user_bot_webhook(owner_id: str, request: Request):
    if request.method == "HEAD":
        return JSONResponse({"status": "OK"})

    data = await request.json()
    print(f"USER BOT {owner_id}:", data)

    with get_db() as conn:
        row = conn.execute("SELECT token, welcome_text FROM bots WHERE owner_id = ?", (owner_id,)).fetchone()
    if not row:
        return JSONResponse({"status": "OK"})

    token = row["token"]
    welcome_text = row["welcome_text"] or "سلام! به ربات خوش آمدید."

    # ---------- کلیک دکمه ----------
    if "inline_message" in data:
        im = data["inline_message"]
        chat_id = im.get("chat_id")
        user_id = im.get("sender_id")
        button_id = im.get("aux_data", {}).get("button_id")
        is_owner = (user_id == owner_id)

        if not is_owner:
            return JSONResponse({"status": "OK"})

        if button_id == "set_welcome":
            set_state(user_id, "waiting_welcome")
            send_message(token, chat_id, "متن خوش‌آمدگویی جدید را وارد کنید:")

        elif button_id == "create_panel_btn":
            set_state(user_id, "waiting_panel_btn_text")
            send_message(token, chat_id, "متن دکمه پنلی را وارد کنید:")

        elif button_id == "create_glass_btn":
            set_state(user_id, "waiting_glass_btn_text")
            send_message(token, chat_id, "متن دکمه شیشه‌ای را وارد کنید:")

        elif button_id == "test_bot":
            set_state(user_id, "test_mode")
            send_message(token, chat_id, welcome_text,
                inline_keypad=make_glass([[{"id": "back_admin", "text": "🔙 بازگشت به پنل ادمین"}]]))

        elif button_id == "back_admin":
            clear_state(user_id)
            send_message(token, chat_id, "به پنل ادمین برگشتید.", inline_keypad=admin_menu())

        elif button_id == "confirm_welcome":
            state, sdata = get_state(user_id)
            new_text = sdata.get("welcome_text", "")
            with get_db() as conn:
                conn.execute("UPDATE bots SET welcome_text = ? WHERE owner_id = ?", (new_text, owner_id))
                conn.commit()
            clear_state(user_id)
            send_message(token, chat_id, "✅ متن خوش‌آمدگویی ذخیره شد.", inline_keypad=admin_menu())

        elif button_id == "cancel_welcome":
            clear_state(user_id)
            send_message(token, chat_id, "انصراف داده شد.", inline_keypad=admin_menu())

        return JSONResponse({"status": "OK"})

    # ---------- پیام جدید ----------
    if "update" in data:
        update = data["update"]
        if update.get("type") == "NewMessage":
            msg = update.get("new_message", {})
            chat_id = update.get("chat_id")
            user_id = msg.get("sender_id")
            text = (msg.get("text") or "").strip()

            # فقط چت خصوصی
            if not chat_id.startswith("b0"):
                return JSONResponse({"status": "OK"})

            is_owner = (user_id == owner_id)
            state, sdata = get_state(user_id)

            if is_owner:
                if state == "waiting_welcome":
                    set_state(user_id, "confirm_welcome", {"welcome_text": text})
                    send_message(token, chat_id,
                        f"متن جدید:\n\n{text}\n\nآیا تأیید می‌کنید؟",
                        inline_keypad=make_glass([
                            [{"id": "confirm_welcome", "text": "✅ تأیید"}, {"id": "cancel_welcome", "text": "❌ انصراف"}]
                        ]))
                    return JSONResponse({"status": "OK"})

                if text.lower() in ["/start", "start", "شروع"] or state is None:
                    clear_state(user_id)
                    send_message(token, chat_id, "پنل مدیریت ربات شما:", inline_keypad=admin_menu())
                    return JSONResponse({"status": "OK"})

            else:
                # کاربر عادی
                if text.lower() in ["/start", "start", "شروع"]:
                    send_message(token, chat_id, welcome_text)

    return JSONResponse({"status": "OK"})

# ====================== صفحه اصلی ======================
@app.get("/")
async def home():
    return {
        "status": "ربات ساز مریکوبات فعال است",
        "main_token_set": bool(MAIN_TOKEN),
        "base_url": BASE_URL
    }

# ====================== استارت ======================
@app.on_event("startup")
def startup():
    init_db()
    if BASE_URL:
        main_webhook_url = f"{BASE_URL}/webhook/main"
        for ep in ["ReceiveUpdate", "ReceiveInlineMessage"]:
            res = api(MAIN_TOKEN, "updateBotEndpoints", {"url": main_webhook_url, "type": ep})
            print(f"Main {ep}: {res}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
