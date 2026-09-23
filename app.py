# -*- coding: utf-8 -*-

import os
import time
import requests
import threading

from flask import Flask, request
import google.generativeai as genai


# ============================================================
# Flask
# ============================================================

app = Flask(__name__)


# ============================================================
# Facebook Environment Variables
# ============================================================

PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")


# ============================================================
# Gemini API Keys
# ============================================================

GEMINI_API_KEYS = [
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3"),
    os.getenv("GEMINI_API_KEY_4"),
    os.getenv("GEMINI_API_KEY_5")
]

# إزالة المفاتيح غير الموجودة
GEMINI_API_KEYS = [
    key for key in GEMINI_API_KEYS
    if key
]


if not GEMINI_API_KEYS:

    raise RuntimeError(
        "No Gemini API keys configured."
    )


# ============================================================
# Round-Robin State
# ============================================================

api_index = 0

api_lock = threading.Lock()


def get_next_api_key():

    global api_index

    with api_lock:

        key = GEMINI_API_KEYS[api_index]

        api_index = (
            api_index + 1
        ) % len(GEMINI_API_KEYS)

        return key


# ============================================================
# Gemini Settings
# ============================================================

MEMORY_SECONDS = 3 * 60 * 60

MAX_MEMORY_MESSAGES = 30

MAX_IMAGE_SIZE = 10 * 1024 * 1024


# ============================================================
# Python Memory
# ============================================================

memory = {}


# ============================================================
# Memory
# ============================================================

def clean_memory(sender_id):

    if sender_id not in memory:
        return

    now = time.time()

    valid_messages = []

    for item in memory[sender_id]:

        message_time = item.get(
            "time",
            0
        )

        if (
            now - message_time
            <= MEMORY_SECONDS
        ):

            valid_messages.append(item)

    memory[sender_id] = (
        valid_messages[
            -MAX_MEMORY_MESSAGES:
        ]
    )

    if not memory[sender_id]:

        del memory[sender_id]


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


def get_memory(sender_id):

    clean_memory(sender_id)

    return memory.get(
        sender_id,
        []
    )


# ============================================================
# Download Image
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

        if len(image_data) > MAX_IMAGE_SIZE:

            print(
                "IMAGE TOO LARGE"
            )

            return None, None

        mime_type = response.headers.get(
            "Content-Type",
            "image/jpeg"
        )

        if not mime_type.startswith(
            "image/"
        ):

            mime_type = "image/jpeg"

        return (
            image_data,
            mime_type
        )

    except Exception as e:

        print(
            "IMAGE DOWNLOAD ERROR:",
            repr(e)
        )

        return None, None


# ============================================================
# Build Gemini Context
# ============================================================

def build_gemini_contents(
    sender_id,
    current_text=None,
    current_image=None,
    current_mime_type=None
):

    contents = []

    contents.append(
        """
أنت مساعد ذكي داخل Facebook Messenger.

القواعد:

- أجب باللغة التي يستخدمها المستخدم.
- استخدم المحادثة السابقة عندما تكون مفيدة.
- الذاكرة المتاحة آخر 3 ساعات فقط.
- الصور لا يتم حفظها في الذاكرة.
- إذا كانت هناك صورة حالية، حلل الصورة الحالية فقط.
- لا تدّعي رؤية صورة سابقة.
- يمكن استخدام المعلومات النصية المحفوظة عن صورة سابقة.
- اجعل الإجابة واضحة ومباشرة.
"""
    )

    # --------------------------------------------------------
    # Previous text memory
    # --------------------------------------------------------

    for item in get_memory(sender_id):

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
                "المستخدم:\n"
                + text
            )

        elif role == "model":

            contents.append(
                "المساعد:\n"
                + text
            )

    # --------------------------------------------------------
    # Current text
    # --------------------------------------------------------

    if current_text:

        contents.append(
            "المستخدم الآن:\n"
            + current_text
        )

    # --------------------------------------------------------
    # Current image
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
            "حللها مع السؤال الحالي."
        )

    return contents


# ============================================================
# Gemini Request
# ============================================================

def generate_gemini_response(
    sender_id,
    user_text=None,
    image_data=None,
    mime_type=None
):

    api_key = get_next_api_key()

    print(
        "Gemini API key selected:",
        GEMINI_API_KEYS.index(api_key) + 1
    )

    try:

        # تهيئة Gemini بالمفتاح المختار
        genai.configure(
            api_key=api_key
        )

        model = genai.GenerativeModel(
            "gemini-3.5-flash-lite"
        )

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

            return (
                "عذراً، لم أتمكن من إنشاء رد."
            )

        return reply_text.strip()

    except Exception as e:

        print(
            "GEMINI ERROR:",
            repr(e)
        )

        error_text = str(e).upper()

        if (
            "429" in error_text
            or "RESOURCE_EXHAUSTED"
            in error_text
            or "QUOTA"
            in error_text
        ):

            return (
                "تم الوصول إلى حد الطلبات "
                "حاليًا. يرجى الانتظار قليلًا "
                "ثم إعادة الرسالة."
            )

        return (
            "عذراً، حدث خطأ أثناء معالجة الطلب."
        )


# ============================================================
# Facebook Send Message
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
# Home
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
# Webhook Verification
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

    if data.get(
        "object"
    ) != "page":

        return (
            "Not Found",
            404
        )

    for entry in data.get(
        "entry",
        []
    ):

        for event in entry.get(
            "messaging",
            []
        ):

            message = event.get(
                "message"
            )

            if not message:

                continue

            if message.get(
                "is_echo"
            ):

                continue

            sender = event.get(
                "sender",
                {}
            )

            sender_id = sender.get(
                "id"
            )

            if not sender_id:

                continue

            user_text = message.get(
                "text"
            )

            attachments = message.get(
                "attachments",
                []
            )

            image_data = None

            image_mime_type = None

            # ------------------------------------------------
            # Current image
            # ------------------------------------------------

            for attachment in attachments:

                if attachment.get(
                    "type"
                ) != "image":

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

                (
                    image_data,
                    image_mime_type
                ) = download_image(
                    image_url
                )

                break

            # ------------------------------------------------
            # Ignore empty events
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
            # Clean memory
            # ------------------------------------------------

            clean_memory(
                sender_id
            )

            # ------------------------------------------------
            # Gemini
            # ------------------------------------------------

            reply_text = generate_gemini_response(

                sender_id=sender_id,

                user_text=user_text,

                image_data=image_data,

                mime_type=image_mime_type

            )

            # ------------------------------------------------
            # Save user text only
            # ------------------------------------------------

            if user_text:

                add_to_memory(

                    sender_id,

                    "user",

                    user_text

                )

            elif image_data:

                add_to_memory(

                    sender_id,

                    "user",

                    "[أرسل المستخدم صورة]"

                )

            # ------------------------------------------------
            # Save Gemini response
            # ------------------------------------------------

            add_to_memory(

                sender_id,

                "model",

                reply_text

            )

            # ------------------------------------------------
            # Delete image from Python variable
            # ------------------------------------------------

            image_data = None

            image_mime_type = None

            # ------------------------------------------------
            # Send reply
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
