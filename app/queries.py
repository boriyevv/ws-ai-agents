"""Bir necha joyda ishlatiladigan ma'lumot so'rovlari."""
import re
from datetime import timedelta

from . import db
from .core import Ctx, ToolError, fuzzy, norm, payment_state, today


# ---------- kontekst yaratish ----------
async def make_ctx(staff, **kw):
    if staff["role"] == "owner":
        branch_ids, perms = None, {}
    else:
        rows = await db.q("select branch_id from staff_branch_access where staff_id=%s", staff["id"])
        branch_ids = [r["branch_id"] for r in rows]
        prow = await db.q("select action, level::text as level from role_permissions where role=%s::user_role",
                          staff["role"])
        perms = {r["action"]: r["level"] for r in prow}
    return Ctx(staff=staff, branch_ids=branch_ids, perms=perms, **kw)


# ---------- filial / guruh / o'quvchi qidirish ----------
ORDINALS = {"bir": 1, "birinchi": 1, "ikki": 2, "ikkinchi": 2, "uch": 3, "uchinchi": 3, "tort": 4,
            "tortinchi": 4, "besh": 5, "beshinchi": 5, "olti": 6, "oltinchi": 6}


def _branch_number(text):
    """'2-filial', 'ikkinchi filial', '2' -> 2"""
    t = norm(text)
    m = re.search(r"\d+", t)
    if m:
        return int(m.group())
    for w in t.replace("-", " ").split():
        if w in ORDINALS:
            return ORDINALS[w]
    return None


async def branches_for(ctx, branch=None, active_only=False):
    """Foydalanuvchi ko'ra oladigan filiallar. branch berilsa, faqat mos keladigani."""
    rows = await db.q("select id, name, is_active from branches order by name")
    if ctx.branch_ids is not None:
        rows = [r for r in rows if r["id"] in ctx.branch_ids]
    if branch:
        bs = str(branch).strip()
        exact = [r for r in rows if str(r["id"]) == bs or norm(r["name"]) == norm(bs)]
        if not exact:
            num = _branch_number(bs)
            if num is not None:
                exact = [r for r in rows if _branch_number(r["name"]) == num]
        if not exact:
            hits = fuzzy(bs, [(r["id"], r["name"]) for r in rows], limit=1)
            exact = [r for r in rows if hits and r["id"] == hits[0][1]]
        if not exact:
            raise ToolError(f"Filial topilmadi yoki sizga ruxsat yo'q: {branch}. Sizning filiallaringiz: "
                            + (", ".join(r["name"] for r in rows) or "yo'q"))
        return exact
    if active_only:
        rows = [r for r in rows if r["is_active"]]
    if not rows:
        raise ToolError("Sizga hali hech qaysi filial biriktirilmagan. Rahbardan ruxsat so'rang.")
    return rows


async def branch_ids_for(ctx, branch=None):
    return [r["id"] for r in await branches_for(ctx, branch)]


async def _teacher_group_ids(ctx):
    rows = await db.q("select g.id from groups g join teachers t on t.id = g.teacher_id where t.staff_id = %s",
                      ctx.staff_id)
    return [r["id"] for r in rows]


def _pick(query, rows, key, what):
    """id yoki taxminiy ism bo'yicha bitta qatorni tanlaydi, aks holda tushunarli xato."""
    q = str(query).strip()
    for r in rows:
        if str(r["id"]) == q:
            return r
    hits = fuzzy(q, [(r["id"], r[key]) for r in rows], limit=4)
    if not hits:
        return None
    exact = [h for h in hits if h[0] >= 0.99]
    if len(exact) == 1:
        return next(r for r in rows if r["id"] == exact[0][1])
    if len(hits) > 1 and hits[0][0] - hits[1][0] < 0.1:
        raise ToolError(f"'{query}' bir nechta {what}ga mos keldi: " + ", ".join(h[2] for h in hits) + ". Qaysi biri?")
    return next(r for r in rows if r["id"] == hits[0][1])


async def find_group(ctx, query, branch=None):
    if not query:
        raise ToolError("Guruh nomini ayting.")
    bids = await branch_ids_for(ctx, branch)
    rows = await db.q(
        """select g.id, g.name, g.subject, g.branch_id, g.days, g.start_time, g.end_time, b.name as branch
           from groups g join branches b on b.id = g.branch_id
           where g.is_active and g.branch_id = any(%s) order by g.name""", bids)
    if ctx.role == "teacher":
        mine = set(await _teacher_group_ids(ctx))
        rows = [r for r in rows if r["id"] in mine]
    g = _pick(query, rows, "name", "guruh")
    if not g:
        raise ToolError(f"Guruh topilmadi: {query}. Mavjud guruhlar: " + (", ".join(r["name"] for r in rows) or "yo'q"))
    return g


async def _student_rows(ctx, branch=None):
    bids = await branch_ids_for(ctx, branch)
    rows = await db.q("select id, full_name, branch_id, status::text as status from students "
                      "where branch_id = any(%s) and status <> 'left'", bids)
    if ctx.role == "teacher":
        gids = await _teacher_group_ids(ctx)
        ok = {r["student_id"] for r in await db.q(
            "select student_id from enrollments where group_id = any(%s) and status <> 'left'", gids)}
        rows = [r for r in rows if r["id"] in ok]
    return rows


async def _candidates(ctx, ids):
    rows = await db.q(
        """select s.id, s.full_name as ism, s.status::text as holat, b.name as filial,
                  coalesce(string_agg(g.name, ', ' order by g.name), '') as guruhlar
           from students s join branches b on b.id = s.branch_id
           left join enrollments e on e.student_id = s.id and e.status <> 'left'
           left join groups g on g.id = e.group_id
           where s.id = any(%s) group by s.id, b.name""", list(ids))
    order = {i: n for n, i in enumerate(ids)}
    return sorted(rows, key=lambda r: order.get(r["id"], 99))


async def find_student(ctx, query, branch=None):
    if not query:
        raise ToolError("O'quvchi ismini ayting.")
    rows = await _student_rows(ctx, branch)
    q = str(query).strip()
    for r in rows:
        if str(r["id"]) == q:
            return r
    hits = fuzzy(q, [(r["id"], r["full_name"]) for r in rows], limit=5)
    if not hits:
        raise ToolError(f"O'quvchi topilmadi: {query}")
    exact = [h for h in hits if h[0] >= 0.99]
    best = None
    if len(exact) == 1:
        best = exact[0]
    elif not exact and (len(hits) == 1 or hits[0][0] - hits[1][0] >= 0.1):
        best = hits[0]
    if best:
        return next(r for r in rows if r["id"] == best[1])
    cands = await _candidates(ctx, [h[1] for h in hits])
    raise ToolError("Bir nechta o'quvchi mos keldi, qaysi biri? " + "; ".join(
        f"{c['ism']} ({c['guruhlar'] or 'guruhsiz'}, id {c['id']})" for c in cands))


async def find_enrollment(ctx, student_id, group_query=None):
    rows = await db.q(
        """select e.id, e.group_id, g.name as group_name, g.days, e.cycle_start, e.cycle_paid, e.unpaid_cycles,
                  e.monthly_fee, e.status::text as status
           from enrollments e join groups g on g.id = e.group_id
           where e.student_id = %s and e.status <> 'left' order by e.joined_on""", student_id)
    if group_query:
        hits = fuzzy(group_query, [(r["id"], r["group_name"]) for r in rows])
        if not hits:
            raise ToolError("Bu o'quvchi ko'rsatilgan guruhda emas.")
        return next(r for r in rows if r["id"] == hits[0][1])
    if not rows:
        raise ToolError("Bu o'quvchi hech qaysi guruhga yozilmagan.")
    if len(rows) > 1:
        raise ToolError("O'quvchi bir nechta guruhda: " + ", ".join(r["group_name"] for r in rows)
                        + ". Qaysi guruh?")
    return rows[0]


# ---------- tahlil so'rovlari ----------
async def payment_overview(bids, on=None):
    """Faol o'quvchilarning to'lov holati."""
    on = on or today()
    rows = await db.q(
        """select e.id as enrollment_id, s.id as student_id, s.full_name, g.name as group_name,
                  g.days, b.name as branch, e.cycle_start, e.cycle_paid, e.unpaid_cycles, e.monthly_fee
           from enrollments e
           join students s on s.id = e.student_id
           join groups g on g.id = e.group_id
           join branches b on b.id = g.branch_id
           where e.status = 'active' and s.status = 'active' and g.branch_id = any(%s)
           order by b.name, g.name, s.full_name""", bids)
    out = []
    for r in rows:
        st = payment_state(r["cycle_start"], r["days"], r["cycle_paid"], r["unpaid_cycles"], on)
        r["state"] = st
        out.append(r)
    return out


async def absence_streaks(bids, n=3):
    rows = await db.q(
        """select s.full_name, g.name as group_name, b.name as branch, e.id as enrollment_id,
                  (select array_agg(x.status::text order by x.lesson_date desc)
                   from (select a.status, a.lesson_date from attendance a
                         where a.enrollment_id = e.id order by a.lesson_date desc limit %s) x) as last
           from enrollments e
           join students s on s.id = e.student_id
           join groups g on g.id = e.group_id
           join branches b on b.id = g.branch_id
           where e.status = 'active' and s.status = 'active' and g.branch_id = any(%s)""", n, bids)
    return [r for r in rows if r["last"] and len(r["last"]) >= n and all(x == "absent" for x in r["last"])]


async def unmarked_groups(bids, day):
    return await db.q(
        """select g.name, b.name as branch
           from groups g join branches b on b.id = g.branch_id
           where g.is_active and b.is_active and g.branch_id = any(%s)
             and extract(isodow from %s::date)::int = any(g.days)
             and exists (select 1 from enrollments e where e.group_id = g.id and e.status = 'active')
             and not exists (select 1 from attendance a join enrollments e on e.id = a.enrollment_id
                             where e.group_id = g.id and a.lesson_date = %s::date)""", bids, day, day)


async def finance_summary(bids, start, end):
    income = await db.q(
        """select b.name as branch, coalesce(sum(p.amount), 0) as total, count(*) as payments
           from payments p join enrollments e on e.id = p.enrollment_id
           join groups g on g.id = e.group_id join branches b on b.id = g.branch_id
           where g.branch_id = any(%s) and p.paid_on between %s and %s group by b.name""", bids, start, end)
    expenses = await db.q(
        """select coalesce(category, 'boshqa') as category, coalesce(sum(amount), 0) as total
           from expenses where (branch_id = any(%s) or branch_id is null) and spent_on between %s and %s
           group by 1 order by 2 desc""", bids, start, end)
    ads = await db.one(
        """select coalesce(sum(ms.amount), 0) as total
           from marketing_spend ms join campaigns c on c.id = ms.campaign_id
           where (c.branch_id = any(%s) or c.branch_id is null) and ms.spend_date between %s and %s""",
        bids, start, end)
    total_income = sum(int(r["total"]) for r in income)
    total_exp = sum(int(r["total"]) for r in expenses)
    ad_spend = int(ads["total"]) if ads else 0
    return {
        "davr": f"{start} dan {end} gacha",
        "tushum_jami": total_income,
        "tushum_filiallar": [{"filial": r["branch"], "summa": int(r["total"]), "tolovlar_soni": r["payments"]}
                             for r in income],
        "xarajat_jami": total_exp,
        "xarajat_toifalar": [{"toifa": r["category"], "summa": int(r["total"])} for r in expenses],
        "reklama_xarajati": ad_spend,
        "sof_foyda_taxminan": total_income - total_exp - ad_spend,
    }


async def lead_stats(bids, days=30):
    by_source = await db.q(
        """select coalesce(source, 'noma''lum') as source, count(*) as jami,
                  count(*) filter (where status = 'trial') as sinov,
                  count(*) filter (where status = 'enrolled') as oquvchi_boldi,
                  count(*) filter (where status = 'rejected') as rad_etdi
           from leads where (branch_id = any(%s) or branch_id is null)
             and created_at >= now() - make_interval(days => %s::int) group by 1 order by 2 desc""", bids, days)
    campaigns = await db.q(
        """select c.name, c.platform,
                  coalesce((select sum(ms.amount) from marketing_spend ms where ms.campaign_id = c.id
                            and ms.spend_date >= current_date - %s::int), 0) as sarf,
                  count(l.id) as lidlar,
                  count(l.id) filter (where l.status = 'enrolled') as oquvchi_boldi
           from campaigns c
           left join leads l on l.campaign_id = c.id and l.created_at >= now() - make_interval(days => %s::int)
           where (c.branch_id = any(%s) or c.branch_id is null)
           group by c.id order by 3 desc""", days, days, bids)
    for c in campaigns:
        c["sarf"] = int(c["sarf"])
        c["bir_lid_narxi"] = int(c["sarf"] / c["lidlar"]) if c["lidlar"] else None
        c["bir_oquvchi_narxi"] = int(c["sarf"] / c["oquvchi_boldi"]) if c["oquvchi_boldi"] else None
    return {"kunlar": days, "manbalar_boyicha": by_source, "kampaniyalar": campaigns}


async def teacher_stats(bids, teacher_staff_id=None):
    rows = await db.q(
        """select st.id as staff_id, st.full_name as teacher, g.id as group_id, g.name as group_name,
                  (select count(*) filter (where a.status = 'present')::float / nullif(count(*), 0)
                   from attendance a join enrollments e on e.id = a.enrollment_id
                   where e.group_id = g.id and a.lesson_date >= current_date - 30) as davomat_30kun,
                  (select count(*) from enrollments e where e.group_id = g.id and e.status = 'active') as faol_oquvchi,
                  (select count(*) from enrollments e where e.group_id = g.id and e.status = 'left') as ketgan,
                  (select count(*) from exams x where x.group_id = g.id and x.exam_date >= current_date - 90) as imtihon_90,
                  (select avg(x.score) from exams x where x.group_id = g.id and x.exam_date >= current_date - 90) as ball_90,
                  (select avg(x.score) from exams x where x.group_id = g.id
                     and x.exam_date < current_date - 90 and x.exam_date >= current_date - 180) as ball_oldingi_90,
                  (select count(*) filter (where x.score >= x.target_score) from exams x
                     where x.group_id = g.id and x.exam_date >= current_date - 90 and x.target_score is not null) as maqsadga_yetdi,
                  (select count(*) from exams x
                     where x.group_id = g.id and x.exam_date >= current_date - 90 and x.target_score is not null) as maqsadli_imtihon
           from groups g
           join teachers t on t.id = g.teacher_id
           join staff st on st.id = t.staff_id
           where g.is_active and g.branch_id = any(%s)
             and (%s::uuid is null or st.id = %s::uuid)
           order by st.full_name, g.name""", bids, teacher_staff_id, teacher_staff_id)
    for r in rows:
        for k in ("davomat_30kun", "ball_90", "ball_oldingi_90"):
            if r[k] is not None:
                r[k] = round(float(r[k]), 2)
    return rows


async def unanswered_leads(hours=2):
    return await db.q(
        """select l.id, l.full_name, l.phone, l.source, l.branch_id, l.created_at
           from leads l
           where l.status = 'new' and l.alerted_at is null
             and l.created_at < now() - make_interval(hours => %s::int)
             and not exists (select 1 from lead_activities a where a.lead_id = l.id)""", hours)


def week_range(on=None):
    on = on or today()
    return on - timedelta(days=6), on
