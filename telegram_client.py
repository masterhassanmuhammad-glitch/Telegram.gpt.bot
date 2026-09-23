# -*- coding: utf-8 -*-

import os
import asyncio
import threading
from pyrogram import Client
from pyrogram.enums import ChatType

# ============================================================
# Telegram Environment Variables
# ============================================================
TG_API_ID = int(os.getenv("TG_API_ID", "0"))
TG_API_HASH = os.getenv("TG_API_HASH", "")
TG_SESSION = os.getenv("TELEGRAM_SESSION", "")

# ============================================================
# Pyrogram TDLib Client Instance
# ============================================================
tg_app = None
loop = asyncio.new_event_loop()

if TG_API_ID and TG_API_HASH and TG_SESSION:
    tg_app = Client(
        "messenger_tdlib_session",
        api_id=TG_API_ID,
        api_hash=TG_API_HASH,
        session_string=TG_SESSION,
        in_memory=True
    )

    def start_telegram_loop():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(tg_app.start())
        loop.run_forever()

    threading.Thread(target=start_telegram_loop, daemon=True).start()


# ============================================================
# User Navigation State
# ============================================================
user_states = {}
PAGE_SIZE = 5


def get_user_state(sender_id):
    if sender_id not in user_states:
        user_states[sender_id] = {
            "state": "IDLE",
            "channels": [],
            "groups": [],
            "chats": [],
            "current_list": [],
            "current_chat_id": None,
            "current_page": 0
        }
    return user_states[sender_id]


def run_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


# ============================================================
# Async Telegram Helpers
# ============================================================
async def async_get_dialogs(dialog_type="channels"):
    items = []
    if not tg_app:
        return items
    async for dialog in tg_app.get_dialogs():
        chat = dialog.chat
        if dialog_type == "channels" and chat.type == ChatType.CHANNEL:
            items.append({"id": chat.id, "title": chat.title})
        elif dialog_type == "groups" and chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            items.append({"id": chat.id, "title": chat.title})
        elif dialog_type == "chats" and chat.type == ChatType.PRIVATE:
            items.append({
                "id": chat.id,
                "title": f"{chat.first_name or ''} {chat.last_name or ''}".strip() or chat.username or "محادثة"
            })
    return items


async def async_get_messages(chat_id, limit=20):
    messages = []
    if not tg_app:
        return messages
    async for msg in tg_app.get_chat_history(chat_id, limit=limit):
        text_content = msg.text or msg.caption or "[مرفق / وسائط]"
        messages.append({
            "id": msg.id,
            "text": text_content,
            "date": str(msg.date)
        })
    return messages


async def async_get_single_message(chat_id, message_id):
    if not tg_app:
        return ""
    msg = await tg_app.get_messages(chat_id, message_id)
    return msg.text or msg.caption or "[لا يوجد نص]"


async def async_search_messages(query):
    results = []
    if not tg_app:
        return results
    async for msg in tg_app.search_global(query, limit=10):
        results.append({
            "chat_title": msg.chat.title if msg.chat else "محادثة",
            "chat_id": msg.chat.id if msg.chat else None,
            "msg_id": msg.id,
            "text": msg.text or msg.caption or "محتوى غير نصي"
        })
    return results


# ============================================================
# Router Command Handlers
# ============================================================
def is_telegram_command(text):
    if not text:
        return False
    cmd = text.strip()
    
    # 1. أي نص يبدأ بـ / هو أمر تليجرام حصراً ولن يذهب لـ Gemini
    if cmd.startswith("/"):
        return True
    
    # 2. السماح بكتائبة رقم فقط للتنقل في القوائم (مثل 1 أو 2)
    if cmd.isdigit():
        return True
        
    # 3. الأوامر الكلاسيكية (اختياري)
    keywords = ["القنوات", "قنوات", "المجموعات", "مجموعات", "المحادثات", "محادثات", "التالي", "السابق"]
    if cmd.lower() in keywords or cmd.lower().startswith("فتح ") or cmd.lower().startswith("بحث "):
        return True

    return False


def handle_telegram_command(sender_id, text, gemini_response_fn):
    if not tg_app:
        return "⚠️ حساب Telegram غير مفعل. يرجى التأكد من ضبط متغيرات الجلسة (TELEGRAM_SESSION)."

    state = get_user_state(sender_id)
    raw_cmd = text.strip()
    
    # إزالة السلاش / لمعالجة الأمر
    cmd = raw_cmd[1:].strip() if raw_cmd.startswith("/") else raw_cmd
    cmd_lower = cmd.lower()

    # --- أمر المساعدة ---
    if cmd_lower in ["help", "مساعدة", "اوامر", "الأوامر"]:
        return (
            "🤖 **أوامر التحكم في Telegram:**\n\n"
            "🔹 `/channels` أو `/قنوات` - عرض القنوات\n"
            "🔹 `/groups` أو `/مجموعات` - عرض المجموعات\n"
            "🔹 `/chats` أو `/محادثات` - عرض المحادثات الخاصّة\n"
            "🔹 `/search <كلمة>` أو `/بحث <كلمة>` - البحث في التليجرام\n"
            "🔹 `/open <رقم>` أو `/فتح <رقم>` - قراءة وتحليل رسالة بـ Gemini\n"
            "🔹 `/next` أو `/التالي` - الصفحة التالية من الرسائل\n"
            "🔹 `/prev` أو `/السابق` - الصفحة السابقة من الرسائل\n"
            "🔹 أرسل **رقم فقط** (مثل: 1) لفتح العناصر"
        )

    # --- القنوات ---
    if cmd_lower in ["channels", "القنوات", "قنوات"]:
        channels = run_async(async_get_dialogs("channels"))
        state["channels"] = channels
        state["state"] = "VIEWING_CHANNELS"
        if not channels:
            return "📚 لم يتم العثور على قنوات في هذا الحساب."
        res = "📚 قنوات Telegram:\n\n"
        for idx, ch in enumerate(channels[:10], 1):
            res += f"{idx}️⃣ {ch['title']}\n"
        res += "\nأرسل رقم القناة للفتح (مثال: 1)"
        return res

    # --- المجموعات ---
    if cmd_lower in ["groups", "المجموعات", "مجموعات"]:
        groups = run_async(async_get_dialogs("groups"))
        state["groups"] = groups
        state["state"] = "VIEWING_GROUPS"
        if not groups:
            return "👥 لم يتم العثور على مجموعات."
        res = "👥 مجموعات Telegram:\n\n"
        for idx, grp in enumerate(groups[:10], 1):
            res += f"{idx}️⃣ {grp['title']}\n"
        res += "\nأرسل رقم المجموعة للفتح (مثال: 1)"
        return res

    # --- المحادثات ---
    if cmd_lower in ["chats", "المحادثات", "محادثات"]:
        chats = run_async(async_get_dialogs("chats"))
        state["chats"] = chats
        state["state"] = "VIEWING_CHATS"
        if not chats:
            return "📨 لا توجد محادثات خاصة."
        res = "📨 المحادثات الخاصة:\n\n"
        for idx, ch in enumerate(chats[:10], 1):
            res += f"{idx}️⃣ {ch['title']}\n"
        res += "\nأرسل رقم المحادثة للفتح (مثال: 1)"
        return res

    # --- اختيار من القائمة برقم ---
    if cmd.isdigit() and state["state"] in ["VIEWING_CHANNELS", "VIEWING_GROUPS", "VIEWING_CHATS"]:
        idx = int(cmd) - 1
        target = []
        if state["state"] == "VIEWING_CHANNELS":
            target = state["channels"]
        elif state["state"] == "VIEWING_GROUPS":
            target = state["groups"]
        elif state["state"] == "VIEWING_CHATS":
            target = state["chats"]

        if 0 <= idx < len(target):
            selected = target[idx]
            messages = run_async(async_get_messages(selected["id"], limit=20))
            state["current_chat_id"] = selected["id"]
            state["current_list"] = messages
            state["current_page"] = 0
            state["state"] = "VIEWING_MESSAGES"
            return format_messages_page(sender_id, selected["title"])
        return "❌ رقم غير صحيح."

    # --- التنقل (التالي / السابق) ---
    if cmd_lower in ["next", "التالي"] and state["state"] == "VIEWING_MESSAGES":
        state["current_page"] += 1
        return format_messages_page(sender_id)

    if cmd_lower in ["prev", "previous", "السابق"] and state["state"] == "VIEWING_MESSAGES":
        if state["current_page"] > 0:
            state["current_page"] -= 1
            return format_messages_page(sender_id)
        return "أنت في الصفحة الأولى بالفعل."

    # --- فتح رسالة وتحليلها بـ Gemini ---
    if (cmd_lower.startswith("open ") or cmd_lower.startswith("فتح ")) and state["state"] == "VIEWING_MESSAGES":
        try:
            parts = cmd.split(" ", 1)
            num = int(parts[1]) - 1
            msgs = state["current_list"]
            page = state["current_page"]
            real_idx = (page * PAGE_SIZE) + num

            if 0 <= real_idx < len(msgs):
                selected_msg = msgs[real_idx]
                full_text = run_async(async_get_single_message(state["current_chat_id"], selected_msg["id"]))
                
                # تحليل النص الجاهز عبر Gemini
                prompt = f"قم بتحليل وتلخيص النص التالي المستخرج من Telegram بشكل دقيق ومباشر:\n\n{full_text}"
                ai_summary = gemini_response_fn(sender_id, user_text=prompt)
                
                return f"📖 النص الأصلي من Telegram:\n\n{full_text}\n\n💡 تحليل Gemini:\n\n{ai_summary}"
            return "❌ رقم الرسالة غير موجود."
        except Exception:
            return "❌ الاستخدام الصحيح: `/open 1` أو `/فتح 1`"

    # --- البحث في Telegram ---
    if cmd_lower.startswith("search ") or cmd_lower.startswith("بحث "):
        parts = cmd.split(" ", 1)
        q = parts[1].strip() if len(parts) > 1 else ""
        if not q:
            return "❌ يرجى كتابة كلمة للبحث، مثال: `/search pathology` أو `/بحث محاضرات`"
        results = run_async(async_search_messages(q))
        if not results:
            return f"🔎 لم يتم العثور على نتائج للبحث عن: {q}"
        res = f"🔎 نتائج البحث عن ({q}):\n\n"
        for idx, item in enumerate(results[:5], 1):
            res += f"{idx}. [{item['chat_title']}]: {item['text'][:60]}...\n\n"
        return res

    # إذا كانت الرسالة تبدأ بـ / ولكن لم تطابق أي أمر معروف
    if raw_cmd.startswith("/"):
        return f"❌ الأمر `{raw_cmd}` غير معروف.\n\nأرسل `/help` أو `/أوامر` للتعرف على الأوامر المتاحة."

    return None


def format_messages_page(sender_id, title="المحادثة"):
    state = get_user_state(sender_id)
    msgs = state["current_list"]
    page = state["current_page"]
    start_i = page * PAGE_SIZE
    end_i = start_i + PAGE_SIZE
    page_msgs = msgs[start_i:end_i]

    if not page_msgs:
        return "📭 لا توجد رسائل إضافية."

    res = f"📚 {title} (صفحة {page + 1}):\n\n"
    for idx, m in enumerate(page_msgs, 1):
        prev = m['text'][:50].replace('\n', ' ')
        res += f"{idx}. {prev}\n"
    res += "\nأرسل:\n- `/open 1` أو `/فتح 1`\n- `/next` أو `/التالي`\n- `/prev` أو `/السابق`"
    return res
        
