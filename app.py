import os
import requests
from flask import Flask, request, jsonify
import google.generativeai as genai

app = Flask(__name__)

# جلب المتغيرات من إعدادات البيئة في Render
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# إعداد نموذج Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

@app.route('/', methods=['GET'])
def home():
    return "Gemini Facebook Bot is Running!", 200

# 1. التحقق من الـ Webhook عند ربطه بفيسبوك
@app.route('/webhook', methods=['GET'])
def verify_webhook():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')

    if mode and token:
        if mode == 'subscribe' and token == VERIFY_TOKEN:
            print("WEBHOOK_VERIFIED")
            return challenge, 200
        else:
            return 'Forbidden', 403
    return 'Bad Request', 400

# 2. استقبال الرسائل من فيسبوك والرد عليها بـ Gemini
@app.route('/webhook', methods=['POST'])
def handle_messages():
    data = request.get_json()

    if data.get('object') == 'page':
        for entry in data.get('entry', []):
            for messaging_event in entry.get('messaging', []):
                # التأكد من أن الحدث هو رسالة نصية واردة
                if messaging_event.get('message') and not messaging_event['message'].get('is_echo'):
                    sender_id = messaging_event['sender']['id']
                    user_message = messaging_event['message'].get('text')

                    if user_message:
                        try:
                            # توليد الرد من Gemini
                            response = model.generate_content(user_message)
                            reply_text = response.text
                        except Exception as e:
                            print(f"Gemini API Error: {e}")
                            reply_text = "عذراً، حدث خطأ أثناء معالجة طلبك."

                        # إرسال الرد للفيسبوك
                        send_facebook_message(sender_id, reply_text)

        return 'EVENT_RECEIVED', 200
    return 'Not Found', 404

def send_facebook_message(recipient_id, text):
    url = f"https://graph.facebook.com/v20.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "messaging_type": "RESPONSE",
        "message": {"text": text}
    }
    headers = {"Content-Type": "application/json"}
    requests.post(url, json=payload, headers=headers)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
    
