# -*- coding: utf-8 -*-

import os
import io
import time
import requests
import threading

from flask import Flask, request

# ============================================================
# Safe Import for Telegram Module
# ============================================================
try:
    from telegram_client import handle_telegram_command, is_telegram_command
except Exception as e:
    print("ERROR IMPORTING TELEGRAM_CLIENT:", repr(e))
    def is_telegram_command(text):
        return bool(text and text.strip().startswith("/"))
    def handle_telegram_command(s_id, text, gemini_fn):
        return f"⚠️ وحدة التليجرام غير متوفرة حالياً.\nالسبب: {e}"

# ملاحظة: استيراد google.generativeai يتم بشكل كسول (lazy import)
genai = None
_genai_lock = threading.Lock()


def get_genai():
    """يستورد ويهيئ مكتبة google.generativeai عند أول حاجة فعلية لها فقط."""
    global genai
    if genai is None:
        with _genai_lock:
            if genai is None:
                import google.generativeai as _genai
                genai = _genai
    return genai


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

GEMINI_API_KEYS = [key for key in GEMINI_API_KEYS if key]

if not GEMINI_API_KEYS:
    raise RuntimeError("No Gemini API keys configured.")


# ============================================================
# Round-Robin State
# ============================================================

api_index = 0
api_lock = threading.Lock()


def get_next_api_key():
    global api_index
    with api_lock:
        key = GEMINI_API_KEYS[api_index]
        api_index = (api_index + 1) % len(GEMINI_API_KEYS)
        return key


# ============================================================
# Gemini Settings
# ============================================================

MEMORY_SECONDS = 3 * 60 * 60
MAX_MEMORY_MESSAGES = 30
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


# ============================================================
# Python Memory
# ============================================================

memory = {}


def clean_memory(sender_id):
    if sender_id not in memory:
        return

    now = time.time()
    valid_messages = []

    for item in memory[sender_id]:
        message_time = item.get("time", 0)
        if now - message_time <= MEMORY_SECONDS:
            valid_messages.append(item)

    memory[sender_id] = valid_messages[-MAX_MEMORY_MESSAGES:]

    if not memory[sender_id]:
        del memory[sender_id]


def add_to_memory(sender_id, role, text):
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
    return memory.get(sender_id, [])


# ============================================================
# Mime types that Gemini can read natively (inline_data)
# ============================================================

NATIVE_MIME_PREFIXES = (
    "image/",
    "audio/",
    "video/",
)

NATIVE_MIME_EXACT = {
    "application/pdf",
}

EXTENSION_MIME_MAP = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".mp4": "video/mp4",
}


def guess_extension_from_url(file_url):
    try:
        path = file_url.split("?")[0]
        for ext in EXTENSION_MIME_MAP:
            if path.lower().endswith(ext):
                return ext
    except Exception:
        pass
    return None


# ============================================================
# Download Any File
# ============================================================

def download_file(file_url):
    try:
        response = requests.get(file_url, timeout=30)
        if response.status_code != 200:
            print("FILE DOWNLOAD ERROR:", response.status_code)
            return None, None

        file_data = response.content
        if len(file_data) > MAX_FILE_SIZE:
            print("FILE TOO LARGE")
            return None, None

        mime_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()

        if not mime_type or mime_type == "application/octet-stream":
            ext = guess_extension_from_url(file_url)
            if ext:
                mime_type = EXTENSION_MIME_MAP[ext]
            else:
                mime_type = "application/octet-stream"

        return file_data, mime_type

    except Exception as e:
        print("FILE DOWNLOAD ERROR:", repr(e))
        return None, None


# ============================================================
# Extract Text From Office Documents
# ============================================================

def extract_text_from_docx(file_data):
    try:
        import docx
        doc = docx.Document(io.BytesIO(file_data))
        parts = [p.text for p in doc.paragraphs if p.text]
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text for cell in row.cells)
                if row_text.strip():
                    parts.append(row_text)
        return "\n".join(parts).strip()
    except Exception as e:
        print("DOCX EXTRACT ERROR:", repr(e))
        return None


def extract_text_from_pptx(file_data):
    try:
        from pptx import Presentation
        prs = Presentation(io.BytesIO(file_data))
        parts = []
        for i, slide in enumerate(prs.slides, start=1):
            slide_lines = ["-- Slide {} --".format(i)]
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        line = "".join(run.text for run in para.runs)
                        if line.strip():
                            slide_lines.append(line)
            parts.append("\n".join(slide_lines))
        return "\n\n".join(parts).strip()
    except Exception as e:
        print("PPTX EXTRACT ERROR:", repr(e))
        return None


def extract_text_from_xlsx(file_data):
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file_data), data_only=True)
        parts = []
        for sheet in wb.worksheets:
            parts.append("-- Sheet: {} --".format(sheet.title))
            for row in sheet.iter_rows(values_only=True):
                row_text = " | ".join("" if cell is None else str(cell) for cell in row)
                if row_text.strip(" |"):
                    parts.append(row_text)
        return "\n".join(parts).strip()
    except Exception as e:
        print("XLSX EXTRACT ERROR:", repr(e))
        return None


def extract_text_from_txt(file_data):
    try:
        return file_data.decode("utf-8", errors="ignore").strip()
    except Exception as e:
        print("TXT EXTRACT ERROR:", repr(e))
        return None


TEXT_EXTRACTORS = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": extract_text_from_docx,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": extract_text_from_pptx,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": extract_text_from_xlsx,
    "text/plain": extract_text_from_txt,
    "text/csv": extract_text_from_txt,
}


# ============================================================
# Process One Incoming Attachment
# ============================================================

def process_attachment(attachment):
    attach_type = attachment.get("type")
    if attach_type not in ("image", "audio", "video", "file"):
        return None

    payload = attachment.get("payload", {})
    file_url = payload.get("url")
    if not file_url:
        return None

    file_data, mime_type = download_file(file_url)
    if not file_data:
        return {
            "kind": "unsupported",
            "label": "تعذر تحميل الملف (قد يكون كبيرًا جدًا أو الرابط غير صالح)"
        }

    if mime_type in NATIVE_MIME_EXACT or mime_type.startswith(NATIVE_MIME_PREFIXES):
        return {
            "kind": "native",
            "data": file_data,
            "mime_type": mime_type
        }

    extractor = TEXT_EXTRACTORS.get(mime_type)
    if extractor:
        extracted = extractor(file_data)
        if extracted:
            return {
                "kind": "text",
                "text": extracted,
                "label": mime_type
            }
        return {
            "kind": "unsupported",
            "label": "تعذر استخراج محتوى الملف"
        }

    return {
        "kind": "unsupported",
        "label": "نوع الملف غير مدعوم حاليًا ({})".format(mime_type)
    }


# ============================================================
# Build Gemini Context
# ============================================================

def build_gemini_contents(sender_id, current_text=None, processed_attachments=None):
    processed_attachments = processed_attachments or []
    contents = []

    contents.append("""
أنت مساعد ذكي داخل Facebook Messenger.

القواعد:
- أجب باللغة التي يستخدمها المستخدم.
- استخدم المحادثة السابقة عندما تكون مفيدة.
- الذاكرة المتاحة آخر 3 ساعات فقط (نصوص فقط، بدون الملفات).
- إذا كانت هناك ملفات مرفقة حالياً (صورة، صوت، فيديو، PDF، أو نص مستخرج من Word/PowerPoint/Excel)، حلّلها كجزء من الرد.
- لا تدّعِ رؤية أو قراءة ملف سابق غير موجود الآن.
- إذا كان الملف غير مدعوم، اعتذر بوضوح واذكر السبب باختصار.
- اجعل الإجابة واضحة ومباشرة.
""")

    for item in get_memory(sender_id):
        role = item.get("role")
        text = item.get("text")
        if not text:
            continue
        if role == "user":
            contents.append("المستخدم:\n" + text)
        elif role == "model":
            contents.append("المساعد:\n" + text)

    if current_text:
        contents.append("المستخدم الآن:\n" + current_text)

    for item in processed_attachments:
        kind = item.get("kind")
        if kind == "native":
            contents.append({
                "mime_type": item["mime_type"],
                "data": item["data"]
            })
            contents.append("هذا ملف (mime: {}) أرسله المستخدم الآن. حلله مع السؤال الحالي.".format(item["mime_type"]))
        elif kind == "text":
            contents.append("محتوى نصي مستخرج من ملف أرسله المستخدم الآن ({}):\n{}".format(
                item.get("label", ""),
                item.get("text", "")[:15000]
            ))
        elif kind == "unsupported":
            contents.append("ملاحظة: المستخدم أرسل ملفًا لكن حدثت مشكلة: {}".format(item.get("label", "")))

    return contents


# ============================================================
# Gemini Request
# ============================================================

def generate_gemini_response(sender_id, user_text=None, processed_attachments=None):
    api_key = get_next_api_key()
    print("Gemini API key selected:", GEMINI_API_KEYS.index(api_key) + 1)

    try:
        gen_ai_module = get_genai()
        gen_ai_module.configure(api_key=api_key)
        model = gen_ai_module.GenerativeModel("gemini-2.5-flash")

        contents = build_gemini_contents(
            sender_id=sender_id,
            current_text=user_text,
            processed_attachments=processed_attachments
        )

        response = model.generate_content(contents)
        reply_text = getattr(response, "text", None)

        if not reply_text:
            return "عذراً، لم أتمكن من إنشاء رد."

        return reply_text.strip()

    except Exception as e:
        print("GEMINI ERROR:", repr(e))
        error_text = str(e).upper()
        if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text or "QUOTA" in error_text:
            return "تم الوصول إلى حد الطلبات حاليًا. يرجى الانتظار قليلًا ثم إعادة الرسالة."
        return "عذراً، حدث خطأ أثناء معالجة الطلب."


# ============================================================
# Facebook Send Message
# ============================================================

def send_facebook_message(recipient_id, text):
    if not text:
        return

    url = "https://graph.facebook.com/v20.0/me/messages"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    max_length = 2000

    chunks = [text[i:i + max_length] for i in range(0, len(text), max_length)]

    for chunk in chunks:
        payload = {
            "recipient": {"id": recipient_id},
            "messaging_type": "RESPONSE",
            "message": {"text": chunk}
        }
        try:
            response = requests.post(url, params=params, json=payload, timeout=20)
            print("FACEBOOK STATUS:", response.status_code)
            if response.status_code != 200:
                print("FACEBOOK ERROR:", response.text)
        except Exception as e:
            print("FACEBOOK SEND ERROR:", repr(e))


# ============================================================
# Home
# ============================================================

@app.route("/", methods=["GET"])
def home():
    return "Gemini Facebook Bot is Running!", 200


# ============================================================
# Webhook Verification
# ============================================================

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("WEBHOOK_VERIFIED")
        return challenge, 200

    return "Forbidden", 403


# ============================================================
# Facebook Webhook
# ============================================================

@app.route("/webhook", methods=["POST"])
def handle_messages():
    data = request.get_json(silent=True)
    if not data:
        return "Bad Request", 400

    if data.get("object") != "page":
        return "Not Found", 404

    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            message = event.get("message")
            if not message or message.get("is_echo"):
                continue

            sender = event.get("sender", {})
            sender_id = sender.get("id")
            if not sender_id:
                continue

            user_text = message.get("text", "")
            attachments = message.get("attachments", [])

            # ------------------------------------------------
            # 1. التثبت هل الرسالة أمر مخصص لـ Telegram؟
            # ------------------------------------------------
            if user_text and is_telegram_command(user_text):
                print("================================")
                print("SENDER:", sender_id)
                print("TELEGRAM COMMAND:", user_text)
                
                try:
                    tg_reply = handle_telegram_command(sender_id, user_text, generate_gemini_response)
                except Exception as err:
                    print("TELEGRAM EXECUTION ERROR:", repr(err))
                    tg_reply = f"❌ حدث خطأ أثناء تنفيذ الأمر: {err}"

                send_facebook_message(sender_id, tg_reply)
                continue  # منع وصول هذه الرسالة لـ Gemini تماماً

            # ------------------------------------------------
            # 2. معالجة المرفقات للـ Gemini
            # ------------------------------------------------
            processed_attachments = []
            attachment_summaries = []

            for attachment in attachments:
                result = process_attachment(attachment)
                if result is None:
                    continue

                processed_attachments.append(result)
                if result["kind"] == "native":
                    attachment_summaries.append(result["mime_type"])
                elif result["kind"] == "text":
                    attachment_summaries.append(result.get("label", "text file"))
                elif result["kind"] == "unsupported":
                    attachment_summaries.append("unsupported: " + result.get("label", ""))

            if not user_text and not processed_attachments:
                continue

            print("================================")
            print("SENDER:", sender_id)
            print("TEXT:", user_text)
            print("ATTACHMENTS:", attachment_summaries)

            clean_memory(sender_id)

            reply_text = generate_gemini_response(
                sender_id=sender_id,
                user_text=user_text,
                processed_attachments=processed_attachments
            )

            if user_text:
                add_to_memory(sender_id, "user", user_text)
            elif processed_attachments:
                add_to_memory(sender_id, "user", f"[أرسل المستخدم ملف/ملفات: {', '.join(attachment_summaries)}]")

            add_to_memory(sender_id, "model", reply_text)
            processed_attachments = None

            send_facebook_message(sender_id, reply_text)

    return "EVENT_RECEIVED", 200


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
        
