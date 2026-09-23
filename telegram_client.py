# -*- coding: utf-8 -*-

import os
import sys
import asyncio
import inspect
import threading

def log(msg):
    print(msg, flush=True)

log("⚡ Loading telegram_client.py module...")

raw_api_id = os.getenv("TG_API_ID", "0").strip()
TG_API_ID = int(raw_api_id) if raw_api_id.isdigit() else 0
TG_API_HASH = os.getenv("TG_API_HASH", "").strip().strip("'").strip('"')
TG_SESSION = os.getenv("TELEGRAM_SESSION", "").strip().strip("'").strip('"')

tg_app = None
loop = None
telegram_ready = False
telegram_error = ""


def run_telegram_worker():
    global tg_app, loop, telegram_ready, telegram_error

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    _original_wait = asyncio.wait
    async def _patched_wait(fs, *args, **kwargs):
        cleaned_fs = set()
        for f in fs:
            if inspect.iscoroutine(f):
                cleaned_fs.add(loop.create_task(f))
            else:
                cleaned_fs.add(f)
        return await _original_wait(cleaned_fs, *args, **kwargs)
    asyncio.wait = _patched_wait

    try:
        from pyrogram import Client

        log("🚀 Initializing Pyrogram Client inside worker thread...")
        
        tg_app = Client(
            "messenger_tdlib_session",
            api_id=TG_API_ID,
            api_hash=TG_API_HASH,
            session_string=TG_SESSION,
            in_memory=True
        )

        async def main_async():
            global telegram_ready
            await tg_app.start()
            telegram_ready = True
            log("✅ TELEGRAM CLIENT CONNECTED SUCCESSFULLY!")

        loop.run_until_complete(main_async())
        loop.run_forever()

    except Exception as e:
        telegram_ready = False
        telegram_error = str(e)
        log(f"❌ TELEGRAM WORKER ERROR: {repr(e)}")


if TG_API_ID and TG_API_HASH and TG_SESSION:
    threading.Thread(target=run_telegram_worker, daemon=True).start()
else:
    telegram_error = "متغيرات البيئة غير مكتملة."
    log(f"⚠️ {telegram_error}")

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
    if not tg_app or not loop or not loop.is_running() or not telegram_ready:
        if inspect.iscoroutine(coro):
            try:
                coro.close()
            except Exception:
                pass
        err_msg = telegram_error if telegram_error else "جاري الاتصال بتليجرام..."
        raise RuntimeError(f"حساب Telegram غير متصل. السبب: {err_msg}")
    try:
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=15)
    except Exception as e:
        if inspect.iscoroutine(coro):
            try:
                coro.close()
            except Exception:
                pass
        raise e


async def async_get_dialogs(dialog_type="channels"):
    items = []
    if not tg_app:
        return items
    from pyrogram.enums import ChatType
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
    try:
        async for msg in tg_app.get_chat_history(chat_id, limit=limit):
            text_content = "[مرفق / وسائط]"
            # معالجة آمنة للنص لتفادي أخطاء فك التشفير UTF-16
            try:
                raw_text = msg.text or msg.caption
                if raw_text:
                    text_content = str(raw_text)
            except Exception:
                text_content = "[نص غير قابل للقراءة أو يضم رموزاً خاصة]"

            # تنظيف النص من الأحرف المكسورة
            text_content = text_content.encode("utf-8", "ignore").decode("utf-8")

            messages.append({
                "id": msg.id,
                "text": text_content,
                "date": str(msg.date)
            })
    except Exception as e:
        log(f"⚠️ Error fetching chat history: {e}")

    return messages


async def async_get_single_message(chat_id, message_id):
    if not tg_app:
        return ""
    try:
        msg = await tg_app.get_messages(chat_id, message_id)
        if not msg:
            return "[الرسالة غير موجودة]"
        try:
            raw_text = msg.text or msg.caption or "[لا يوجد نص]"
            return str(raw_text).encode("utf-8", "ignore").decode("utf-8")
        except Exception:
            return "[نص يحتوي على رموز تعذر فك شفرتها]"
    except Exception as e:
        return f"[خطأ في جلب الرسالة: {e}]"


async def async_search_messages(query):
    results = []
    if not tg_app:
        return results
    try:
        async for msg in tg_app.search_global(query, limit=10):
            try:
                raw_text = msg.text or msg.caption or "محتوى غير نصي"
                clean_text = str(raw_text).encode("utf-8", "ignore").decode("utf-8")
            except Exception:
                clean_text = "[محتوى تعذر فك شفرته]"

            results.append({
                "chat_title": msg.chat.title if msg.chat else "محادثة",
                "chat_id": msg.chat.id if msg.chat else None,
                "msg_id": msg.id,
                "text": clean_text
            })
    except Exception as e:
        log(f"⚠️ Search error: {e}")

    return results


def is_telegram_command(text):
    if not text:
        return False
    cmd = text.strip()
    if cmd.startswith("/"):
        return True
    if cmd.isdigit():
        return True
    keywords = ["القنوات", "قنوات", "المجموعات", "مجموعات", "المحادثات", "محادثات", "التالي", "السابق"]
    if cmd.lower() in keywords or cmd.lower().startswith("فتح ") or cmd.lower().startswith("بحث "):
        return True
    return False


def handle_telegram_command(sender_id, text, gemini_response_fn):
    if not tg_app or not telegram_ready:
        err_details = telegram_error if telegram_error else "جاري الاتصال بالتليجرام..."
        return f"⚠️ حساب Telegram غير متصل حالياً.\nالسبب: {err_details}"

    state = get_user_state(sender_id)
    raw_cmd = text.strip()
    cmd = raw_cmd[1:].strip() if raw_cmd.startswith("/") else raw_cmd
    cmd_lower = cmd.lower()

    if cmd_lower in ["help", "مساعدة", "اوامر", "الأوامر"]:
        return (
            "🤖 **أوامر التحكم في Telegram:**\n\n"
            "🔹 `/channels` أو `/قنوات` - عرض القنوات\n"
            "🔹 `/groups` أو `/مجموعات` - عرض المجموعات\n"
            "🔹 `/chats` أو `/محادثات` - عرض المحادثات الخاصة\n"
            "🔹 `/search <كلمة>` أو `/بحث <كلمة>` - البحث في التليجرام\n"
            "🔹 `/open <رقم>` أو `/فتح <رقم>` - قراءة وتحليل رسالة بـ Gemini\n"
            "🔹 `/next` أو `/التالي` - الصفحة التالية\n"
            "🔹 `/prev` أو `/السابق` - الصفحة السابقة\n"
            "🔹 أرسل **رقم فقط** (مثل: 1) لفتح العناصر"
        )

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

    if cmd_lower in ["next", "التالي"] and state["state"] == "VIEWING_MESSAGES":
        state["current_page"] += 1
        return format_messages_page(sender_id)

    if cmd_lower in ["prev", "previous", "السابق"] and state["state"] == "VIEWING_MESSAGES":
        if state["current_page"] > 0:
            state["current_page"] -= 1
            return format_messages_page(sender_id)
        return "أنت في الصفحة الأولى بالفعل."

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
                
                prompt = f"قم بتحليل وتلخيص النص التالي المستخرج من Telegram بشكل دقيق ومباشر:\n\n{full_text}"
                ai_summary = gemini_response_fn(sender_id, user_text=prompt)
                
                return f"📖 النص الأصلي من Telegram:\n\n{full_text}\n\n💡 تحليل Gemini:\n\n{ai_summary}"
            return "❌ رقم الرسالة غير موجود."
        except Exception:
            return "❌ الاستخدام الصحيح: `/open 1` أو `/فتح 1`"

    if cmd_lower.startswith("search ") or cmd_lower.startswith("بحث "):
        parts = cmd.split(" ", 1)
        q = parts[1].strip() if len(parts) > 1 else ""
        if not q:
            return "❌ يرجى كتابة كلمة للبحث، مثال: `/search pathology`"
        results = run_async(async_search_messages(q))
        if not results:
            return f"🔎 لم يتم العثور على نتائج للبحث عن: {q}"
        res = f"🔎 نتائج البحث عن ({q}):\n\n"
        for idx, item in enumerate(results[:5], 1):
            res += f"{idx}. [{item['chat_title']}]: {item['text'][:60]}...\n\n"
        return res

    if raw_cmd.startswith("/"):
        return f"❌ الأمر `{raw_cmd}` غير معروف.\nأرسل `/help` لمشاهدة جميع الأوامر."

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
            
