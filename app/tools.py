"""Agent vositalari (tools).

Har bir vosita = bitta aniq amal. Xavfsizlik shu yerda kod bilan ta'minlanadi:
  1. ruxsat (rol)            -> role_permissions jadvali
  2. filial doirasi          -> staff_branch_access jadvali
  3. egasining tasdig'i      -> approval_requests (needs_owner_approval)
  4. foydalanuvchi tasdig'i  -> pending_actions ("ha" deguncha bajarilmaydi)
  5. jurnal                  -> audit_log
"""
import json
import logging
import secrets
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from . import config, db, exports, social
from .core import (DAY_NAMES, ROLE_UZ, Ctx, ToolError, apply_payment, fmt_money, fuzzy, invite_link,
                   norm, now, parse_date, payment_state, rt, send_tg, today)
from . import queries as Q

log = logging.getLogger("wstizim.tools")

TOOLS: dict = {}
TEACHER_TOOLS = {"confirm_pending_action", "mark_attendance", "group_attendance", "add_exam_result", "find_student",
                 "list_tasks", "update_task", "add_homework", "check_homework"}


# ---------- sxema yordamchilari ----------
def S(desc):
    return {"type": "string", "description": desc}


def N(desc):
    return {"type": "number", "description": desc}


def B(desc):
    return {"type": "boolean", "description": desc}


def LS(desc):
    return {"type": "array", "items": {"type": "string"}, "description": desc}


def LN(desc):
    return {"type": "array", "items": {"type": "integer"}, "description": desc}


DAYS_HELP = "Hafta kunlari raqamlari: 1=Dushanba, 2=Seshanba, 3=Chorshanba, 4=Payshanba, 5=Juma, 6=Shanba, 7=Yakshanba"


@dataclass
class Tool:
    name: str
    fn: object
    schema: dict
    perm: str | None
    write: bool
    confirm: bool
    roles: set | None


def tool(name, desc, props=None, req=None, perm=None, write=False, confirm=False, roles=None):
    props = dict(props or {})
    req = list(req or [])
    if write:
        props["summary"] = S("Amalning odam tushunadigan qisqa tavsifi, masalan: 'Ali (Ingliz 1) ota-onasiga "
                             "kelmagani haqida xabar'. Tasdiq so'rovida ko'rsatiladi.")
        req.append("summary")

    def deco(fn):
        TOOLS[name] = Tool(name, fn, {"name": name, "description": desc,
                                       "input_schema": {"type": "object", "properties": props, "required": req}},
                           perm, write, confirm, roles)
        return fn
    return deco


def visible(ctx: Ctx, t: Tool) -> bool:
    """Bu foydalanuvchi shu vositani ko'ra oladimi?"""
    if ctx.readonly and t.write:
        return False
    if t.roles is not None:
        return ctx.role in t.roles
    if ctx.role == "teacher":
        # O'qituvchi faqat o'z guruhlari bilan ishlaydi (queries.find_group buni cheklaydi)
        return t.name in TEACHER_TOOLS and not (t.perm and ctx.level(t.perm) == "deny")
    if t.perm and ctx.level(t.perm) == "deny":
        return False
    return True


# ---------- jurnal, tasdiq, kutilayotgan amallar ----------
async def audit(ctx, name, args, summary):
    try:
        await db.ex("insert into audit_log (actor_id, action, details) values (%s, %s, %s)",
                    ctx.staff_id, name, db.js({"args": args, "summary": summary, "egasi_tasdiqlagan": ctx.bypass}))
    except Exception:
        log.exception("audit yozilmadi")


async def store_pending(ctx, t, args, summary):
    await db.ex("update pending_actions set status='replaced' where staff_id=%s and status='pending'", ctx.staff_id)
    await db.ex("insert into pending_actions (staff_id, tool, args, summary, created_at) values (%s,%s,%s,%s,%s)",
                ctx.staff_id, t.name, db.js(args), summary, datetime.now(timezone.utc))
    return {"status": "awaiting_user_confirmation", "amal": summary,
            "korsatma": "Foydalanuvchiga nima qilmoqchi ekaningizni aniq ayting va 'ha' deb tasdiqlashini kuting. "
                        "U tasdiqlagandan KEYIN (keyingi xabarida) confirm_pending_action(confirm=true) chaqiring."}


async def request_approval(ctx, t, args, summary):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    row = await db.one(
        "insert into approval_requests (requested_by, action, payload) values (%s,%s,%s) returning id",
        ctx.staff_id, t.perm, db.js({"tool": t.name, "args": args, "summary": summary}))
    owners = await db.q("select telegram_id from staff where role='owner' and is_active and telegram_id is not null")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"ap:{row['id']}:y"),
                                InlineKeyboardButton("❌ Rad etish", callback_data=f"ap:{row['id']}:n")]])
    detail = json.dumps(args, ensure_ascii=False)[:600]
    for o in owners:
        await rt.bot.send_message(
            o["telegram_id"],
            f"🔔 Tasdiq so'rovi\n{ctx.staff['full_name']} ({ROLE_UZ.get(ctx.role, ctx.role)}) so'raydi:\n"
            f"{summary}\n\nTafsilot: {detail}\n\nTugmani bosing yoki menga «tasdiqla» / «rad et» deng.",
            reply_markup=kb)
    return {"status": "sent_to_owner",
            "xabar": "So'rov rahbarga tasdiq uchun yuborildi. Tasdiqlansa, avtomatik bajariladi va sizga xabar keladi."}


async def execute_approval(approval_id, approve, decider):
    """Egasi tasdiqlaganda yoki rad etganda chaqiriladi (tugma yoki ovoz orqali)."""
    row = await db.one("select * from approval_requests where id=%s", approval_id)
    if not row or row["status"] != "pending":
        return "Bu so'rov topilmadi yoki allaqachon ko'rib chiqilgan."
    await db.ex("update approval_requests set status=%s::request_status, decided_by=%s, decided_at=now() where id=%s",
                "approved" if approve else "rejected", decider["id"], approval_id)
    requester = await db.one("select * from staff where id=%s", row["requested_by"])
    payload = row["payload"]
    summary = payload.get("summary", payload["tool"])
    if not approve:
        if requester and requester["telegram_id"]:
            await send_tg(requester["telegram_id"], f"❌ Rahbar rad etdi: {summary}")
        return f"Rad etildi: {summary}"
    # Egasi aniq shu amalni ko'rib tasdiqladi, shuning uchun u egasi doirasida bajariladi
    rctx = await Q.make_ctx(requester, msg_time=now(), chat_id=requester["telegram_id"], bypass=True, confirmed=True)
    rctx.branch_ids = None
    res = await dispatch(rctx, payload["tool"], {**payload["args"], "summary": summary})
    if isinstance(res, dict) and "error" in res:
        text = f"Rahbar tasdiqladi, lekin bajarilmadi: {res['error']}"
    else:
        text = f"✅ Rahbar tasdiqladi va bajarildi: {summary}"
    if requester and requester["telegram_id"]:
        await send_tg(requester["telegram_id"], text)
    return text


# ---------- markaziy dispatcher ----------
async def dispatch(ctx: Ctx, name: str, args: dict):
    t = TOOLS.get(name)
    if not t:
        return {"error": f"Noma'lum vosita: {name}"}
    args = dict(args or {})
    summary = args.pop("summary", None) or f"{name} {json.dumps(args, ensure_ascii=False)[:200]}"
    # Yuborilgan rasm/video tasdiq kutilayotganda yo'qolmasin: amal bilan birga saqlanadi
    if "_attachments" in args:
        ctx = replace(ctx, attachments=args.pop("_attachments") or [])
    files = [{k: a.get(k) for k in ("kind", "url", "file_id")} for a in ctx.attachments]
    if not ctx.bypass and not visible(ctx, t):
        if ctx.readonly and t.write:
            return {"error": "Hozir faqat o'qish rejimi: amal bajarilmaydi. Taklif sifatida yozib qo'ying."}
        return {"error": "Sizda bu amal uchun ruxsat yo'q."}
    try:
        keep = {**args, "_attachments": files} if files else args
        if t.write and t.perm and not ctx.bypass and ctx.level(t.perm) == "needs_owner_approval":
            return await request_approval(ctx, t, keep, summary)
        if t.write and t.confirm and not (ctx.confirmed or ctx.bypass):
            return await store_pending(ctx, t, keep, summary)
        result = await t.fn(ctx, **args)
        if t.write:
            await audit(ctx, name, args, summary)
        return result
    except ToolError as e:
        return {"error": str(e)}
    except TypeError as e:
        log.exception("vosita parametr xatosi")
        return {"error": f"Parametrlar noto'g'ri: {e}"}
    except Exception as e:
        log.exception("vosita xatosi: %s", name)
        return {"error": f"Ichki xato ({type(e).__name__}): {str(e)[:200]}"}


# ---------- umumiy yordamchilar ----------
def same_person(a, b):
    """Takroriy o'quvchi: bir xil so'zlar (tartibi farqli bo'lsa ham) yoki juda kichik yozuv farqi."""
    import difflib
    ta, tb = sorted(norm(a).split()), sorted(norm(b).split())
    if ta == tb:
        return True
    return difflib.SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio() >= 0.92

async def single_branch(ctx, branch=None):
    rows = await Q.branches_for(ctx, branch, active_only=(branch is None))
    if len(rows) > 1:
        raise ToolError("Qaysi filial? Variantlar: " + ", ".join(r["name"] for r in rows))
    return rows[0]


def _t(s):
    try:
        return datetime.strptime(str(s).strip(), "%H:%M").time()
    except ValueError:
        raise ToolError(f"Vaqtni tushunmadim: {s} (format: 14:00)")


def _sched(days, start, end):
    return f"{'/'.join(DAY_NAMES[d][:3] for d in days)} {str(start)[:5]}-{str(end)[:5]}"


async def _find_staff(ctx, query, roles=None):
    rows = [r for r in await staff_in_scope(ctx) if r["role"] != "owner"]
    if roles:
        rows = [r for r in rows if r["role"] in roles]
    for r in rows:
        if str(r["id"]) == str(query):
            return r
    hits = fuzzy(query, [(r["id"], r["full_name"]) for r in rows], limit=3)
    if not hits:
        raise ToolError(f"Xodim topilmadi: {query}. Xodimlar: " + ", ".join(r["full_name"] for r in rows[:15]))
    exact = [h for h in hits if h[0] >= 0.97]
    if len(exact) > 1 or (not exact and len(hits) > 1 and hits[0][0] - hits[1][0] < 0.1):
        raise ToolError("Bir nechta xodim mos keldi: " + ", ".join(h[2] for h in (exact or hits)) + ". Qaysi biri?")
    return next(r for r in rows if r["id"] == hits[0][1])


# =====================================================================
#  O'QISH / TAHLIL VOSITALARI
# =====================================================================
@tool("overview", "Filiallar, xonalar va guruhlar ro'yxati: jadval, o'qituvchi, xona, o'quvchilar soni.",
      {"branch": S("Filial nomi (ixtiyoriy)")})
async def overview(ctx, branch=None):
    brs = await Q.branches_for(ctx, branch)
    bids = [b["id"] for b in brs]
    groups = await db.q(
        """select g.id, g.name, g.subject, b.name as branch, ts.full_name as teacher, r.name as room,
                  g.days, g.start_time, g.end_time,
                  (select count(*) from enrollments e where e.group_id = g.id and e.status = 'active') as students
           from groups g join branches b on b.id = g.branch_id
           left join teachers t on t.id = g.teacher_id left join staff ts on ts.id = t.staff_id
           left join rooms r on r.id = g.room_id
           where g.is_active and g.branch_id = any(%s) order by b.name, g.name""", bids)
    rooms = await db.q("select r.name, b.name as branch from rooms r join branches b on b.id = r.branch_id "
                       "where r.branch_id = any(%s) order by b.name, r.name", bids)
    return {"filiallar": [{"nom": b["name"], "faol": b["is_active"]} for b in brs],
            "xonalar": [f'{r["branch"]}: {r["name"]}' for r in rooms],
            "guruhlar": [{"id": g["id"], "nom": g["name"], "fan": g["subject"], "filial": g["branch"],
                          "oqituvchi": g["teacher"], "xona": g["room"], "jadval": _sched(g["days"], g["start_time"], g["end_time"]),
                          "oquvchilar": g["students"]} for g in groups]}


@tool("find_student", "O'quvchini ism bo'yicha qidiradi (taxminiy moslik). Id va guruhlarini qaytaradi.",
      {"query": S("Ism yoki familiya"), "branch": S("Filial (ixtiyoriy)")}, ["query"])
async def find_student(ctx, query, branch=None):
    rows = await Q._student_rows(ctx, branch)
    hits = fuzzy(query, [(r["id"], r["full_name"]) for r in rows], limit=6)
    if not hits:
        return {"topildi": []}
    cands = await Q._candidates(ctx, [h[1] for h in hits])
    return {"topildi": cands}


@tool("student_profile", "O'quvchi haqida to'liq ma'lumot: guruhlar, to'lov holati, davomat, ota-ona, imtihonlar.",
      {"student": S("O'quvchi ismi yoki id")}, ["student"])
async def student_profile(ctx, student):
    st = await Q.find_student(ctx, student)
    can_money = ctx.level("view_finance") == "allow"
    full = await db.one("select full_name, status::text as status, joined_on, notes, invite_code from students "
                        "where id=%s", st["id"])
    parents = await db.q(
        """select p.full_name, p.phone, (p.telegram_id is not null) as telegramga_ulangan, sp.relation
           from student_parents sp join parents p on p.id = sp.parent_id where sp.student_id = %s""", st["id"])
    enr = await db.q(
        """select g.name as group_name, g.days, e.cycle_start, e.cycle_paid, e.unpaid_cycles, e.monthly_fee,
                  e.status::text as status from enrollments e join groups g on g.id = e.group_id
           where e.student_id = %s and e.status <> 'left'""", st["id"])
    for e in enr:
        e["tolov_holati"] = payment_state(e["cycle_start"], e["days"], e["cycle_paid"], e["unpaid_cycles"], today())
        e["oylik_tolov"] = int(e["monthly_fee"]) if (e["monthly_fee"] and can_money) else None
        for k in ("days", "monthly_fee", "cycle_paid"):
            e.pop(k, None)
    att = await db.q(
        """select a.lesson_date, a.status::text as status, g.name as group_name
           from attendance a join enrollments e on e.id = a.enrollment_id join groups g on g.id = e.group_id
           where e.student_id = %s order by a.lesson_date desc limit 10""", st["id"])
    exams = await db.q("select exam_name, exam_date, score, target_score from exams where student_id=%s "
                       "order by exam_date desc limit 5", st["id"])
    out = {"id": st["id"], "ism": full["full_name"], "holat": full["status"], "qoshilgan": full["joined_on"],
           "izoh": full["notes"], "ota_ona": parents, "guruhlar": enr, "oxirgi_davomat": att, "imtihonlar": exams,
           "ota_ona_havolasi": invite_link("pr", full["invite_code"])}
    if can_money:
        out["oxirgi_tolovlar"] = await db.q(
            """select p.paid_on, p.amount, g.name as group_name from payments p
               join enrollments e on e.id = p.enrollment_id join groups g on g.id = e.group_id
               where e.student_id = %s order by p.paid_on desc limit 5""", st["id"])
    return out


@tool("group_attendance", "Guruhning ma'lum kundagi davomati (keldi / kelmadi / belgilanmagan).",
      {"group": S("Guruh nomi"), "date": S("Sana, standart: bugun (2026-11-25)"), "branch": S("Filial (ixtiyoriy)")},
      ["group"])
async def group_attendance(ctx, group, date=None, branch=None):
    g = await Q.find_group(ctx, group, branch)
    d = parse_date(date, today())
    rows = await db.q(
        """select s.id, s.full_name, a.status::text as status from enrollments e
           join students s on s.id = e.student_id
           left join attendance a on a.enrollment_id = e.id and a.lesson_date = %s
           where e.group_id = %s and e.status = 'active' and s.status = 'active' order by s.full_name""", d, g["id"])
    return {"guruh": g["name"], "sana": d,
            "royxat": [{"id": r["id"], "ism": r["full_name"], "holat": r["status"] or "belgilanmagan"} for r in rows]}


@tool("debtors", "To'lov holati: qarzdorlar (muddati o'tgan) va to'lov oynasi ochiq (3-6 dars) o'quvchilar.",
      {"branch": S("Filial (ixtiyoriy)")})
async def debtors(ctx, branch=None):
    bids = await Q.branch_ids_for(ctx, branch)
    rows = await Q.payment_overview(bids)
    show = lambda r: {"ism": r["full_name"], "guruh": r["group_name"], "filial": r["branch"],
                      "oylik_tolov": int(r["monthly_fee"]) if r["monthly_fee"] else None,
                      "tolanmagan_tsikllar": max(r["unpaid_cycles"], 0), "tsikl_boshi": r["cycle_start"]}
    overdue = [show(r) for r in rows if r["state"] == "overdue"]
    window = [show(r) for r in rows if r["state"] == "window"]
    return {"qarzdorlar_soni": len(overdue), "qarzdorlar": overdue,
            "tolov_oynasi_ochiq_soni": len(window), "tolov_oynasi_ochiq": window}


@tool("absence_alerts", "Ketma-ket 3 darsga kelmagan faol o'quvchilar (muzlatish yoki aloqa qilish kerak bo'lishi mumkin).",
      {"branch": S("Filial (ixtiyoriy)")})
async def absence_alerts(ctx, branch=None):
    bids = await Q.branch_ids_for(ctx, branch)
    rows = await Q.absence_streaks(bids)
    return {"soni": len(rows), "royxat": [{"ism": r["full_name"], "guruh": r["group_name"],
                                           "filial": r["branch"]} for r in rows]}


@tool("finance_summary", "Moliyaviy xulosa: tushum, xarajat, reklama sarfi, taxminiy foyda.",
      {"period": S("this_month | last_month | last_30_days | this_week | today"),
       "branch": S("Filial (ixtiyoriy)")}, perm="view_finance")
async def finance_summary(ctx, period="this_month", branch=None):
    bids = await Q.branch_ids_for(ctx, branch)
    t = today()
    if period == "last_month":
        end = t.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    elif period == "last_30_days":
        start, end = t - timedelta(days=29), t
    elif period == "this_week":
        start, end = t - timedelta(days=t.weekday()), t
    elif period == "today":
        start, end = t, t
    else:
        start, end = t.replace(day=1), t
    return await Q.finance_summary(bids, start, end)


@tool("lead_stats", "Lidlar tahlili: manbalar va kampaniyalar bo'yicha lidlar soni, narxi, o'quvchiga aylanishi.",
      {"days": N("Necha kunlik davr (standart 30)"), "branch": S("Filial (ixtiyoriy)")}, perm="view_marketing")
async def lead_stats(ctx, days=30, branch=None):
    return await Q.lead_stats(await Q.branch_ids_for(ctx, branch), int(days))


@tool("list_leads", "Lidlar ro'yxati (so'nggilari).",
      {"status": S("new | contacted | trial | enrolled | rejected (ixtiyoriy)"), "branch": S("Filial (ixtiyoriy)"),
       "limit": N("Nechta (standart 20)")}, perm="manage_leads")
async def list_leads(ctx, status=None, branch=None, limit=20):
    bids = await Q.branch_ids_for(ctx, branch)
    rows = await db.q(
        """select l.id, l.created_at::date as sana, l.full_name, l.phone, l.source, l.status::text as status,
                  c.name as kampaniya, l.note
           from leads l left join campaigns c on c.id = l.campaign_id
           where (l.branch_id = any(%s) or l.branch_id is null)
             and (%s::text is null or l.status::text = %s::text)
           order by l.created_at desc limit %s""", bids, status, status, int(limit))
    return {"lidlar": rows}


@tool("teacher_report", "O'qituvchilar tahlili: davomat, imtihon natijalari, maqsad balliga yetganlar ulushi, tendensiya.",
      {"teacher": S("O'qituvchi ismi (ixtiyoriy, bo'lmasa hammasi)"), "branch": S("Filial (ixtiyoriy)")},
      perm="view_teacher_reports")
async def teacher_report(ctx, teacher=None, branch=None):
    bids = await Q.branch_ids_for(ctx, branch)
    tid = None
    if teacher:
        tid = (await _find_staff(ctx, teacher, roles={"teacher"}))["id"]
    return {"guruhlar": await Q.teacher_stats(bids, tid)}


@tool("my_report", "O'qituvchining o'z guruhlari natijalari.", roles={"teacher"})
async def my_report(ctx):
    all_b = [r["id"] for r in await db.q("select id from branches")]
    return {"guruhlar": await Q.teacher_stats(all_b, ctx.staff_id)}


@tool("free_rooms", "Berilgan kun va vaqtda bo'sh xonalarni topadi.",
      {"branch": S("Filial"), "days": LN(DAYS_HELP), "start_time": S("14:00"), "end_time": S("16:00")},
      ["branch", "days", "start_time", "end_time"])
async def free_rooms(ctx, branch, days, start_time, end_time):
    br = await single_branch(ctx, branch)
    s, e = _t(start_time), _t(end_time)
    days = [int(d) for d in days]
    rooms = await db.q("select id, name from rooms where branch_id=%s order by name", br["id"])
    busy = await db.q(
        """select distinct room_id from groups where is_active and branch_id = %s and room_id is not null
           and days && %s::smallint[] and start_time < %s and end_time > %s""", br["id"], days, e, s)
    busy_ids = {b["room_id"] for b in busy}
    return {"filial": br["name"], "bosh_xonalar": [r["name"] for r in rooms if r["id"] not in busy_ids],
            "band_xonalar": [r["name"] for r in rooms if r["id"] in busy_ids]}


@tool("list_staff", "Xodimlar ro'yxati: rol, filiallar, botga ulanganmi.", perm="view_staff")
async def list_staff(ctx):
    rows = await db.q(
        """select s.id, s.full_name, s.role::text as role, (s.telegram_id is not null) as botga_ulangan,
                  s.invite_code, coalesce(string_agg(b.name, ', '), '-') as filiallar
           from staff s left join staff_branch_access a on a.staff_id = s.id
           left join branches b on b.id = a.branch_id where s.is_active
           group by s.id order by s.role, s.full_name""")
    for r in rows:
        r["taklif_havolasi"] = invite_link("st", r["invite_code"]) if r["invite_code"] and not r["botga_ulangan"] else None
        r.pop("invite_code")
    return {"xodimlar": rows}


@tool("list_approvals", "Rahbar tasdig'ini kutayotgan so'rovlar.", roles={"owner"})
async def list_approvals(ctx):
    rows = await db.q(
        """select r.id, s.full_name as kim, r.payload->>'summary' as nima, r.created_at
           from approval_requests r join staff s on s.id = r.requested_by
           where r.status = 'pending' order by r.created_at""")
    return {"kutayotganlar": rows}


# =====================================================================
#  YOZISH VOSITALARI
# =====================================================================
@tool("add_student", "Yangi o'quvchini guruhga qo'shadi (ixtiyoriy: ota-ona ma'lumoti bilan). Ota-ona uchun Telegram "
      "havolasini qaytaradi.",
      {"full_name": S("Ism-familiya"), "group": S("Guruh nomi"), "parent_name": S("Ota-ona ismi"),
       "parent_phone": S("Ota-ona telefoni"), "monthly_fee": N("Oylik to'lov (so'm)"),
       "joined_on": S("Kelgan sana (standart bugun)"), "allow_duplicate": B("O'xshash ism bo'lsa ham qo'shish")},
      ["full_name", "group"], perm="add_student", write=True)
async def add_student(ctx, full_name, group, parent_name=None, parent_phone=None, monthly_fee=None,
                      joined_on=None, allow_duplicate=False):
    g = await Q.find_group(ctx, group)
    existing = await db.q("select id, full_name from students where branch_id=%s and status <> 'left'", g["branch_id"])
    dup = [r["full_name"] for r in existing if same_person(full_name, r["full_name"])]
    if dup and not allow_duplicate:
        raise ToolError("Shunga o'xshash o'quvchi allaqachon bor: " + ", ".join(dup) +
                        ". Agar bu boshqa odam bo'lsa, allow_duplicate=true bilan qayta urinib ko'ring.")
    d = parse_date(joined_on, today())
    if monthly_fee is None:
        last = await db.one("select monthly_fee from enrollments where group_id=%s and monthly_fee is not null "
                            "order by joined_on desc limit 1", g["id"])
        monthly_fee = last["monthly_fee"] if last else None
    async with db.tx() as c:
        cur = await c.execute("insert into students (branch_id, full_name, joined_on) values (%s,%s,%s) "
                              "returning id, invite_code", (g["branch_id"], full_name.strip(), d))
        s = await cur.fetchone()
        await c.execute("insert into enrollments (student_id, group_id, joined_on, cycle_start, monthly_fee) "
                        "values (%s,%s,%s,%s,%s)", (s["id"], g["id"], d, d, monthly_fee))
        if parent_name or parent_phone:
            pid = None
            if parent_phone:
                cur = await c.execute("select id from parents where phone=%s limit 1", (parent_phone,))
                row = await cur.fetchone()
                pid = row["id"] if row else None
            if not pid:
                cur = await c.execute("insert into parents (full_name, phone) values (%s,%s) returning id",
                                      (parent_name, parent_phone))
                pid = (await cur.fetchone())["id"]
            await c.execute("insert into student_parents (student_id, parent_id) values (%s,%s) "
                            "on conflict do nothing", (s["id"], pid))
    return {"ok": True, "student_id": s["id"], "guruh": g["name"],
            "oylik_tolov": int(monthly_fee) if monthly_fee else None,
            "ota_ona_havolasi": invite_link("pr", s["invite_code"]),
            "eslatma": "Havolani ota-onaga yuborish kerak: bosganda bot ularni shu o'quvchiga bog'laydi."}


@tool("enroll_student", "Mavjud o'quvchini yana bir guruhga yozadi.",
      {"student": S("O'quvchi"), "group": S("Guruh"), "monthly_fee": N("Oylik to'lov"), "joined_on": S("Sana")},
      ["student", "group"], perm="add_student", write=True)
async def enroll_student(ctx, student, group, monthly_fee=None, joined_on=None):
    st = await Q.find_student(ctx, student)
    g = await Q.find_group(ctx, group)
    d = parse_date(joined_on, today())
    try:
        await db.ex("insert into enrollments (student_id, group_id, joined_on, cycle_start, monthly_fee) "
                    "values (%s,%s,%s,%s,%s)", st["id"], g["id"], d, d, monthly_fee)
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise ToolError("O'quvchi bu guruhga allaqachon yozilgan.")
        raise
    return {"ok": True, "oquvchi": st["full_name"], "guruh": g["name"]}


@tool("add_parent", "O'quvchiga ota-ona (ism, telefon) qo'shadi va Telegram havolasini qaytaradi.",
      {"student": S("O'quvchi"), "parent_name": S("Ota-ona ismi"), "phone": S("Telefon"), "relation": S("ota / ona")},
      ["student", "phone"], perm="add_student", write=True)
async def add_parent(ctx, student, phone, parent_name=None, relation=None):
    st = await Q.find_student(ctx, student)
    row = await db.one("select id from parents where phone=%s limit 1", phone)
    if row:
        pid = row["id"]
    else:
        pid = (await db.one("insert into parents (full_name, phone) values (%s,%s) returning id",
                            parent_name, phone))["id"]
    await db.ex("insert into student_parents (student_id, parent_id, relation) values (%s,%s,%s) "
                "on conflict do nothing", st["id"], pid, relation)
    code = (await db.one("select invite_code from students where id=%s", st["id"]))["invite_code"]
    return {"ok": True, "oquvchi": st["full_name"], "ota_ona_havolasi": invite_link("pr", code)}


@tool("mark_attendance", "Guruh davomatini belgilaydi: ro'yxatdagi hamma KELDI, faqat 'absent' ro'yxatidagilar KELMADI. "
      "Natijada kelmaganlarning ota-onasi botga ulanganmi, shuni ko'rsatadi.",
      {"group": S("Guruh nomi"), "absent": LS("Kelmagan o'quvchilar ismlari (hamma kelgan bo'lsa bo'sh ro'yxat)"),
       "date": S("Sana (standart bugun)"), "branch": S("Filial (ixtiyoriy)")},
      ["group", "absent"], perm="mark_attendance", write=True)
async def mark_attendance(ctx, group, absent, date=None, branch=None):
    g = await Q.find_group(ctx, group, branch)
    d = parse_date(date, today())
    if d > today():
        raise ToolError("Kelajak sanasi uchun davomat belgilab bo'lmaydi.")
    roster = await db.q(
        """select e.id as eid, s.id as sid, s.full_name from enrollments e join students s on s.id = e.student_id
           where e.group_id = %s and e.status = 'active' and s.status = 'active'""", g["id"])
    if not roster:
        raise ToolError("Guruhda faol o'quvchi yo'q.")
    items = [(r["eid"], r["full_name"]) for r in roster]
    absent_eids, unknown = set(), []
    by_sid = {str(r["sid"]): r["eid"] for r in roster}
    for name in absent or []:
        if str(name) in by_sid:                  # paneldan o'quvchi id si keladi
            absent_eids.add(by_sid[str(name)])
            continue
        hits = fuzzy(name, items, limit=3)
        if not hits:
            unknown.append(name)
            continue
        if len(hits) > 1 and hits[0][0] < 0.99 and hits[0][0] - hits[1][0] < 0.12:
            raise ToolError(f"'{name}' bir nechta o'quvchiga mos: " + ", ".join(h[2] for h in hits) + ". Qaysi biri?")
        absent_eids.add(hits[0][1])
    if unknown:
        raise ToolError("Guruhda bunday o'quvchi yo'q: " + ", ".join(unknown) + ". Guruh ro'yxati: " +
                        ", ".join(r["full_name"] for r in roster))
    async with db.tx() as c:
        for r in roster:
            status = "absent" if r["eid"] in absent_eids else "present"
            await c.execute(
                """insert into attendance (enrollment_id, lesson_date, status, marked_by)
                   values (%s,%s,%s::attendance_status,%s)
                   on conflict (enrollment_id, lesson_date)
                   do update set status = excluded.status, marked_by = excluded.marked_by, marked_at = now()""",
                (r["eid"], d, status, ctx.staff_id))
    absent_sids = [r["sid"] for r in roster if r["eid"] in absent_eids]
    info = []
    if absent_sids:
        info = await db.q(
            """select s.id, s.full_name, coalesce(bool_or(p.telegram_id is not null), false) as ota_ona_ulangan,
                      string_agg(distinct p.phone, ', ') as telefon
               from students s left join student_parents sp on sp.student_id = s.id
               left join parents p on p.id = sp.parent_id where s.id = any(%s) group by s.id""", absent_sids)
    warn = None
    if d.isoweekday() not in g["days"]:
        warn = f"Diqqat: {DAY_NAMES[d.isoweekday()]} kuni bu guruhning dars kuni emas."
    return {"ok": True, "guruh": g["name"], "sana": d, "jami": len(roster), "keldi": len(roster) - len(absent_eids),
            "kelmadi": len(absent_eids), "kelmaganlar": info, "ogohlantirish": warn,
            "keyingi_qadam": "Kelmaganlar ota-onasiga xabar yuborishni taklif qiling (message_parents)."}


@tool("record_payment", "O'quvchi to'lovini yozadi va to'lov tsikli holatini yangilaydi.",
      {"student": S("O'quvchi"), "amount": N("Summa (so'm)"), "group": S("Guruh (o'quvchi bir nechta guruhda bo'lsa)"),
       "paid_on": S("Sana (standart bugun)"), "method": S("naqd / karta / o'tkazma")},
      ["student", "amount"], perm="record_payment", write=True)
async def record_payment(ctx, student, amount, group=None, paid_on=None, method=None):
    st = await Q.find_student(ctx, student)
    enr = await Q.find_enrollment(ctx, st["id"], group)
    amt = int(amount)
    if amt <= 0:
        raise ToolError("Summa musbat bo'lishi kerak.")
    d = parse_date(paid_on, today())
    cs = enr["cycle_start"] or d
    paid, unpaid = apply_payment(enr["cycle_paid"], enr["unpaid_cycles"])
    async with db.tx() as c:
        await c.execute("insert into payments (enrollment_id, amount, paid_on, period_start, period_end, method, "
                        "recorded_by) values (%s,%s,%s,%s,%s,%s,%s)",
                        (enr["id"], amt, d, cs, cs + timedelta(days=29), method, ctx.staff_id))
        await c.execute("update enrollments set cycle_paid=%s, unpaid_cycles=%s, cycle_start=%s where id=%s",
                        (paid, unpaid, cs, enr["id"]))
    try:
        await tools_school.referral_on_payment(st["id"])
    except Exception:
        log.exception("referral tekshiruvi")
    return {"ok": True, "oquvchi": st["full_name"], "guruh": enr["group_name"], "summa": fmt_money(amt),
            "holat": payment_state(cs, enr["days"], paid, unpaid, today())}


@tool("message_parents", "O'quvchilarning ota-onasiga Telegram orqali xabar yuboradi. Ota-ona botga ulanmagan bo'lsa, "
      "telefon raqamini qaytaradi (qo'ng'iroq qilish kerak).",
      {"messages": {"type": "array", "description": "Xabarlar ro'yxati",
                    "items": {"type": "object", "properties": {"student": S("O'quvchi ismi yoki id"),
                                                               "text": S("Xabar matni (o'zbekcha, hurmatli, qisqa)")},
                              "required": ["student", "text"]}}},
      ["messages"], perm="message_parents", write=True, confirm=True)
async def message_parents(ctx, messages):
    results = []
    for m in messages:
        st = await Q.find_student(ctx, m["student"])
        parents = await db.q(
            """select p.full_name, p.phone, p.telegram_id from student_parents sp
               join parents p on p.id = sp.parent_id where sp.student_id = %s""", st["id"])
        linked = [p for p in parents if p["telegram_id"]]
        if not linked:
            results.append({"oquvchi": st["full_name"], "holat": "ota-ona botga ulanmagan",
                            "telefonlar": [p["phone"] for p in parents if p["phone"]]})
            continue
        sent = 0
        for p in linked:
            try:
                await rt.bot.send_message(chat_id=p["telegram_id"], text=m["text"])
                sent += 1
                await db.ex("insert into message_log (sender_id, to_kind, to_ref, body, ok) values (%s,'parent',%s,%s,true)",
                            ctx.staff_id, st["full_name"], m["text"])
            except Exception as e:
                await db.ex("insert into message_log (sender_id, to_kind, to_ref, body, ok, error) "
                            "values (%s,'parent',%s,%s,false,%s)", ctx.staff_id, st["full_name"], m["text"], str(e)[:200])
        results.append({"oquvchi": st["full_name"], "holat": f"yuborildi ({sent} ta)" if sent else "yuborilmadi"})
    return {"natija": results}


@tool("create_group", "Yangi guruh ochadi. Xona o'sha kun/vaqtda band bo'lsa, rad etadi.",
      {"branch": S("Filial"), "name": S("Guruh nomi"), "subject": S("Fan"), "teacher": S("O'qituvchi ismi"),
       "room": S("Xona nomi"), "days": LN(DAYS_HELP), "start_time": S("14:00"), "end_time": S("16:00")},
      ["branch", "name", "subject", "days", "start_time", "end_time"], perm="open_group", write=True, confirm=True)
async def create_group(ctx, branch, name, subject, days, start_time, end_time, teacher=None, room=None):
    br = await single_branch(ctx, branch)
    s, e = _t(start_time), _t(end_time)
    days = sorted({int(d) for d in days})
    if not days or any(d < 1 or d > 7 for d in days):
        raise ToolError("Kunlar 1 dan 7 gacha bo'lishi kerak.")
    teacher_id = room_id = None
    if teacher:
        tr = await db.q("select t.id, st.full_name from teachers t join staff st on st.id = t.staff_id "
                        "where st.is_active")
        hits = fuzzy(teacher, [(r["id"], r["full_name"]) for r in tr], limit=2)
        if not hits:
            raise ToolError(f"O'qituvchi topilmadi: {teacher}. Avval add_staff bilan qo'shing.")
        teacher_id = hits[0][1]
        clash = await db.one("""select name from groups where is_active and teacher_id=%s and days && %s::smallint[]
                                and start_time < %s and end_time > %s limit 1""", teacher_id, days, e, s)
        if clash:
            raise ToolError(f"O'qituvchi shu kun/vaqtda «{clash['name']}» guruhida band. suggest_slots bilan bo'sh vaqt toping.")
    if room:
        rr = await db.q("select id, name from rooms where branch_id=%s", br["id"])
        hits = fuzzy(room, [(r["id"], r["name"]) for r in rr], limit=2)
        if not hits:
            raise ToolError(f"Xona topilmadi: {room}. Mavjud xonalar: " + ", ".join(r["name"] for r in rr))
        room_id = hits[0][1]
    try:
        row = await db.one(
            """insert into groups (branch_id, name, subject, teacher_id, room_id, days, start_time, end_time)
               values (%s,%s,%s,%s,%s,%s::smallint[],%s,%s) returning id""",
            br["id"], name, subject, teacher_id, room_id, days, s, e)
    except Exception as ex_:
        if "band" in str(ex_):
            raise ToolError("Bu xona shu kun va vaqtda band. free_rooms bilan bo'sh xonani toping.")
        raise
    return {"ok": True, "group_id": row["id"], "jadval": _sched(days, s, e), "filial": br["name"]}


@tool("freeze_student", "O'quvchini muzlatadi (uzoq vaqt kelmaydigan bo'lsa). Qaytganda unfreeze_student bilan "
      "to'lov tsikli qoldirilgan kunlarga suriladi.",
      {"student": S("O'quvchi"), "reason": S("Sabab"), "group": S("Faqat shu guruh (ixtiyoriy)"),
       "from_date": S("Muzlatish boshlanishi (standart bugun)")},
      ["student", "reason"], perm="freeze_student", write=True, confirm=True)
async def freeze_student(ctx, student, reason, group=None, from_date=None):
    st = await Q.find_student(ctx, student)
    d = parse_date(from_date, today())
    rows = await db.q("select e.id, g.name from enrollments e join groups g on g.id = e.group_id "
                      "where e.student_id=%s and e.status='active'", st["id"])
    if group:
        hits = fuzzy(group, [(r["id"], r["name"]) for r in rows])
        rows = [r for r in rows if hits and r["id"] == hits[0][1]]
    if not rows:
        raise ToolError("Muzlatiladigan faol guruh topilmadi.")
    async with db.tx() as c:
        for r in rows:
            await c.execute("update enrollments set status='frozen' where id=%s", (r["id"],))
            await c.execute("insert into freezes (enrollment_id, start_date, reason, status, requested_by, approved_by) "
                            "values (%s,%s,%s,'approved',%s,%s)", (r["id"], d, reason, ctx.staff_id, ctx.staff_id))
        cur = await c.execute("select count(*) as n from enrollments where student_id=%s and status='active'",
                              (st["id"],))
        if (await cur.fetchone())["n"] == 0:
            await c.execute("update students set status='frozen' where id=%s", (st["id"],))
    return {"ok": True, "oquvchi": st["full_name"], "muzlatilgan_guruhlar": [r["name"] for r in rows]}


@tool("unfreeze_student", "Muzlatilgan o'quvchini qaytaradi; to'lov tsikli muzlagan kunlarga suriladi.",
      {"student": S("O'quvchi")}, ["student"], perm="freeze_student", write=True)
async def unfreeze_student(ctx, student):
    st = await db.q("select id, full_name from students where branch_id = any(%s) and status <> 'left'",
                    await Q.branch_ids_for(ctx))
    hits = fuzzy(student, [(r["id"], r["full_name"]) for r in st], limit=2)
    if not hits:
        raise ToolError(f"O'quvchi topilmadi: {student}")
    sid, sname = hits[0][1], hits[0][2]
    rows = await db.q(
        """select e.id as eid, e.cycle_start, f.id as fid, f.start_date from enrollments e
           join freezes f on f.enrollment_id = e.id and f.end_date is null
           where e.student_id = %s and e.status = 'frozen'""", sid)
    if not rows:
        raise ToolError("Bu o'quvchi muzlatilmagan.")
    shifted = 0
    async with db.tx() as c:
        for r in rows:
            days = max((today() - r["start_date"]).days, 0)
            shifted = max(shifted, days)
            new_cs = (r["cycle_start"] + timedelta(days=days)) if r["cycle_start"] else None
            await c.execute("update enrollments set status='active', cycle_start=%s where id=%s", (new_cs, r["eid"]))
            await c.execute("update freezes set end_date=%s where id=%s", (today(), r["fid"]))
        await c.execute("update students set status='active' where id=%s", (sid,))
    return {"ok": True, "oquvchi": sname, "tsikl_surildi_kun": shifted}


@tool("add_staff", "Yangi xodim (manager, admin, o'qituvchi) qo'shadi va botga kirish havolasini qaytaradi.",
      {"full_name": S("Ism-familiya"), "role": S("manager | admin | teacher"), "branches": LS("Filiallar nomlari"),
       "subject": S("O'qituvchi uchun fan"), "phone": S("Telefon")},
      ["full_name", "role", "branches"], perm="add_staff", write=True, confirm=True)
async def add_staff(ctx, full_name, role, branches, subject=None, phone=None):
    if role not in ("manager", "admin", "teacher"):
        raise ToolError("Rol: manager, admin yoki teacher bo'lishi kerak.")
    brs = []
    for b in branches:
        brs += await Q.branches_for(ctx, b)
    code = secrets.token_hex(5)
    async with db.tx() as c:
        cur = await c.execute("insert into staff (full_name, role, phone, invite_code) values (%s,%s::user_role,%s,%s) "
                              "returning id", (full_name.strip(), role, phone, code))
        sid = (await cur.fetchone())["id"]
        for b in {b["id"]: b for b in brs}.values():
            await c.execute("insert into staff_branch_access (staff_id, branch_id, granted_by) values (%s,%s,%s) "
                            "on conflict do nothing", (sid, b["id"], ctx.staff_id))
        if role == "teacher":
            await c.execute("insert into teachers (staff_id, subject) values (%s,%s)", (sid, subject))
    return {"ok": True, "xodim": full_name, "rol": role, "botga_kirish_havolasi": invite_link("st", code),
            "eslatma": "Havolani shu xodimga yuboring: bosganda u botga ulanadi."}


@tool("set_branch_access", "Xodimga filialni ko'rish/boshqarish ruxsatini beradi yoki olib tashlaydi.",
      {"staff": S("Xodim ismi"), "branch": S("Filial"), "grant": B("true = berish, false = olib tashlash")},
      ["staff", "branch", "grant"], perm="grant_branch_access", write=True, confirm=True)
async def set_branch_access(ctx, staff, branch, grant):
    target = await db.q("select id, full_name, role::text as role from staff where is_active and role <> 'owner'")
    hits = fuzzy(staff, [(r["id"], r["full_name"]) for r in target], limit=2)
    if not hits:
        raise ToolError(f"Xodim topilmadi: {staff}")
    br = (await Q.branches_for(ctx, branch))[0]
    if grant:
        await db.ex("insert into staff_branch_access (staff_id, branch_id, granted_by) values (%s,%s,%s) "
                    "on conflict do nothing", hits[0][1], br["id"], ctx.staff_id)
    else:
        await db.ex("delete from staff_branch_access where staff_id=%s and branch_id=%s", hits[0][1], br["id"])
    return {"ok": True, "xodim": hits[0][2], "filial": br["name"], "ruxsat": "berildi" if grant else "olib tashlandi"}


@tool("add_lead", "Yangi lid (potensial o'quvchi) qo'shadi.",
      {"full_name": S("Ism"), "phone": S("Telefon"), "source": S("instagram_forma | telegram | tavsiya | boshqa"),
       "branch": S("Filial"), "campaign": S("Kampaniya nomi (ixtiyoriy)"), "note": S("Izoh")},
      ["phone"], perm="manage_leads", write=True)
async def add_lead(ctx, phone, full_name=None, source=None, branch=None, campaign=None, note=None):
    br = await single_branch(ctx, branch)
    cid = None
    if campaign:
        cr = await db.q("select id, name from campaigns")
        hits = fuzzy(campaign, [(r["id"], r["name"]) for r in cr], limit=1, min_score=0.78)
        cid = hits[0][1] if hits else None
    assignee = ctx.staff_id if ctx.role in ("admin", "manager") else None
    row = await db.one("insert into leads (branch_id, full_name, phone, source, campaign_id, assigned_to, note) "
                       "values (%s,%s,%s,%s,%s,%s,%s) returning id", br["id"], full_name, phone, source, cid,
                       assignee, note)
    return {"ok": True, "lead_id": row["id"], "filial": br["name"]}


@tool("update_lead", "Lid holatini yangilaydi va aloqa tarixiga yozadi.",
      {"lead": S("Lid ismi, telefoni yoki id"), "status": S("new | contacted | trial | enrolled | rejected"),
       "note": S("Aloqa izohi"), "kind": S("qo'ng'iroq | yozishma | sinov darsi")},
      ["lead"], perm="manage_leads", write=True)
async def update_lead(ctx, lead, status=None, note=None, kind=None):
    bids = await Q.branch_ids_for(ctx)
    rows = await db.q("select id, full_name, phone from leads where (branch_id = any(%s) or branch_id is null) "
                      "order by created_at desc limit 500", bids)
    digits = "".join(ch for ch in str(lead) if ch.isdigit())
    match = [r for r in rows if str(r["id"]) == str(lead)
             or (len(digits) >= 7 and r["phone"] and "".join(ch for ch in r["phone"] if ch.isdigit()).endswith(digits[-9:]))]
    if not match:
        hits = fuzzy(lead, [(r["id"], r["full_name"] or "") for r in rows], limit=2)
        match = [r for r in rows if hits and r["id"] == hits[0][1]]
    if not match:
        raise ToolError(f"Lid topilmadi: {lead}")
    lid = match[0]["id"]
    if status:
        if status not in ("new", "contacted", "trial", "enrolled", "rejected"):
            raise ToolError("Holat: new, contacted, trial, enrolled yoki rejected.")
        await db.ex("update leads set status=%s::lead_status where id=%s", status, lid)
    if note or kind:
        await db.ex("insert into lead_activities (lead_id, staff_id, kind, note) values (%s,%s,%s,%s)",
                    lid, ctx.staff_id, kind, note)
    return {"ok": True, "lid": match[0]["full_name"], "holat": status}


@tool("add_expense", "Xarajat yozadi (ijara, maosh, kommunal va h.k.).",
      {"amount": N("Summa (so'm)"), "category": S("ijara | maosh | kommunal | reklama | jihoz | boshqa"),
       "note": S("Izoh"), "spent_on": S("Sana (standart bugun)"), "branch": S("Filial")},
      ["amount", "category"], perm="add_expense", write=True)
async def add_expense(ctx, amount, category, note=None, spent_on=None, branch=None):
    br = await single_branch(ctx, branch)
    await db.ex("insert into expenses (branch_id, amount, category, note, spent_on, recorded_by) "
                "values (%s,%s,%s,%s,%s,%s)", br["id"], int(amount), category, note, parse_date(spent_on, today()),
                ctx.staff_id)
    return {"ok": True, "summa": fmt_money(amount), "toifa": category, "filial": br["name"]}


@tool("log_marketing_spend", "Reklama xarajatini kampaniyaga yozadi (kampaniya yo'q bo'lsa yaratadi).",
      {"campaign": S("Kampaniya nomi"), "amount": N("Summa (so'm)"), "platform": S("instagram | telegram | boshqa"),
       "spend_date": S("Sana"), "branch": S("Filial")},
      ["campaign", "amount"], perm="manage_marketing", write=True)
async def log_marketing_spend(ctx, campaign, amount, platform=None, spend_date=None, branch=None):
    br = await single_branch(ctx, branch)
    rows = await db.q("select id, name from campaigns")
    exact = [r for r in rows if norm(r["name"]) == norm(campaign)]
    if exact:
        cid = exact[0]["id"]
    else:
        cid = (await db.one("insert into campaigns (branch_id, name, platform, start_date) values (%s,%s,%s,%s) "
                            "returning id", br["id"], campaign, platform, today()))["id"]
    await db.ex("insert into marketing_spend (campaign_id, spend_date, amount) values (%s,%s,%s)",
                cid, parse_date(spend_date, today()), int(amount))
    return {"ok": True, "kampaniya": campaign, "summa": fmt_money(amount)}


@tool("add_exam_result", "O'quvchining imtihon natijasini yozadi (o'qituvchi tahlili uchun).",
      {"student": S("O'quvchi"), "exam_name": S("Imtihon nomi, masalan IELTS mock"), "score": N("Ball"),
       "target_score": N("Maqsad ball (ixtiyoriy)"), "exam_date": S("Sana"), "group": S("Guruh (ixtiyoriy)")},
      ["student", "exam_name", "score"], perm="add_exam_result", write=True)
async def add_exam_result(ctx, student, exam_name, score, target_score=None, exam_date=None, group=None):
    st = await Q.find_student(ctx, student)
    enr = await Q.find_enrollment(ctx, st["id"], group)
    await db.ex("insert into exams (student_id, group_id, exam_name, exam_date, score, target_score) "
                "values (%s,%s,%s,%s,%s,%s)", st["id"], enr["group_id"], exam_name, parse_date(exam_date, today()),
                score, target_score)
    return {"ok": True, "oquvchi": st["full_name"], "guruh": enr["group_name"], "ball": score}


@tool("message_staff", "Xodimga (manager, admin, o'qituvchi) Telegram orqali xabar yuboradi: ogohlantirish, yo'l-yo'riq.",
      {"staff": S("Xodim ismi"), "text": S("Xabar matni")}, ["staff", "text"],
      perm="message_staff", write=True, confirm=True)
async def message_staff(ctx, staff, text):
    target = await _find_staff(ctx, staff)
    if not target["telegram_id"]:
        raise ToolError(f"{target['full_name']} hali botga ulanmagan.")
    await rt.bot.send_message(chat_id=target["telegram_id"], text=text)
    await db.ex("insert into message_log (sender_id, to_kind, to_ref, body, ok) values (%s,'staff',%s,%s,true)",
                ctx.staff_id, target["full_name"], text)
    return {"ok": True, "yuborildi": target["full_name"]}


# =====================================================================
#  KONTENT: Telegram kanal va Instagram (matn, rasm, video; darhol yoki rejalashtirilgan)
# =====================================================================
def parse_dt(s, default_time="09:00"):
    """'2026-11-26 14:00', '26.11.2026 14:00', '14:00' (bugun), '2026-11-26' -> Toshkent vaqtidagi datetime"""
    if not s:
        return None
    s = str(s).strip().replace("T", " ")
    t_only = None
    try:
        t_only = datetime.strptime(s, "%H:%M").time()
    except ValueError:
        pass
    if t_only:
        return datetime.combine(today(), t_only, tzinfo=config.TZ)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m %H:%M"):
        try:
            d = datetime.strptime(s, fmt)
            if fmt == "%d.%m %H:%M":
                d = d.replace(year=today().year)
            return d.replace(tzinfo=config.TZ)
        except ValueError:
            pass
    d = parse_date(s)
    return datetime.combine(d, datetime.strptime(default_time, "%H:%M").time(), tzinfo=config.TZ)


@tool("publish_post", "Telegram kanal va/yoki Instagramga post chiqaradi: matn, rasm yoki video (Instagramda video = "
      "Reels). Foydalanuvchi botga/panelga rasm yoki video yuborgan bo'lsa, avtomatik o'sha fayl ishlatiladi. "
      "schedule_at berilsa, o'sha vaqtda avtomatik chiqadi.",
      {"text": S("Post matni (o'zbek lotin, jonli, chaqiriq bilan)"),
       "targets": LS("telegram, instagram, youtube, tiktok (youtube/tiktok faqat video, n8n/Make orqali)"),
       "media_url": S("Rasm/video ochiq havolasi (ixtiyoriy)"), "media_kind": S("photo | video (ixtiyoriy)"),
       "file_id": S("Telegram file_id (make_design/edit_video qaytargan, ixtiyoriy)"),
       "schedule_at": S("Chiqish vaqti, masalan '2026-11-26 18:00' (bo'sh = hozir)"),
       "plan_item": S("Kontent reja bandi id (ixtiyoriy: reja 'chiqdi' bo'ladi)"),
       "signup_link": B("Telegram postiga 'yozilish' havolasi qo'shilsin (standart true; murojaatlarni kuzatish uchun)")},
      ["text", "targets"], perm="publish_post", write=True, confirm=True)
async def publish_post(ctx, text, targets, media_url=None, media_kind=None, schedule_at=None, file_id=None,
                       plan_item=None, signup_link=True):
    targets = [t.strip().lower() for t in targets if t and t.strip()]
    bad = [t for t in targets if t not in ("telegram", "instagram", "youtube", "tiktok")]
    if bad or not targets:
        raise ToolError("Joy: telegram, instagram, youtube, tiktok.")
    if not media_url and not file_id:
        att = next((a for a in ctx.attachments if a.get("kind") in ("photo", "video")), None)
        if att:
            media_url, media_kind, file_id = att.get("url"), att["kind"], att.get("file_id")
    if (media_url or file_id) and not media_kind:
        media_kind = (social.guess_kind(media_url) if media_url else None) or "photo"
    kind = media_kind if (media_url or file_id) else "none"
    if any(t != "telegram" for t in targets) and not media_url:
        raise ToolError("Instagram/YouTube/TikTok uchun rasm yoki video ochiq havolada bo'lishi kerak (Supabase Storage "
                        "sozlanganda bot/panel buni o'zi qiladi).")
    if any(t in ("youtube", "tiktok") for t in targets) and kind != "video":
        raise ToolError("YouTube Shorts va TikTok uchun video kerak.")
    plan_id = None
    if plan_item:
        pr = await db.one("select id from content_plan where id::text=%s", str(plan_item))
        plan_id = pr["id"] if pr else None
    when = parse_dt(schedule_at, "10:00") if schedule_at else None
    future = when and when > now() + timedelta(minutes=1)
    row = await db.one(
        "insert into content_posts (body, media_kind, media_url, tg_file_id, targets, scheduled_at, created_by, plan_id, "
        "signup_link) values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id", text, kind, media_url, file_id, targets,
        when or now(), ctx.staff_id, plan_id, bool(signup_link))
    if plan_id:
        await db.ex("update content_plan set post_id=%s, status=%s where id=%s", row["id"],
                    "tayyor" if future else "chiqdi", plan_id)
    if future:
        return {"ok": True, "holat": "rejalashtirildi", "vaqt": when.strftime("%d.%m.%Y %H:%M"), "post_id": row["id"]}
    res = await social.publish(row["id"])
    return {"ok": res["holat"] != "failed", **res, "post_id": row["id"]}


@tool("list_posts", "So'nggi va rejalashtirilgan postlar (Telegram kanal, Instagram) va ularning natijasi.",
      {"limit": N("Nechta (standart 15)")}, perm="publish_post")
async def list_posts(ctx, limit=15):
    rows = await db.q(
        """select p.id, p.body, p.media_kind, p.media_url, p.targets, p.status, p.scheduled_at, p.published_at,
                  p.results, s.full_name as kim
           from content_posts p left join staff s on s.id = p.created_by
           order by (p.status = 'scheduled') desc, p.scheduled_at desc limit %s""", int(limit))
    return {"postlar": rows}


@tool("cancel_post", "Rejalashtirilgan postni bekor qiladi.", {"post": S("Post id (bo'sh = eng yaqin rejalashtirilgani)")},
      perm="publish_post", write=True)
async def cancel_post(ctx, post=None):
    if post:
        row = await db.one("update content_posts set status='cancelled' where id::text=%s and status='scheduled' "
                           "returning id, body", str(post))
    else:
        row = await db.one("update content_posts set status='cancelled' where id = (select id from content_posts "
                           "where status='scheduled' order by scheduled_at limit 1) returning id, body")
    if not row:
        raise ToolError("Bekor qilinadigan rejalashtirilgan post topilmadi.")
    return {"ok": True, "bekor_qilindi": (row["body"] or "")[:80]}


# =====================================================================
#  VAZIFALAR: xodimlarga individual yoki umumiy topshiriq
# =====================================================================
TASK_STATUS_UZ = {"sent": "yuborildi", "seen": "ko'rdi", "done": "bajarildi", "cancelled": "bekor qilindi"}


async def staff_in_scope(ctx, include_self=False):
    """Foydalanuvchi ko'ra oladigan xodimlar (egasi: hammasi; boshqalar: umumiy filialdagilar)."""
    if ctx.role == "owner":
        rows = await db.q("select id, full_name, role::text as role, telegram_id from staff where is_active "
                          "order by role, full_name")
    else:
        rows = await db.q(
            """select s.id, s.full_name, s.role::text as role, s.telegram_id from staff s
               where s.is_active and (s.role = 'owner' or exists (select 1 from staff_branch_access a
                     where a.staff_id = s.id and a.branch_id = any(%s)))
               order by s.role, s.full_name""", ctx.branch_ids or [])
    return [r for r in rows if include_self or r["id"] != ctx.staff_id]


def task_keyboard(task_id):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Bajarildi", callback_data=f"tk:{task_id}:done"),
                                  InlineKeyboardButton("👀 Ko'rdim", callback_data=f"tk:{task_id}:seen")]])


@tool("send_task", "Xodim(lar)ga Telegram orqali vazifa/topshiriq yuboradi va bajarilishini kuzatadi. Bir kishiga "
      "(recipients), rol bo'yicha (role: teacher/admin/manager/all) yoki filial bo'yicha. Masalan 'Zufar bugun darsini "
      "1 soat ertaroq boshlasin' -> recipients=['Zufar'], text='Bugun darsingizni 1 soat ertaroq boshlang.'",
      {"text": S("Vazifa matni: xodimga to'g'ridan-to'g'ri, hurmatli, aniq ('...ni qiling')"),
       "recipients": LS("Xodimlar ismlari (ixtiyoriy)"),
       "role": S("Hammasiga yuborish uchun: teacher | admin | manager | all (ixtiyoriy)"),
       "branch": S("Faqat shu filial xodimlari (ixtiyoriy)"),
       "due": S("Muddat, masalan '2026-11-26 18:00' yoki '18:00' (ixtiyoriy)")},
      ["text"], perm="assign_tasks", write=True, confirm=True)
async def send_task(ctx, text, recipients=None, role=None, branch=None, due=None):
    pool = await staff_in_scope(ctx)
    targets = {}
    for name in recipients or []:
        r = await _find_staff(ctx, name)
        targets[r["id"]] = r
    if role:
        roles = {"teacher", "admin", "manager"} if role == "all" else {role}
        if not roles <= {"teacher", "admin", "manager"}:
            raise ToolError("Rol: teacher, admin, manager yoki all.")
        cand = [r for r in pool if r["role"] in roles]
        if branch:
            br = (await Q.branches_for(ctx, branch))[0]
            ids = {a["staff_id"] for a in await db.q("select staff_id from staff_branch_access where branch_id=%s",
                                                    br["id"])}
            cand = [r for r in cand if r["id"] in ids]
        targets.update({r["id"]: r for r in cand})
    targets.pop(ctx.staff_id, None)
    if not targets:
        raise ToolError("Kimga yuborish kerak? Xodim ismini yoki rolni ayting.")
    due_at = parse_dt(due, "18:00") if due else None
    batch = uuid.uuid4() if len(targets) > 1 else None
    sent, not_linked = [], []
    head = f"📋 Vazifa — {ctx.staff['full_name']} ({ROLE_UZ.get(ctx.role, ctx.role)}):\n\n{text.strip()}"
    if due_at:
        head += f"\n\n⏰ Muddat: {due_at:%d.%m.%Y %H:%M}"
    for r in targets.values():
        row = await db.one(
            "insert into tasks (text, assigned_to, created_by, batch_id, due_at) values (%s,%s,%s,%s,%s) "
            "returning id", text.strip(), r["id"], ctx.staff_id, batch, due_at)
        if not r["telegram_id"]:
            not_linked.append(r["full_name"])
            continue
        try:
            await rt.bot.send_message(chat_id=r["telegram_id"], text=head + "\n\nBajargach «✅ Bajarildi» tugmasini bosing.",
                                      reply_markup=task_keyboard(row["id"]))
            await db.ex("update tasks set delivered=true where id=%s", row["id"])
            sent.append(r["full_name"])
        except Exception as e:
            log.warning("vazifa yuborilmadi: %s", e)
            not_linked.append(r["full_name"])
    return {"ok": True, "yuborildi": sent, "yetkazilmadi_botga_ulanmagan": not_linked,
            "muddat": due_at.strftime("%d.%m.%Y %H:%M") if due_at else None}


async def _task_rows(me, where, *params):
    return await db.q(
        f"""select t.id, t.text, t.status, t.due_at, t.created_at, t.done_at, t.delivered,
                   a.full_name as kimga, c.full_name as kimdan,
                   (t.assigned_to = %s) as menga, (t.created_by = %s) as men_bergan,
                   (t.due_at is not null and t.due_at < now() and t.status in ('sent','seen')) as kechikkan
            from tasks t join staff a on a.id = t.assigned_to left join staff c on c.id = t.created_by
            where {where} order by (t.status in ('sent','seen')) desc, t.created_at desc limit 80""", me, me, *params)


@tool("list_tasks", "Vazifalar ro'yxati: menga berilganlar, men berganlar yoki hammasi; bajarilganmi.",
      {"scope": S("menga | men_bergan | hammasi (standart: hammasi)"),
       "only_open": B("Faqat bajarilmaganlar")})
async def list_tasks(ctx, scope="hammasi", only_open=False):
    open_sql = " and t.status in ('sent','seen')" if only_open else ""
    me = ctx.staff_id
    if scope == "menga":
        rows = await _task_rows(me, "t.assigned_to = %s" + open_sql, me)
    elif scope == "men_bergan":
        rows = await _task_rows(me, "t.created_by = %s" + open_sql, me)
    elif ctx.role == "owner":
        rows = await _task_rows(me, "true" + open_sql)
    else:
        rows = await _task_rows(me, "(t.assigned_to = %s or t.created_by = %s)" + open_sql, me, me)
    for r in rows:
        r["holat_kod"] = r["status"]
        r["holat"] = TASK_STATUS_UZ.get(r.pop("status"), "")
    return {"vazifalar": rows}


async def set_task_status(task_id, status, actor):
    """Tugma, panel yoki Jimi orqali vazifa holatini o'zgartiradi; berganiga xabar beradi."""
    t = await db.one("select t.*, c.telegram_id as creator_tg from tasks t left join staff c on c.id = t.created_by "
                     "where t.id::text = %s", str(task_id))
    if not t:
        raise ToolError("Vazifa topilmadi.")
    is_assignee, is_creator = t["assigned_to"] == actor["id"], t["created_by"] == actor["id"]
    if status in ("done", "seen") and not (is_assignee or actor["role"] == "owner"):
        raise ToolError("Bu vazifa sizga berilmagan.")
    if status == "cancelled" and not (is_creator or actor["role"] == "owner"):
        raise ToolError("Vazifani faqat bergan odam bekor qila oladi.")
    if t["status"] in ("done", "cancelled") or (status == "seen" and t["status"] == "seen"):
        return t
    await db.ex("update tasks set status=%s, done_at = case when %s='done' then now() else done_at end where id=%s",
                status, status, t["id"])
    if status == "done" and t["creator_tg"] and not is_creator:
        await send_tg(t["creator_tg"], f"✅ {actor['full_name']} vazifani bajardi:\n{t['text'][:500]}")
    if status == "cancelled":
        who = await db.one("select telegram_id from staff where id=%s", t["assigned_to"])
        if who and who["telegram_id"] and not is_assignee:
            await send_tg(who["telegram_id"], f"❎ Vazifa bekor qilindi:\n{t['text'][:500]}")
    return t


@tool("update_task", "Vazifa holatini o'zgartiradi: bajarildi (done), ko'rdim (seen) yoki bekor (cancelled).",
      {"task": S("Vazifa id yoki matnidan bir qismi"), "status": S("done | seen | cancelled")},
      ["task", "status"], write=True)
async def update_task(ctx, task, status):
    if status not in ("done", "seen", "cancelled"):
        raise ToolError("Holat: done, seen yoki cancelled.")
    rows = await db.q("select id, text from tasks where status in ('sent','seen') and (assigned_to=%s or created_by=%s "
                      "or %s)", ctx.staff_id, ctx.staff_id, ctx.role == "owner")
    match = [r for r in rows if str(r["id"]) == str(task)]
    if not match:
        q_ = norm(task)
        match = [r for r in rows if q_ and q_ in norm(r["text"])]
    if not match:
        raise ToolError("Ochiq vazifa topilmadi. list_tasks bilan ro'yxatni ko'ring.")
    if len(match) > 1:
        raise ToolError("Bir nechta vazifa mos keldi: " + "; ".join(r["text"][:60] for r in match[:5]))
    await set_task_status(match[0]["id"], status, ctx.staff)
    return {"ok": True, "vazifa": match[0]["text"][:100], "holat": TASK_STATUS_UZ[status]}


# =====================================================================
#  AI JAMOA: agentlar ro'yxati va yangi agent qo'shish (HR taklifi, rahbar tasdig'i)
# =====================================================================
FORBIDDEN_AGENT_TOOLS = {"propose_agent", "ask_specialist", "decide_approval", "confirm_pending_action"}


@tool("list_agents", "AI jamoa: mavjud agentlar (mutaxassislar), vazifasi va vositalari.")
async def list_agents(ctx):
    from . import brain
    return {"agentlar": [{"nom": a["name"], "lavozim": a["title"], "vazifa": a["desc"],
                          "vositalar": a["tools"]} for a in brain.AGENTS.values()]}


@tool("propose_agent", "Yangi AI agent (mutaxassis) qo'shadi: masalan 'sales', 'call_center'. Faqat tizimdagi mavjud "
      "vositalardan foydalanadi (internetdan dastur o'rnatmaydi). Rahbar tasdig'idan keyin darhol ishga tushadi.",
      {"name": S("Lotin harflarda qisqa nom: sales, hr_recruiter"), "title": S("Lavozimi, masalan 'Sotuv menejeri'"),
       "desc": S("Bir gapda vazifasi"), "tools": LS("Ruxsat etilgan vositalar nomlari (list_agents dan)"),
       "prompt": S("Agentning to'liq yo'riqnomasi: vazifalari, qoidalari, uslubi")},
      ["name", "title", "desc", "tools", "prompt"], perm="manage_agents", write=True, confirm=True)
async def propose_agent(ctx, name, title, desc, tools, prompt):
    import pathlib
    import re as _re
    from . import brain
    name = name.strip().lower()
    if not _re.fullmatch(r"[a-z][a-z0-9_]{2,30}", name):
        raise ToolError("Nom lotin kichik harflar, raqam va _ dan iborat bo'lsin (3-31 belgi).")
    if name in brain.AGENTS:
        raise ToolError(f"'{name}' nomli agent allaqachon bor.")
    unknown = [t for t in tools if t not in TOOLS or t in FORBIDDEN_AGENT_TOOLS]
    if unknown or not tools:
        raise ToolError("Bu vositalar mavjud emas yoki ruxsat etilmagan: " + ", ".join(unknown or ["(bo'sh)"]))
    clean = lambda x: " ".join(str(x).split())
    body = (f"---\nname: {name}\ntitle: {clean(title)}\ndesc: {clean(desc)}\nmodel: main\n"
            f"tools: {', '.join(tools)}\n---\n{prompt.strip()}\n")
    path = pathlib.Path(brain.AGENT_DIR) / f"{name}.md"
    path.write_text(body, encoding="utf-8")
    brain.load_agents()
    return {"ok": True, "agent": name, "lavozim": title, "xabar": "Agent qo'shildi va Jimi unga topshiriq bera oladi."}


@tool("export_excel", "Ma'lumotni Excel faylga nusxalab, shu chatga yuboradi.",
      {"kind": S("students | payments | debtors | leads | invite_links | attendance_grid"),
       "group": S("attendance_grid uchun guruh nomi"), "month": S("YYYY-MM (payments, attendance_grid uchun)"),
       "branch": S("Filial (ixtiyoriy)")}, ["kind"], perm="export_data")
async def export_excel(ctx, kind, group=None, month=None, branch=None):
    if kind == "payments" and ctx.level("view_finance") != "allow":
        raise ToolError("To'lovlar hisobotini ko'rishga ruxsat yo'q.")
    bids = await Q.branch_ids_for(ctx, branch)
    g = await Q.find_group(ctx, group, branch) if kind == "attendance_grid" else None
    try:
        fname, data = await exports.build(kind, bids, group=g, month=month)
    except ValueError as e:
        raise ToolError(str(e))
    await rt.bot.send_document(chat_id=ctx.chat_id, document=data, filename=fname)
    return {"ok": True, "fayl": fname, "xabar": "Fayl chatga yuborildi."}


@tool("remember", "Biznes haqida doimiy eslatma saqlaydi (narxlar, maqsadlar, qarorlar). Keyingi suhbatlarda ham bilinadi.",
      {"note": S("Eslab qolinadigan fakt yoki qaror")}, ["note"], perm="remember", write=True)
async def remember(ctx, note):
    await db.ex("insert into business_notes (note, created_by) values (%s,%s)", note, ctx.staff_id)
    return {"ok": True}


@tool("set_cycle_start", "O'quvchining to'lov tsikli boshlanish sanasini (yoki to'langanlik holatini) qo'lda to'g'rilaydi.",
      {"student": S("O'quvchi"), "cycle_start": S("Tsikl boshi sanasi"), "group": S("Guruh"),
       "paid": B("Joriy tsikl to'langanmi"), "unpaid_cycles": N("Qarz tsikllari soni (0 = qarz yo'q)")},
      ["student", "cycle_start"], perm="edit_payment_cycle", write=True)
async def set_cycle_start(ctx, student, cycle_start, group=None, paid=None, unpaid_cycles=None):
    st = await Q.find_student(ctx, student)
    enr = await Q.find_enrollment(ctx, st["id"], group)
    cs = parse_date(cycle_start)
    new_paid = enr["cycle_paid"] if paid is None else bool(paid)
    new_unpaid = enr["unpaid_cycles"] if unpaid_cycles is None else int(unpaid_cycles)
    await db.ex("update enrollments set cycle_start=%s, cycle_paid=%s, unpaid_cycles=%s where id=%s",
                cs, new_paid, new_unpaid, enr["id"])
    return {"ok": True, "oquvchi": st["full_name"], "tsikl_boshi": cs,
            "holat": payment_state(cs, enr["days"], new_paid, new_unpaid, today())}


# =====================================================================
#  TASDIQ VOSITALARI
# =====================================================================
@tool("confirm_pending_action",
      "Foydalanuvchi tasdiq kutilayotgan amalga 'ha' (yoki 'yo'q') degandan KEYIN chaqiriladi.",
      {"confirm": B("true = bajarish, false = bekor qilish")}, ["confirm"])
async def confirm_pending_action(ctx, confirm):
    row = await db.one(
        "select * from pending_actions where staff_id=%s and status='pending' and created_at < %s "
        "order by created_at desc limit 1", ctx.staff_id, ctx.msg_time)
    if not row:
        raise ToolError("Tasdiq kutayotgan amal yo'q yoki foydalanuvchi hali javob bermadi. "
                        "Avval foydalanuvchidan so'rang.")
    if not confirm:
        await db.ex("update pending_actions set status='cancelled' where id=%s", row["id"])
        return {"status": "bekor_qilindi", "amal": row["summary"]}
    await db.ex("update pending_actions set status='executed' where id=%s", row["id"])
    res = await dispatch(replace(ctx, confirmed=True), row["tool"], {**row["args"], "summary": row["summary"]})
    return {"status": "bajarildi", "amal": row["summary"], "natija": res}


@tool("decide_approval", "Rahbar xodimlarning tasdiq so'rovini tasdiqlaydi yoki rad etadi (tugma bosish o'rniga).",
      {"approve": B("true = tasdiqlash, false = rad etish"),
       "approval_id": S("So'rov id (bo'lmasa eng oxirgisi)")},
      ["approve"], roles={"owner"}, write=True)
async def decide_approval(ctx, approve, approval_id=None):
    if approval_id:
        row = await db.one("select id from approval_requests where id=%s::uuid and status='pending'", approval_id)
    else:
        row = await db.one("select id from approval_requests where status='pending' order by created_at desc limit 1")
    if not row:
        raise ToolError("Kutayotgan so'rov yo'q.")
    text = await execute_approval(row["id"], bool(approve), ctx.staff)
    return {"natija": text}


def load_plugins():
    """plugins/ papkasidagi .py fayllarni yuklaydi: yangi vosita qo'shish uchun (README ga qarang)."""
    import importlib.util
    import pathlib
    folder = pathlib.Path(__file__).resolve().parent.parent / "plugins"
    for f in sorted(folder.glob("*.py")):
        if f.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"plugin_{f.stem}", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        log.info("plagin yuklandi: %s", f.name)


def _agent_meta(path):
    text = path.read_text(encoding="utf-8")
    meta = {}
    if text.startswith("---"):
        for line in text.split("---", 2)[1].strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    return {"nom": meta.get("name", path.stem), "lavozim": meta.get("title", ""), "vazifa": meta.get("desc", ""),
            "vositalar": [t.strip() for t in meta.get("tools", "").split(",") if t.strip()]}


@tool("list_agent_catalog", "HR katalogi: hali ishga tushirilmagan tayyor agentlar (o'rnatish mumkin).")
async def list_agent_catalog(ctx):
    import pathlib as _p
    from . import brain
    folder = _p.Path(brain.AGENT_DIR) / "katalog"
    items = [_agent_meta(f) for f in sorted(folder.glob("*.md"))] if folder.exists() else []
    return {"katalog": items, "eslatma": "Mos agent bo'lmasa, propose_agent bilan yangisini yozish mumkin."}


@tool("install_agent", "Katalogdagi tayyor agentni ishga tushiradi (rahbar tasdig'i bilan).",
      {"name": S("Katalogdagi agent nomi")}, ["name"], perm="manage_agents", write=True, confirm=True)
async def install_agent(ctx, name):
    import pathlib as _p
    from . import brain
    src = _p.Path(brain.AGENT_DIR) / "katalog" / f"{name.strip().lower()}.md"
    if not src.exists():
        raise ToolError("Katalogda bunday agent yo'q. list_agent_catalog bilan ko'ring.")
    meta = _agent_meta(src)
    bad = [t for t in meta["vositalar"] if t not in TOOLS]
    if bad:
        raise ToolError("Bu agent uchun kerakli vositalar tizimda yo'q: " + ", ".join(bad))
    dst = _p.Path(brain.AGENT_DIR) / src.name
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    src.unlink()
    brain.load_agents()
    return {"ok": True, "agent": meta["nom"], "lavozim": meta["lavozim"], "xabar": "Agent jamoaga qo'shildi."}


@tool("deactivate_agent", "Agentni ishdan to'xtatadi (katalogga qaytaradi, keyin qayta o'rnatish mumkin).",
      {"name": S("Agent nomi")}, ["name"], roles={"owner"}, write=True, confirm=True)
async def deactivate_agent(ctx, name):
    import pathlib as _p
    from . import brain
    name = name.strip().lower()
    if name == "jimi" or name not in brain.AGENTS:
        raise ToolError("Bunday faol agent yo'q (Jimini o'chirib bo'lmaydi).")
    folder = _p.Path(brain.AGENT_DIR)
    (folder / "katalog").mkdir(exist_ok=True)
    src = folder / f"{name}.md"
    (folder / "katalog" / f"{name}.md").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    src.unlink()
    brain.load_agents()
    return {"ok": True, "toxtatildi": name}


# Qo'shimcha vositalar modullari (shu fayldagi tool() dan foydalanadi)
from . import tools_media, tools_school  # noqa: E402,F401
