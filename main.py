import os
import sqlite3
import json
import requests
import time
import secrets
import subprocess
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import contextmanager
from datetime import datetime

MAIN_TOKEN = os.getenv("RUBIKA_TOKEN")
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
DB_PATH = "/data/bots.db"

if not MAIN_TOKEN:
    raise ValueError("RUBIKA_TOKEN is not set!")

app = FastAPI()

# ============== Database ==============
def init_db():
    os.makedirs("/data", exist_ok=True)
    with get_db() as conn:
        conn.execute("DROP TABLE IF EXISTS bots")
        conn.execute("DROP TABLE IF EXISTS states")
        conn.execute("DROP TABLE IF EXISTS buttons")
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
        conn.execute("""
            CREATE TABLE buttons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT,
                button_type TEXT,
                button_text TEXT,
                response_text TEXT,
                created_at TEXT
            )
        """)
        conn.commit()
        print("✅ Database initialized")

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# ============== Helpers ==============
def api_with_curl(token: str, method: str, data: dict = None):
    """ارسال درخواست با CURL دقیقاً مثل دستوری که دستی می‌زنیم"""
    url = f"https://botapi.rubika.ir/v3/{token}/{method}"
    payload = json.dumps(data or {})
    
    # ساخت دستور curl
    cmd = [
        "curl", "-X", "POST", url,
        "-H", "Content-Type: application/json",
        "-d", payload
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        print(f"CURL output: {result.stdout}")
        return json.loads(result.stdout)
    except Exception as e:
        print(f"CURL Error: {e}")
        return {"status": "ERROR", "error": str(e)}

def send_message(token: str, chat_id: str, text: str, inline_keypad=None):
    payload = {"chat_id": chat_id, "text": text}
    if inline_keypad:
        payload["inline_keypad"] = inline_keypad
    return api_with_curl(token, "sendMessage", payload)

def edit_message(token: str, chat_id: str, message_id: str, text: str, inline_keypad=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if inline_keypad:
        payload["inline_keypad"] = inline_keypad
    return api_with_curl(token, "editMessageText", payload)

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
        return f"main{(row['cnt'] or 0) + 1}"

# ============== State ==============
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

# ============== Menus ==============
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
        [{"id": "back_main", "text": "🔙 بازگشت به منوی اصلی"}]
    ])

def test_mode_menu():
    return make_glass([
        [{"id": "back_admin", "text": "🔙 بازگشت به پنل ادمین"}]
    ])

# ============== تابع پردازش مشترک ==============
async def process_webhook(data: dict, bot_token: str, owner_id: str = None, is_main: bool = False):
    print("PROCESSING:", data)

    if "inline_message" in data:
        im = data["inline_message"]
        chat_id = im.get("chat_id")
        user_id = im.get("sender_id")
        message_id = im.get("message_id")
        button_id = im.get("aux_data", {}).get("button_id")

        if not is_main and owner_id and user_id != owner_id:
            return JSONResponse({"status": "OK"})

        if is_main:
            if button_id == "premium":
                edit_message(bot_token, chat_id, message_id, "کاربر گرامی این دکمه فعلاً غیرفعال است.", inline_keypad=main_menu())
            elif button_id == "connect_bot":
                set_state(user_id, "waiting_token")
                edit_message(bot_token, chat_id, message_id, 
                    "برای وصل کردن ربات خودت این مراحل رو انجام بده:\n\n"
                    "۱. برو داخل روبیکا به @BotFather\n"
                    "۲. دستور /newbot رو بزن و ربات جدید بساز\n"
                    "۳. توکنی که بهت می‌ده رو کپی کن\n\n"
                    "حالا توکن ربات خود را در همین چت بدون هیچ تغییری وارد کنید:")
            elif button_id == "my_bots":
                with get_db() as conn:
                    bots = conn.execute("SELECT bot_username, path FROM bots WHERE owner_id = ?", (user_id,)).fetchall()
                if not bots:
                    text = "شما هنوز هیچ رباتی وصل نکرده‌اید."
                else:
                    text = "ربات‌های شما:\n\n"
                    for b in bots:
                        text += f"• @{b['bot_username'] or 'بدون یوزرنیم'}\n  مسیر: /webhook/{b['path']}\n\n"
                edit_message(bot_token, chat_id, message_id, text, inline_keypad=main_menu())
            return JSONResponse({"status": "OK"})

        # ====== منوی ادمین ربات ثانویه ======
        if button_id == "set_welcome":
            set_state(user_id, "waiting_welcome")
            edit_message(bot_token, chat_id, message_id, "متن خوش‌آمدگویی جدید را وارد کنید:")
        elif button_id == "create_panel_btn":
            set_state(user_id, "waiting_panel_btn_text")
            edit_message(bot_token, chat_id, message_id, "متن دکمه پنلی را وارد کنید:\n(کاربر با کلیک روی این دکمه چه پیامی ببیند؟)")
        elif button_id == "create_glass_btn":
            set_state(user_id, "waiting_glass_btn_text")
            edit_message(bot_token, chat_id, message_id, "متن دکمه شیشه‌ای را وارد کنید:\n(کاربر با کلیک روی این دکمه چه پیامی ببیند؟)")
        elif button_id == "test_bot":
            set_state(user_id, "test_mode")
            with get_db() as conn:
                bot_row = conn.execute("SELECT welcome_text FROM bots WHERE owner_id = ?", (owner_id,)).fetchone()
            welcome = bot_row["welcome_text"] if bot_row else "سلام! به ربات خوش آمدید."
            edit_message(bot_token, chat_id, message_id, welcome, inline_keypad=test_mode_menu())
        elif button_id == "back_admin":
            clear_state(user_id)
            edit_message(bot_token, chat_id, message_id, "به پنل ادمین برگشتید.", inline_keypad=admin_menu())
        elif button_id == "back_main":
            clear_state(user_id)
            edit_message(bot_token, chat_id, message_id, "به منوی اصلی برگشتید.", inline_keypad=main_menu())
        elif button_id == "confirm_welcome":
            state, sdata = get_state(user_id)
            new_text = sdata.get("welcome_text", "")
            with get_db() as conn:
                conn.execute("UPDATE bots SET welcome_text = ? WHERE owner_id = ?", (new_text, owner_id))
                conn.commit()
            clear_state(user_id)
            edit_message(bot_token, chat_id, message_id, f"✅ متن خوش‌آمدگویی ذخیره شد:\n\n{new_text}", inline_keypad=admin_menu())
        elif button_id == "cancel_welcome":
            clear_state(user_id)
            edit_message(bot_token, chat_id, message_id, "انصراف داده شد.", inline_keypad=admin_menu())
        elif button_id == "confirm_button":
            state, sdata = get_state(user_id)
            btn_text = sdata.get("button_text", "")
            btn_response = sdata.get("response_text", "")
            btn_type = sdata.get("button_type", "panel")
            
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO buttons (owner_id, button_type, button_text, response_text, created_at) VALUES (?, ?, ?, ?, ?)",
                    (owner_id, btn_type, btn_text, btn_response, datetime.now().isoformat())
                )
                conn.commit()
            
            clear_state(user_id)
            edit_message(bot_token, chat_id, message_id, f"✅ دکمه '{btn_text}' با موفقیت ساخته شد!", inline_keypad=admin_menu())
        elif button_id == "cancel_button":
            clear_state(user_id)
            edit_message(bot_token, chat_id, message_id, "ساخت دکمه لغو شد.", inline_keypad=admin_menu())

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

            state, sdata = get_state(user_id)

            # ====== دریافت توکن (ربات اصلی) ======
            if is_main and state == "waiting_token":
                token = text
                me = api_with_curl(token, "getMe")
                if me.get("status") != "OK":
                    send_message(bot_token, chat_id, "❌ توکن نامعتبر است. لطفاً دوباره تلاش کنید.")
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

                # ثبت وب‌هوک با CURL و Cooldown بین درخواست‌ها
                for ep in ["ReceiveUpdate", "ReceiveInlineMessage"]:
                    res = api_with_curl(token, "updateBotEndpoints", {"url": webhook_url, "type": ep})
                    print(f"User bot {ep}: {res}")
                    time.sleep(3)  # Cooldown 3 ثانیه بین درخواست‌ها

                clear_state(user_id)
                send_message(bot_token, chat_id,
                    f"✅ ربات شما با موفقیت وصل شد!\n\n"
                    f"یوزرنیم: @{bot_username or 'نامشخص'}\n\n"
                    f"حالا برو داخل ربات خودت و /start بزن تا پنل ادمین باز شود.",
                    inline_keypad=main_menu())
                return JSONResponse({"status": "OK"})

            # ====== تنظیم متن خوش‌آمدگویی (ربات ثانویه) ======
            if not is_main and state == "waiting_welcome":
                if owner_id and user_id != owner_id:
                    return JSONResponse({"status": "OK"})
                set_state(user_id, "confirm_welcome", {"welcome_text": text})
                send_message(bot_token, chat_id,
                    f"متن جدید:\n\n{text}\n\nآیا تأیید می‌کنید؟",
                    inline_keypad=make_glass([
                        [{"id": "confirm_welcome", "text": "✅ تأیید"}, {"id": "cancel_welcome", "text": "❌ انصراف"}]
                    ]))
                return JSONResponse({"status": "OK"})

            # ====== ساخت دکمه پنلی ======
            if not is_main and state == "waiting_panel_btn_text":
                if owner_id and user_id != owner_id:
                    return JSONResponse({"status": "OK"})
                set_state(user_id, "waiting_panel_btn_response", {"button_text": text, "button_type": "panel"})
                send_message(bot_token, chat_id, f"متن دکمه: {text}\n\nحالا پیامی که کاربر با کلیک روی این دکمه ببیند را وارد کنید:")
                return JSONResponse({"status": "OK"})

            if not is_main and state == "waiting_panel_btn_response":
                if owner_id and user_id != owner_id:
                    return JSONResponse({"status": "OK"})
                btn_text = sdata.get("button_text", "")
                set_state(user_id, "confirm_button", {
                    "button_text": btn_text,
                    "response_text": text,
                    "button_type": "panel"
                })
                send_message(bot_token, chat_id,
                    f"دکمه: {btn_text}\nپاسخ: {text}\n\nآیا تأیید می‌کنید؟",
                    inline_keypad=make_glass([
                        [{"id": "confirm_button", "text": "✅ تأیید"}, {"id": "cancel_button", "text": "❌ انصراف"}]
                    ]))
                return JSONResponse({"status": "OK"})

            # ====== ساخت دکمه شیشه‌ای ======
            if not is_main and state == "waiting_glass_btn_text":
                if owner_id and user_id != owner_id:
                    return JSONResponse({"status": "OK"})
                set_state(user_id, "waiting_glass_btn_response", {"button_text": text, "button_type": "glass"})
                send_message(bot_token, chat_id, f"متن دکمه: {text}\n\nحالا پیامی که کاربر با کلیک روی این دکمه ببیند را وارد کنید:")
                return JSONResponse({"status": "OK"})

            if not is_main and state == "waiting_glass_btn_response":
                if owner_id and user_id != owner_id:
                    return JSONResponse({"status": "OK"})
                btn_text = sdata.get("button_text", "")
                set_state(user_id, "confirm_button", {
                    "button_text": btn_text,
                    "response_text": text,
                    "button_type": "glass"
                })
                send_message(bot_token, chat_id,
                    f"دکمه: {btn_text}\nپاسخ: {text}\n\nآیا تأیید می‌کنید؟",
                    inline_keypad=make_glass([
                        [{"id": "confirm_button", "text": "✅ تأیید"}, {"id": "cancel_button", "text": "❌ انصراف"}]
                    ]))
                return JSONResponse({"status": "OK"})

            # ====== /start ======
            if text.lower() in ["/start", "start", "شروع"]:
                clear_state(user_id)
                if is_main:
                    send_message(bot_token, chat_id,
                        "به ربات‌ساز مریکوبات خوش آمدید\nشما میتوانید با استفاده از دکمه های زیر ربات خود را بسازید.",
                        inline_keypad=main_menu())
                else:
                    if owner_id and user_id == owner_id:
                        send_message(bot_token, chat_id, "به پنل مدیریت ربات خود خوش آمدید:", inline_keypad=admin_menu())
                    else:
                        with get_db() as conn:
                            bot_row = conn.execute("SELECT welcome_text FROM bots WHERE owner_id = ?", (owner_id,)).fetchone()
                            buttons = conn.execute(
                                "SELECT button_type, button_text, response_text FROM buttons WHERE owner_id = ?",
                                (owner_id,)
                            ).fetchall()
                        welcome = bot_row["welcome_text"] if bot_row else "سلام! به ربات خوش آمدید."
                        
                        glass_rows = []
                        for btn in buttons:
                            if btn["button_type"] == "panel":
                                glass_rows.append([{"id": f"custom_{btn['button_text']}", "text": btn["button_text"]}])
                            elif btn["button_type"] == "glass":
                                if len(glass_rows) > 0 and len(glass_rows[-1]) < 2:
                                    glass_rows[-1].append({"id": f"custom_{btn['button_text']}", "text": btn["button_text"]})
                                else:
                                    glass_rows.append([{"id": f"custom_{btn['button_text']}", "text": btn["button_text"]}])
                        
                        if glass_rows:
                            inline_keypad = make_glass(glass_rows)
                            send_message(bot_token, chat_id, welcome, inline_keypad=inline_keypad)
                        else:
                            send_message(bot_token, chat_id, welcome)

    return JSONResponse({"status": "OK"})

# ============== Webhook اصلی ==============
@app.api_route("/webhook/main", methods=["POST", "HEAD", "GET"])
async def main_webhook(request: Request):
    if request.method in ["HEAD", "GET"]:
        return JSONResponse({"status": "OK"})

    try:
        data = await request.json()
        return await process_webhook(data, MAIN_TOKEN, is_main=True)
    except Exception as e:
        print(f"Main webhook error: {e}")
        return JSONResponse({"status": "OK"})

# ============== Webhook ربات‌های کاربر ==============
@app.api_route("/webhook/{path}", methods=["POST", "HEAD", "GET"])
async def user_bot_webhook(path: str, request: Request):
    if request.method in ["HEAD", "GET"]:
        return JSONResponse({"status": "OK"})

    try:
        with get_db() as conn:
            bot = conn.execute("SELECT * FROM bots WHERE path = ?", (path,)).fetchone()
        if not bot:
            return JSONResponse({"status": "OK"})

        data = await request.json()
        
        if "inline_message" in data:
            im = data["inline_message"]
            button_id = im.get("aux_data", {}).get("button_id")
            if button_id and button_id.startswith("custom_"):
                btn_text = button_id.replace("custom_", "")
                with get_db() as conn:
                    btn = conn.execute(
                        "SELECT response_text FROM buttons WHERE owner_id = ? AND button_text = ?",
                        (bot["owner_id"], btn_text)
                    ).fetchone()
                if btn:
                    chat_id = im.get("chat_id")
                    message_id = im.get("message_id")
                    edit_message(bot["token"], chat_id, message_id, btn["response_text"])
                    return JSONResponse({"status": "OK"})
        
        return await process_webhook(data, bot["token"], owner_id=bot["owner_id"], is_main=False)
    except Exception as e:
        print(f"User bot webhook error for {path}: {e}")
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
            res = api_with_curl(MAIN_TOKEN, "updateBotEndpoints", {"url": webhook_url, "type": ep})
            print(f"Main {ep}: {res}")
            time.sleep(3)
