"""Telegram kanal va Instagramga post chiqarish (matn, rasm, video); faylni Supabase Storage'ga yuklash."""
import asyncio
import logging
import mimetypes
import uuid

import httpx

from . import config, db
from .core import ToolError, rt

log = logging.getLogger("wstizim.social")
GRAPH = f"https://graph.facebook.com/{config.META_API_VERSION}"     # Facebook sahifa orqali Instagram + Meta Ads
IG_GRAPH = f"https://graph.instagram.com/{config.META_API_VERSION}" # "Instagram Login" usuli (Facebook sahifasiz)


def ig_configured():
    return bool(config.IG_ACCESS_TOKEN and (config.IG_USER_ID or config.IG_ACCESS_TOKEN.startswith("IG")))


async def ig_auth():
    """-> (api manzili, instagram foydalanuvchi id, token).
    Token "IG..." bilan boshlansa — Instagram Login usuli (graph.instagram.com), aks holda Facebook sahifa usuli.
    Instagram Login tokeni 60 kunda eskiradi: tizim uni har hafta yangilab, bazada saqlaydi."""
    tok = config.IG_ACCESS_TOKEN or ""
    if tok.startswith("IG"):
        row = await db.one("select value from settings where key='ig_token'")
        tok = row["value"] if row else tok
        return IG_GRAPH, config.IG_USER_ID or "me", tok
    return GRAPH, config.IG_USER_ID, tok


async def refresh_ig_token():
    """Instagram Login tokenini uzaytiradi (har hafta). Facebook sahifa tokeniga tegmaydi."""
    if not (config.IG_ACCESS_TOKEN or "").startswith("IG"):
        return False
    _, _, tok = await ig_auth()
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get("https://graph.instagram.com/refresh_access_token",
                        params={"grant_type": "ig_refresh_token", "access_token": tok})
    if r.status_code >= 300 or not r.json().get("access_token"):
        log.warning("Instagram tokeni yangilanmadi: %s", r.text[:200])
        return False
    await db.ex("insert into settings (key, value, updated_at) values ('ig_token', %s, now()) "
                "on conflict (key) do update set value=excluded.value, updated_at=now()", r.json()["access_token"])
    return True
MAX_UPLOAD = 50 * 1024 * 1024        # Supabase bepul tarifi va Telegram bot yuklash chegarasi


def storage_enabled():
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)


async def upload_public(data: bytes, ext="jpg", content_type="image/jpeg"):
    """Faylni Supabase Storage (public bucket) ga yuklaydi va ochiq havolani qaytaradi.
    Instagram rasm/videoni faqat ochiq havola orqali oladi."""
    if not storage_enabled():
        return None
    if len(data) > MAX_UPLOAD:
        raise ToolError("Fayl juda katta (50 MB gacha).")
    name = f"{uuid.uuid4().hex}.{ext.lstrip('.')}"
    url = f"{config.SUPABASE_URL}/storage/v1/object/{config.SUPABASE_BUCKET}/{name}"
    key = config.SUPABASE_SERVICE_KEY
    headers = {"Content-Type": content_type, "apikey": key}
    if not key.startswith("sb_"):
        # eski (legacy) service_role JWT kaliti; yangi sb_secret_ kalitlari faqat apikey sarlavhasida yuboriladi
        headers["Authorization"] = f"Bearer {key}"
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(url, content=data, headers=headers)
    if r.status_code >= 300:
        raise ToolError(f"Fayl yuklanmadi: {r.status_code} {r.text[:200]}")
    return f"{config.SUPABASE_URL}/storage/v1/object/public/{config.SUPABASE_BUCKET}/{name}"


def guess_kind(filename="", content_type=""):
    ct = content_type or mimetypes.guess_type(filename)[0] or ""
    if ct.startswith("video/"):
        return "video"
    if ct.startswith("image/"):
        return "photo"
    return None


async def _download(url):
    async with httpx.AsyncClient(timeout=180, follow_redirects=True) as c:
        r = await c.get(url)
    r.raise_for_status()
    if len(r.content) > MAX_UPLOAD:
        raise ToolError("Fayl Telegram uchun juda katta (50 MB gacha).")
    return r.content


# ---------- Telegram kanal ----------
async def post_telegram(text, kind="none", media_url=None, file_id=None):
    """Qaytaradi: (natija matni, telegram file_id yoki None)"""
    if not config.TELEGRAM_CHANNEL_ID:
        raise ToolError("Telegram kanal sozlanmagan (.env da TELEGRAM_CHANNEL_ID).")
    ch, text = config.TELEGRAM_CHANNEL_ID, text or ""
    if kind == "none":
        msg = await rt.bot.send_message(chat_id=ch, text=text[:4096])
        return f"message_id={msg.message_id}", None
    media = file_id or await _download(media_url)
    caption = text if len(text) <= 1024 else None
    if kind == "video":
        msg = await rt.bot.send_video(chat_id=ch, video=media, caption=caption, supports_streaming=True,
                                      read_timeout=180, write_timeout=180)
        new_id = msg.video.file_id if msg.video else None
    else:
        msg = await rt.bot.send_photo(chat_id=ch, photo=media, caption=caption, read_timeout=120,
                                      write_timeout=120)
        new_id = msg.photo[-1].file_id if msg.photo else None
    if caption is None and text:                 # uzun matn alohida xabar bo'lib ketadi
        await rt.bot.send_message(chat_id=ch, text=text[:4096])
    return f"message_id={msg.message_id}", new_id


# ---------- Instagram ----------
async def post_instagram(caption, kind="photo", media_url=None):
    if not ig_configured():
        raise ToolError("Instagram sozlanmagan (.env da IG_ACCESS_TOKEN va IG_USER_ID).")
    if kind not in ("photo", "video") or not media_url:
        raise ToolError("Instagram uchun rasm yoki video kerak (ochiq havola). Faylni botga yoki panelga yuklang.")
    api, ig_user, tok = await ig_auth()
    base = f"{api}/{ig_user}"
    data = {"caption": (caption or "")[:2200], "access_token": tok}
    if kind == "video":
        data.update(media_type="REELS", video_url=media_url, share_to_feed="true")
    else:
        data["image_url"] = media_url
    async with httpx.AsyncClient(timeout=120) as c:
        r1 = await c.post(f"{base}/media", data=data)
        if r1.status_code >= 300:
            raise ToolError(f"Instagram media xatosi: {r1.text[:300]}")
        creation_id = r1.json().get("id")
        # Video serverda qayta ishlanadi: tayyor bo'lguncha kutamiz (ko'pi bilan ~5 daqiqa)
        for _ in range(60 if kind == "video" else 12):
            st = await c.get(f"{api}/{creation_id}", params={"fields": "status_code,status", "access_token": tok})
            code = st.json().get("status_code") if st.status_code < 300 else None
            if code == "FINISHED" or (code is None and kind == "photo"):
                break
            if code == "ERROR":
                raise ToolError(f"Instagram videoni qabul qilmadi: {st.json().get('status', '')[:200]}")
            await asyncio.sleep(5)
        else:
            raise ToolError("Instagram videoni 5 daqiqada tayyorlamadi. Keyinroq qayta urinib ko'ring.")
        r2 = await c.post(f"{base}/media_publish", data={"creation_id": creation_id, "access_token": tok})
        if r2.status_code >= 300:
            raise ToolError(f"Instagram publish xatosi: {r2.text[:300]}")
        return f"media_id={r2.json().get('id')}"


# ---------- YouTube Shorts / TikTok: n8n yoki Make orqali ----------
WEBHOOK_TARGETS = ("youtube", "tiktok")


async def post_webhook(platform, post):
    """n8n/Make ssenariysiga postni yuboradi; u YouTube/TikTok ga joylaydi (README: 'Nashr agenti')."""
    if not config.N8N_WEBHOOK_URL:
        raise ToolError(f"{platform} uchun n8n/Make ulanmagan (.env da N8N_WEBHOOK_URL).")
    if post["media_kind"] != "video" or not post["media_url"]:
        raise ToolError(f"{platform} uchun video (ochiq havola) kerak.")
    payload = {"platform": platform, "text": post["body"], "media_url": post["media_url"],
               "media_kind": post["media_kind"], "post_id": str(post["id"])}
    headers = {"X-WS-Secret": config.N8N_WEBHOOK_SECRET} if config.N8N_WEBHOOK_SECRET else {}
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(config.N8N_WEBHOOK_URL, json=payload, headers=headers)
    if r.status_code >= 300:
        raise ToolError(f"n8n/Make javobi: {r.status_code} {r.text[:200]}")
    return f"webhook {r.status_code}"


def signup_link(post):
    from .core import invite_link
    return invite_link("ld", post["ref_code"]) if post.get("ref_code") else ""


# ---------- umumiy chop etish ----------
async def publish(post_id):
    """content_posts dagi bitta postni hamma manzillarga chiqaradi va natijani yozadi."""
    post = await db.one("update content_posts set status='publishing' where id=%s and status in ('scheduled','failed') "
                        "returning *", post_id)
    if not post:
        return None
    results, file_id = {}, post["tg_file_id"]
    for tg in post["targets"]:
        try:
            if tg == "telegram":
                body = post["body"] or ""
                if post.get("signup_link") and config.BOT_USERNAME:
                    body += f"\n\n👉 Yozilish / savol: {signup_link(post)}"
                res, new_id = await post_telegram(body, post["media_kind"], post["media_url"], file_id)
                file_id = file_id or new_id
            elif tg == "instagram":
                res = await post_instagram(post["body"], post["media_kind"], post["media_url"])
            elif tg in WEBHOOK_TARGETS:
                res = await post_webhook(tg, post)
            else:
                raise ToolError(f"Noma'lum joy: {tg}")
            results[tg] = {"ok": True, "natija": res}
        except Exception as e:
            log.warning("post xatosi (%s): %s", tg, e)
            results[tg] = {"ok": False, "xato": str(e)[:300]}
        await db.ex("insert into social_posts (platform, body, image_url, ok, result, posted_by) values (%s,%s,%s,%s,%s,%s)",
                    tg, post["body"], post["media_url"], results[tg]["ok"],
                    results[tg].get("natija") or results[tg].get("xato"), post["created_by"])
    oks = [r["ok"] for r in results.values()]
    status = "published" if all(oks) else "partial" if any(oks) else "failed"
    await db.ex("update content_posts set status=%s, results=%s, tg_file_id=%s, published_at=now() where id=%s",
                status, db.js(results), file_id, post_id)
    return {"holat": status, "natija": results}


async def publish_due():
    """Vaqti kelgan rejalashtirilgan postlar (har daqiqada chaqiriladi)."""
    rows = await db.q("select id from content_posts where status='scheduled' and scheduled_at <= now() "
                      "order by scheduled_at limit 5")
    for r in rows:
        try:
            await publish(r["id"])
        except Exception:
            log.exception("rejalashtirilgan post xatosi")
