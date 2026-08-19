import os
import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

# ====================== تنظیمات ======================
TOKEN = os.getenv("RUBIKA_TOKEN")          # توکن ربات (از Railway می‌گیری)
BASE_URL = os.getenv("BASE_URL", "")       # آدرس عمومی Railway (اختیاری)

if not TOKEN:
    raise ValueError("متغیر محیطی RUBIKA_TOKEN تنظیم نشده!")

API = f"https://botapi.rubika.ir/v3/{TOKEN}"

app = FastAPI()

# ====================== توابع کمکی ======================
def send_message(chat_id: str, text: str, inline_keypad: dict = None):
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    if inline_keypad:
        payload["inline_keypad"] = inline_keypad

    r = requests.post(f"{API}/sendMessage", json=payload, timeout=10)
    return r.json()


def make_glass_buttons():
    """ساخت دکمه‌های شیشه‌ای نمونه"""
    return {
        "rows": [
            {
                "buttons": [
                    {"id": "btn_yes", "type": "Simple", "button_text": "✅ بله"}
                ]
            },
            {
                "buttons": [
                    {"id": "btn_no", "type": "Simple", "button_text": "❌ خیر"},
                    {"id": "btn_maybe", "type": "Simple", "button_text": "🤔 شاید"}
                ]
            },
            {
                "buttons": [
                    {"id": "btn_info", "type": "Simple", "button_text": "ℹ️ اطلاعات بیشتر"}
                ]
            }
        ]
    }


# ====================== Webhook ها ======================
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    print("دریافت شد:", data)  # برای لاگ در Railway

    # ---------- کلیک روی دکمه شیشه‌ای ----------
    if "inline_message" in data:
        inline = data["inline_message"]
        chat_id = inline.get("chat_id")
        button_id = inline.get("aux_data", {}).get("button_id")

        if button_id == "btn_yes":
            send_message(chat_id, "عالی! شما گزینه «بله» رو انتخاب کردید 🎉")
        elif button_id == "btn_no":
            send_message(chat_id, "باشه، گزینه «خیر» ثبت شد.")
        elif button_id == "btn_maybe":
            send_message(chat_id, "باشه، فعلاً «شاید» رو انتخاب کردید.")
        elif button_id == "btn_info":
            send_message(chat_id, "دنبال چه میگگردی؟")
        else:
            send_message(chat_id, f"دکمه ناشناخته: {button_id}")

        return JSONResponse({"status": "OK"})

    # ---------- پیام جدید (Update) ----------
    if "update" in data:
        update = data["update"]
        if update.get("type") == "NewMessage":
            msg = update.get("new_message", {})
            chat_id = update.get("chat_id")
            text = msg.get("text", "").strip()

            # اگر دکمه chat keypad بود
            button_id = msg.get("aux_data", {}).get("button_id")
            if button_id:
                send_message(chat_id, f"روی دکمه چت کلیک شد: {button_id}")
                return JSONResponse({"status": "OK"})

            # پیام عادی
            if text.lower() in ["/start", "start", "شروع"]:
                send_message(
                    chat_id,
                    "سلام! 👋\nاین یک ربات تست دکمه‌های شیشه‌ای است.\nروی یکی از دکمه‌های زیر کلیک کن:",
                    inline_keypad=make_glass_buttons()
                )
            else:
                send_message(
                    chat_id,
                    f"پیام شما: {text}\n\nبرای دیدن دکمه‌های شیشه‌ای، /start بزنید.",
                    inline_keypad=make_glass_buttons()
                )

    return JSONResponse({"status": "OK"})


@app.get("/")
async def home():
    return {
        "status": "ربات روبیکا با دکمه‌های شیشه‌ای فعال است",
        "token_set": bool(TOKEN),
        "base_url": BASE_URL or "تنظیم نشده"
    }


# ====================== ثبت خودکار Endpoint (اختیاری) ======================
def register_endpoints(base_url: str):
    """این تابع endpointها را در روبیکا ثبت می‌کند"""
    endpoints = [
        "ReceiveUpdate",
        "ReceiveInlineMessage",
        "ReceiveQuery",
        "GetSelectionItem",
        "SearchSelectionItems"
    ]
    webhook_url = f"{base_url.rstrip('/')}/webhook"

    print(f"در حال ثبت endpointها روی: {webhook_url}")
    for ep in endpoints:
        try:
            r = requests.post(
                f"{API}/updateBotEndpoints",
                json={"url": webhook_url, "type": ep},
                timeout=15
            )
            print(f"  {ep}: {r.status_code} → {r.text[:100]}")
        except Exception as e:
            print(f"  خطا در {ep}: {e}")


if __name__ == "__main__":
    # اگر BASE_URL تنظیم شده باشد، endpointها را ثبت می‌کند
    if BASE_URL:
        register_endpoints(BASE_URL)

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
