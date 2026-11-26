"""AI bilan rasm va video yaratish.

Asosiy: Higgsfield (Kling 3.0 Pro video, Seedream rasm) — .env da HIGGSFIELD_API_KEY/SECRET bo'lsa.
Zaxira: OpenAI (gpt-image-1, Sora) — faqat Higgsfield ulanmagan bo'lsa. Ikkalasi ham pullik.
Video bir necha daqiqa tayyorlanadi: fonda kutiladi va tayyor bo'lgach foydalanuvchiga yuboriladi.
"""
import asyncio
import base64
import logging

import httpx

from . import config, db
from .core import ToolError, rt

log = logging.getLogger("wstizim.genai")
API = "https://api.openai.com/v1"

IMAGE_SIZES = {"post": "1024x1024", "story": "1024x1536", "afisha": "1024x1536", "landscape": "1536x1024"}
VIDEO_SIZES = {True: "720x1280", False: "1280x720"}


def provider():
    from . import higgsfield
    if higgsfield.enabled():
        return "higgsfield"
    if config.OPENAI_API_KEY:
        return "openai"
    return None


def enabled():
    return provider() is not None


def _headers():
    if not config.OPENAI_API_KEY:
        raise ToolError("AI rasm/video uchun OpenAI ulanmagan (.env da OPENAI_API_KEY).")
    return {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}


def _explain(r):
    try:
        msg = r.json().get("error", {}).get("message", r.text)
    except ValueError:
        msg = r.text
    low = msg.lower()
    if r.status_code == 401:
        hint = "OpenAI kaliti noto'g'ri yoki o'chirilgan"
    elif "verif" in low:
        hint = "OpenAI tashkilotingizni tasdiqlash (Organization verification) kerak: platform.openai.com → Settings → Organization"
    elif r.status_code == 429 or "quota" in low or "billing" in low or "credit" in low:
        hint = "OpenAI hisobida kredit yoki limit yetmayapti (platform.openai.com → Billing)"
    elif r.status_code == 403 or "permission" in low:
        hint = "kalitda bu xizmat uchun ruxsat yo'q (API Keys → ruxsatlar)"
    elif "safety" in low or "moderation" in low or "content policy" in low:
        hint = "so'rov OpenAI qoidalariga to'g'ri kelmadi: tavsifni o'zgartiring"
    else:
        hint = "OpenAI xatosi"
    return ToolError(f"{hint}. ({r.status_code}: {msg[:200]})")


async def image(prompt, fmt="post"):
    """-> rasm bytes (Higgsfield yoki OpenAI)"""
    if provider() == "higgsfield":
        from . import higgsfield
        return await higgsfield.image(prompt, fmt)
    if not config.OPENAI_API_KEY:
        raise ToolError("AI rasm uchun Higgsfield yoki OpenAI ulanmagan (.env).")
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(f"{API}/images/generations", headers=_headers(),
                         json={"model": config.OPENAI_IMAGE_MODEL, "prompt": prompt[:4000], "n": 1,
                               "size": IMAGE_SIZES.get(fmt, "1024x1024")})
    if r.status_code >= 300:
        raise _explain(r)
    item = r.json()["data"][0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    async with httpx.AsyncClient(timeout=120) as c:
        return (await c.get(item["url"])).content


async def start_video(prompt, seconds=8, vertical=True, ref_image: bytes | None = None):
    """Video tayyorlashni boshlaydi -> video id"""
    form = {"model": (None, config.OPENAI_VIDEO_MODEL), "prompt": (None, prompt[:4000]),
            "seconds": (None, str(seconds)), "size": (None, VIDEO_SIZES[bool(vertical)])}
    if ref_image:
        form["input_reference"] = ("ref.jpg", ref_image, "image/jpeg")
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{API}/videos", headers=_headers(), files=form)
    if r.status_code >= 300:
        raise _explain(r)
    return r.json()["id"]


async def wait_video(video_id, timeout=900, every=10):
    """Tayyor bo'lguncha kutadi -> mp4 bytes"""
    async with httpx.AsyncClient(timeout=120) as c:
        waited = 0
        while waited < timeout:
            r = await c.get(f"{API}/videos/{video_id}", headers=_headers())
            if r.status_code >= 300:
                raise _explain(r)
            st = r.json().get("status")
            if st == "completed":
                v = await c.get(f"{API}/videos/{video_id}/content", headers=_headers(), follow_redirects=True)
                if v.status_code >= 300:
                    raise _explain(v)
                return v.content
            if st == "failed":
                err = (r.json().get("error") or {}).get("message", "noma'lum sabab")
                raise ToolError(f"Video yaratilmadi: {err}")
            await asyncio.sleep(every)
            waited += every
    raise ToolError("Video 15 daqiqada tayyor bo'lmadi.")


async def remember(staff_id, kind, url, file_id, prompt, source):
    """Oxirgi yaratilgan media: keyin "shuni kanalga chiqar" desa ishlatiladi."""
    try:
        await db.ex("insert into generated_media (staff_id, kind, url, file_id, prompt, source) values (%s,%s,%s,%s,%s,%s)",
                    staff_id, kind, url, file_id, (prompt or "")[:1000], source)
    except Exception:
        log.warning("media eslab qolinmadi")


async def last_media(staff_id, hours=48):
    return await db.one("select * from generated_media where staff_id=%s and created_at > now() - make_interval(hours => %s::int) "
                        "order by created_at desc limit 1", staff_id, hours)


async def video_job(chat_id, staff_id, prompt, seconds, vertical, ref_image, deliver):
    """Fon vazifa: videoni yaratadi, tayyor bo'lgach chatga yuboradi."""
    try:
        if provider() == "higgsfield":
            from . import higgsfield
            await rt.bot.send_message(chat_id, f"🎬 Higgsfield'da video tayyorlanmoqda ({seconds} soniya). Odatda 2-6 daqiqa "
                                               "oladi, tayyor bo'lgach shu yerga yuboraman.")
            data = await higgsfield.video(prompt, seconds, vertical, ref_image)
        else:
            vid = await start_video(prompt, seconds, vertical, ref_image)
            await rt.bot.send_message(chat_id, f"🎬 Video tayyorlanmoqda ({seconds} soniya). Odatda 1-5 daqiqa oladi, tayyor "
                                               "bo'lgach shu yerga yuboraman.")
            data = await wait_video(vid)
        url, file_id = await deliver(data)
        await remember(staff_id, "video", url, file_id, prompt, "ai_video")
        await rt.bot.send_message(chat_id, "✅ Video tayyor. Chiqarish uchun yozing: «Jimi, shu videoni kanalga chiqar» "
                                           "(yoki Instagramga). Subtitr/sarlavha kerak bo'lsa: «Jimi, shu videoga sarlavha qo'y».")
    except ToolError as e:
        await rt.bot.send_message(chat_id, f"❌ Video yaratilmadi: {e}")
    except Exception as e:
        log.exception("video vazifa xatosi")
        await rt.bot.send_message(chat_id, f"❌ Video yaratishda xato: {str(e)[:200]}")
