import os
import requests
from flask import Flask, request, jsonify
from google import genai

app = Flask(__name__)

# جلب المتغيرات البيئية من Render
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# تهيئة العميل الخاص بـ Gemini API
client = genai.Client(api_key=GEMINI_API_KEY)

@app.route("/", methods=["GET"])
def home():
    return "WhatsApp Gemini Bot is active!"

# 1. نقطة التحقق لـ Webhook (تطلبها Meta عند الربط)
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        return "Forbidden", 403
    return "Bad Request", 400

# 2. استقبال رسائل واتساب والمعالجة (POST)
@app.route("/webhook", methods=["POST"])
def receive_message():
    data = request.get_json()

    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if messages:
            msg = messages[0]
            from_number = msg.get("from")  # رقم المستخدم
            text_body = msg.get("text", {}).get("body")  # نص الرسالة

            if text_body:
                # توليد الرد باستخدام Gemini
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=text_body,
                )
                reply_text = response.text

                # إرسال الرد إلى واتساب
                send_whatsapp_message(from_number, reply_text)

    except Exception as e:
        print(f"Error processing message: {e}")

    return jsonify({"status": "success"}), 200

def send_whatsapp_message(to_number, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text}
    }
    requests.post(url, json=payload, headers=headers)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
