# -*- coding: utf-8 -*-

import os
import time
import requests

from flask import Flask, request
import google.generativeai as genai


# ============================================================
# Flask Application
# ============================================================

app = Flask(__name__)


# ============================================================
# Environment Variables - Render
# ============================================================

PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


# ============================================================
# Settings
# ============================================================

# مدة الذاكرة: 3 ساعات
MEMORY_SECONDS = 3 * 60 * 60

# أقصى عدد رسائل محفوظة لكل مستخدم
MAX_MEMORY_MESSAGES = 30

# أقصى حجم للصورة
MAX_IMAGE_SIZE = 10 * 1024 * 1024


# ============================================================
# Gemini
# ============================================================

genai.configure(
    api_key=GEMINI_API_KEY
)

model = genai.GenerativeModel(
    "gemini-3.7-flash"
)


# ============================================================
# In-Memory Storage
#
# يتم حفظ النصوص والردود فقط.
# الصور لا يتم حفظها.
#
# memory = {
#     "USER_ID": [
#         {
#             "role": "user",
#             "text": "مرحبا",
#             "time": 1234567890
#         },
#         {
#             "role": "model",
#             "text": "مرحبا بك",
#             "time": 1234567891
#         }
#     ]
# }
# ============================================================

memory = {}


# ============================================================
# Clean Old Memory
# ============================================================

def clean_memory(sender_id):

    if sender_id not in memory:
        return

    now = time.time()

    valid_messages = []

    for item in memory[sender_id]:

        message_time = item.get("time", 0)

        # الاحتفاظ بالرسائل التي لم تتجاوز 3 ساعات
        if now - message_time <= MEMORY_SECONDS:
            valid_messages.append(item)

    # الاحتفاظ بآخر 30 رسالة فقط
    memory[sender_id] = valid_messages[
        -MAX_MEMORY_MESSAGES:
    ]

    # حذف المستخدم إذا لم تعد لديه ذاكرة
    if not memory[sender_id]:

        del memory[sender_id]


# ============================================================
# Add Text Message to Memory
# ============================================================

def add_to_memory(
    sender_id,
    role,
    text
):

    if not text:
        return

    if sender_id not in memory:

        memory[sender_id] = []

    memory[sender_id].append({

        "role": role,

        "text": text,

        "time": time.time()

    })

    clean_memory(sender_id)


# ============================================================
# Get Recent Memory
# ============================================================

def get_memory(sender_id):

    clean_memory(sender_id)

    return memory.get(
        sender_id,
        []
    )


# ============================================================
# Download Facebook Image
#
# الصورة تستخدم فقط أثناء الطلب
# ولا يتم حفظها في memory
# ============================================================

def download_image(image_url):

    try:

        response = requests.get(
            image_url,
            timeout=20
        )

        if response.status_code != 200:

            print(
                "IMAGE DOWNLOAD ERROR:",
                response.status_code
            )

            return None, None

        image_data = response.content

        # منع الصور الكبيرة جدًا
        if len(image_data) > MAX_IMAGE_SIZE:

            print(
                "IMAGE TOO LARGE:",
                len(image_data)
            )

            return None, None

        content_type = response.headers.get(
            "Content-Type",
            "image/jpeg"
        )

        # التأكد من أن الملف صورة
        if not content_type.startswith(
            "image/"
        ):

            print(
                "INVALID IMAGE TYPE:",
                content_type
            )

            return None, None

        return (
            image_data,
            content_type
        )

    except Exception as e:

        print(
            "IMAGE DOWNLOAD ERROR:",
            repr(e)
        )

        return None, None


# ============================================================
# Build Gemini Conversation
# ============================================================

def build_gemini_contents(
    sender_id,
    current_text=None,
    current_image=None,
    current_mime_type=None
):

    contents = []

    # --------------------------------------------------------
    # تعليمات Gemini
    # --------------------------------------------------------

    contents.append(
        """
أنت مساعد ذكي داخل Facebook Messenger.

القواعد:

- أجب باللغة التي يستخدمها المستخدم.
- استخدم المحادثة السابقة عندما تكون مفيدة للسؤال الحالي.
- الذاكرة المتاحة هي آخر 3 ساعات فقط.
- الصور لا يتم الاحتفاظ بها بعد انتهاء معالجة الرسالة.
- إذا كانت الرسالة الحالية تحتوي على صورة، حلل الصورة الحالية فقط.
- لا تدّعي رؤية صورة لم يتم إرسالها في الرسالة الحالية.
- إذا سأل المستخدم عن صورة سابقة، استخدم فقط المعلومات النصية
  التي تم حفظها من الرد السابق.
- اجعل الإجابة واضحة ومباشرة.
"""
    )

    # --------------------------------------------------------
    # Previous Text Messages
    # --------------------------------------------------------

    recent_memory = get_memory(
        sender_id
    )

    for item in recent_memory:

        role = item.get(
            "role"
        )

        text = item.get(
            "text"
        )

        if not text:
            continue

        if role == "user":

            contents.append(
                "المستخدم:\n" + text
            )

        elif role == "model":

            contents.append(
                "المساعد:\n" + text
            )

    # --------------------------------------------------------
    # Current Text
    # --------------------------------------------------------

    if current_text:

        contents.append(
            "المستخدم الآن:\n"
            + current_text
        )

    # --------------------------------------------------------
    # Current Image
    #
    # الصورة الحالية فقط يتم إرسالها.
    # لا تدخل إلى memory.
    # --------------------------------------------------------

    if current_image:

        contents.append({

            "mime_type":
                current_mime_type
                or "image/jpeg",

            "data":
                current_image

        })

        contents.append(
            "هذه صورة أرسلها المستخدم الآن. "
            "حلل الصورة الحالية مع السؤال إن وجد."
        )

    return contents


# ============================================================
# Generate Gemini Response
# ============================================================

def generate_gemini_response(
    sender_id,
    user_text=None,
    image_data=None,
    mime_type=None
):

    try:

        contents = build_gemini_contents(

            sender_id=sender_id,

            current_text=user_text,

            current_image=image_data,

            current_mime_type=mime_type

        )

        response = model.generate_content(
            contents
        )

        reply_text = getattr(
            response,
            "text",
            None
        )

        if not reply_text:

            reply_text = (
                "عذراً، لم أتمكن من إنشاء رد."
            )

        return reply_text.strip()

    except Exception as e:

        print(
            "GEMINI ERROR:",
            repr(e)
        )

        error_text = str(e).upper()

        # ----------------------------------------------------
        # Rate Limit / Quota
        # ----------------------------------------------------

        if (
            "429" in error_text
            or "RESOURCE_EXHAUSTED" in error_text
            or "QUOTA" in error_text
        ):

            return (
                "تم الوصول إلى حد الطلبات في الوقت الحالي. "
                "يرجى الانتظار قليلًا ثم إعادة الرسالة."
            )

        # ----------------------------------------------------
        # Other Gemini errors
        # ----------------------------------------------------

        return (
            "عذراً، حدث خطأ أثناء معالجة طلبك."
        )


# ============================================================
# Send Text Message to Facebook
# ============================================================

def send_facebook_message(
    recipient_id,
    text
):

    if not text:

        return

    url = (
        "https://graph.facebook.com/v20.0/me/messages"
    )

    params = {

        "access_token":
            PAGE_ACCESS_TOKEN

    }

    # تقسيم الرد الطويل
    max_length = 2000

    chunks = [

        text[i:i + max_length]

        for i in range(
            0,
            len(text),
            max_length
        )

    ]

    for chunk in chunks:

        payload = {

            "recipient": {

                "id":
                    recipient_id

            },

            "messaging_type":
                "RESPONSE",

            "message": {

                "text":
                    chunk

            }

        }

        try:

            response = requests.post(

                url,

                params=params,

                json=payload,

                timeout=20

            )

            print(
                "FACEBOOK STATUS:",
                response.status_code
            )

            if response.status_code != 200:

                print(
                    "FACEBOOK ERROR:",
                    response.text
                )

        except Exception as e:

            print(
                "FACEBOOK SEND ERROR:",
                repr(e)
            )


# ============================================================
# Home Route
# ============================================================

@app.route(
    "/",
    methods=["GET"]
)
def home():

    return (
        "Gemini Facebook Bot is Running!",
        200
    )


# ============================================================
# Facebook Webhook Verification
# ============================================================

@app.route(
    "/webhook",
    methods=["GET"]
)
def verify_webhook():

    mode = request.args.get(
        "hub.mode"
    )

    token = request.args.get(
        "hub.verify_token"
    )

    challenge = request.args.get(
        "hub.challenge"
    )

    if (
        mode == "subscribe"
        and token == VERIFY_TOKEN
    ):

        print(
            "WEBHOOK_VERIFIED"
        )

        return challenge, 200

    return (
        "Forbidden",
        403
    )


# ============================================================
# Facebook Webhook
# ============================================================

@app.route(
    "/webhook",
    methods=["POST"]
)
def handle_messages():

    data = request.get_json(
        silent=True
    )

    if not data:

        return (
            "Bad Request",
            400
        )

    # --------------------------------------------------------
    # التأكد أن الحدث من Facebook Page
    # --------------------------------------------------------

    if data.get("object") != "page":

        return (
            "Not Found",
            404
        )

    # --------------------------------------------------------
    # Process Entries
    # --------------------------------------------------------

    for entry in data.get(
        "entry",
        []
    ):

        for messaging_event in entry.get(
            "messaging",
            []
        ):

            # ------------------------------------------------
            # Message
            # ------------------------------------------------

            message = messaging_event.get(
                "message"
            )

            if not message:

                continue

            # تجاهل رسائل البوت نفسه
            if message.get(
                "is_echo"
            ):

                continue

            # ------------------------------------------------
            # Sender
            # ------------------------------------------------

            sender = messaging_event.get(
                "sender",
                {}
            )

            sender_id = sender.get(
                "id"
            )

            if not sender_id:

                continue

            # ------------------------------------------------
            # Text
            # ------------------------------------------------

            user_text = message.get(
                "text"
            )

            # ------------------------------------------------
            # Attachments
            # ------------------------------------------------

            attachments = message.get(
                "attachments",
                []
            )

            image_data = None

            image_mime_type = None

            # ------------------------------------------------
            # Find Current Image
            # ------------------------------------------------

            for attachment in attachments:

                attachment_type = attachment.get(
                    "type"
                )

                if attachment_type != "image":

                    continue

                payload = attachment.get(
                    "payload",
                    {}
                )

                image_url = payload.get(
                    "url"
                )

                if not image_url:

                    continue

                print(
                    "IMAGE RECEIVED"
                )

                # تحميل الصورة مؤقتًا
                image_data, image_mime_type = (
                    download_image(
                        image_url
                    )
                )

                break

            # ------------------------------------------------
            # Ignore Unsupported Events
            # ------------------------------------------------

            if (
                not user_text
                and not image_data
            ):

                continue

            print(
                "================================"
            )

            print(
                "SENDER:",
                sender_id
            )

            print(
                "TEXT:",
                user_text
            )

            print(
                "IMAGE:",
                bool(image_data)
            )

            # ------------------------------------------------
            # Clean old memory
            # ------------------------------------------------

            clean_memory(
                sender_id
            )

            # ------------------------------------------------
            # Generate Gemini Response
            # ------------------------------------------------

            reply_text = generate_gemini_response(

                sender_id=sender_id,

                user_text=user_text,

                image_data=image_data,

                mime_type=image_mime_type

            )

            # ------------------------------------------------
            # IMPORTANT:
            #
            # الصورة لا يتم حفظها.
            #
            # فقط النص الذي كتبه المستخدم والرد
            # من Gemini يتم حفظهما.
            # ------------------------------------------------

            if user_text:

                add_to_memory(

                    sender_id=sender_id,

                    role="user",

                    text=user_text

                )

            elif image_data:

                # إذا أرسل صورة بدون نص
                # نحفظ وصفًا نصيًا فقط بدل الصورة

                add_to_memory(

                    sender_id=sender_id,

                    role="user",

                    text="[أرسل المستخدم صورة]"

                )

            # ------------------------------------------------
            # Save Gemini Response
            # ------------------------------------------------

            add_to_memory(

                sender_id=sender_id,

                role="model",

                text=reply_text

            )

            # ------------------------------------------------
            # Delete image reference
            #
            # حتى لا تبقى في الذاكرة
            # بعد انتهاء المعالجة.
            # ------------------------------------------------

            image_data = None
            image_mime_type = None

            # ------------------------------------------------
            # Send Response
            # ------------------------------------------------

            send_facebook_message(

                sender_id,

                reply_text

            )

    return (
        "EVENT_RECEIVED",
        200
    )


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(

        host="0.0.0.0",

        port=port

    )
