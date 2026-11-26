"""Media va marketing jamoasi vositalari: kontent reja, ohang, dizayn, video, izohlar, reklama, raqobatchilar."""
import html
import json
import logging
import re
from datetime import timedelta
from html.parser import HTMLParser

import httpx

from . import config, db, design, social, video
from .core import ROLE_UZ, ToolError, now, parse_date, rt, send_tg, today
from .tools import B, LS, N, S, tool

log = logging.getLogger("wstizim.media")

SETTING_KEYS = {
    "brand_voice": "Markaz ohangi (post va javoblar uslubi)",
    "review_url": "Google Maps sharh havolasi (5 baho berganlarga yuboriladi)",
    "referral_bonus_percent": "Do'stini olib kelganga bonus foizi (oylik to'lovdan)",
    "meta_usd_rate": "Meta reklama hisobi dollarda bo'lsa: 1$ = necha so'm",
    "group_capacity_default": "Yangi guruh sig'imi (standart)",
    "auto_monthly_survey": "Har oy oxirida ota-onalarga so'rovnoma avtomatik yuborilsinmi (ha/yo'q)",
}
OWNER_ONLY_KEYS = {"review_url", "referral_bonus_percent", "meta_usd_rate", "auto_monthly_survey"}


async def get_setting(key, default=None):
    row = await db.one("select value from settings where key=%s", key)
    return row["value"] if row else default


# ---------- sozlamalar va ohang ----------
@tool("get_settings", "Markaz sozlamalari: ohang (brand_voice), sharh havolasi, referral bonusi va boshqalar.")
async def get_settings(ctx):
    rows = {r["key"]: r["value"] for r in await db.q("select key, value from settings")}
    return {"sozlamalar": [{"kalit": k, "nima": d, "qiymat": rows.get(k)} for k, d in SETTING_KEYS.items()]}


@tool("set_setting", "Sozlamani o'zgartiradi. Masalan markaz ohangini bir marta o'rgatish: key=brand_voice, "
      "value='Samimiy, ...'. Kopirayter va boshqa agentlar keyin shu uslubda yozadi.",
      {"key": S(", ".join(SETTING_KEYS)), "value": S("Yangi qiymat")}, ["key", "value"],
      perm="manage_content", write=True, confirm=True)
async def set_setting(ctx, key, value):
    if key not in SETTING_KEYS:
        raise ToolError("Kalit: " + ", ".join(SETTING_KEYS))
    if key in OWNER_ONLY_KEYS and ctx.role != "owner" and not ctx.bypass:
        raise ToolError("Bu sozlamani faqat rahbar o'zgartiradi.")
    await db.ex("insert into settings (key, value, updated_by, updated_at) values (%s,%s,%s,now()) "
                "on conflict (key) do update set value=excluded.value, updated_by=excluded.updated_by, updated_at=now()",
                key, str(value).strip()[:3000], ctx.staff_id)
    return {"ok": True, "kalit": key}


# ---------- kontent reja ----------
CATEGORIES = {"natija", "oqituvchi", "maslahat", "aksiya", "tadbir", "boshqa"}


@tool("plan_content", "Kontent rejaga bir yoki bir nechta post qo'shadi (oylik reja tuzish uchun).",
      {"items": {"type": "array", "description": "Reja bandlari",
                 "items": {"type": "object", "properties": {
                     "date": S("Sana 2026-12-03"), "category": S("natija | oqituvchi | maslahat | aksiya | tadbir | boshqa"),
                     "topic": S("Mavzu va qisqa g'oya"), "channels": LS("telegram, instagram, youtube, tiktok")},
                     "required": ["date", "topic"]}}},
      ["items"], perm="manage_content", write=True)
async def plan_content(ctx, items):
    n = 0
    for it in items[:62]:
        cat = it.get("category") or "boshqa"
        await db.ex("insert into content_plan (plan_date, category, topic, channels, created_by) values (%s,%s,%s,%s,%s)",
                    parse_date(it["date"]), cat if cat in CATEGORIES else "boshqa", it["topic"].strip()[:500],
                    it.get("channels") or ["telegram", "instagram"], ctx.staff_id)
        n += 1
    return {"ok": True, "qoshildi": n}


@tool("list_content_plan", "Kontent reja (oy bo'yicha): sana, mavzu, toifa, holat.",
      {"month": S("YYYY-MM (standart: shu oy)")}, perm="manage_content")
async def list_content_plan(ctx, month=None):
    y, m = (month or today().strftime("%Y-%m")).split("-")
    first = today().replace(year=int(y), month=int(m), day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    rows = await db.q("select id, plan_date, category, topic, channels, status, post_id from content_plan "
                      "where plan_date >= %s and plan_date < %s order by plan_date", first, nxt)
    return {"oy": f"{y}-{m}", "reja": rows}


@tool("update_plan_item", "Kontent reja bandini o'zgartiradi (sana, mavzu, holat: rejada/tayyor/chiqdi/bekor).",
      {"item": S("Band id"), "status": S("rejada | tayyor | chiqdi | bekor"), "date": S("Yangi sana"),
       "topic": S("Yangi mavzu")}, ["item"], perm="manage_content", write=True)
async def update_plan_item(ctx, item, status=None, date=None, topic=None):
    row = await db.one("select id from content_plan where id::text=%s", str(item))
    if not row:
        raise ToolError("Reja bandi topilmadi.")
    if status and status not in ("rejada", "tayyor", "chiqdi", "bekor"):
        raise ToolError("Holat: rejada, tayyor, chiqdi yoki bekor.")
    await db.ex("update content_plan set status=coalesce(%s,status), plan_date=coalesce(%s,plan_date), "
                "topic=coalesce(%s,topic) where id=%s", status, parse_date(date) if date else None, topic, row["id"])
    return {"ok": True}


@tool("content_performance", "Qaysi postlar ko'p murojaat (lid) keltirgani: postdagi 'yozilish' havolasi orqali "
      "kelgan lidlar, toifa bo'yicha natija. Rejani yangilash uchun asos.",
      {"days": N("Necha kunlik (standart 60)")}, perm="view_marketing")
async def content_performance(ctx, days=60):
    rows = await db.q(
        """select p.id, p.published_at::date as sana, left(p.body, 120) as matn, p.media_kind, p.targets,
                  coalesce(cp.category, 'rejasiz') as toifa,
                  (select count(*) from leads l where l.post_id = p.id) as lidlar,
                  (select count(*) from leads l where l.post_id = p.id and l.status = 'enrolled') as oquvchi_boldi
           from content_posts p left join content_plan cp on cp.id = p.plan_id
           where p.status in ('published','partial') and p.published_at >= now() - make_interval(days => %s::int)
           order by lidlar desc, p.published_at desc limit 40""", int(days))
    cats = {}
    for r in rows:
        c = cats.setdefault(r["toifa"], {"postlar": 0, "lidlar": 0, "oquvchi": 0})
        c["postlar"] += 1
        c["lidlar"] += r["lidlar"]
        c["oquvchi"] += r["oquvchi_boldi"]
    return {"postlar": rows, "toifalar_boyicha": cats,
            "eslatma": "Lidlar faqat Telegram postidagi 'yozilish' havolasi yoki kampaniya orqali bog'lanadi. "
                       "Instagramdan kelganlar manba bo'yicha lead_stats da ko'rinadi."}


# ---------- dizayn ----------
async def _deliver_media(ctx, data, kind, filename, caption):
    """Faylni yuklaydi (Instagram uchun ochiq havola) va foydalanuvchiga yuboradi. -> (url, file_id)"""
    url = None
    if social.storage_enabled():
        ext = filename.rsplit(".", 1)[-1]
        url = await social.upload_public(data, ext, "video/mp4" if kind == "video" else "image/png")
    file_id = None
    if ctx.chat_id and rt.bot:
        try:
            if kind == "video":
                m = await rt.bot.send_video(ctx.chat_id, video=data, caption=caption[:1000], filename=filename,
                                            supports_streaming=True, read_timeout=180, write_timeout=180)
                file_id = m.video.file_id if m.video else None
            else:
                m = await rt.bot.send_photo(ctx.chat_id, photo=data, caption=caption[:1000])
                file_id = m.photo[-1].file_id if m.photo else None
        except Exception:
            log.exception("media yuborilmadi")
    return url, file_id


@tool("make_design", "Markaz uslubida dizayn kartochka tayyorlaydi (post 1080x1080, story 1080x1920, afisha 1080x1350). "
      "Shablonlar: " + "; ".join(f"{k} = {v[0]}" for k, v in design.TEMPLATES.items()) +
      ". Natija chatga yuboriladi; publish_post ga media_url yoki file_id sifatida berish mumkin. "
      "Foydalanuvchi rasm yuborgan bo'lsa (masalan o'quvchi surati), 'natija' shablonida aylana ichida chiqadi.",
      {"template": S("natija | aksiya | yangi_guruh | elon"), "format": S("post | story | afisha"),
       "title": S("Sarlavha"), "score": S("Katta raqam/ball (natija, aksiya)"), "subtitle": S("Kichik sarlavha"),
       "details": S("Qo'shimcha matn (yangi_guruh: har qator alohida)"), "badge": S("Yorliq matni (ixtiyoriy)")},
      ["template", "title"], perm="manage_content", write=True)
async def make_design(ctx, template, title, format="post", score=None, subtitle=None, details=None, badge=None):
    photo = None
    att = next((a for a in ctx.attachments if a.get("kind") == "photo"), None)
    if att and template == "natija":
        try:
            if att.get("url"):
                async with httpx.AsyncClient(timeout=60) as c:
                    photo = (await c.get(att["url"])).content
            elif att.get("file_id") and rt.bot:
                photo = bytes(await (await rt.bot.get_file(att["file_id"])).download_as_bytearray())
        except Exception:
            log.warning("foto olinmadi")
    try:
        data = design.render(template, format, {"title": title, "score": score, "subtitle": subtitle,
                                                 "details": details, "badge": badge}, photo)
    except ValueError as e:
        raise ToolError(str(e))
    url, file_id = await _deliver_media(ctx, data, "photo", f"{template}.png", f"{template}: {title}")
    from . import genai
    await genai.remember(ctx.staff_id, "photo", url, file_id, title, "design")
    return {"ok": True, "media_url": url, "file_id": file_id, "media_kind": "photo",
            "xabar": "Dizayn chatga yuborildi." if file_id else "Dizayn tayyor (panelda ko'rinadi)."}


# ---------- video ----------
@tool("edit_video", "Yuborilgan videoni tahrirlaydi: kerakli qismini qirqadi, vertikal 9:16 (Reels/Shorts/TikTok) "
      "formatga moslaydi, sarlavha va avtomatik o'zbekcha subtitr qo'shadi. Natija chatga yuboriladi.",
      {"start": S("Boshlanish, masalan '0:05' (ixtiyoriy)"), "end": S("Tugash, masalan '0:40' (ixtiyoriy)"),
       "vertical": B("9:16 formatga (standart true)"), "subtitles": B("Avtomatik subtitr (standart true)"),
       "title": S("Video tepasidagi sarlavha (ixtiyoriy, qisqa)"), "video_url": S("Video havolasi (ixtiyoriy)")},
      [], perm="manage_content", write=True)
async def edit_video(ctx, start=None, end=None, vertical=True, subtitles=True, title=None, video_url=None):
    src = None
    att = next((a for a in ctx.attachments if a.get("kind") == "video"), None)
    if not att and not video_url:
        from . import genai
        last = await genai.last_media(ctx.staff_id)
        if last and last["kind"] == "video":
            att = {"kind": "video", "url": last["url"], "file_id": last["file_id"]}
    try:
        if video_url or (att and att.get("url")):
            async with httpx.AsyncClient(timeout=180, follow_redirects=True) as c:
                src = (await c.get(video_url or att["url"])).content
        elif att and att.get("file_id") and rt.bot:
            src = bytes(await (await rt.bot.get_file(att["file_id"])).download_as_bytearray())
    except Exception as e:
        raise ToolError(f"Video olinmadi: {e}")
    if not src:
        raise ToolError("Avval videoni yuboring (botga 20 MB gacha, panelga 50 MB gacha), keyin tahrirlashni so'rang.")
    from . import voice
    if subtitles and not voice.stt_enabled():
        subtitles = False
    out, info = await video.edit(src, start, end, vertical, subtitles, title)
    url, file_id = await _deliver_media(ctx, out, "video", "reels.mp4", title or "Tayyor video")
    from . import genai
    await genai.remember(ctx.staff_id, "video", url, file_id, title, "edit_video")
    return {"ok": True, "media_url": url, "file_id": file_id, "media_kind": "video", **info,
            "subtitr_holati": info.get("subtitr") or ("qo'shildi" if subtitles else "ovoz kaliti yo'q, subtitrsiz")}


# ---------- izohlar (Instagram va Telegram muhokama guruhi) ----------
async def classify_comment(text):
    from . import brain
    voice_ = await get_setting("brand_voice", "")
    raw = await brain.quick(
        "Quyidagi izohni tahlil qiling va FAQAT JSON qaytaring: "
        '{"category": "savol|yozilish|ijobiy|salbiy|spam", "reply": "qisqa javob (o\'zbek yoki izoh tilida), '
        'spam uchun bo\'sh"}.\n'
        "Narx, jadval kabi aniq ma'lumotni bilmasangiz, 'Batafsil ma'lumot uchun direktga yozing yoki qo'ng'iroq "
        "qiling' deng.\n\nIzoh: " + text[:1000],
        system="Siz o'quv markazining SMM menejerisiz. Ohang: " + voice_, fast=True, max_tokens=1500)
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        d = json.loads(m.group()) if m else {}
    except json.JSONDecodeError:
        d = {}
    cat = d.get("category") if d.get("category") in ("savol", "yozilish", "ijobiy", "salbiy", "spam") else "savol"
    return cat, (d.get("reply") or "").strip()[:900]


async def notify_comment(row):
    """Salbiy izoh -> rahbarga; savol/yozilish -> admin va managerlarga, tayyor javob va tugma bilan."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    platform = "Telegram" if row["id"].startswith("tg:") else "Instagram"
    head = {"salbiy": "⚠️ Salbiy izoh", "yozilish": "🔥 Yozilmoqchi", "savol": "❓ Savol"}.get(row["category"])
    if not head:
        return
    roles = ("owner",) if row["category"] == "salbiy" else ("owner", "manager", "admin")
    staff = await db.q("select telegram_id from staff where is_active and telegram_id is not null and role::text = any(%s)",
                       list(roles))
    text = (f"{head} ({platform}) @{row['username'] or '?'}:\n«{row['text'][:600]}»\n\n"
            + (f"Tayyor javob:\n{row['suggested_reply']}" if row["suggested_reply"] else ""))
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📨 Javobni yuborish", callback_data=f"cm:{row['id']}:send"),
                                InlineKeyboardButton("🙈 E'tiborsiz", callback_data=f"cm:{row['id']}:skip")]]) \
        if row["suggested_reply"] else None
    for s in staff:
        try:
            await rt.bot.send_message(s["telegram_id"], text, reply_markup=kb)
        except Exception:
            log.warning("izoh xabari yuborilmadi")


async def save_comment(cid, media_id, username, text, when=None):
    exists = await db.one("select 1 from ig_comments where id=%s", cid)
    if exists or not (text or "").strip():
        return None
    cat, reply = await classify_comment(text)
    row = await db.one("insert into ig_comments (id, media_id, username, text, commented_at, category, suggested_reply) "
                       "values (%s,%s,%s,%s,%s,%s,%s) on conflict do nothing returning *",
                       cid, media_id, username, text, when, cat, reply or None)
    if row:
        await notify_comment(row)
    return row


async def poll_instagram_comments():
    """Oxirgi 10 ta Instagram post izohlarini tekshiradi (har 15 daqiqada)."""
    if not social.ig_configured():
        return 0
    api, ig_user, tok = await social.ig_auth()
    n = 0
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{api}/{ig_user}/media",
                        params={"fields": "id,timestamp", "limit": 10, "access_token": tok})
        if r.status_code >= 300:
            log.warning("IG media: %s", r.text[:200])
            return 0
        for m in r.json().get("data", []):
            rc = await c.get(f"{api}/{m['id']}/comments",
                             params={"fields": "id,text,username,timestamp", "limit": 50, "access_token": tok})
            for cm in rc.json().get("data", []) if rc.status_code < 300 else []:
                if await save_comment(cm["id"], m["id"], cm.get("username"), cm.get("text"), cm.get("timestamp")):
                    n += 1
    return n


async def send_comment_reply(cid, text):
    if cid.startswith("tg:"):
        _, chat, msg = cid.split(":")
        await rt.bot.send_message(int(chat), text, reply_to_message_id=int(msg))
    else:
        api, _, tok = await social.ig_auth()
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{api}/{cid}/replies", data={"message": text, "access_token": tok})
        if r.status_code >= 300:
            raise ToolError(f"Instagram javobi yuborilmadi: {r.text[:200]}")
    await db.ex("update ig_comments set status='javob_berildi', suggested_reply=%s where id=%s", text, cid)


@tool("list_comments", "Instagram va Telegram kanal izohlari: savol, yozilmoqchi, salbiy; tayyor javob bilan.",
      {"status": S("yangi | javob_berildi | etiborsiz (standart: yangi)")}, perm="manage_comments")
async def list_comments(ctx, status="yangi"):
    rows = await db.q("select id, username, text, category, suggested_reply, status, created_at from ig_comments "
                      "where status=%s order by created_at desc limit 40", status)
    return {"izohlar": rows}


@tool("reply_comment", "Izohga javob yozadi (Instagram yoki Telegram muhokama guruhida).",
      {"comment": S("Izoh id"), "text": S("Javob matni")}, ["comment", "text"], perm="manage_comments",
      write=True, confirm=True)
async def reply_comment(ctx, comment, text):
    row = await db.one("select id from ig_comments where id=%s", comment)
    if not row:
        raise ToolError("Izoh topilmadi.")
    await send_comment_reply(row["id"], text)
    return {"ok": True}


# ---------- reklama (Meta Ads) ----------
async def sync_meta_ads_data(days=7):
    ig_tok = config.IG_ACCESS_TOKEN if not (config.IG_ACCESS_TOKEN or "").startswith("IG") else None
    acc, tok = config.META_AD_ACCOUNT_ID, config.META_ACCESS_TOKEN or ig_tok
    if not (acc and tok):
        raise ToolError("Meta Ads ulanmagan (.env: META_AD_ACCOUNT_ID va META_ACCESS_TOKEN).")
    acc = acc if acc.startswith("act_") else f"act_{acc}"
    rate = float(await get_setting("meta_usd_rate", "1") or 1) if config.META_CURRENCY.upper() != "UZS" else 1.0
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.get(f"{social.GRAPH}/{acc}/insights",
                        params={"level": "campaign", "fields": "campaign_id,campaign_name,spend,actions",
                                "time_increment": 1, "date_preset": f"last_{int(days)}d" if days in (7, 14, 30) else "last_7d",
                                "limit": 500, "access_token": tok})
    if r.status_code >= 300:
        raise ToolError(f"Meta Ads xatosi: {r.text[:300]}")
    rows = r.json().get("data", [])
    n = 0
    for x in rows:
        camp = await db.one(
            "insert into campaigns (name, platform, external_id, start_date) values (%s,'meta',%s,%s) "
            "on conflict (external_id) do update set name=excluded.name returning id",
            x["campaign_name"], x["campaign_id"], parse_date(x["date_start"]))
        await db.ex("insert into marketing_spend (campaign_id, spend_date, amount) values (%s,%s,%s) "
                    "on conflict (campaign_id, spend_date) do update set amount=excluded.amount",
                    camp["id"], parse_date(x["date_start"]), int(float(x.get("spend") or 0) * rate))
        n += 1
    return n


@tool("sync_meta_ads", "Meta (Instagram/Facebook) reklama kampaniyalari sarfini avtomatik tortib oladi (oxirgi 7/14/30 kun).",
      {"days": N("7, 14 yoki 30")}, perm="manage_ads", write=True)
async def sync_meta_ads(ctx, days=7):
    n = await sync_meta_ads_data(int(days))
    return {"ok": True, "yozuvlar": n, "keyingi_qadam": "lead_stats bilan bir murojaat narxini ko'ring."}


# ---------- raqobatchilar ----------
class _TgParser(HTMLParser):
    """t.me/s/<kanal> sahifasidan postlarni ajratadi."""

    def __init__(self):
        super().__init__()
        self.posts, self._cur, self._depth, self._in_text = [], None, 0, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        if tag == "div" and "tgme_widget_message " in cls + " " and a.get("data-post"):
            self._cur = {"key": a["data-post"], "text": "", "time": None}
            self.posts.append(self._cur)
        if self._cur is not None and tag == "div" and "tgme_widget_message_text" in cls:
            self._in_text = 1
        elif self._in_text and tag == "div":
            self._in_text += 1
        if self._in_text and tag == "br":
            self._cur["text"] += "\n"
        if self._cur is not None and tag == "time" and a.get("datetime"):
            self._cur["time"] = a["datetime"]

    def handle_endtag(self, tag):
        if self._in_text and tag == "div":
            self._in_text -= 1

    def handle_data(self, data):
        if self._in_text and self._cur is not None:
            self._cur["text"] += data


async def fetch_channel(channel):
    name = channel.strip().lstrip("@").replace("https://t.me/", "").replace("t.me/", "").split("/")[0]
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (compatible; WS-Tizim)"}) as c:
        r = await c.get(f"https://t.me/s/{name}")
    if r.status_code >= 300:
        raise ToolError(f"@{name} kanali ochilmadi ({r.status_code}).")
    p = _TgParser()
    p.feed(r.text)
    return [{"key": x["key"], "text": html.unescape(x["text"]).strip(), "time": x["time"]} for x in p.posts]


@tool("add_competitor", "Raqobatchi markazni kuzatuvga qo'shadi (ochiq Telegram kanali bo'lsa postlari avtomatik "
      "yig'iladi; narx/aksiya haqidagi ma'lumotni notes ga yozish mumkin).",
      {"name": S("Markaz nomi"), "telegram_channel": S("@kanal (ixtiyoriy)"), "instagram": S("Instagram sahifa (ixtiyoriy)"),
       "notes": S("Narxlar, aksiyalar, kuzatuvlar")}, ["name"], perm="manage_marketing", write=True)
async def add_competitor(ctx, name, telegram_channel=None, instagram=None, notes=None):
    await db.ex("insert into competitors (name, telegram_channel, instagram, notes) values (%s,%s,%s,%s) "
                "on conflict (name) do update set telegram_channel=coalesce(excluded.telegram_channel, competitors.telegram_channel), "
                "instagram=coalesce(excluded.instagram, competitors.instagram), "
                "notes=concat_ws(E'\\n', competitors.notes, excluded.notes)", name.strip(), telegram_channel, instagram, notes)
    return {"ok": True}


async def collect_competitor_posts():
    n = 0
    for c in await db.q("select id, name, telegram_channel from competitors where telegram_channel is not null"):
        try:
            for p in await fetch_channel(c["telegram_channel"]):
                if not p["text"]:
                    continue
                r = await db.one("insert into competitor_posts (competitor_id, post_key, text, posted_at) "
                                 "values (%s,%s,%s,%s) on conflict (post_key) do nothing returning id",
                                 c["id"], p["key"], p["text"][:4000], p["time"])
                n += 1 if r else 0
        except Exception as e:
            log.warning("raqobatchi %s: %s", c["name"], e)
    return n


@tool("competitor_report", "Raqobatchilar: so'nggi kunlardagi Telegram postlari (narx, aksiya, yangiliklar) va "
      "qo'lda yozilgan kuzatuvlar. Haftalik xulosa uchun.",
      {"days": N("Necha kunlik (standart 7)")}, perm="view_marketing")
async def competitor_report(ctx, days=7):
    new = await collect_competitor_posts()
    comps = await db.q("select id, name, telegram_channel, instagram, notes from competitors order by name")
    for c in comps:
        c["postlar"] = await db.q(
            "select posted_at, left(text, 600) as text from competitor_posts where competitor_id=%s "
            "and coalesce(posted_at, fetched_at) >= now() - make_interval(days => %s::int) order by posted_at desc limit 15",
            c.pop("id"), int(days))
    return {"yangi_postlar": new, "raqobatchilar": comps,
            "eslatma": "Instagram ma'lumoti avtomatik yig'ilmaydi (Meta ruxsat bermaydi): notes ga qo'lda yoziladi."}



# ---------- AI rasm va video (OpenAI) ----------
@tool("generate_image", "AI bilan professional rasm chizadi (Higgsfield Seedream 2K; zaxira: OpenAI): post, story yoki afisha. "
      "brand=true bo'lsa ustiga markaz logosi va sarlavha qo'yiladi. Tavsifni (prompt) ingliz tilida, aniq va batafsil "
      "yozing: kim, nima, qayerda, uslub, yorug'lik, ranglar (markaz ranglari: to'q ko'k va binafsha). Rasmda yozuv "
      "so'ramang: matn title/subtitle orqali qo'yiladi.",
      {"prompt": S("Rasm tavsifi (ingliz tilida)"), "format": S("post | story | afisha | landscape"),
       "title": S("Rasm ustidagi sarlavha (o'zbekcha, qisqa; ixtiyoriy)"), "subtitle": S("Kichik matn (ixtiyoriy)"),
       "brand": B("Logo va sarlavha qo'yilsin (standart true)")},
      ["prompt"], perm="manage_content", write=True, confirm=True)
async def generate_image(ctx, prompt, format="post", title=None, subtitle=None, brand=True):
    from . import genai
    raw = await genai.image(prompt, format)
    data = design.brand_overlay(raw, title, subtitle, format if format in design.SIZES else "post") if brand else raw
    url, file_id = await _deliver_media(ctx, data, "photo", "ai.png", title or "AI rasm")
    await genai.remember(ctx.staff_id, "photo", url, file_id, prompt, "ai_image")
    return {"ok": True, "media_url": url, "file_id": file_id, "media_kind": "photo",
            "xabar": "Rasm chatga yuborildi. Chiqarish: publish_post(use_last_media=true)."}


@tool("generate_video", "AI bilan professional video yaratadi (Higgsfield: Kling 3.0 Pro; zaxira: OpenAI Sora): 3-15 soniya, "
      "vertikal (Reels/Shorts/TikTok) yoki gorizontal. Fonda tayyorlanadi (2-6 daqiqa) va tayyor bo'lgach chatga yuboriladi. "
      "Foydalanuvchi rasm yuborgan bo'lsa, rasm jonlantiriladi (image-to-video). Prompt ingliz tilida, kinematografik: "
      "sahna, harakat, kamera harakati (dolly, close-up), yorug'lik, kayfiyat, birinchi 2 soniyada diqqatni tortadigan "
      "lahza; haqiqiy odamlar ismini va brendlarni yozmang. Pullik: har safar tasdiq so'raladi.",
      {"prompt": S("Video tavsifi (ingliz tilida, kinematografik, batafsil; 500 belgigacha)"),
       "seconds": N("Davomiyligi, soniya (Higgsfield: 3-15, standart 8)"),
       "vertical": B("9:16 vertikal (standart true)")},
      ["prompt"], perm="manage_content", write=True, confirm=True)
async def generate_video(ctx, prompt, seconds=8, vertical=True):
    import asyncio as _a
    from . import genai
    if not genai.enabled():
        raise ToolError("AI video uchun Higgsfield ulanmagan (.env da HIGGSFIELD_API_KEY va HIGGSFIELD_API_SECRET).")
    if not ctx.chat_id:
        raise ToolError("Video tayyor bo'lgach yuborish uchun Telegram chat kerak: buni botda so'rang.")
    want = int(float(seconds or 8))
    sec = max(3, min(15, want)) if genai.provider() == "higgsfield" else min((4, 8, 12), key=lambda x: abs(x - want))
    ref = None
    att = next((a for a in ctx.attachments if a.get("kind") == "photo"), None)
    if att and att.get("b64"):
        import base64 as _b
        ref = _b.b64decode(att["b64"])

    async def deliver(data):
        return await _deliver_media(ctx, data, "video", "ai_video.mp4", "AI video")

    _a.create_task(genai.video_job(ctx.chat_id, ctx.staff_id, prompt, sec, vertical, ref, deliver))
    return {"ok": True, "holat": "boshlandi", "soniya": sec,
            "xabar": "Video fonda tayyorlanmoqda (1-5 daqiqa); tayyor bo'lgach chatga keladi."}
