"""Telegram bot: xabarlar, ovoz, rasm, tugmalar, taklif havolalari va jadvalli ishlar."""
import asyncio
import logging
from datetime import time as dtime

from telegram import Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler,
                          filters)

from . import brain, config, db, reception, reports, social, tools, tools_media, tools_school, voice
from . import queries as Q
from .core import ROLE_UZ, now, rt, send_tg

log = logging.getLogger("wstizim.bot")

UNKNOWN_TEXT = ("Assalomu alaykum! Bu o'quv markazining xabarnoma boti. Ro'yxatdan o'tish uchun markaz "
                "administratori bergan havolani bosing.")


async def get_staff(tg_id):
    return await db.one("select * from staff where telegram_id=%s and is_active", tg_id)


# ---------- /start, /id ----------
async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Sizning Telegram ID raqamingiz: {update.effective_user.id}")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, msg = update.effective_user, update.message
    arg = context.args[0] if context.args else ""

    if arg.startswith("st_"):                                  # xodim taklifi
        try:
            row = await db.one(
                "update staff set telegram_id=%s, invite_code=null where invite_code=%s and telegram_id is null "
                "returning full_name, role::text as role", user.id, arg[3:])
        except Exception:
            row = None
        if row:
            await msg.reply_text(f"Xush kelibsiz, {row['full_name']}! Siz {ROLE_UZ[row['role']]} sifatida ulandingiz. "
                                 "Menga yozing yoki ovozli xabar yuboring, yordam beraman.")
        else:
            await msg.reply_text("Havola yaroqsiz yoki avval ishlatilgan. Rahbardan yangisini so'rang.")
        return

    if arg.startswith("pr_"):                                  # ota-ona havolasi
        stu = await db.one("select id, full_name from students where invite_code=%s", arg[3:])
        if not stu:
            await msg.reply_text("Havola yaroqsiz. Markaz administratoridan yangisini so'rang.")
            return
        parent = await db.one("select id from parents where telegram_id=%s", user.id)
        if not parent:
            cand = await db.one(
                """select p.id from student_parents sp join parents p on p.id = sp.parent_id
                   where sp.student_id = %s and p.telegram_id is null order by p.created_at limit 1""", stu["id"])
            if cand:
                await db.ex("update parents set telegram_id=%s where id=%s", user.id, cand["id"])
                parent = cand
            else:
                parent = await db.one("insert into parents (full_name, telegram_id) values (%s,%s) returning id",
                                      user.full_name, user.id)
        await db.ex("insert into student_parents (student_id, parent_id) values (%s,%s) on conflict do nothing",
                    stu["id"], parent["id"])
        await msg.reply_text(f"Rahmat! Endi farzandingiz {stu['full_name']} haqidagi muhim xabarlarni (davomat, "
                             "to'lov eslatmalari) shu yerda olasiz.")
        return

    staff = await get_staff(user.id)
    if staff:
        await msg.reply_text(f"Salom, {staff['full_name']}! Men Jimi, WS-Tizim yordamchisiman. Menga «Jimi, ...» deb yozing yoki ovozli xabar yuboring.")
        return
    if await db.one("select 1 from parents where telegram_id=%s", user.id) and not arg:
        await msg.reply_text("Assalomu alaykum! Savol yoki xabaringizni yozing, administratorga yetkazaman.")
        return
    await reception.start_visitor(update, arg)        # mijoz (ld_...) yoki ishga nomzod (vk_...)


async def cmd_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kompyuter paneliga bir martalik kirish havolasi."""
    staff = await get_staff(update.effective_user.id)
    if not staff:
        await update.message.reply_text(UNKNOWN_TEXT)
        return
    if not config.PANEL_ENABLED:
        await update.message.reply_text("Panel o'chirilgan (.env da PANEL_ENABLED=true qiling).")
        return
    from . import web
    link = await web.create_login_link(staff)
    await update.message.reply_text(
        "🖥 WS-Tizim paneliga kirish havolasi (15 daqiqa amal qiladi, bir marta ishlaydi):\n"
        f"{link}\n\nHavolani bot ishlayotgan kompyuterdagi brauzerda oching. Uni hech kimga yubormang.",
        disable_web_page_preview=True)


# ---------- asosiy ishlov ----------
async def send_voice_reply(bot, chat, audio):
    """Ovozli javob. Foydalanuvchi Telegram'da ovozli xabarlarni cheklagan bo'lsa, audio fayl sifatida yuboradi."""
    from telegram.error import BadRequest
    try:
        await bot.send_voice(chat_id=chat, voice=audio)
    except BadRequest as e:
        if "voice_messages_forbidden" not in str(e).lower():
            log.warning("ovozli javob yuborilmadi: %s", e)
            return
        try:
            await bot.send_audio(chat_id=chat, audio=audio, filename="jimi.mp3", title="Jimi")
        except Exception as e2:
            log.info("ovozli javob o'tkazib yuborildi (Telegram sozlamasi): %s", e2)


def explain_error(e, staff):
    """Xatoni oddiy tilda tushuntiradi (rahbarga batafsilroq)."""
    import anthropic
    msg = str(e)
    reason = None
    if isinstance(e, anthropic.AuthenticationError):
        reason = "Claude kaliti (ANTHROPIC_API_KEY) noto'g'ri yoki o'chirilgan."
    elif isinstance(e, anthropic.PermissionDeniedError):
        reason = "Claude kalitida ruxsat yetarli emas."
    elif "credit balance" in msg.lower() or "billing" in msg.lower():
        reason = "Anthropic hisobida kredit yo'q: console.anthropic.com → Billing → kredit qo'shing."
    elif isinstance(e, anthropic.NotFoundError) or "model" in msg.lower() and "not" in msg.lower():
        reason = f"Model topilmadi ({config.MODEL_MAIN} / {config.MODEL_FAST}). .env dagi MODEL_MAIN/MODEL_FAST ni tekshiring."
    elif isinstance(e, anthropic.RateLimitError):
        reason = "Claude limitiga yetildi, bir daqiqadan keyin urinib ko'ring."
    elif isinstance(e, anthropic.APIConnectionError):
        reason = "Claude serveriga ulanib bo'lmadi (internet)."
    elif "connection" in msg.lower() and ("postgres" in msg.lower() or "pool" in msg.lower()):
        reason = "Bazaga ulanib bo'lmadi: DATABASE_URL ni tekshiring."
    elif "does not exist" in msg.lower() and "relation" in msg.lower():
        reason = "Bazada jadval yo'q: Supabase'da sql/setup.sql ni ishga tushiring."
    base = "Kechirasiz, xatolik yuz berdi."
    if staff and staff.get("role") == "owner":
        return f"{base}\nSabab: {reason or type(e).__name__ + ': ' + msg[:300]}\n(To'liq xato terminalda.)"
    return base + (f" {reason}" if reason else " Birozdan keyin qayta urinib ko'ring.")


async def process(update, context, text, was_voice=False, attachments=None):
    try:
        await _process(update, context, text, was_voice, attachments)
    except Exception as e:
        log.exception("xabar ishlanmadi")
        try:
            staff = await get_staff(update.effective_user.id)
        except Exception:
            staff = None
        try:
            await update.message.reply_text(explain_error(e, staff))
        except Exception:
            pass


async def _process(update, context, text, was_voice=False, attachments=None):
    tg, chat = update.effective_user.id, update.effective_chat.id
    staff = await get_staff(tg)
    if not staff:
        if not text:
            await update.message.reply_text("Iltimos, xabaringizni matn bilan yozing.")
            return
        async with rt.lock(tg):
            try:
                if await db.one("select 1 from parents where telegram_id=%s", tg):
                    await reception.parent_message(update, text)
                else:
                    await reception.handle(update, context, text=text)
            except Exception:
                log.exception("qabul xatosi")
                await update.message.reply_text("Kechirasiz, xatolik. Administrator siz bilan bog'lanadi.")
        return
    async with rt.lock(tg):
        await context.bot.send_chat_action(chat_id=chat, action="typing")
        ctx = await Q.make_ctx(staff, msg_time=now(), chat_id=chat, was_voice=was_voice,
                               attachments=attachments or [])
        # "ha" / "yo'q": kutilayotgan amalni modelga qoldirmasdan, kodning o'zi bajaradi yoki bekor qiladi
        if text and not attachments and (tools.is_yes(text) or tools.is_no(text)) \
                and await tools.last_pending(staff["id"]):
            res = await tools.run_pending(ctx, confirm=tools.is_yes(text))
            if res:
                answer = await brain.after_confirm(ctx, text, res)
                await send_tg(chat, answer)
                return
        try:
            answer = await brain.chat(ctx, text)
        except Exception as e:
            log.exception("chat xatosi")
            answer = explain_error(e, staff)
        await send_tg(chat, answer)
        if was_voice and config.VOICE_REPLIES:
            audio = await voice.synthesize(answer)
            if audio:
                await send_voice_reply(context.bot, chat, audio)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process(update, context, update.message.text)


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not await get_staff(update.effective_user.id):
        return await process(update, context, "")
    if not voice.stt_enabled():
        await msg.reply_text("Ovozli buyruq hali yoqilmagan (.env da ELEVENLABS_API_KEY kerak). Hozircha matn yozing.")
        return
    v = msg.voice or msg.audio
    if msg.audio or (v.duration and v.duration > 180):
        # Uzun audio/fayl = buyruq emas, material (masalan dars yozuvi tahlili uchun)
        if (v.file_size or 0) > 20 * 1024 * 1024:
            await msg.reply_text("Fayl 20 MB dan katta: Telegram bot uni yuklab ololmaydi. Siqib yoki bo'lib yuboring.")
            return
        att = {"kind": "audio", "file_id": v.file_id, "name": getattr(v, "file_name", None) or "audio.ogg",
               "mime": getattr(v, "mime_type", None) or "audio/ogg"}
        return await process(update, context, msg.caption or "Audio fayl yubordim (masalan dars yozuvi).",
                             attachments=[att])
    try:
        f = await context.bot.get_file(v.file_id)
        data = bytes(await f.download_as_bytearray())
        text = await voice.transcribe(data)
    except voice.SttError as e:
        log.error("ovoz xizmati: %s", e)
        await msg.reply_text("Ovozni matnga o'girib bo'lmadi: " + str(e).split(". Javob:")[0]
                             + ".\nHozircha matn bilan yozing.")
        return
    except Exception:
        log.exception("ovoz xatosi")
        await msg.reply_text("Ovozni tushuna olmadim. Qayta yuboring yoki matn yozing.")
        return
    if not text:
        await msg.reply_text("Hech narsa eshitilmadi. Qayta urinib ko'ring.")
        return
    await msg.reply_text(f"🎤 Eshitdim: {text}")
    await process(update, context, text, was_voice=True)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not await get_staff(update.effective_user.id):
        return await process(update, context, "")
    ph = msg.photo[-1]
    url, b64 = None, None
    try:
        f = await context.bot.get_file(ph.file_id)
        data = bytes(await f.download_as_bytearray())
        import base64
        b64 = base64.b64encode(data).decode()
        url = await social.upload_public(data)
    except Exception:
        log.exception("rasm yuklash xatosi")
    caption = msg.caption or "Rasm yubordim."
    atts = [{"kind": "photo", "url": url, "file_id": ph.file_id, "b64": b64, "mime": "image/jpeg"}]
    if not url:
        caption += ("\n[Tizim eslatmasi: rasm qabul qilindi. Uni Telegram kanalga chiqarish mumkin, lekin Instagram uchun "
                    "ochiq havola yo'q (Supabase Storage sozlanmagan).]")
    await process(update, context, caption, attachments=atts)


async def on_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Video (yoki video-fayl) yuborilsa: kanal/Instagramga post qilish uchun."""
    msg = update.message
    if not await get_staff(update.effective_user.id):
        return await process(update, context, "")
    v = msg.video or msg.animation or msg.document
    size = getattr(v, "file_size", 0) or 0
    url = None
    note = ""
    if size > 20 * 1024 * 1024:
        note = ("\n[Tizim eslatmasi: video 20 MB dan katta. Telegram botlar bunday faylni yuklab ololmaydi, shuning "
                "uchun Instagramga chiqarib bo'lmaydi; Telegram kanalga esa chiqarsa bo'ladi. Katta videoni panel "
                "orqali yuklang (50 MB gacha).]")
    else:
        try:
            f = await context.bot.get_file(v.file_id)
            ext = (getattr(v, "file_name", "") or "video.mp4").rsplit(".", 1)[-1] or "mp4"
            url = await social.upload_public(bytes(await f.download_as_bytearray()), ext=ext,
                                             content_type=getattr(v, "mime_type", None) or "video/mp4")
            if not url:
                note = ("\n[Tizim eslatmasi: video qabul qilindi. Telegram kanalga chiqarish mumkin; Instagram uchun "
                        "Supabase Storage sozlanishi kerak.]")
        except Exception:
            log.exception("video yuklash xatosi")
            note = "\n[Tizim eslatmasi: video ochiq havolaga yuklanmadi, faqat Telegram kanalga chiqarsa bo'ladi.]"
    caption = (msg.caption or "Video yubordim.") + note
    await process(update, context, caption, attachments=[{"kind": "video", "url": url, "file_id": v.file_id}])


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    staff = await get_staff(q.from_user.id)
    if not staff or staff["role"] != "owner":
        await q.answer("Faqat rahbar tasdiqlay oladi.", show_alert=True)
        return
    await q.answer()
    _, approval_id, decision = q.data.split(":")
    text = await tools.execute_approval(approval_id, decision == "y", staff)
    try:
        await q.edit_message_text((q.message.text or "") + "\n\n" + text)
    except Exception:
        pass


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """PDF, Word, Excel, matn fayli yoki fayl sifatida yuborilgan rasm."""
    msg = update.message
    if not await get_staff(update.effective_user.id):
        return await process(update, context, msg.caption or "")
    d = msg.document
    if (d.file_size or 0) > 20 * 1024 * 1024:
        await msg.reply_text("Fayl 20 MB dan katta: Telegram bot uni yuklab ololmaydi.")
        return
    try:
        data = bytes(await (await context.bot.get_file(d.file_id)).download_as_bytearray())
    except Exception:
        log.exception("fayl yuklash xatosi")
        await msg.reply_text("Faylni yuklab bo'lmadi, qayta yuboring.")
        return
    from . import files
    att = files.to_attachment(d.file_name, d.mime_type, data)
    if not att:
        await msg.reply_text("Bu turdagi faylni o'qiy olmayman. PDF, Word (.docx), Excel (.xlsx), matn (.txt/.csv) "
                             "yoki rasm yuboring.")
        return
    if att["kind"] == "photo":
        att["file_id"] = d.file_id
        try:
            att["url"] = await social.upload_public(data, (d.file_name or "img.jpg").rsplit(".", 1)[-1], att["mime"])
        except Exception:
            pass
    default = {"pdf": "Shu PDF ni o'qib chiq.", "text_file": "Shu faylni o'qib chiq.", "photo": "Rasm yubordim."}
    await process(update, context, msg.caption or default.get(att["kind"], ""), attachments=[att])


async def on_task_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vazifa xabaridagi «✅ Bajarildi» / «👀 Ko'rdim» tugmalari."""
    q = update.callback_query
    staff = await get_staff(q.from_user.id)
    if not staff:
        await q.answer("Siz tizimda ro'yxatdan o'tmagansiz.", show_alert=True)
        return
    _, task_id, status = q.data.split(":")
    try:
        await tools.set_task_status(task_id, status, staff)
    except tools.ToolError as e:
        await q.answer(str(e), show_alert=True)
        return
    await q.answer("Rahmat!" if status == "done" else "Belgilandi")
    mark = "\n\n✅ Bajarildi" if status == "done" else "\n\n👀 Ko'rildi"
    try:
        kb = None if status == "done" else tools.task_keyboard(task_id).inline_keyboard[0][:1]
        from telegram import InlineKeyboardMarkup
        await q.edit_message_text((q.message.text or "") + mark,
                                  reply_markup=InlineKeyboardMarkup([kb]) if kb else None)
    except Exception:
        pass


async def on_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_staff(update.effective_user.id):
        return
    async with rt.lock(update.effective_user.id):
        await reception.handle(update, context, contact=update.message.contact)


async def cmd_dars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """O'qituvchi: bugungi darslari va «Boshladim/Tugatdim» tugmalari."""
    staff = await get_staff(update.effective_user.id)
    if not staff or staff["role"] not in ("teacher", "owner"):
        await update.message.reply_text("Bu buyruq o'qituvchilar uchun.")
        return
    from .core import today as _today
    groups = await db.q("""select g.id, g.name, g.start_time from groups g join teachers t on t.id = g.teacher_id
                           where g.is_active and t.staff_id=%s and %s::int = any(g.days) order by g.start_time""",
                        staff["id"], _today().isoweekday())
    if not groups:
        await update.message.reply_text("Bugun darsingiz yo'q.")
        return
    for g in groups:
        s = await tools_school.ensure_session(g)
        started = bool(s["started_at"])
        if s["ended_at"]:
            await update.message.reply_text(f"«{g['name']}»: dars tugagan ✅")
            continue
        await update.message.reply_text(f"{str(g['start_time'])[:5]} «{g['name']}»" + (" — boshlangan" if started else ""),
                                        reply_markup=tools_school.lesson_keyboard(s["id"], started))


async def on_lesson_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    staff = await get_staff(q.from_user.id)
    if not staff:
        await q.answer()
        return
    _, sid, action = q.data.split(":")
    try:
        s, late = await tools_school.lesson_mark(sid, action, staff)
    except tools.ToolError as e:
        await q.answer(str(e), show_alert=True)
        return
    await q.answer("Belgilandi")
    if action == "start":
        note = f"\n▶️ Boshlandi {now():%H:%M}" + (f" (kechikish {late} daqiqa)" if late and late > 5 else "")
        await q.edit_message_text((q.message.text or "") + note, reply_markup=tools_school.lesson_keyboard(sid, True))
    else:
        await q.edit_message_text((q.message.text or "") + f"\n⏹ Tugadi {now():%H:%M}")
        await context.bot.send_message(q.from_user.id, f"Rahmat! Davomat va uy vazifasini yozib qo'ying, masalan:\n"
                                       f"«Jimi, {s['name']}: Ali kelmadi. Uy vazifasi: 5-mashq»")


async def on_survey_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, sid, rating = q.data.split(":")
    text = await tools_school.survey_answer(sid, int(rating), q.from_user.id)
    await q.answer("Rahmat!")
    try:
        await q.edit_message_text((q.message.text or "") + f"\n\nSizning bahoingiz: {rating} ⭐")
    except Exception:
        pass
    await context.bot.send_message(q.from_user.id, text)


async def on_comment_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    staff = await get_staff(q.from_user.id)
    if not staff:
        await q.answer()
        return
    ctx = await Q.make_ctx(staff, msg_time=now())
    if ctx.level("manage_comments") == "deny":
        await q.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, rest = q.data.split(":", 1)
    cid, action = rest.rsplit(":", 1)
    row = await db.one("select * from ig_comments where id=%s", cid)
    if not row or row["status"] != "yangi":
        await q.answer("Allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    try:
        if action == "send":
            await tools_media.send_comment_reply(cid, row["suggested_reply"])
            mark = f"\n\n✅ {staff['full_name']} javob yubordi"
        else:
            await db.ex("update ig_comments set status='etiborsiz' where id=%s", cid)
            mark = f"\n\n🙈 {staff['full_name']}: e'tiborsiz"
    except Exception as e:
        await q.answer(f"Xato: {str(e)[:150]}", show_alert=True)
        return
    await q.answer("Bajarildi")
    try:
        await q.edit_message_text((q.message.text or "") + mark)
    except Exception:
        pass


async def on_discussion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal izohlari guruhidagi xabarlar (kanal postlarining o'zi emas)."""
    msg = update.message
    if not msg or msg.is_automatic_forward or not msg.text or (msg.from_user and msg.from_user.is_bot):
        return
    if await get_staff(msg.from_user.id):
        return
    try:
        await tools_media.save_comment(f"tg:{msg.chat_id}:{msg.message_id}", "telegram",
                                       msg.from_user.username or msg.from_user.full_name, msg.text, msg.date)
    except Exception:
        log.exception("izoh xatosi")


async def on_error(update, context):
    log.error("Kutilmagan xato", exc_info=context.error)


# ---------- ishga tushirish ----------
async def ensure_owner():
    row = await db.one("select id from staff where role='owner' limit 1")
    if row:
        await db.ex("update staff set telegram_id=%s, full_name=%s, is_active=true where id=%s",
                    config.OWNER_TELEGRAM_ID, config.OWNER_NAME, row["id"])
    else:
        await db.ex("insert into staff (full_name, role, telegram_id) values (%s,'owner',%s)",
                    config.OWNER_NAME, config.OWNER_TELEGRAM_ID)


async def post_init(app: Application):
    await db.open_pool()
    me = await app.bot.get_me()
    config.BOT_USERNAME = me.username
    rt.bot = app.bot
    await ensure_owner()
    brain.load_agents()
    tools.load_plugins()
    jq, tz = app.job_queue, config.TZ
    jq.run_daily(reports.morning_job, time=dtime(config.MORNING_HOUR, 0, tzinfo=tz), name="morning")
    jq.run_daily(reports.roll_cycles_job, time=dtime(0, 10, tzinfo=tz), name="roll_cycles")
    jq.run_daily(reports.weekly_job, time=dtime(9, 0, tzinfo=tz), name="weekly")
    jq.run_repeating(reports.lead_alert_job, interval=1800, first=120, name="lead_alerts")
    jq.run_repeating(reports.publish_due_job, interval=60, first=30, name="scheduled_posts")
    jq.run_repeating(reports.task_reminder_job, interval=900, first=90, name="task_reminders")
    jq.run_repeating(reports.lesson_reminder_job, interval=300, first=60, name="lesson_reminders")
    jq.run_daily(reports.retention_job, time=dtime(10, 30, tzinfo=tz), name="retention")
    jq.run_repeating(reports.comments_job, interval=900, first=180, name="ig_comments")
    jq.run_daily(reports.ads_job, time=dtime(7, 30, tzinfo=tz), name="meta_ads")
    jq.run_daily(reports.competitors_job, time=dtime(9, 40, tzinfo=tz), days=(1,), name="competitors")
    jq.run_daily(reports.content_plan_job, time=dtime(11, 0, tzinfo=tz), name="content_plan")
    jq.run_daily(reports.monthly_survey_job, time=dtime(12, 0, tzinfo=tz), name="monthly_survey")
    jq.run_daily(reports.hr_review_job, time=dtime(10, 0, tzinfo=tz), name="hr_review")
    jq.run_daily(reports.ig_token_job, time=dtime(6, 15, tzinfo=tz), days=(1,), name="ig_token")
    if config.PANEL_ENABLED:
        from . import web
        app.bot_data["web_task"] = asyncio.create_task(web.serve())
    try:
        from telegram import BotCommand
        await app.bot.set_my_commands([BotCommand("start", "Boshlash"),
                                       BotCommand("panel", "WS-Tizim paneliga kirish havolasi"),
                                       BotCommand("dars", "O'qituvchi: bugungi darslar (boshladim/tugatdim)"),
                                       BotCommand("id", "Telegram ID raqamim")])
    except Exception:
        log.warning("bot buyruqlari ro'yxati o'rnatilmadi")
    log.info("WS-Tizim ishga tushdi (AI: Jimi): @%s", me.username)


async def post_shutdown(app: Application):
    if rt.web_server:
        rt.web_server.should_exit = True
        task = app.bot_data.get("web_task")
        if task:
            try:
                await asyncio.wait_for(task, timeout=5)
            except Exception:
                pass
    await db.close_pool()


def build_app() -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init) \
        .post_shutdown(post_shutdown).build()
    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler("start", cmd_start, filters=private))
    app.add_handler(CommandHandler("id", cmd_id, filters=private))
    app.add_handler(CommandHandler("panel", cmd_panel, filters=private))
    app.add_handler(CommandHandler("dars", cmd_dars, filters=private))
    app.add_handler(MessageHandler(private & filters.CONTACT, on_contact))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^ap:"))
    app.add_handler(CallbackQueryHandler(on_task_button, pattern=r"^tk:"))
    app.add_handler(CallbackQueryHandler(on_lesson_button, pattern=r"^ls:"))
    app.add_handler(CallbackQueryHandler(on_survey_button, pattern=r"^sv:"))
    app.add_handler(CallbackQueryHandler(on_comment_button, pattern=r"^cm:"))
    if config.TELEGRAM_DISCUSSION_ID:
        app.add_handler(MessageHandler(filters.Chat(chat_id=int(config.TELEGRAM_DISCUSSION_ID)) & filters.TEXT
                                       & ~filters.COMMAND, on_discussion))
    app.add_handler(MessageHandler(private & (filters.VOICE | filters.AUDIO), on_voice))
    app.add_handler(MessageHandler(private & filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(private & (filters.VIDEO | filters.ANIMATION | filters.Document.VIDEO), on_video))
    app.add_handler(MessageHandler(private & filters.Document.ALL & ~filters.Document.VIDEO, on_document))
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    return app
