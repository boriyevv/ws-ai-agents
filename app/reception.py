"""Qabul agenti: botga yozgan notanish odamlar (mijoz yoki ishga nomzod) va ota-onalar xabarlari.

- t.me/bot?start=ld_<post>  -> postdan kelgan mijoz (lid postga bog'lanadi)
- t.me/bot?start=vk_<kod>   -> vakansiyaga nomzod (savollar, AI saralash)
- oddiy /start yoki xabar   -> mijoz
"""
import asyncio
import json
import logging
import re

from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from . import config, db
from .core import send_tg

log = logging.getLogger("wstizim.reception")
DAILY_AI_LIMIT = 25


async def _state(tg):
    return await db.one("select * from bot_visitors where telegram_id=%s", tg)


async def _save(tg, kind, ref, step, data):
    await db.ex("insert into bot_visitors (telegram_id, kind, ref, step, data, updated_at) values (%s,%s,%s,%s,%s,now()) "
                "on conflict (telegram_id) do update set kind=excluded.kind, ref=excluded.ref, step=excluded.step, "
                "data=excluded.data, updated_at=now()", tg, kind, ref, step, db.js(data))


def _phone_kb():
    return ReplyKeyboardMarkup([[KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True)]],
                               resize_keyboard=True, one_time_keyboard=True)


async def _notify(text, roles=("admin", "manager")):
    rows = await db.q("select telegram_id from staff where is_active and telegram_id is not null and role::text = any(%s)",
                      list(roles))
    if not rows:
        rows = await db.q("select telegram_id from staff where role='owner' and telegram_id is not null")
    for r in rows:
        try:
            await send_tg(r["telegram_id"], text)
        except Exception:
            log.warning("xabar yuborilmadi")


async def start_visitor(update, arg):
    tg, msg = update.effective_user.id, update.message
    if arg and arg.startswith("vk_"):
        vac = await db.one("select id, title, status, questions from vacancies where code=%s", arg[3:])
        if not vac or vac["status"] != "ochiq":
            await msg.reply_text("Bu vakansiya yopilgan. Qiziqishingiz uchun rahmat!")
            return
        await _save(tg, "candidate", str(vac["id"]), "name", {"answers": {}})
        await msg.reply_text(f"Assalomu alaykum! {config.CENTER_NAME}: «{vac['title']}» vakansiyasiga ariza.\n\n"
                             "Ism-familiyangizni yozing:")
        return
    ref = arg[3:] if arg and arg.startswith("ld_") else None
    await _save(tg, "lead", ref, "name", {})
    await msg.reply_text(f"Assalomu alaykum! {config.CENTER_NAME} ga xush kelibsiz 👋\n"
                         "Kurslar, narxlar va bepul sinov darsi haqida yordam beraman.\n\nIsmingiz nima?")


async def handle(update, context, text=None, contact=None):
    tg, msg = update.effective_user.id, update.message
    st = await _state(tg)
    if not st:
        await _save(tg, "lead", None, "name", {"first_q": text})
        await msg.reply_text(f"Assalomu alaykum! {config.CENTER_NAME}. Savolingizga javob beraman, avval ismingizni "
                             "yozing:")
        return
    data = st["data"] or {}
    step = st["step"]

    if step == "name":
        if not text or len(text) > 80:
            await msg.reply_text("Ismingizni yozing:")
            return
        data["name"] = text.strip()
        await _save(tg, st["kind"], st["ref"], "phone", data)
        await msg.reply_text(f"Rahmat, {data['name']}! Bog'lanish uchun telefon raqamingizni yuboring "
                             "(pastdagi tugma yoki yozib):", reply_markup=_phone_kb())
        return

    if step == "phone":
        phone = contact.phone_number if contact else re.sub(r"[^\d+]", "", text or "")
        if len(re.sub(r"\D", "", phone)) < 9:
            await msg.reply_text("Telefon raqamini to'liq yozing, masalan +998901234567:", reply_markup=_phone_kb())
            return
        data["phone"] = phone if phone.startswith("+") else "+" + phone if len(phone) >= 12 else phone
        if st["kind"] == "candidate":
            await _save(tg, "candidate", st["ref"], "q0", data)
            vac = await db.one("select questions from vacancies where id::text=%s", st["ref"])
            await msg.reply_text((vac["questions"] or ["Tajribangiz haqida yozing"])[0], reply_markup=ReplyKeyboardRemove())
            return
        await _create_lead(update, st, data)
        return

    if st["kind"] == "candidate" and step.startswith("q"):
        vac = await db.one("select id, title, questions from vacancies where id::text=%s", st["ref"])
        qs = vac["questions"] if vac else []
        i = int(step[1:])
        data.setdefault("answers", {})[qs[i] if i < len(qs) else f"savol {i + 1}"] = (text or "")[:1500]
        if i + 1 < len(qs):
            await _save(tg, "candidate", st["ref"], f"q{i + 1}", data)
            await msg.reply_text(qs[i + 1])
            return
        cand = await db.one("insert into candidates (vacancy_id, full_name, phone, telegram_id, answers) "
                            "values (%s,%s,%s,%s,%s) returning id", vac["id"] if vac else None, data.get("name"),
                            data.get("phone"), tg, db.js(data["answers"]))
        await _save(tg, "candidate", st["ref"], "done", data)
        await msg.reply_text("Rahmat! Arizangiz qabul qilindi. Ko'rib chiqib, shu yerda javob beramiz.")
        from .tools_school import screen_candidate
        asyncio.create_task(_safe(screen_candidate(cand["id"])))
        return

    if st["kind"] == "candidate":
        await msg.reply_text("Arizangiz ko'rib chiqilmoqda. Javobni shu yerda olasiz.")
        return

    # mijoz bilan suhbat (lid yaratilgan)
    await _answer(update, st, data, text or "")


async def _safe(coro):
    try:
        await coro
    except Exception:
        log.exception("fon vazifa xatosi")


async def _create_lead(update, st, data):
    tg, msg = update.effective_user.id, update.message
    post = await db.one("select id from content_posts where ref_code=%s", st["ref"]) if st["ref"] else None
    branch = await db.one("select id from branches where is_active order by name limit 1")
    exists = await db.one("select id from leads where telegram_id=%s or phone=%s limit 1", tg, data["phone"])
    if not exists:
        await db.ex("insert into leads (branch_id, full_name, phone, source, post_id, telegram_id, note) "
                    "values (%s,%s,%s,%s,%s,%s,%s)", branch["id"] if branch else None, data.get("name"), data["phone"],
                    "telegram_post" if post else "telegram_bot", post["id"] if post else None, tg,
                    data.get("first_q"))
    await _save(tg, "lead", st["ref"], "chat", data)
    await msg.reply_text("Rahmat! Administratorimiz tez orada siz bilan bog'lanadi. Savollaringiz bo'lsa, shu yerga "
                         "yozing — javob beraman.", reply_markup=ReplyKeyboardRemove())
    await _notify(f"🆕 Yangi murojaat (bot{', postdan' if post else ''}): {data.get('name')}, {data['phone']}"
                  + (f"\nSavoli: {data['first_q']}" if data.get("first_q") else "") + "\nTezroq qo'ng'iroq qiling.")
    if data.get("first_q"):
        await _answer(update, {**st, "step": "chat"}, data, data["first_q"])


async def knowledge():
    notes = await db.q("select note from business_notes order by id desc limit 30")
    groups = await db.q(
        """select g.name, g.subject, g.days, g.start_time, g.end_time, b.name as branch, g.capacity,
                  (select count(*) from enrollments e where e.group_id = g.id and e.status='active') as n,
                  (select max(monthly_fee) from enrollments e where e.group_id = g.id) as fee
           from groups g join branches b on b.id = g.branch_id where g.is_active and b.is_active order by g.subject""")
    from .tools import _sched
    lines = [f"- {g['subject']} ({g['name']}, {g['branch']}): {_sched(g['days'], g['start_time'], g['end_time'])}; "
             f"bo'sh joy: {max(g['capacity'] - g['n'], 0)}" + (f"; oylik: {int(g['fee'])} so'm" if g["fee"] else "")
             for g in groups]
    return ("GURUHLAR:\n" + "\n".join(lines) + "\n\nMARKAZ HAQIDA:\n" + "\n".join(f"- {n['note']}" for n in notes)
            + f"\nTelefon: {config.CENTER_PHONE or 'administrator bog`lanadi'}")


async def _answer(update, st, data, text):
    from . import brain
    from .tools_media import get_setting
    tg, msg = update.effective_user.id, update.message
    used = int(data.get("ai_count", 0))
    if used >= DAILY_AI_LIMIT:
        await msg.reply_text("Savolingiz administratorga yetkazildi, tez orada javob beradi.")
        await _notify(f"💬 {data.get('name')} ({data.get('phone')}): {text[:800]}")
        return
    hist = data.get("hist", [])[-6:]
    voice_ = await get_setting("brand_voice", "")
    raw = await brain.quick(
        "Suhbat tarixi:\n" + "\n".join(hist) + f"\n\nMijoz: {text[:1500]}\n\n"
        'FAQAT JSON qaytaring: {"reply": "javob", "category": "savol|yozilish|shikoyat|boshqa"}',
        system=(f"Siz {config.CENTER_NAME} o'quv markazining qabul bo'limisiz (Telegram bot). Mijoz tilida (o'zbek yoki "
                f"rus) qisqa, samimiy javob bering. Ohang: {voice_}\nFaqat quyidagi ma'lumotlarga tayaning; bilmagan "
                "narsangizni to'qimang, 'administrator aniqlab beradi' deng. Bepul sinov darsiga taklif qiling.\n\n"
                + await knowledge()), fast=True, max_tokens=2000)
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        d = json.loads(m.group()) if m else {}
    except json.JSONDecodeError:
        d = {}
    reply = (d.get("reply") or raw or "Administrator tez orada javob beradi.").strip()[:3500]
    await msg.reply_text(reply)
    data["ai_count"] = used + 1
    data["hist"] = (hist + [f"Mijoz: {text[:300]}", f"Siz: {reply[:300]}"])[-8:]
    await _save(tg, "lead", st["ref"], "chat", data)
    if d.get("category") in ("yozilish", "shikoyat"):
        label = "🔥 Yozilmoqchi" if d["category"] == "yozilish" else "⚠️ Shikoyat"
        await _notify(f"{label}: {data.get('name')} ({data.get('phone')})\n«{text[:600]}»",
                      roles=("admin", "manager", "owner") if d["category"] == "shikoyat" else ("admin", "manager"))
        if d["category"] == "yozilish":
            await db.ex("update leads set status='contacted' where telegram_id=%s and status='new'", tg)


async def parent_message(update, text):
    """Ota-ona yozsa: so'rovnoma izohi bo'lsa saqlaydi, aks holda administratorga yetkazadi."""
    from .tools_school import survey_comment
    tg, msg = update.effective_user.id, update.message
    if await survey_comment(tg, text):
        await msg.reply_text("Rahmat, fikringiz yetkazildi!")
        return
    p = await db.one("""select p.full_name, p.phone, string_agg(s.full_name, ', ') as kids from parents p
                        left join student_parents sp on sp.parent_id = p.id left join students s on s.id = sp.student_id
                        where p.telegram_id=%s group by p.id""", tg)
    await _notify(f"👪 Ota-ona xabari ({p['full_name'] or ''}, {p['phone'] or ''}; farzand: {p['kids'] or '-'}):\n{text[:1500]}",
                  roles=("admin",))
    await msg.reply_text("Xabaringiz administratorga yetkazildi. Tez orada javob beramiz."
                         + (f" Shoshilinch bo'lsa: {config.CENTER_PHONE}" if config.CENTER_PHONE else ""))
