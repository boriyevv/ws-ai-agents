"""O'quv sifati, o'quvchini ushlab qolish, so'rovnoma/sharh, referral, yollash, jadval vositalari."""
import json
import logging
import re
from datetime import datetime, time as dtime, timedelta

from . import config, db
from . import queries as Q
from .core import DAY_NAMES, ROLE_UZ, ToolError, fmt_money, fuzzy, invite_link, now, parse_date, rt, send_tg, today
from .tools import B, LN, LS, N, S, _find_staff, _sched, single_branch, tool

log = logging.getLogger("wstizim.school")


# =====================================================================
#  DARS BOSHLANDI / TUGADI
# =====================================================================
def lesson_keyboard(session_id, started=False):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if started:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⏹ Darsni tugatdim", callback_data=f"ls:{session_id}:end")]])
    return InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Darsni boshladim", callback_data=f"ls:{session_id}:start")]])


async def ensure_session(group, lesson_date=None):
    d = lesson_date or today()
    row = await db.one(
        """insert into lesson_sessions (group_id, teacher_id, lesson_date, planned_start, planned_end)
           select g.id, t.staff_id, %s, g.start_time, g.end_time from groups g left join teachers t on t.id = g.teacher_id
           where g.id = %s
           on conflict (group_id, lesson_date) do update set teacher_id = excluded.teacher_id
           returning *, (xmax = 0) as created""", d, group["id"] if isinstance(group, dict) else group)
    return row


async def lesson_mark(session_id, action, staff):
    s = await db.one("select ls.*, g.name from lesson_sessions ls join groups g on g.id = ls.group_id "
                     "where ls.id::text=%s", str(session_id))
    if not s:
        raise ToolError("Dars topilmadi.")
    if staff["role"] == "teacher" and s["teacher_id"] != staff["id"]:
        raise ToolError("Bu sizning darsingiz emas.")
    col = "started_at" if action == "start" else "ended_at"
    if s[col]:
        return s, None
    await db.ex(f"update lesson_sessions set {col}=now() where id=%s", s["id"])
    late = None
    if action == "start" and s["planned_start"]:
        planned = datetime.combine(s["lesson_date"], s["planned_start"], tzinfo=config.TZ)
        late = int((now() - planned).total_seconds() // 60)
    return s, late


@tool("lesson_checkin", "O'qituvchi darsni boshlaganini yoki tugatganini belgilaydi (botdagi tugma bilan bir xil).",
      {"group": S("Guruh"), "action": S("start | end")}, ["group", "action"], roles={"teacher", "owner"}, write=True)
async def lesson_checkin(ctx, group, action):
    if action not in ("start", "end"):
        raise ToolError("action: start yoki end.")
    g = await Q.find_group(ctx, group)
    s = await ensure_session(g)
    _, late = await lesson_mark(s["id"], action, ctx.staff)
    out = {"ok": True, "guruh": g["name"], "amal": "boshlandi" if action == "start" else "tugadi"}
    if late is not None:
        out["kechikish_daqiqa"] = max(late, 0)
    return out


async def lesson_reminders():
    """Dars boshlanishidan ~15 daqiqa oldin o'qituvchiga «Darsni boshladim» tugmasi (har 5 daqiqada)."""
    t = now()
    rows = await db.q(
        """select g.id, g.name, g.start_time, st.telegram_id from groups g
           join branches b on b.id = g.branch_id and b.is_active
           join teachers tt on tt.id = g.teacher_id join staff st on st.id = tt.staff_id and st.is_active
           where g.is_active and %s::int = any(g.days) and st.telegram_id is not null
             and g.start_time between %s and %s""",
        t.isoweekday(), t.time(), (t + timedelta(minutes=15)).time())
    for g in rows:
        s = await ensure_session(g)
        if not s["created"]:
            continue
        try:
            await rt.bot.send_message(g["telegram_id"], f"⏰ {str(g['start_time'])[:5]} da «{g['name']}» darsi. "
                                      "Boshlaganingizda tugmani bosing.", reply_markup=lesson_keyboard(s["id"]))
        except Exception:
            log.warning("dars eslatmasi yuborilmadi")


# =====================================================================
#  UY VAZIFASI
# =====================================================================
@tool("add_homework", "Guruhga berilgan uy vazifasini yozadi.",
      {"group": S("Guruh"), "text": S("Uy vazifasi"), "date": S("Dars sanasi (standart bugun)")},
      ["group", "text"], perm="manage_homework", write=True)
async def add_homework(ctx, group, text, date=None):
    g = await Q.find_group(ctx, group)
    await db.ex("insert into homework (group_id, lesson_date, text, given_by) values (%s,%s,%s,%s)",
                g["id"], parse_date(date, today()), text.strip(), ctx.staff_id)
    return {"ok": True, "guruh": g["name"]}


@tool("check_homework", "Guruhning oxirgi uy vazifasi tekshirilganini belgilaydi.",
      {"group": S("Guruh")}, ["group"], perm="manage_homework", write=True)
async def check_homework(ctx, group):
    g = await Q.find_group(ctx, group)
    row = await db.one("update homework set checked=true, checked_at=now() where id = (select id from homework "
                       "where group_id=%s and not checked order by lesson_date desc limit 1) returning text", g["id"])
    if not row:
        raise ToolError("Tekshirilmagan uy vazifasi yo'q.")
    return {"ok": True, "vazifa": row["text"][:80]}


# =====================================================================
#  O'QITUVCHI SIFATI
# =====================================================================
@tool("quality_report", "O'qituvchilar sifat ko'rsatkichlari: darsni vaqtida boshlash, davomatni o'z vaqtida kiritish, "
      "uy vazifasi berish/tekshirish, imtihon natijasi va o'sishi, ota-onalar bahosi, ketgan o'quvchilar.",
      {"teacher": S("O'qituvchi (ixtiyoriy)"), "days": N("Davr, kun (standart 30)")}, perm="view_quality")
async def quality_report(ctx, teacher=None, days=30):
    bids = await Q.branch_ids_for(ctx)
    tid = (await _find_staff(ctx, teacher, roles={"teacher"}))["id"] if teacher else None
    days = int(days)
    rows = await db.q(
        """with tg as (
             select st.id as staff_id, st.full_name, g.id as gid, g.days
             from groups g join teachers t on t.id = g.teacher_id join staff st on st.id = t.staff_id
             where g.is_active and g.branch_id = any(%s) and (%s::uuid is null or st.id = %s::uuid))
           select tg.staff_id, tg.full_name as oqituvchi, count(distinct tg.gid) as guruhlar,
             (select count(*) from lesson_sessions s where s.teacher_id = tg.staff_id and s.started_at is not null
                and s.lesson_date >= current_date - %s::int) as belgilangan_darslar,
             (select round(avg(greatest(extract(epoch from (s.started_at - (s.lesson_date + s.planned_start)::timestamp
                       at time zone %s))/60, 0))::numeric, 1)
                from lesson_sessions s where s.teacher_id = tg.staff_id and s.started_at is not null
                and s.lesson_date >= current_date - %s::int) as ortacha_kechikish_daqiqa,
             (select count(*) from lesson_sessions s where s.teacher_id = tg.staff_id and s.started_at is null
                and s.lesson_date >= current_date - %s::int and s.lesson_date < current_date) as boshlanmagan_belgilanmagan,
             (select count(distinct (e.group_id, a.lesson_date)) from attendance a join enrollments e on e.id = a.enrollment_id
                where e.group_id in (select gid from tg t2 where t2.staff_id = tg.staff_id)
                and a.lesson_date >= current_date - %s::int) as davomat_kiritilgan_darslar,
             (select count(distinct (e.group_id, a.lesson_date)) from attendance a join enrollments e on e.id = a.enrollment_id
                where e.group_id in (select gid from tg t2 where t2.staff_id = tg.staff_id)
                and a.lesson_date >= current_date - %s::int and a.marked_at::date > a.lesson_date) as davomat_kechikib,
             (select count(*) from homework h where h.group_id in (select gid from tg t2 where t2.staff_id = tg.staff_id)
                and h.lesson_date >= current_date - %s::int) as uy_vazifasi_berildi,
             (select count(*) filter (where h.checked) from homework h where h.group_id in
                (select gid from tg t2 where t2.staff_id = tg.staff_id) and h.lesson_date >= current_date - %s::int) as uy_vazifasi_tekshirildi,
             (select round(avg(rating)::numeric, 2) from surveys sv where sv.teacher_id = tg.staff_id
                and sv.answered_at >= now() - make_interval(days => %s::int * 3)) as ota_ona_bahosi,
             (select count(*) from surveys sv where sv.teacher_id = tg.staff_id and sv.rating is not null
                and sv.answered_at >= now() - make_interval(days => %s::int * 3)) as baholar_soni,
             (select count(*) from lesson_reviews lr where lr.teacher_id = tg.staff_id) as dars_tahlillari
           from tg group by tg.staff_id, tg.full_name order by tg.full_name""",
        bids, tid, tid, days, str(config.TZ), days, days, days, days, days, days, days, days)
    exams = await Q.teacher_stats(bids, tid)
    for r in rows:
        mine = [e for e in exams if e["staff_id"] == r["staff_id"]]
        r["imtihon_ortacha_90kun"] = round(sum(e["ball_90"] for e in mine if e["ball_90"]) / max(1, sum(1 for e in mine if e["ball_90"])), 2) if any(e["ball_90"] for e in mine) else None
        r["imtihon_oldingi_90kun"] = round(sum(e["ball_oldingi_90"] for e in mine if e["ball_oldingi_90"]) / max(1, sum(1 for e in mine if e["ball_oldingi_90"])), 2) if any(e["ball_oldingi_90"] for e in mine) else None
        r["ketgan_oquvchilar"] = sum(e["ketgan"] for e in mine)
        r["davomat_30kun"] = round(sum(e["davomat_30kun"] or 0 for e in mine) / max(1, sum(1 for e in mine if e["davomat_30kun"] is not None)), 2) if mine else None
        r.pop("staff_id")
    return {"davr_kun": days, "oqituvchilar": rows,
            "eslatma": "Xulosa jazo uchun emas, yordam va rivojlanish uchun; qaror rahbar qo'lida."}


@tool("my_recording_consent", "O'qituvchi dars yozuvini AI tahlil qilishiga roziligini beradi yoki qaytarib oladi.",
      {"consent": B("true = roziman, false = rozi emasman")}, ["consent"], roles={"teacher"}, write=True)
async def my_recording_consent(ctx, consent):
    await db.ex("update staff set recording_consent=%s, consent_at=now() where id=%s", bool(consent), ctx.staff_id)
    return {"ok": True, "rozilik": bool(consent)}


ANALYSIS_RUBRIC = """Dars yozuvi matni (avtomatik o'girilgan, xatolar bo'lishi mumkin). Quyidagilarni baholang, har biriga
1-5 ball va 1-2 gap izoh: 1) tushuntirish aniqligi va tuzilishi; 2) o'quvchilar faolligi (savol-javob, ular gapirgan
ulush); 3) dars rejasiga rioya (kirish, asosiy qism, mustahkamlash, uy vazifasi); 4) vaqtdan foydalanish;
5) ohang va qo'llab-quvvatlash. Oxirida: 3 ta kuchli tomon va 3 ta aniq, amaliy tavsiya. Ohang: hurmatli, rivojlantiruvchi,
hukm chiqarmaydigan. Ma'lumot yetarli bo'lmasa, buni ochiq ayting."""


@tool("analyze_lesson", "O'qituvchi dars yozuvini (audio/video) AI tahlil qiladi: tushuntirish sifati, o'quvchilar "
      "faolligi, dars rejasiga rioya. FAQAT o'qituvchi rozilik bergan bo'lsa ishlaydi.",
      {"teacher": S("O'qituvchi"), "group": S("Guruh (ixtiyoriy)"), "date": S("Dars sanasi (ixtiyoriy)")},
      ["teacher"], perm="analyze_lessons", write=True, confirm=True)
async def analyze_lesson(ctx, teacher, group=None, date=None):
    from . import brain, voice
    t = await _find_staff(ctx, teacher, roles={"teacher"})
    st = await db.one("select recording_consent from staff where id=%s", t["id"])
    if not st["recording_consent"]:
        raise ToolError(f"{t['full_name']} dars yozuvini tahlil qilishga rozilik bermagan. Avval o'qituvchiga ochiq "
                        "ayting; u botga «Jimi, dars yozuvi tahliliga roziman» deb yozsa, rozilik saqlanadi.")
    att = next((a for a in ctx.attachments if a.get("kind") in ("audio", "video")), None)
    if not att:
        raise ToolError("Dars yozuvini (audio yoki video fayl, 20 MB gacha) yuboring, keyin tahlilni so'rang.")
    if not voice.stt_enabled():
        raise ToolError("Nutqni matnga o'girish uchun ELEVENLABS_API_KEY kerak.")
    data = bytes(await (await rt.bot.get_file(att["file_id"])).download_as_bytearray())
    transcript = await voice.transcribe(data, filename=att.get("name") or "lesson.mp3", mime=att.get("mime") or "audio/mpeg")
    if len(transcript) < 200:
        raise ToolError("Yozuvdan yetarli nutq topilmadi.")
    analysis = await brain.quick(ANALYSIS_RUBRIC + "\n\nMATN:\n" + transcript[:60000],
                                 system="Siz tajribali metodist va o'qituvchilar murabbiysiz. O'zbek tilida yozing.",
                                 fast=False, max_tokens=6000)
    gid = (await Q.find_group(ctx, group))["id"] if group else None
    await db.ex("insert into lesson_reviews (teacher_id, group_id, lesson_date, transcript, analysis, created_by) "
                "values (%s,%s,%s,%s,%s,%s)", t["id"], gid, parse_date(date, today()), transcript, analysis, ctx.staff_id)
    return {"ok": True, "oqituvchi": t["full_name"], "tahlil": analysis}


# =====================================================================
#  SO'ROVNOMA VA SHARH
# =====================================================================
def survey_keyboard(survey_id):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"{n} ⭐", callback_data=f"sv:{survey_id}:{n}") for n in range(1, 6)]])


@tool("send_surveys", "Ota-onalarga qisqa so'rovnoma yuboradi (1-5 baho va izoh): oylik yoki kurs yakunida. "
      "5 baho berganlarga Google Maps sharh havolasi taklif qilinadi; 3 va undan pasti rahbarga bildiriladi.",
      {"kind": S("oylik | kurs_yakuni"), "group": S("Faqat shu guruh (ixtiyoriy)")}, ["kind"],
      perm="send_surveys", write=True, confirm=True)
async def send_surveys(ctx, kind, group=None):
    if kind not in ("oylik", "kurs_yakuni"):
        raise ToolError("kind: oylik yoki kurs_yakuni.")
    bids = await Q.branch_ids_for(ctx)
    gid = (await Q.find_group(ctx, group))["id"] if group else None
    rows = await db.q(
        """select distinct on (p.id, s.id) p.id as pid, p.telegram_id, s.id as sid, s.full_name, g.id as gid, g.name,
                  t.staff_id as tid
           from enrollments e join students s on s.id = e.student_id join groups g on g.id = e.group_id
           left join teachers t on t.id = g.teacher_id
           join student_parents sp on sp.student_id = s.id join parents p on p.id = sp.parent_id
           where e.status = 'active' and p.telegram_id is not null and g.branch_id = any(%s)
             and (%s::uuid is null or g.id = %s::uuid)
             and not exists (select 1 from surveys v where v.parent_id = p.id and v.student_id = s.id
                             and v.kind = %s and v.sent_at > now() - interval '20 days')""",
        bids, gid, gid, kind)
    sent = 0
    for r in rows:
        sv = await db.one("insert into surveys (kind, student_id, parent_id, group_id, teacher_id) values (%s,%s,%s,%s,%s) "
                          "returning id", kind, r["sid"], r["pid"], r["gid"], r["tid"])
        q_ = (f"Assalomu alaykum! {config.CENTER_NAME}. Farzandingiz {r['full_name']} «{r['name']}» guruhida o'qimoqda. "
              + ("Shu oy darslardan qanchalik mamnunsiz?" if kind == "oylik" else
                 "Kurs yakunlandi. Umumiy taassurotingizni baholang:") + " (1 — yomon, 5 — a'lo)")
        try:
            await rt.bot.send_message(r["telegram_id"], q_, reply_markup=survey_keyboard(sv["id"]))
            sent += 1
        except Exception:
            log.warning("so'rovnoma yuborilmadi")
    return {"ok": True, "yuborildi": sent}


async def survey_answer(survey_id, rating, tg_user):
    """Ota-ona tugmani bosganda. Qaytaradi: javob matni."""
    from .tools_media import get_setting
    sv = await db.one("update surveys set rating=%s, status='answered', answered_at=now() where id::text=%s "
                      "and parent_id in (select id from parents where telegram_id=%s) returning *, "
                      "(select full_name from students where id = surveys.student_id) as student",
                      int(rating), str(survey_id), tg_user)
    if not sv:
        return "So'rovnoma topilmadi."
    text = "Rahmat! Fikringizni bir-ikki gap bilan yozib qoldirsangiz, juda xursand bo'lamiz (ixtiyoriy)."
    review = await get_setting("review_url")
    if int(rating) == 5 and review and sv["kind"] == "kurs_yakuni":
        text += f"\n\nYuqori bahoingiz uchun rahmat! Google Maps'da qisqa sharh qoldirsangiz, boshqa ota-onalarga yordam beradi: {review}"
    if int(rating) <= 3:
        bosses = await db.q("select telegram_id from staff where is_active and telegram_id is not null "
                            "and role in ('owner','manager')")
        for b in bosses:
            await send_tg(b["telegram_id"], f"⚠️ Past baho ({rating}/5): {sv['student']} ota-onasi. Izoh kelsa, yuboraman.")
    return text


async def survey_comment(tg_user, text):
    """Baho berilgandan keyin 3 soat ichida yozilgan matn = izoh. True qaytarsa, xabar shu yerda ishlandi."""
    sv = await db.one("""update surveys set comment=%s where id = (select v.id from surveys v join parents p on p.id = v.parent_id
                         where p.telegram_id=%s and v.status='answered' and v.comment is null
                         and v.answered_at > now() - interval '3 hours' order by v.answered_at desc limit 1)
                         returning rating, (select full_name from students where id = surveys.student_id) as student""",
                      text[:2000], tg_user)
    if not sv:
        return False
    if sv["rating"] <= 3:
        for b in await db.q("select telegram_id from staff where is_active and telegram_id is not null "
                            "and role in ('owner','manager')"):
            await send_tg(b["telegram_id"], f"💬 {sv['student']} ota-onasi izohi ({sv['rating']}/5): {text[:800]}")
    return True


@tool("survey_report", "So'rovnoma natijalari: o'rtacha baho, o'qituvchi va guruh bo'yicha, izohlar.",
      {"days": N("Davr (standart 60)")}, perm="view_quality")
async def survey_report(ctx, days=60):
    rows = await db.q(
        """select st.full_name as oqituvchi, g.name as guruh, count(v.rating) as javoblar,
                  round(avg(v.rating)::numeric, 2) as ortacha,
                  array_remove(array_agg(v.comment order by v.answered_at desc), null) as izohlar
           from surveys v left join staff st on st.id = v.teacher_id left join groups g on g.id = v.group_id
           where v.answered_at >= now() - make_interval(days => %s::int)
           group by st.full_name, g.name order by ortacha nulls last""", int(days))
    sent = await db.one("select count(*) as n from surveys where sent_at >= now() - make_interval(days => %s::int)", int(days))
    for r in rows:
        r["izohlar"] = (r["izohlar"] or [])[:5]
    return {"yuborilgan": sent["n"], "natijalar": rows}


# =====================================================================
#  O'QUVCHINI USHLAB QOLISH
# =====================================================================
async def compute_risks(bids):
    rows = await db.q(
        """select e.id as eid, s.id as sid, s.full_name, g.name as guruh, g.branch_id, e.unpaid_cycles,
                  (select count(*) filter (where a.status='absent') from attendance a where a.enrollment_id = e.id
                     and a.lesson_date >= current_date - 14) as kelmagan_14kun,
                  (select count(*) from attendance a where a.enrollment_id = e.id and a.lesson_date >= current_date - 14) as darslar_14kun,
                  (select count(*) filter (where a.status='absent')::float / nullif(count(*),0) from attendance a
                     where a.enrollment_id = e.id and a.lesson_date between current_date - 60 and current_date - 15) as oldingi_kelmaslik,
                  (select array_agg(x.score order by x.exam_date desc) from (select score, exam_date from exams
                     where student_id = s.id and group_id = g.id order by exam_date desc limit 2) x) as oxirgi_ballar,
                  (select min(v.rating) from surveys v where v.student_id = s.id and v.answered_at > now() - interval '45 days') as past_baho
           from enrollments e join students s on s.id = e.student_id join groups g on g.id = e.group_id
           where e.status = 'active' and s.status = 'active' and g.branch_id = any(%s)""", bids)
    out = []
    for r in rows:
        reasons = []
        if r["kelmagan_14kun"] >= 2 and r["darslar_14kun"]:
            ratio = r["kelmagan_14kun"] / r["darslar_14kun"]
            prev = r["oldingi_kelmaslik"] or 0
            if ratio >= 0.34 and ratio > prev + 0.15:
                reasons.append(f"davomat pasaydi: 2 haftada {r['kelmagan_14kun']}/{r['darslar_14kun']} dars qoldirdi")
        sc = r["oxirgi_ballar"] or []
        if len(sc) == 2 and sc[0] is not None and sc[1] is not None and float(sc[0]) < float(sc[1]) * 0.9:
            reasons.append(f"baho tushdi: {float(sc[1]):g} -> {float(sc[0]):g}")
        if (r["unpaid_cycles"] or 0) >= 1:
            reasons.append("to'lov kechikkan")
        if r["past_baho"] is not None and r["past_baho"] <= 3:
            reasons.append(f"ota-ona bahosi past ({r['past_baho']}/5)")
        if reasons and (len(reasons) >= 2 or "davomat" in reasons[0]):
            out.append({"eid": r["eid"], "student_id": r["sid"], "ism": r["full_name"], "guruh": r["guruh"],
                        "branch_id": r["branch_id"], "sabablar": reasons, "xavf": "yuqori" if len(reasons) >= 2 else "o'rta"})
    out.sort(key=lambda x: -len(x["sabablar"]))
    return out


@tool("retention_risks", "Ketib qolish xavfi bor o'quvchilar: davomati yoki bahosi pasaygan, to'lovi kechikkan, "
      "ota-onasi past baho bergan. Har biriga sabab va tavsiya.", {"branch": S("Filial (ixtiyoriy)")})
async def retention_risks(ctx, branch=None):
    rows = await compute_risks(await Q.branch_ids_for(ctx, branch))
    for r in rows:
        r.pop("eid"), r.pop("branch_id")
    return {"soni": len(rows), "royxat": rows,
            "tavsiya": "Admin ota-ona bilan qo'ng'iroq qilsin; kerak bo'lsa message_parents bilan yumshoq xabar."}


async def retention_job():
    """Har kuni: yangi xavf signallari admin/managerlarga (bir o'quvchi haftada bir marta)."""
    branches = await db.q("select id from branches where is_active")
    week = today() - timedelta(days=today().weekday())
    for b in branches:
        new = []
        for r in await compute_risks([b["id"]]):
            ok = await db.one("insert into retention_alerts (enrollment_id, week_start, reasons) values (%s,%s,%s) "
                              "on conflict do nothing returning id", r["eid"], week, "; ".join(r["sabablar"]))
            if ok:
                new.append(r)
        if not new:
            continue
        text = "🔔 Ketib qolish xavfi bor o'quvchilar:\n" + "\n".join(
            f"• {r['ism']} ({r['guruh']}): {', '.join(r['sabablar'])}" for r in new[:15])
        text += "\n\nOta-ona bilan bog'laning. Jimi xabar matnini tayyorlab beradi: «Jimi, Alining ota-onasiga yumshoq xabar yoz»."
        staff = await db.q("""select distinct s.telegram_id from staff s join staff_branch_access a on a.staff_id = s.id
                              where s.is_active and s.telegram_id is not null and s.role in ('admin','manager')
                              and a.branch_id = %s""", b["id"])
        for s in staff:
            await send_tg(s["telegram_id"], text)


# =====================================================================
#  REFERRAL (do'stini olib kelish)
# =====================================================================
@tool("add_referral", "O'quvchi do'stini olib kelganini yozadi; bonus (oylik to'lovdan foiz) hisoblanadi va do'sti "
      "birinchi to'lovni qilganda avtomatik tasdiqlanadi.",
      {"referrer": S("Olib kelgan o'quvchi"), "new_student": S("Yangi o'quvchi (agar yozilgan bo'lsa)"),
       "note": S("Izoh (masalan do'stining ismi/telefoni)")}, ["referrer"], perm="manage_referrals", write=True)
async def add_referral(ctx, referrer, new_student=None, note=None):
    from .tools_media import get_setting
    ref = await Q.find_student(ctx, referrer)
    new = await Q.find_student(ctx, new_student) if new_student else None
    pct = float(await get_setting("referral_bonus_percent", "10") or 10)
    fee = await db.one("select monthly_fee from enrollments where student_id=%s and status='active' "
                       "and monthly_fee is not null order by joined_on limit 1", ref["id"])
    amount = int(float(fee["monthly_fee"]) * pct / 100) if fee else None
    await db.ex("insert into referrals (referrer_student_id, new_student_id, bonus_percent, bonus_amount, note, created_by) "
                "values (%s,%s,%s,%s,%s,%s)", ref["id"], new["id"] if new else None, pct, amount, note, ctx.staff_id)
    return {"ok": True, "olib_keldi": ref["full_name"], "yangi": new["full_name"] if new else None,
            "bonus": f"{pct:g}% ≈ {fmt_money(amount)}" if amount else f"{pct:g}%"}


async def referral_on_payment(student_id):
    """Yangi o'quvchi to'lov qilganda referralni tasdiqlaydi va adminlarga bildiradi."""
    rows = await db.q("update referrals set status='tasdiqlandi' where new_student_id=%s and status='kutilmoqda' "
                      "returning bonus_amount, (select full_name from students where id = referrer_student_id) as who",
                      student_id)
    for r in rows:
        for s in await db.q("select telegram_id from staff where is_active and telegram_id is not null "
                            "and role in ('owner','manager','admin')"):
            await send_tg(s["telegram_id"], f"🎁 Referral tasdiqlandi: {r['who']} bonus oladi ({fmt_money(r['bonus_amount'])}).")


@tool("list_referrals", "Referrallar ro'yxati va bonuslar.", {"status": S("kutilmoqda | tasdiqlandi | berildi (ixtiyoriy)")},
      perm="manage_referrals")
async def list_referrals(ctx, status=None):
    rows = await db.q(
        """select r.id, a.full_name as olib_kelgan, b.full_name as yangi, r.bonus_percent, r.bonus_amount, r.status,
                  r.note, r.created_at::date as sana
           from referrals r join students a on a.id = r.referrer_student_id left join students b on b.id = r.new_student_id
           where (%s::text is null or r.status = %s) order by r.created_at desc limit 50""", status, status)
    return {"referrallar": rows}


@tool("set_referral_status", "Referral holatini o'zgartiradi (masalan bonus berildi).",
      {"referral": S("Referral id"), "status": S("tasdiqlandi | berildi | bekor")}, ["referral", "status"],
      perm="manage_referrals", write=True)
async def set_referral_status(ctx, referral, status):
    if status not in ("tasdiqlandi", "berildi", "bekor"):
        raise ToolError("Holat: tasdiqlandi, berildi yoki bekor.")
    r = await db.one("update referrals set status=%s where id::text=%s returning id", status, str(referral))
    if not r:
        raise ToolError("Referral topilmadi.")
    return {"ok": True}


# =====================================================================
#  YOLLASH
# =====================================================================
DEFAULT_QUESTIONS = ["Tajribangiz haqida qisqacha yozing (qayerda, necha yil).",
                     "Qaysi fan yoki yo'nalish bo'yicha ishlamoqchisiz? Sertifikatlaringiz bormi?",
                     "Qaysi kunlar va soatlarda ishlay olasiz?"]


@tool("create_vacancy", "Vakansiya ochadi va nomzodlar ariza beradigan bot havolasini qaytaradi (nomzod botda savollarga "
      "javob beradi, AI dastlabki saralaydi va sizga yuboradi). E'lon matnini o'zingiz yozib bering.",
      {"title": S("Lavozim, masalan 'Ingliz tili o'qituvchisi (IELTS 7+)'"), "description": S("Ish sharoiti"),
       "requirements": S("Talablar"), "questions": LS("Nomzodga beriladigan savollar (ixtiyoriy)")},
      ["title"], perm="manage_hiring", write=True)
async def create_vacancy(ctx, title, description=None, requirements=None, questions=None):
    row = await db.one("insert into vacancies (title, description, requirements, questions, created_by) "
                       "values (%s,%s,%s,%s,%s) returning id, code", title, description, requirements,
                       questions or DEFAULT_QUESTIONS, ctx.staff_id)
    return {"ok": True, "vakansiya_id": row["id"], "ariza_havolasi": invite_link("vk", row["code"]),
            "eslatma": "Havolani e'lon ostiga qo'ying (kanal, HH, Telegram guruhlar)."}


async def screen_candidate(cand_id):
    from . import brain
    c = await db.one("select c.*, v.title, v.requirements from candidates c left join vacancies v on v.id = c.vacancy_id "
                     "where c.id=%s", cand_id)
    raw = await brain.quick(
        f"Lavozim: {c['title']}\nTalablar: {c['requirements'] or '-'}\nNomzod: {c['full_name']}\nJavoblari: "
        f"{json.dumps(c['answers'], ensure_ascii=False)}\n\nFAQAT JSON qaytaring: "
        '{"score": 1-10, "summary": "2-3 gap: kuchli tomonlar, xavotirlar, suhbatda nimani so\'rash"}',
        system="Siz o'quv markazining HR mutaxassisisiz. Adolatli, faqat javoblarga tayanib baholang.", fast=True,
        max_tokens=1500)
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        d = json.loads(m.group()) if m else {}
    except json.JSONDecodeError:
        d = {}
    score = int(d.get("score") or 0) or None
    await db.ex("update candidates set ai_score=%s, ai_summary=%s, status='saralandi' where id=%s",
                score, d.get("summary"), cand_id)
    for s in await db.q("""select s.telegram_id from staff s join role_permissions rp on rp.role = s.role
                           where s.is_active and s.telegram_id is not null and
                           (s.role = 'owner' or (rp.action = 'manage_hiring' and rp.level = 'allow'))"""):
        await send_tg(s["telegram_id"], f"🧑‍💼 Yangi nomzod: {c['full_name']} ({c['phone']}) — {c['title']}\n"
                                        f"AI baho: {score or '?'}/10\n{d.get('summary') or ''}")


@tool("list_candidates", "Nomzodlar ro'yxati (AI bahosi bilan).",
      {"status": S("yangi | saralandi | suhbat | qabul | rad (ixtiyoriy)")}, perm="manage_hiring")
async def list_candidates(ctx, status=None):
    rows = await db.q(
        """select c.id, c.full_name, c.phone, v.title as vakansiya, c.ai_score, c.ai_summary, c.status, c.interview_at,
                  c.created_at::date as sana from candidates c left join vacancies v on v.id = c.vacancy_id
           where (%s::text is null or c.status = %s) order by c.ai_score desc nulls last, c.created_at desc limit 50""",
        status, status)
    return {"nomzodlar": rows}


@tool("update_candidate", "Nomzod holatini o'zgartiradi; suhbat vaqti belgilansa nomzodga Telegramda xabar boradi.",
      {"candidate": S("Nomzod ismi yoki id"), "status": S("suhbat | qabul | rad"),
       "interview_at": S("Suhbat vaqti '2026-12-01 15:00'"), "message": S("Nomzodga qo'shimcha xabar (ixtiyoriy)")},
      ["candidate", "status"], perm="manage_hiring", write=True, confirm=True)
async def update_candidate(ctx, candidate, status, interview_at=None, message=None):
    from .tools import parse_dt
    rows = await db.q("select id, full_name, telegram_id from candidates order by created_at desc limit 300")
    hit = next((r for r in rows if str(r["id"]) == str(candidate)), None)
    if not hit:
        h = fuzzy(candidate, [(r["id"], r["full_name"] or "") for r in rows], limit=1)
        hit = next((r for r in rows if h and r["id"] == h[0][1]), None)
    if not hit:
        raise ToolError("Nomzod topilmadi.")
    when = parse_dt(interview_at, "15:00") if interview_at else None
    await db.ex("update candidates set status=%s, interview_at=coalesce(%s, interview_at) where id=%s", status, when, hit["id"])
    if hit["telegram_id"]:
        txt = {"suhbat": f"Assalomu alaykum! Arizangiz ko'rib chiqildi. Sizni suhbatga taklif qilamiz"
                         + (f": {when:%d.%m.%Y %H:%M}" if when else "") + ".",
               "qabul": "Tabriklaymiz! Siz ishga qabul qilindingiz. Tez orada bog'lanamiz.",
               "rad": "Arizangiz uchun rahmat. Hozircha boshqa nomzodni tanladik, sizga omad tilaymiz."}.get(status, "")
        if message:
            txt += "\n" + message
        if txt:
            await send_tg(hit["telegram_id"], txt)
    return {"ok": True, "nomzod": hit["full_name"], "holat": status}


# =====================================================================
#  JADVAL VA XONALAR
# =====================================================================
@tool("schedule_overview", "Filial jadvali: xonalar va o'qituvchilar bandligi (kun/vaqt), guruh sig'imi va bo'sh joylar.",
      {"branch": S("Filial")}, ["branch"])
async def schedule_overview(ctx, branch):
    br = await single_branch(ctx, branch)
    rows = await db.q(
        """select g.name, g.days, g.start_time, g.end_time, r.name as room, st.full_name as teacher, g.capacity,
                  (select count(*) from enrollments e where e.group_id = g.id and e.status = 'active') as students
           from groups g left join rooms r on r.id = g.room_id left join teachers t on t.id = g.teacher_id
           left join staff st on st.id = t.staff_id where g.is_active and g.branch_id = %s
           order by r.name, g.start_time""", br["id"])
    rooms = {}
    teachers = {}
    for g in rows:
        rooms.setdefault(g["room"] or "xonasiz", []).append(f"{_sched(g['days'], g['start_time'], g['end_time'])}: {g['name']}")
        if g["teacher"]:
            hrs = len(g["days"]) * (datetime.combine(today(), g["end_time"]) - datetime.combine(today(), g["start_time"])).seconds / 3600
            teachers[g["teacher"]] = teachers.get(g["teacher"], 0) + hrs
    return {"filial": br["name"], "xonalar": rooms, "oqituvchi_soat_haftasiga": teachers,
            "bosh_joylar": [{"guruh": g["name"], "sigim": g["capacity"], "oquvchi": g["students"],
                             "bosh": max(g["capacity"] - g["students"], 0)} for g in rows]}


@tool("suggest_slots", "Yangi guruh uchun to'qnashuvsiz bo'sh vaqt va xonalarni taklif qiladi (o'qituvchi bandligini ham hisobga oladi).",
      {"branch": S("Filial"), "days": LN("Kunlar: 1=Du ... 7=Yak"), "duration_hours": N("Dars davomiyligi (standart 2)"),
       "teacher": S("O'qituvchi (ixtiyoriy)"), "from_hour": N("Eng erta (standart 8)"), "to_hour": N("Eng kech tugash (standart 20)")},
      ["branch", "days"])
async def suggest_slots(ctx, branch, days, duration_hours=2, teacher=None, from_hour=8, to_hour=20):
    br = await single_branch(ctx, branch)
    days = [int(d) for d in days]
    rooms = await db.q("select id, name from rooms where branch_id=%s order by name", br["id"])
    busy = await db.q("select room_id, days, start_time, end_time from groups where is_active and branch_id=%s", br["id"])
    tbusy = []
    if teacher:
        t = await _find_staff(ctx, teacher, roles={"teacher"})
        tbusy = await db.q("select g.days, g.start_time, g.end_time from groups g join teachers tt on tt.id = g.teacher_id "
                           "where g.is_active and tt.staff_id=%s", t["id"])
    out = []
    dur = timedelta(hours=float(duration_hours))
    h = int(from_hour)
    while h * 60 + dur.seconds // 60 <= int(to_hour) * 60:
        s = dtime(h, 0)
        e = (datetime.combine(today(), s) + dur).time()
        clash_t = any(set(g["days"]) & set(days) and g["start_time"] < e and g["end_time"] > s for g in tbusy)
        if not clash_t:
            free = [r["name"] for r in rooms if not any(b["room_id"] == r["id"] and set(b["days"]) & set(days)
                                                         and b["start_time"] < e and b["end_time"] > s for b in busy)]
            if free:
                out.append({"vaqt": f"{s:%H:%M}-{e:%H:%M}", "bosh_xonalar": free})
        h += 1
    return {"filial": br["name"], "kunlar": [DAY_NAMES[d] for d in days], "variantlar": out}


# =====================================================================
#  O'QUVCHI KETDI
# =====================================================================
@tool("student_left", "O'quvchi markazni tark etganini belgilaydi (sababi bilan). Guruhdan chiqariladi, ketish "
      "statistikasi va haftalik hisobotda ko'rinadi.",
      {"student": S("O'quvchi"), "reason": S("Sabab: narx, vaqt, ko'chdi, natija, o'qituvchi, boshqa"),
       "group": S("Faqat shu guruhdan (ixtiyoriy; bo'sh = markazdan butunlay)")},
      ["student", "reason"], perm="add_student", write=True, confirm=True)
async def student_left(ctx, student, reason, group=None):
    st = await Q.find_student(ctx, student)
    if group:
        enr = await Q.find_enrollment(ctx, st["id"], group)
        await db.ex("update enrollments set status='left', left_on=current_date where id=%s", enr["id"])
        left_all = not await db.one("select 1 from enrollments where student_id=%s and status <> 'left'", st["id"])
    else:
        await db.ex("update enrollments set status='left', left_on=current_date where student_id=%s and status <> 'left'",
                    st["id"])
        left_all = True
    if left_all:
        await db.ex("update students set status='left', left_on=current_date, left_reason=%s where id=%s", reason, st["id"])
    return {"ok": True, "oquvchi": st["full_name"], "markazdan_ketdi": left_all}


@tool("weekly_report_data", "Haftalik hisobot raqamlari: murojaat konversiyasi, tushum, qarz, bo'sh joylar, davomat va ketish, "
      "marketing (post/reklama), o'qituvchilar.", perm="view_finance")
async def weekly_report_data(ctx):
    from .reports import weekly_data
    return await weekly_data(await Q.branch_ids_for(ctx))
