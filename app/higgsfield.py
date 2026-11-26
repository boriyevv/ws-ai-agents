"""Higgsfield AI: professional video va rasm (Kling 3.0, MiniMax, Seedream ...).

API rasmiy Python SDK (higgsfield-client) bilan bir xil ishlaydi:
  POST https://api.higgsfield.ai/<model>        JSON argumentlar, "Authorization: Key <id>:<secret>"
  -> {"request_id", "status_url", "cancel_url"}
  GET  status_url  -> {"status": queued|in_progress|completed|failed|nsfw|canceled, ... natija}
  Natija: video -> result["video"]["url"], rasm -> result["images"][0]["url"]
Model nomlari .env da (HIGGSFIELD_T2V_MODEL va boshqalar) — Higgsfield'dagi istalgan modelga almashtirsa bo'ladi.
"""
import asyncio
import logging

import httpx

from . import config
from .core import ToolError

log = logging.getLogger("wstizim.higgsfield")
BASE = "https://api.higgsfield.ai"


def enabled():
    return bool(_key())


def _key():
    if config.HIGGSFIELD_KEY:
        return config.HIGGSFIELD_KEY
    if config.HIGGSFIELD_API_KEY and config.HIGGSFIELD_API_SECRET:
        return f"{config.HIGGSFIELD_API_KEY}:{config.HIGGSFIELD_API_SECRET}"
    return None


def _headers():
    key = _key()
    if not key:
        raise ToolError("Higgsfield ulanmagan (.env da HIGGSFIELD_API_KEY va HIGGSFIELD_API_SECRET).")
    return {"Authorization": f"Key {key}", "Content-Type": "application/json", "User-Agent": "ws-tizim"}


def _err(r):
    try:
        d = r.json()
        msg = d.get("detail") or d.get("details") or d.get("message") or d.get("error") or r.text
    except ValueError:
        msg = r.text
    msg = str(msg)
    low = msg.lower()
    if r.status_code in (401, 403):
        hint = "Higgsfield kaliti noto'g'ri (HIGGSFIELD_API_KEY / SECRET)"
    elif r.status_code == 402 or "credit" in low or "balance" in low or "insufficient" in low:
        hint = "Higgsfield hisobida kredit yetmayapti (cloud.higgsfield.ai → Billing)"
    elif r.status_code == 404:
        hint = "bunday model topilmadi: .env dagi HIGGSFIELD_*_MODEL nomini Higgsfield saytidagi bilan solishtiring"
    elif r.status_code == 422 or r.status_code == 400:
        hint = "parametrlar modelga mos kelmadi"
    else:
        hint = "Higgsfield xatosi"
    return ToolError(f"{hint}. ({r.status_code}: {msg[:250]})")


async def submit(model, args):
    """So'rov yuboradi. Model qo'shimcha maydonni (masalan aspect_ratio) qabul qilmasa, usiz qayta urinadi."""
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{BASE}/{model.strip('/')}", json=args, headers=_headers())
        if r.status_code in (400, 422):
            optional = [k for k in ("aspect_ratio", "resolution", "sound") if k in args and k in r.text]
            if optional:
                log.info("%s: %s maydonisiz qayta yuborilmoqda", model, optional)
                r = await c.post(f"{BASE}/{model.strip('/')}", json={k: v for k, v in args.items() if k not in optional},
                                 headers=_headers())
    if r.status_code >= 300:
        raise _err(r)
    d = r.json()
    return d.get("status_url") or f"{BASE}/requests/{d['request_id']}/status"


def _find_url(data, kind):
    """Natijadan video yoki rasm havolasini topadi (rasmiy shakl: video.url / images[0].url)."""
    if kind == "video":
        v = data.get("video")
        if isinstance(v, dict) and v.get("url"):
            return v["url"]
        vs = data.get("videos")
        if isinstance(vs, list) and vs and isinstance(vs[0], dict) and vs[0].get("url"):
            return vs[0]["url"]
    else:
        im = data.get("images")
        if isinstance(im, list) and im and isinstance(im[0], dict) and im[0].get("url"):
            return im[0]["url"]
        if isinstance(data.get("image"), dict) and data["image"].get("url"):
            return data["image"]["url"]
    # zaxira: ichma-ich qidirish
    stack = [data]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            for k, val in x.items():
                if k == "url" and isinstance(val, str) and val.startswith("http"):
                    if kind != "video" or any(e in val.lower() for e in (".mp4", ".mov", "video")):
                        return val
                stack.append(val)
        elif isinstance(x, list):
            stack.extend(x)
    return None


async def wait(status_url, kind, timeout=900, every=6):
    """Natija tayyor bo'lguncha kutadi -> fayl baytlari"""
    waited = 0
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
        while waited <= timeout:
            r = await c.get(status_url, headers=_headers())
            if r.status_code >= 300:
                raise _err(r)
            d = r.json()
            st = d.get("status")
            if st == "completed":
                url = _find_url(d, kind)
                if not url:
                    raise ToolError("Higgsfield natija qaytardi, lekin fayl havolasi topilmadi.")
                f = await c.get(url)
                if f.status_code >= 300:
                    raise ToolError(f"Tayyor faylni yuklab bo'lmadi ({f.status_code}).")
                return f.content
            if st == "nsfw":
                raise ToolError("Higgsfield natijani nomaqbul kontent deb blokladi: tavsifni o'zgartiring.")
            if st in ("failed", "canceled"):
                raise ToolError(f"Higgsfield: generatsiya muvaffaqiyatsiz ({st}). {str(d.get('error') or '')[:200]}")
            await asyncio.sleep(every)
            waited += every
    raise ToolError("Higgsfield 15 daqiqada tayyorlamadi.")


async def upload(data: bytes, content_type="image/jpeg"):
    """Faylni Higgsfield'ga yuklaydi (rasmdan video uchun) -> ochiq havola"""
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{BASE}/files/generate-upload-url", json={"content_type": content_type}, headers=_headers())
        if r.status_code >= 300:
            raise _err(r)
        d = r.json()
        put = await c.put(d["upload_url"], content=data, headers=d.get("upload_headers") or {"Content-Type": content_type})
        if put.status_code >= 300:
            raise ToolError(f"Rasm Higgsfield'ga yuklanmadi ({put.status_code}).")
        return d["public_url"]


async def video(prompt, seconds=8, vertical=True, ref_image: bytes | None = None):
    """-> mp4 bytes"""
    aspect = "9:16" if vertical else "16:9"
    if ref_image:
        img_url = await upload(ref_image)
        model = config.HIGGSFIELD_I2V_MODEL
        args = {"prompt": prompt[:1500], "image_url": img_url, "duration": int(seconds), "aspect_ratio": aspect}
    else:
        model = config.HIGGSFIELD_T2V_MODEL
        args = {"prompt": prompt[:512], "duration": max(3, min(15, int(seconds))), "aspect_ratio": aspect}
    status_url = await submit(model, args)
    return await wait(status_url, "video")


async def image(prompt, fmt="post"):
    """-> rasm bytes"""
    aspect = {"post": "1:1", "story": "9:16", "afisha": "4:5", "landscape": "16:9"}.get(fmt, "1:1")
    status_url = await submit(config.HIGGSFIELD_IMAGE_MODEL,
                              {"prompt": prompt[:2000], "resolution": "2K", "aspect_ratio": aspect})
    return await wait(status_url, "image", timeout=300, every=3)
