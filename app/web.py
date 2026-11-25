"""Kompyuter paneli: brauzerda ochiladigan boshqaruv oynasi.

Bot bilan bitta dasturda ishlaydi. Kirish: Telegramda botga /panel yozasiz, u bir martalik havola beradi
(15 daqiqa amal qiladi). Havolani bosganingizda brauzer 30 kunga eslab qoladi.

Hamma amal Telegram'dagi bilan bir xil vositalar (app/tools.py) orqali bajariladi, shuning uchun ruxsatlar,
filial cheklovi, rahbar tasdig'i va jurnal panelda ham xuddi shunday ishlaydi.
"""
import base64
import contextlib
import hashlib
import json
import logging
import pathlib
import secrets
from dataclasses import replace
from datetime import timedelta

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import brain, config, db, exports, social, tools, voice
from . import queries as Q
from .core import ROLE_UZ, ToolError, fuzzy, invite_link, now, parse_date, rt, today

log = logging.getLogger("wstizim.web")
WEB_DIR = pathlib.Path(__file__).resolve().parent.parent / "web"
COOKIE = "wstizim_session"
SESSION_DAYS = 30

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
if (WEB_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


# ---------- kirish ----------
async def create_login_link(staff):
    """Bot /panel buyrug'i uchun bir martalik havola."""
    token = secrets.token_urlsafe(24)
    await db.ex("delete from web_sessions where expires_at < now()")
    await db.ex("insert into web_sessions (token_hash, staff_id, kind, expires_at) values (%s,%s,'login',%s)",
                _hash(token), staff["id"], now() + timedelta(minutes=15))
    return f"{config.PANEL_URL}/login?t={token}"


def _page(title, text):
    return HTMLResponse(
        f"""<!doctype html><html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;
background:#f6f7f9;color:#16191f}}div{{background:#fff;border:1px solid #e3e6eb;border-radius:12px;padding:28px;
max-width:420px;margin:16px}}</style></head><body><div><h1>{title}</h1><p>{text}</p></div></body></html>""",
        status_code=401)


@app.get("/login")
async def login(t: str = ""):
    row = await db.one("delete from web_sessions where token_hash=%s and kind='login' and expires_at > now() "
                       "returning staff_id", _hash(t)) if t else None
    if not row:
        return _page("Havola eskirgan", "Bu havola ishlatilgan yoki muddati o'tgan. Telegramda botga "
                                        "<b>/panel</b> deb yozing va yangi havola oling.")
    token = secrets.token_urlsafe(32)
    await db.ex("insert into web_sessions (token_hash, staff_id, kind, expires_at) values (%s,%s,'session',%s)",
                _hash(token), row["staff_id"], now() + timedelta(days=SESSION_DAYS))
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                    secure=config.PANEL_URL.startswith("https://"))
    return resp


@app.post("/api/logout")
async def logout(request: Request):
    tok = request.cookies.get(COOKIE)
    if tok:
        await db.ex("delete from web_sessions where token_hash=%s", _hash(tok))
    resp = Response(status_code=204)
    resp.delete_cookie(COOKIE)
    return resp


async def current(request: Request):
    tok = request.cookies.get(COOKIE)
    staff = None
    if tok:
        staff = await db.one(
            """select s.* from web_sessions w join staff s on s.id = w.staff_id
               where w.token_hash = %s and w.kind = 'session' and w.expires_at > now() and s.is_active""",
            _hash(tok))
    if not staff:
        raise HTTPException(401, "Kirish kerak: Telegramda botga /panel deb yozing.")
    return await Q.make_ctx(staff, msg_time=now(), chat_id=staff["telegram_id"])


async def run(ctx, name, args=None, confirmed=False):
    """Vositani panel nomidan bajaradi. Tugma bosish = foydalanuvchi tasdig'i."""
    if confirmed:
        ctx = replace(ctx, confirmed=True)
    res = await tools.dispatch(ctx, name, {k: v for k, v in (args or {}).items() if v not in (None, "")})
    if isinstance(res, dict) and "error" in res:
        raise HTTPException(403 if "ruxsat" in res["error"].lower() else 400, res["error"])
    return res


def can(ctx, name):
    t = tools.TOOLS.get(name)
    return bool(t and tools.visible(ctx, t))


async def body(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Noto'g'ri so'rov")
    if not isinstance(data, dict):
        raise HTTPException(400, "Noto'g'ri so'rov")
    return data


@app.exception_handler(ToolError)
async def _tool_error(request, exc):
    return Response(content=json.dumps({"detail": str(exc)}, ensure_ascii=False), status_code=400,
                    media_type="application/json")


# ---------- sahifa ----------
@app.get("/")
async def index():
    page = WEB_DIR / "index.html"
    if not page.exists():
        return HTMLResponse("Panel fayllari topilmadi: frontend papkasida <code>npm run build</code> qiling.", 500)
    return FileResponse(page, headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(WEB_DIR / "manifest.webmanifest", media_type="application/manifest+json")


PUBLIC_FILES = {"logo.webp", "logo-192.png", "logo-512.png", "favicon.png"}


@app.get("/{fname}")
async def public_file(fname: str):
    if fname not in PUBLIC_FILES or not (WEB_DIR / fname).exists():
        raise HTTPException(404)
    return FileResponse(WEB_DIR / fname, headers={"Cache-Control": "public, max-age=86400"})


# ---------- API ----------
@app.get("/api/me")
async def me(request: Request):
    ctx = await current(request)
    brs = await Q.branches_for(ctx) if ctx.branch_ids is None or ctx.branch_ids else []
    return {"name": ctx.staff["full_name"], "role": ctx.role, "role_uz": ROLE_UZ.get(ctx.role, ctx.role),
            "tools": sorted(n for n, t in tools.TOOLS.items() if tools.visible(ctx, t)),
            "branches": [{"id": b["id"], "name": b["name"], "active": b["is_active"]} for b in brs],
            "voice_input": voice.stt_enabled()}


@app.get("/api/dashboard")
async def dashboard(request: Request):
    ctx = await current(request)
    bids = await Q.branch_ids_for(ctx)
    t = today()
    out = {"sana": t}
    srows = await Q._student_rows(ctx)
    out["faol_oquvchilar"] = sum(1 for s in srows if s["status"] == "active")
    out["muzlatilgan"] = sum(1 for s in srows if s["status"] == "frozen")
    lessons = await db.q(
        """select g.id, g.name, g.start_time, g.end_time, b.name as branch, r.name as room, st.full_name as teacher,
                  (select count(*) from enrollments e where e.group_id = g.id and e.status = 'active') as students,
                  exists (select 1 from attendance a join enrollments e on e.id = a.enrollment_id
                          where e.group_id = g.id and a.lesson_date = %s) as marked
           from groups g join branches b on b.id = g.branch_id
           left join rooms r on r.id = g.room_id
           left join teachers tt on tt.id = g.teacher_id left join staff st on st.id = tt.staff_id
           where g.is_active and b.is_active and g.branch_id = any(%s) and %s::int = any(g.days)
             and (%s::uuid is null or tt.staff_id = %s::uuid)
           order by g.start_time, g.name""",
        t, bids, t.isoweekday(), *(2 * [ctx.staff_id if ctx.role == "teacher" else None]))
    out["bugungi_darslar"] = lessons
    if can(ctx, "debtors"):
        pay = await Q.payment_overview(bids)
        over = [p for p in pay if p["state"] == "overdue"]
        out["qarzdorlar_soni"] = len(over)
        out["tolov_oynasi_soni"] = sum(1 for p in pay if p["state"] == "window")
        out["qarzdorlar"] = [{"id": p["student_id"], "ism": p["full_name"], "guruh": p["group_name"],
                              "summa": int(p["monthly_fee"]) if p["monthly_fee"] else None} for p in over[:8]]
        out["qarz_summa"] = sum(int(p["monthly_fee"]) for p in over if p["monthly_fee"])
    if can(ctx, "absence_alerts"):
        out["kelmayotganlar"] = [{"ism": r["full_name"], "guruh": r["group_name"]}
                                 for r in await Q.absence_streaks(bids)]
    if can(ctx, "list_leads"):
        out["lidlar_7_kun"] = (await db.one(
            "select count(*) as n from leads where (branch_id = any(%s) or branch_id is null) "
            "and created_at >= now() - interval '7 days'", bids))["n"]
        out["javobsiz_lidlar"] = (await db.one(
            """select count(*) as n from leads l where (l.branch_id = any(%s) or l.branch_id is null)
               and l.status = 'new' and l.created_at < now() - interval '2 hours'
               and not exists (select 1 from lead_activities a where a.lead_id = l.id)""", bids))["n"]
    if can(ctx, "finance_summary"):
        fin = await Q.finance_summary(bids, t.replace(day=1), t)
        out["tushum_oy"] = fin["tushum_jami"]
        out["foyda_oy"] = fin["sof_foyda_taxminan"]
    if ctx.role == "owner":
        out["tasdiqlar"] = (await tools.list_approvals(ctx))["kutayotganlar"]
    mine = await db.q(
        """select t.id, t.text, t.due_at, t.status, c.full_name as kimdan from tasks t
           left join staff c on c.id = t.created_by
           where t.assigned_to = %s and t.status in ('sent','seen') order by t.due_at nulls last, t.created_at""",
        ctx.staff_id)
    out["mening_vazifalarim"] = mine
    if can(ctx, "send_task"):
        out["bergan_ochiq_vazifalar"] = (await db.one(
            "select count(*) as n from tasks where created_by=%s and status in ('sent','seen')", ctx.staff_id))["n"]
    if can(ctx, "list_posts"):
        out["rejalashtirilgan_postlar"] = (await db.one(
            "select count(*) as n from content_posts where status='scheduled'"))["n"]
    return out


@app.get("/api/groups")
async def groups(request: Request):
    ctx = await current(request)
    if ctx.role == "teacher":
        bids = await Q.branch_ids_for(ctx)
        rows = await db.q(
            """select g.id, g.name as nom, g.subject as fan, b.name as filial, r.name as xona, g.days,
                      g.start_time, g.end_time,
                      (select count(*) from enrollments e where e.group_id = g.id and e.status='active') as oquvchilar
               from groups g join branches b on b.id = g.branch_id join teachers t on t.id = g.teacher_id
               left join rooms r on r.id = g.room_id
               where g.is_active and t.staff_id = %s and g.branch_id = any(%s) order by g.name""",
            ctx.staff_id, bids)
        for r in rows:
            r["jadval"] = tools._sched(r.pop("days"), r.pop("start_time"), r.pop("end_time"))
            r["oqituvchi"] = ctx.staff["full_name"]
        return {"guruhlar": rows, "xonalar": [], "filiallar": []}
    return await run(ctx, "overview")


@app.post("/api/groups")
async def create_group(request: Request):
    ctx = await current(request)
    b = await body(request)
    return await run(ctx, "create_group", {**{k: b.get(k) for k in (
        "branch", "name", "subject", "teacher", "room", "days", "start_time", "end_time")},
        "summary": f"Paneldan yangi guruh: {b.get('name')}"}, True)


@app.get("/api/groups/{gid}/attendance")
async def group_attendance(gid: str, request: Request, date: str = ""):
    ctx = await current(request)
    g = await Q.find_group(ctx, gid)
    d = date or str(today())
    res = await run(ctx, "group_attendance", {"group": gid, "date": d})
    res["dars_kuni"] = parse_date(d).isoweekday() in g["days"]
    return res


@app.post("/api/attendance")
async def mark_attendance(request: Request):
    ctx = await current(request)
    b = await body(request)
    return await run(ctx, "mark_attendance", {"group": b.get("group"), "absent": b.get("absent") or [],
                                              "date": b.get("date"), "summary": "Paneldan davomat"}, True)


@app.post("/api/message-parents")
async def message_parents(request: Request):
    ctx = await current(request)
    b = await body(request)
    return await run(ctx, "message_parents", {"messages": b.get("messages") or [],
                                              "summary": "Paneldan ota-onalarga xabar"}, True)


@app.get("/api/students")
async def students(request: Request, q: str = ""):
    ctx = await current(request)
    rows = await Q._student_rows(ctx)
    if q:
        hits = fuzzy(q, [(r["id"], r["full_name"]) for r in rows], limit=30, min_score=0.5)
        ids = [h[1] for h in hits]
    else:
        ids = [r["id"] for r in rows]
    if not ids:
        return {"oquvchilar": []}
    data = await db.q(
        """select s.id, s.full_name as ism, s.status::text as holat, b.name as filial,
                  coalesce(string_agg(g.name, ', ' order by g.name), '') as guruhlar,
                  exists (select 1 from student_parents sp join parents p on p.id = sp.parent_id
                          where sp.student_id = s.id and p.telegram_id is not null) as ota_ona_ulangan
           from students s join branches b on b.id = s.branch_id
           left join enrollments e on e.student_id = s.id and e.status <> 'left'
           left join groups g on g.id = e.group_id
           where s.id = any(%s) group by s.id, b.name""", ids)
    order = {i: n for n, i in enumerate(ids)}
    data.sort(key=lambda r: (order[r["id"]] if q else 0, r["ism"]))
    return {"oquvchilar": data}


@app.get("/api/students/{sid}")
async def student(sid: str, request: Request):
    ctx = await current(request)
    return await run(ctx, "student_profile", {"student": sid})


@app.post("/api/students")
async def add_student(request: Request):
    ctx = await current(request)
    b = await body(request)
    return await run(ctx, "add_student", {**{k: b.get(k) for k in (
        "full_name", "group", "parent_name", "parent_phone", "monthly_fee", "joined_on", "allow_duplicate")},
        "summary": f"Paneldan yangi o'quvchi: {b.get('full_name')}"}, True)


@app.post("/api/payments")
async def record_payment(request: Request):
    ctx = await current(request)
    b = await body(request)
    return await run(ctx, "record_payment", {**{k: b.get(k) for k in ("student", "amount", "group", "paid_on",
                                                                      "method")},
                                             "summary": "Paneldan to'lov"}, True)


@app.get("/api/debtors")
async def debtors(request: Request):
    ctx = await current(request)
    return await run(ctx, "debtors")


@app.get("/api/leads")
async def leads(request: Request, status: str = ""):
    ctx = await current(request)
    res = await run(ctx, "list_leads", {"status": status or None, "limit": 200})
    if can(ctx, "lead_stats"):
        res["statistika"] = await run(ctx, "lead_stats", {"days": 30})
    return res


@app.post("/api/leads")
async def add_lead(request: Request):
    ctx = await current(request)
    b = await body(request)
    return await run(ctx, "add_lead", {**{k: b.get(k) for k in ("full_name", "phone", "source", "branch",
                                                                "campaign", "note")},
                                       "summary": "Paneldan yangi lid"}, True)


@app.post("/api/leads/{lid}")
async def update_lead(lid: str, request: Request):
    ctx = await current(request)
    b = await body(request)
    return await run(ctx, "update_lead", {"lead": lid, "status": b.get("status"), "note": b.get("note"),
                                          "kind": b.get("kind"), "summary": "Paneldan lid yangilandi"}, True)


@app.get("/api/finance")
async def finance(request: Request, period: str = "this_month"):
    ctx = await current(request)
    return await run(ctx, "finance_summary", {"period": period})


@app.post("/api/expenses")
async def add_expense(request: Request):
    ctx = await current(request)
    b = await body(request)
    return await run(ctx, "add_expense", {**{k: b.get(k) for k in ("amount", "category", "note", "spent_on",
                                                                   "branch")},
                                          "summary": "Paneldan xarajat"}, True)


@app.get("/api/teachers")
async def teachers(request: Request):
    ctx = await current(request)
    if ctx.role == "teacher":
        return await run(ctx, "my_report")
    return await run(ctx, "teacher_report")


@app.get("/api/staff")
async def staff(request: Request):
    ctx = await current(request)
    return await run(ctx, "list_staff")


@app.post("/api/approvals/{aid}")
async def decide(aid: str, request: Request):
    ctx = await current(request)
    b = await body(request)
    return await run(ctx, "decide_approval", {"approve": bool(b.get("approve")), "approval_id": aid,
                                              "summary": "Paneldan qaror"}, True)


@app.get("/api/export/{kind}")
async def export(kind: str, request: Request, month: str = "", group: str = ""):
    ctx = await current(request)
    if not can(ctx, "export_excel"):
        raise HTTPException(403, "Eksport uchun ruxsat yo'q.")
    if kind == "payments" and ctx.level("view_finance") != "allow":
        raise HTTPException(403, "To'lovlar hisobotini ko'rishga ruxsat yo'q.")
    bids = await Q.branch_ids_for(ctx)
    g = await Q.find_group(ctx, group) if kind == "attendance_grid" else None
    try:
        fname, data = await exports.build(kind, bids, group=g, month=month or None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fname.encode("ascii", "ignore").decode()}"'})


# ---------- vazifalar ----------
@app.get("/api/tasks")
async def tasks_list(request: Request, scope: str = "hammasi", only_open: bool = False):
    ctx = await current(request)
    return await run(ctx, "list_tasks", {"scope": scope, "only_open": only_open})


@app.get("/api/task-recipients")
async def task_recipients(request: Request):
    ctx = await current(request)
    if not can(ctx, "send_task"):
        raise HTTPException(403, "Vazifa berishga ruxsat yo'q.")
    rows = await tools.staff_in_scope(ctx)
    return {"xodimlar": [{"id": r["id"], "ism": r["full_name"], "rol": r["role"], "botda": bool(r["telegram_id"])}
                         for r in rows if r["role"] != "owner"]}


@app.post("/api/tasks")
async def task_create(request: Request):
    ctx = await current(request)
    b = await body(request)
    return await run(ctx, "send_task", {"text": b.get("text"), "recipients": b.get("recipients") or None,
                                        "role": b.get("role") or None, "branch": b.get("branch") or None,
                                        "due": b.get("due") or None, "summary": "Paneldan vazifa"}, True)


@app.post("/api/tasks/{tid}")
async def task_update(tid: str, request: Request):
    ctx = await current(request)
    b = await body(request)
    try:
        await tools.set_task_status(tid, str(b.get("status")), ctx.staff)
    except ToolError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


# ---------- kontent ----------
@app.get("/api/content")
async def content_list(request: Request):
    ctx = await current(request)
    res = await run(ctx, "list_posts", {"limit": 40})
    res["sozlamalar"] = {"telegram": bool(config.TELEGRAM_CHANNEL_ID),
                         "instagram": social.ig_configured(),
                         "storage": social.storage_enabled()}
    return res


@app.post("/api/content")
async def content_create(request: Request, text: str = Form(""), targets: str = Form(""),
                         schedule_at: str = Form(""), media: UploadFile | None = File(None)):
    ctx = await current(request)
    if not can(ctx, "publish_post"):
        raise HTTPException(403, "Post chiqarishga ruxsat yo'q.")
    args = {"text": text, "targets": [t for t in targets.split(",") if t], "schedule_at": schedule_at or None,
            "summary": "Paneldan post"}
    if media and media.filename:
        kind = social.guess_kind(media.filename, media.content_type or "")
        if not kind:
            raise HTTPException(400, "Faqat rasm yoki video yuklash mumkin.")
        data = await media.read()
        if len(data) > social.MAX_UPLOAD:
            raise HTTPException(400, "Fayl juda katta (50 MB gacha).")
        args["media_kind"] = kind
        if social.storage_enabled():
            ext = media.filename.rsplit(".", 1)[-1].lower() if "." in media.filename else ("mp4" if kind == "video" else "jpg")
            args["media_url"] = await social.upload_public(data, ext, media.content_type or "application/octet-stream")
        elif set(args["targets"]) <= {"telegram"} and ctx.staff.get("telegram_id"):
            # Storage yo'q: fayl avval sizning Telegram chatingizga boradi (oldindan ko'rish), uning file_id si bilan
            # kanalga chiqadi (darhol yoki rejalashtirilgan vaqtda)
            cap = "Kanal uchun fayl (oldindan ko'rish)"
            if kind == "video":
                m = await rt.bot.send_video(ctx.staff["telegram_id"], video=data, caption=cap, filename=media.filename,
                                            supports_streaming=True, read_timeout=180, write_timeout=180)
                args["file_id"] = m.video.file_id
            else:
                m = await rt.bot.send_photo(ctx.staff["telegram_id"], photo=data, caption=cap)
                args["file_id"] = m.photo[-1].file_id
        else:
            raise HTTPException(400, "Instagram/YouTube/TikTok uchun fayl ochiq havolada bo'lishi kerak: Supabase Storage "
                                     "sozlang (.env: SUPABASE_URL, SUPABASE_SERVICE_KEY). Faqat Telegram uchun shart emas.")
    return await run(ctx, "publish_post", args, True)


@app.post("/api/content/{pid}/cancel")
async def content_cancel(pid: str, request: Request):
    ctx = await current(request)
    return await run(ctx, "cancel_post", {"post": pid, "summary": "Paneldan post bekor qilindi"}, True)


@app.post("/api/content/draft")
async def content_draft(request: Request):
    """Jimi post matnini yozib beradi (chiqarmaydi)."""
    ctx = await current(request)
    if not can(ctx, "publish_post"):
        raise HTTPException(403, "Ruxsat yo'q.")
    b = await body(request)
    topic = str(b.get("topic") or "").strip()[:1500]
    if not topic:
        raise HTTPException(400, "Mavzuni yozing.")
    agent = brain.AGENTS.get("content") or brain.AGENTS["jimi"]
    notes = await brain.load_notes()
    text = await brain.quick(
        f"Quyidagi mavzuda {', '.join(b.get('targets') or ['telegram'])} uchun bitta tayyor post matnini yozing. "
        "Faqat post matnining o'zini qaytaring, izohsiz.\n\nMavzu: " + topic,
        system=agent["prompt"] + ("\n\nBiznes haqida:\n" + notes if notes else ""), fast=False)
    return {"matn": text}


# ---------- AI jamoa ----------
@app.get("/api/agents")
async def agents(request: Request):
    ctx = await current(request)
    res = await run(ctx, "list_agents")
    res["katalog"] = (await run(ctx, "list_agent_catalog"))["katalog"]
    res["ornata_oladi"] = ctx.level("manage_agents") != "deny"
    return res


@app.post("/api/agents/install")
async def agent_install(request: Request):
    ctx = await current(request)
    b = await body(request)
    return await run(ctx, "install_agent", {"name": b.get("name"), "summary": f"Agent o'rnatish: {b.get('name')}"}, True)


@app.post("/api/agents/{name}/deactivate")
async def agent_deactivate(name: str, request: Request):
    ctx = await current(request)
    return await run(ctx, "deactivate_agent", {"name": name, "summary": f"Agentni to'xtatish: {name}"}, True)


# ---------- kontent reja, dizayn, izohlar ----------
@app.get("/api/plan")
async def plan_list(request: Request, month: str = ""):
    ctx = await current(request)
    return await run(ctx, "list_content_plan", {"month": month or None})


@app.post("/api/plan")
async def plan_add(request: Request):
    ctx = await current(request)
    b = await body(request)
    return await run(ctx, "plan_content", {"items": b.get("items") or [], "summary": "Paneldan reja"}, True)


@app.post("/api/plan/{item}")
async def plan_update(item: str, request: Request):
    ctx = await current(request)
    b = await body(request)
    return await run(ctx, "update_plan_item", {"item": item, "status": b.get("status"), "date": b.get("date"),
                                               "topic": b.get("topic"), "summary": "Paneldan reja o'zgardi"}, True)


@app.get("/api/design/templates")
async def design_templates(request: Request):
    await current(request)
    from . import design
    return {"shablonlar": [{"nom": k, "tavsif": v[0]} for k, v in design.TEMPLATES.items()],
            "formatlar": list(design.SIZES)}


@app.post("/api/design")
async def design_make(request: Request, template: str = Form(...), format: str = Form("post"), title: str = Form(""),
                      score: str = Form(""), subtitle: str = Form(""), details: str = Form(""), badge: str = Form(""),
                      photo: UploadFile | None = File(None)):
    ctx = await current(request)
    if not can(ctx, "make_design"):
        raise HTTPException(403, "Ruxsat yo'q.")
    from . import design
    pdata = await photo.read() if photo and photo.filename else None
    try:
        png = design.render(template, format, {"title": title, "score": score, "subtitle": subtitle,
                                               "details": details, "badge": badge}, pdata)
    except ValueError as e:
        raise HTTPException(400, str(e))
    url = await social.upload_public(png, "png", "image/png") if social.storage_enabled() else None
    return {"rasm": base64.b64encode(png).decode(), "media_url": url}


@app.get("/api/comments")
async def comments(request: Request, status: str = "yangi"):
    ctx = await current(request)
    return await run(ctx, "list_comments", {"status": status})


@app.post("/api/comments/{cid}")
async def comment_action(cid: str, request: Request):
    ctx = await current(request)
    b = await body(request)
    if b.get("action") == "skip":
        if not can(ctx, "list_comments"):
            raise HTTPException(403, "Ruxsat yo'q.")
        await db.ex("update ig_comments set status='etiborsiz' where id=%s", cid)
        return {"ok": True}
    return await run(ctx, "reply_comment", {"comment": cid, "text": b.get("text"), "summary": "Izohga javob"}, True)


# ---------- sifat, ushlab qolish, yollash ----------
@app.get("/api/quality")
async def quality(request: Request):
    ctx = await current(request)
    out = {"sifat": await run(ctx, "quality_report"), "sorovnoma": await run(ctx, "survey_report")}
    if can(ctx, "retention_risks"):
        out["xavf"] = await run(ctx, "retention_risks")
    return out


@app.get("/api/candidates")
async def candidates(request: Request):
    ctx = await current(request)
    res = await run(ctx, "list_candidates")
    res["vakansiyalar"] = await db.q("select id, title, status, code, created_at::date as sana, "
                                     "(select count(*) from candidates c where c.vacancy_id = v.id) as arizalar "
                                     "from vacancies v order by created_at desc limit 20")
    for v in res["vakansiyalar"]:
        v["havola"] = invite_link("vk", v.pop("code"))
    return res


@app.post("/api/vacancies")
async def vacancy_create(request: Request):
    ctx = await current(request)
    b = await body(request)
    return await run(ctx, "create_vacancy", {"title": b.get("title"), "description": b.get("description"),
                                             "requirements": b.get("requirements"),
                                             "questions": [q for q in (b.get("questions") or []) if q.strip()] or None,
                                             "summary": "Paneldan vakansiya"}, True)


@app.post("/api/candidates/{cid}")
async def candidate_update(cid: str, request: Request):
    ctx = await current(request)
    b = await body(request)
    return await run(ctx, "update_candidate", {"candidate": cid, "status": b.get("status"),
                                               "interview_at": b.get("interview_at"), "summary": "Nomzod holati"}, True)


# ---------- sozlamalar va ulanishlar ----------
@app.get("/api/settings")
async def settings_get(request: Request):
    ctx = await current(request)
    from . import video
    res = await run(ctx, "get_settings")
    res["ulanishlar"] = [
        {"nom": "Telegram kanal", "ulangan": bool(config.TELEGRAM_CHANNEL_ID), "kalit": "TELEGRAM_CHANNEL_ID"},
        {"nom": "Instagram (post, Reels, izohlar)", "ulangan": social.ig_configured(),
         "kalit": "IG_USER_ID, IG_ACCESS_TOKEN"},
        {"nom": "Fayl saqlash (Supabase Storage)", "ulangan": social.storage_enabled(),
         "kalit": "SUPABASE_URL, SUPABASE_SERVICE_KEY"},
        {"nom": "Ovoz: nutqni matnga (ElevenLabs)", "ulangan": voice.stt_enabled(), "kalit": "ELEVENLABS_API_KEY"},
        {"nom": "Video tahrir (ffmpeg)", "ulangan": video.available(), "kalit": "ffmpeg o'rnatish"},
        {"nom": "Meta Ads (reklama sarfi)", "ulangan": bool(config.META_AD_ACCOUNT_ID), "kalit": "META_AD_ACCOUNT_ID"},
        {"nom": "YouTube Shorts / TikTok (n8n yoki Make)", "ulangan": bool(config.N8N_WEBHOOK_URL), "kalit": "N8N_WEBHOOK_URL"},
        {"nom": "Lidlar webhook (n8n/Make -> tizim)", "ulangan": bool(config.HOOK_SECRET), "kalit": "HOOK_SECRET"},
        {"nom": "Telegram kanal izohlari", "ulangan": bool(config.TELEGRAM_DISCUSSION_ID), "kalit": "TELEGRAM_DISCUSSION_ID"},
    ]
    res["tahrir_qila_oladi"] = can(ctx, "set_setting")
    res["rahbar"] = ctx.role == "owner"
    return res


@app.post("/api/settings")
async def settings_set(request: Request):
    ctx = await current(request)
    b = await body(request)
    return await run(ctx, "set_setting", {"key": b.get("key"), "value": b.get("value"), "summary": "Sozlama"}, True)


# ---------- tashqi xizmatlardan lid qabul qilish (n8n / Make / Instagram lead-forma) ----------
@app.post("/api/hooks/lead")
async def hook_lead(request: Request, key: str = ""):
    if not config.HOOK_SECRET or not secrets.compare_digest(key, config.HOOK_SECRET):
        raise HTTPException(403, "Kalit noto'g'ri")
    b = await body(request)
    phone = str(b.get("phone") or "").strip()
    if len("".join(ch for ch in phone if ch.isdigit())) < 9:
        raise HTTPException(400, "phone kerak")
    br = await db.one("select id from branches where is_active order by name limit 1")
    camp = None
    if b.get("campaign"):
        camp = await db.one("select id from campaigns where name=%s or external_id=%s limit 1", b["campaign"], b["campaign"])
    row = await db.one("insert into leads (branch_id, full_name, phone, source, campaign_id, note) values (%s,%s,%s,%s,%s,%s) "
                       "returning id", br["id"] if br else None, b.get("full_name"), phone, b.get("source") or "instagram_forma",
                       camp["id"] if camp else None, b.get("note"))
    for s_ in await db.q("select telegram_id from staff where is_active and telegram_id is not null and role in ('admin','manager')"):
        try:
            await rt.bot.send_message(s_["telegram_id"], f"🆕 Yangi lid ({b.get('source') or 'forma'}): "
                                      f"{b.get('full_name') or ''} {phone}. Tezroq qo'ng'iroq qiling.")
        except Exception:
            pass
    return {"ok": True, "lead_id": row["id"]}


# ---------- Jimi bilan suhbat ----------
@app.get("/api/chat")
async def chat_history(request: Request):
    ctx = await current(request)
    rows = await db.q("select role, content, created_at from conversations where staff_id=%s "
                      "order by id desc limit 40", ctx.staff_id)
    return {"xabarlar": list(reversed(rows))}


async def _answer(ctx, text, was_voice=False):
    async with rt.lock(ctx.staff["telegram_id"] or ctx.staff_id):
        ctx = replace(ctx, msg_time=now(), was_voice=was_voice)
        try:
            return await brain.chat(ctx, text)
        except Exception:
            log.exception("panel chat xatosi")
            return "Kechirasiz, hozir xatolik yuz berdi. Birozdan keyin qayta urinib ko'ring."


async def _speech(text):
    audio = await voice.synthesize(text) if config.VOICE_REPLIES else None
    return base64.b64encode(audio).decode() if audio else None


@app.post("/api/chat")
async def chat(request: Request):
    ctx = await current(request)
    b = await body(request)
    text = str(b.get("text") or "").strip()[:4000]
    if not text:
        raise HTTPException(400, "Xabar bo'sh")
    answer = await _answer(ctx, text)
    return {"javob": answer, "audio": await _speech(answer) if b.get("speak") else None}


@app.post("/api/voice")
async def chat_voice(request: Request, audio: UploadFile = File(...)):
    ctx = await current(request)
    if not voice.stt_enabled():
        raise HTTPException(400, "Ovozli buyruq yoqilmagan (.env da ELEVENLABS_API_KEY kerak).")
    data = await audio.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(400, "Ovoz juda uzun.")
    try:
        heard = await voice.transcribe(data, filename=audio.filename or "voice.webm",
                                       mime=audio.content_type or "audio/webm")
    except Exception:
        log.exception("panel ovoz xatosi")
        raise HTTPException(400, "Ovozni tushuna olmadim. Qayta urinib ko'ring.")
    if not heard:
        raise HTTPException(400, "Hech narsa eshitilmadi.")
    answer = await _answer(ctx, heard, was_voice=True)
    return {"eshitildi": heard, "javob": answer, "audio": await _speech(answer)}


# ---------- ishga tushirish ----------
async def serve():
    import uvicorn
    cfg = uvicorn.Config(app, host=config.PANEL_HOST, port=config.PANEL_PORT, log_level="warning",
                         lifespan="off", access_log=False)
    server = uvicorn.Server(cfg)
    # Ctrl+C ni Telegram bot qismi boshqaradi, panel signallarni o'ziga olmasin
    server.capture_signals = contextlib.nullcontext
    rt.web_server = server
    log.info("Panel: %s (botga /panel deb yozing)", config.PANEL_URL)
    try:
        await server.serve()
    except SystemExit:
        log.error("Panel ishga tushmadi: %s porti band bo'lishi mumkin (.env da PANEL_PORT ni o'zgartiring)",
                  config.PANEL_PORT)
