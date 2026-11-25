"""Avtomatik ishlar: ertalabki hisobot, to'lov tsiklini yangilash, lid ogohlantirishi, haftalik tahlil."""
import logging
from datetime import timedelta

import json

from . import brain, config, db, tools_media, tools_school
from . import queries as Q
from .core import ROLE_UZ, ToolError, fmt_money, now, roll_forward, rt, send_tg, today

log = logging.getLogger("wstizim.reports")


async def build_report(bids, include_finance=False):
    t = today()
    y = t - timedelta(days=1)
    lines = []

    todays = await db.q(
        """select g.name, g.start_time, b.name as branch from groups g join branches b on b.id = g.branch_id
           where g.is_active and b.is_active and g.branch_id = any(%s) and %s::int = any(g.days)
           order by g.start_time""", bids, t.isoweekday())
    lines.append(f"Bugungi darslar: {len(todays)} ta guruh")
    for g in todays[:12]:
        lines.append(f"  {str(g['start_time'])[:5]}  {g['name']} ({g['branch']})")

    att = await db.one(
        """select count(*) filter (where a.status = 'present') as keldi, count(*) filter (where a.status = 'absent') as kelmadi
           from attendance a join enrollments e on e.id = a.enrollment_id join groups g on g.id = e.group_id
           where g.branch_id = any(%s) and a.lesson_date = %s""", bids, y)
    lines.append(f"\nKecha davomat: {att['keldi']} keldi, {att['kelmadi']} kelmadi")
    unmarked = await Q.unmarked_groups(bids, y)
    if unmarked:
        lines.append("Davomat kiritilmagan guruhlar (kecha): " + ", ".join(f"{u['name']}" for u in unmarked))

    streaks = await Q.absence_streaks(bids)
    if streaks:
        lines.append(f"\n3 darsdan beri kelmayotganlar ({len(streaks)}):")
        for s in streaks[:8]:
            lines.append(f"  {s['full_name']} ({s['group_name']})")

    pay = await Q.payment_overview(bids)
    overdue = [p for p in pay if p["state"] == "overdue"]
    window = [p for p in pay if p["state"] == "window"]
    debt_sum = sum(int(p["monthly_fee"]) for p in overdue if p["monthly_fee"])
    lines.append(f"\nQarzdorlar: {len(overdue)} ta" + (f", taxminan {fmt_money(debt_sum)}" if debt_sum else ""))
    for p in overdue[:6]:
        lines.append(f"  {p['full_name']} ({p['group_name']})")
    lines.append(f"To'lov oynasi ochiq (3-6 dars): {len(window)} ta")

    leads_new = await db.one("select count(*) as n from leads where (branch_id = any(%s) or branch_id is null) "
                             "and created_at::date = %s", bids, y)
    stale = await db.one("select count(*) as n from leads where (branch_id = any(%s) or branch_id is null) "
                         "and status = 'new' and created_at < now() - interval '2 hours' "
                         "and not exists (select 1 from lead_activities a where a.lead_id = leads.id)", bids)
    lines.append(f"\nKecha yangi lidlar: {leads_new['n']}; javobsiz qolganlar: {stale['n']}")

    if include_finance:
        fin = await Q.finance_summary(bids, t.replace(day=1), t)
        lines.append(f"\nShu oy: tushum {fmt_money(fin['tushum_jami'])}, xarajat {fmt_money(fin['xarajat_jami'])}, "
                     f"reklama {fmt_money(fin['reklama_xarajati'])}")
    return "\n".join(lines)


async def morning_job(context):
    staff = await db.q("select * from staff where is_active and telegram_id is not null "
                       "and role in ('owner','manager','admin')")
    for s in staff:
        try:
            ctx = await Q.make_ctx(s, msg_time=now(), chat_id=s["telegram_id"])
            bids = [b["id"] for b in await Q.branches_for(ctx, active_only=True)]
            text = await build_report(bids, include_finance=ctx.level("view_finance") == "allow")
            head = f"Xayrli tong, {s['full_name']}! Bugungi hisobot ({today():%d.%m.%Y}):\n\n"
            body = head + text
            if s["role"] == "owner":
                tips = await brain.quick(
                    "Quyida o'quv markazlarning ertalabki hisoboti. Rahbar uchun bugunga 3 ta aniq, qisqa "
                    "tavsiya yozing (nima qilish, kim bilan, nima uchun). Oddiy matn, markdownsiz. "
                    "Raqamlarni faqat hisobotdan oling.\n\n" + text,
                    system="Siz o'quv markazlar egasining biznes maslahatchisisiz. O'zbek lotin yozuvida yozing.",
                    fast=False)
                body += "\n\nBugun uchun tavsiyalarim:\n" + tips
            await send_tg(s["telegram_id"], body)
            await brain.save_turn(s["id"], "(avtomatik) Ertalabki hisobotni yubor", body)
        except ToolError:
            continue
        except Exception:
            log.exception("ertalabki hisobot xatosi: %s", s.get("full_name"))


async def roll_cycles_job(context):
    rows = await db.q("select id, cycle_start, cycle_paid, unpaid_cycles from enrollments "
                      "where status = 'active' and cycle_start is not null")
    t = today()
    changed = 0
    for r in rows:
        ncs, npd, nun = roll_forward(r["cycle_start"], r["cycle_paid"], r["unpaid_cycles"], t)
        if (ncs, npd, nun) != (r["cycle_start"], r["cycle_paid"], r["unpaid_cycles"]):
            await db.ex("update enrollments set cycle_start=%s, cycle_paid=%s, unpaid_cycles=%s where id=%s",
                        ncs, npd, nun, r["id"])
            changed += 1
    log.info("to'lov tsikllari yangilandi: %s ta", changed)


async def lead_alert_job(context):
    if not 9 <= now().hour < 21:
        return
    leads = await Q.unanswered_leads(2)
    for l in leads:
        try:
            targets = await db.q(
                """select s.telegram_id from staff s join staff_branch_access a on a.staff_id = s.id
                   where s.is_active and s.telegram_id is not null and s.role in ('admin','manager')
                     and a.branch_id = %s""", l["branch_id"])
            if not targets:
                targets = await db.q("select telegram_id from staff where role='owner' and telegram_id is not null")
            msg = (f"Yangi lid 2 soatdan beri javobsiz: {l['full_name'] or 'ismsiz'}, {l['phone'] or 'telefonsiz'} "
                   f"(manba: {l['source'] or 'noma`lum'}). Tezroq aloqaga chiqing.")
            for t in targets:
                await send_tg(t["telegram_id"], msg)
            await db.ex("update leads set alerted_at = now() where id = %s", l["id"])
        except Exception:
            log.exception("lid ogohlantirishi xatosi")


async def weekly_data(bids):
    """Haftalik hisobot uchun raqamlar (o'tgan 7 kun va undan oldingi 7 kun bilan solishtirish)."""
    t = today()
    w0, p0 = t - timedelta(days=7), t - timedelta(days=14)
    d = {"davr": f"{w0:%d.%m} - {t:%d.%m.%Y}"}
    lead = await db.one(
        """select count(*) filter (where created_at::date > %s) as yangi,
                  count(*) filter (where created_at::date > %s and status in ('trial','enrolled')) as sinov_yoki_yozildi,
                  count(*) filter (where created_at::date > %s and status = 'enrolled') as yozildi,
                  count(*) filter (where created_at::date between %s and %s) as oldingi_hafta_yangi
           from leads where branch_id = any(%s) or branch_id is null""", w0, w0, w0, p0, w0, bids)
    lead["konversiya_foiz"] = round(100 * lead["yozildi"] / lead["yangi"], 1) if lead["yangi"] else None
    d["murojaatlar"] = lead
    d["murojaat_manbalari"] = await db.q(
        """select coalesce(source,'noma''lum') as manba, count(*) as soni, count(*) filter (where status='enrolled') as yozildi
           from leads where (branch_id = any(%s) or branch_id is null) and created_at::date > %s group by 1 order by 2 desc""",
        bids, w0)
    fin_w = await Q.finance_summary(bids, w0 + timedelta(days=1), t)
    fin_p = await Q.finance_summary(bids, p0 + timedelta(days=1), w0)
    pay = await Q.payment_overview(bids)
    over = [p for p in pay if p["state"] == "overdue"]
    d["moliya"] = {"tushum": fin_w["tushum_jami"], "oldingi_hafta_tushum": fin_p["tushum_jami"],
                   "xarajat": fin_w["xarajat_jami"], "reklama": fin_w["reklama_xarajati"],
                   "qarzdorlar_soni": len(over), "qarz_summa": sum(int(p["monthly_fee"] or 0) for p in over)}
    seats = await db.q(
        """select g.name, g.capacity, (select count(*) from enrollments e where e.group_id=g.id and e.status='active') as n
           from groups g join branches b on b.id = g.branch_id where g.is_active and b.is_active and g.branch_id = any(%s)""", bids)
    d["bosh_joylar"] = {"jami": sum(max(x["capacity"] - x["n"], 0) for x in seats),
                        "eng_bosh_guruhlar": sorted([{"guruh": x["name"], "bosh": x["capacity"] - x["n"]} for x in seats
                                                     if x["capacity"] - x["n"] >= 3], key=lambda x: -x["bosh"])[:5]}
    att = await db.one(
        """select avg((a.status='present')::int) filter (where a.lesson_date > %s) as shu_hafta,
                  avg((a.status='present')::int) filter (where a.lesson_date between %s and %s) as oldingi
           from attendance a join enrollments e on e.id = a.enrollment_id join groups g on g.id = e.group_id
           where g.branch_id = any(%s) and a.lesson_date > %s""", w0, p0, w0, bids, p0)
    left = await db.q("select left_reason as sabab, count(*) as soni from students where branch_id = any(%s) "
                      "and left_on > %s group by 1", bids, w0)
    d["davomat_va_ketish"] = {"davomat_shu_hafta": round(float(att["shu_hafta"]) * 100, 1) if att["shu_hafta"] is not None else None,
                              "davomat_oldingi": round(float(att["oldingi"]) * 100, 1) if att["oldingi"] is not None else None,
                              "ketganlar": left, "xavf_ostida": len(await tools_school.compute_risks(bids))}
    d["marketing"] = {
        "postlar": await db.q(
            """select left(p.body, 80) as post, p.targets, (select count(*) from leads l where l.post_id = p.id) as murojaat
               from content_posts p where p.published_at::date > %s order by 3 desc limit 8""", w0),
        "reklama": (await Q.lead_stats(bids, 7))["kampaniyalar"]}
    d["oqituvchilar"] = await Q.teacher_stats(bids)
    for r in d["oqituvchilar"]:
        for k in ("staff_id", "group_id"):
            r.pop(k, None)
    sess = await db.q(
        """select st.full_name as oqituvchi, count(*) filter (where s.started_at is not null) as belgilangan,
                  round(avg(greatest(extract(epoch from (s.started_at - (s.lesson_date + s.planned_start)::timestamp
                        at time zone %s))/60, 0))::numeric, 1) as ortacha_kechikish
           from lesson_sessions s join staff st on st.id = s.teacher_id where s.lesson_date > %s group by 1""",
        str(config.TZ), w0)
    d["dars_vaqtida"] = sess
    return d


WEEKLY_PROMPT = """Quyida o'quv markazlarning o'tgan hafta raqamlari (JSON). Rahbar uchun Telegramda o'qiladigan QISQA
haftalik hisobot yozing (oddiy matn, markdownsiz, har bo'lim 2-4 qator, raqamlar faqat JSON dan):
1) Murojaatlar: yangi, sinov darsi/yozilgan, konversiya, oldingi hafta bilan farq, eng yaxshi manba.
2) Moliya: tushum (oldingi hafta bilan), qarzdorlik, guruhlardagi bo'sh joylar (qaysi guruhlar).
3) Davomat va ketish: davomat foizi o'zgarishi, ketganlar va sabablari, xavf ostidagilar soni.
4) Marketing: qaysi post va reklama murojaat keltirgani, bir murojaat narxi; samarasiz reklama bo'lsa ayting.
5) O'qituvchilar: e'tibor kerak bo'lganlar (davomat, natija, kechikish) — faktlar, hukmsiz.
6) "Bu hafta e'tibor berishingiz kerak bo'lgan 3 ta masala": aniq, amaliy, kim nima qiladi.
Ma'lumot bo'lmasa "ma'lumot kiritilmagan" deng, to'qimang."""


async def weekly_job(context):
    if today().isoweekday() != 1:      # faqat dushanba
        return
    owner = await db.one("select * from staff where role='owner' and telegram_id is not null limit 1")
    if not owner:
        return
    try:
        bids = [b["id"] for b in await db.q("select id from branches")]
        data = await weekly_data(bids)
        text = await brain.quick(WEEKLY_PROMPT + "\n\n" + json.dumps(data, ensure_ascii=False, default=str),
                                 system="Siz o'quv markazlar egasining tajribali biznes tahlilchisisiz. O'zbek lotin yozuvida.",
                                 fast=False, max_tokens=6000)
        body = f"📊 Haftalik hisobot ({data['davr']})\n\n{text}\n\nQaysi masaladan boshlaymiz?"
        await send_tg(owner["telegram_id"], body)
        await brain.save_turn(owner["id"], "(avtomatik) Haftalik hisobotni yubor", body)
    except Exception:
        log.exception("haftalik tahlil xatosi")


async def publish_due_job(context):
    """Rejalashtirilgan postlarni vaqti kelganda chiqaradi."""
    from . import social
    await social.publish_due()


async def task_reminder_job(context):
    """Muddati o'tgan, bajarilmagan vazifalar: xodimga eslatma, berganiga xabar (bir marta)."""
    rows = await db.q(
        """update tasks t set reminded_at = now()
           from staff a where a.id = t.assigned_to and t.status in ('sent','seen') and t.due_at is not null
             and t.due_at < now() and t.reminded_at is null
           returning t.id, t.text, t.created_by, a.full_name, a.telegram_id""")
    for r in rows:
        try:
            if r["telegram_id"]:
                from .tools import task_keyboard
                await rt.bot.send_message(chat_id=r["telegram_id"], text=f"⏰ Vazifa muddati o'tdi:\n{r['text'][:800]}",
                                          reply_markup=task_keyboard(r["id"]))
            boss = await db.one("select telegram_id from staff where id=%s", r["created_by"])
            if boss and boss["telegram_id"]:
                await send_tg(boss["telegram_id"], f"⏰ {r['full_name']} vazifani muddatida bajarmadi:\n{r['text'][:500]}")
        except Exception:
            log.exception("vazifa eslatmasi xatosi")


async def lesson_reminder_job(context):
    await tools_school.lesson_reminders()


async def retention_job(context):
    try:
        await tools_school.retention_job()
    except Exception:
        log.exception("ushlab qolish signali xatosi")


async def comments_job(context):
    if 8 <= now().hour < 23:
        try:
            await tools_media.poll_instagram_comments()
        except Exception:
            log.exception("Instagram izohlari xatosi")


async def ads_job(context):
    if config.META_AD_ACCOUNT_ID:
        try:
            await tools_media.sync_meta_ads_data(7)
        except Exception:
            log.exception("Meta Ads xatosi")


async def _agent_to_owner(agent, prompt, title, readonly=True):
    owner = await db.one("select * from staff where role='owner' and telegram_id is not null limit 1")
    if not owner or agent not in brain.AGENTS:
        return
    ctx = await Q.make_ctx(owner, msg_time=now(), chat_id=owner["telegram_id"], readonly=readonly)
    text = await brain.run_agent(ctx, agent, [{"role": "user", "content": prompt}], max_steps=10)
    body = f"{title}\n\n{text}"
    await send_tg(owner["telegram_id"], body)
    await brain.save_turn(owner["id"], f"(avtomatik) {title}", body)


async def competitors_job(context):
    if not await db.one("select 1 from competitors limit 1"):
        return
    try:
        await _agent_to_owner("competitors", "Raqobatchilarning o'tgan haftadagi faoliyati bo'yicha haftalik xulosa: narx, "
                              "aksiya, yangi kurslar, kontent. Oxirida biz uchun 2-3 ta amaliy taklif.",
                              "🔍 Raqobatchilar: haftalik xulosa")
    except Exception:
        log.exception("raqobatchilar xatosi")


async def content_plan_job(context):
    """Har oyning 25-sanasida: keyingi oy kontent rejasi (o'tgan oy natijalari asosida)."""
    if today().day != 25:
        return
    try:
        await _agent_to_owner("content_strategist",
                              "Keyingi oy uchun kontent reja tuz va plan_content bilan saqla (haftasiga 4-5 post, toifalar "
                              "aralash). Avval content_performance bilan qaysi postlar murojaat keltirganini tahlil qil. "
                              "Oxirida qisqa xulosa: nima o'zgardi va nega.", "🗓 Keyingi oy kontent rejasi tayyor",
                              readonly=False)
    except Exception:
        log.exception("kontent reja xatosi")


async def monthly_survey_job(context):
    if today().day != 28 or (await tools_media.get_setting("auto_monthly_survey", "yo'q")).lower() not in ("ha", "yes", "true"):
        return
    owner = await db.one("select * from staff where role='owner' limit 1")
    ctx = await Q.make_ctx(owner, msg_time=now(), confirmed=True)
    from .tools import dispatch
    await dispatch(ctx, "send_surveys", {"kind": "oylik", "summary": "Oylik so'rovnoma (avtomatik)"})


async def hr_review_job(context):
    """Har oyning 1-sanasi: HR jamoa yuklamasini ko'rib, yangi AI agent kerakmi — taklif (o'rnatmaydi)."""
    if today().day != 1:
        return
    try:
        await _agent_to_owner("hr", "Oylik ko'rib chiqish: o'tgan oydagi vazifalar (list_tasks), xodimlar va AI jamoa "
                              "(list_agents, list_agent_catalog). Qaysi ishlar qo'lda va takror bajarilmoqda? Yangi AI agent "
                              "kerak bo'lsa 1-2 ta taklif ber (nega, qaysi katalog agenti yoki yangi). Hech narsa o'rnatma: "
                              "rahbar 'ha' desa keyin o'rnatiladi.", "🧑‍💼 HR: oylik ko'rib chiqish")
    except Exception:
        log.exception("HR ko'rib chiqish xatosi")


async def ig_token_job(context):
    """Har dushanba: Instagram Login tokenini uzaytirish (60 kunlik muddat tugamasligi uchun)."""
    try:
        from . import social
        await social.refresh_ig_token()
    except Exception:
        log.exception("Instagram token yangilash xatosi")
