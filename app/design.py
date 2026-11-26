"""Dizayn kartochkalari: post (1080x1080), story (1080x1920), afisha (1080x1350).

Shablonlar markaz uslubida (logodagi ko'k-binafsha fon, oq matn). Canva/Figma kerak emas: rasm shu yerda chiziladi.
Yangi shablon qo'shish: TEMPLATES ga nom va render funksiyasini qo'shing.
"""
import io
import pathlib
import random
import textwrap

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config

ASSETS = pathlib.Path(__file__).resolve().parent.parent / "assets"
SIZES = {"post": (1080, 1080), "story": (1080, 1920), "afisha": (1080, 1350)}
DARK, MID, LIGHT, ACCENT = (11, 4, 81), (52, 42, 188), (77, 101, 237), (125, 140, 255)


def font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for p in (ASSETS / "fonts" / name, pathlib.Path("/usr/share/fonts/truetype/dejavu") / name):
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def _background(w, h, seed=7):
    """Logodagidek: markazdan yorug'roq ko'k, chetlarga to'q binafsha, mayda yulduzlar."""
    img = Image.new("RGB", (w, h), DARK)
    glow = Image.new("RGB", (w, h), DARK)
    d = ImageDraw.Draw(glow)
    steps = 40
    for i in range(steps):
        t = i / steps
        col = tuple(int(DARK[k] + (LIGHT[k] - DARK[k]) * t ** 1.6) for k in range(3))
        rx, ry = int(w * (1.1 - t)), int(h * (0.75 - t * 0.6))
        d.ellipse((w // 2 - rx, h // 2 - ry, w // 2 + rx, h // 2 + ry), fill=col)
    img = glow.filter(ImageFilter.GaussianBlur(60))
    d = ImageDraw.Draw(img)
    rnd = random.Random(seed)
    for _ in range(int(w * h / 2500)):
        x, y = rnd.randrange(w), rnd.randrange(h)
        r = rnd.choice((1, 1, 1, 2))
        a = rnd.randrange(120, 255)
        d.ellipse((x, y, x + r, y + r), fill=(a, a, 255))
    return img


def _logo(img, x, y, size):
    p = ASSETS / "logo.png"
    if not p.exists():
        return
    lg = Image.open(p).convert("RGB").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    img.paste(lg, (x, y), mask)


def _wrap(draw, text, fnt, max_w):
    lines = []
    for para in str(text or "").split("\n"):
        words, cur = para.split(), ""
        for w in words:
            test = (cur + " " + w).strip()
            if draw.textlength(test, font=fnt) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def _text(draw, xy, text, size, bold=False, fill=(255, 255, 255), max_w=900, spacing=1.18, align="left", center_w=None):
    fnt = font(size, bold)
    x, y = xy
    for line in _wrap(draw, text, fnt, max_w):
        lx = x
        if align == "center" and center_w:
            lx = (center_w - draw.textlength(line, font=fnt)) / 2
        draw.text((lx, y), line, font=fnt, fill=fill)
        y += int(size * spacing)
    return y


def _pill(draw, x, y, text, size=30, fill=ACCENT, color=(11, 4, 81)):
    fnt = font(size, True)
    tw = draw.textlength(text, font=fnt)
    draw.rounded_rectangle((x, y, x + tw + size * 1.2, y + size * 1.7), radius=size, fill=fill)
    draw.text((x + size * 0.6, y + size * 0.3), text, font=fnt, fill=color)
    return y + size * 1.7


def _photo_circle(img, data, cx, cy, d):
    try:
        ph = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return
    s = min(ph.size)
    ph = ph.crop(((ph.width - s) // 2, (ph.height - s) // 2, (ph.width + s) // 2, (ph.height + s) // 2))
    ph = ph.resize((d, d), Image.LANCZOS)
    mask = Image.new("L", (d, d), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, d - 1, d - 1), fill=255)
    ring = ImageDraw.Draw(img)
    ring.ellipse((cx - d // 2 - 8, cy - d // 2 - 8, cx + d // 2 + 8, cy + d // 2 + 8), fill=ACCENT)
    img.paste(ph, (cx - d // 2, cy - d // 2), mask)


def _footer(img, draw, w, h, pad):
    contact = "   ·   ".join(x for x in (config.CENTER_PHONE, config.TELEGRAM_CHANNEL_ID or "") if x)
    top = h - pad - (95 if contact else 55)
    draw.line((pad, top, w - pad, top), fill=(120, 130, 255), width=2)
    _text(draw, (pad, top + 20), "WEB STREET IT ACADEMY", 30, True, fill=(220, 224, 255), max_w=w - 2 * pad)
    if contact:
        _text(draw, (pad, top + 60), contact, 28, fill=(190, 198, 255), max_w=w - 2 * pad)


# ---------- shablonlar ----------
def _natija(img, draw, w, h, f, photo):
    pad = 80
    y = pad + 130
    y = _pill(draw, pad, y, f.get("badge") or "BITIRUVCHI NATIJASI") + 50
    if photo:
        _photo_circle(img, photo, w - pad - 150, pad + 260, 260)
    y = _text(draw, (pad, y), f.get("score") or "", 170 if h > 1100 else 150, True, max_w=w - 2 * pad - (320 if photo else 0))
    y = _text(draw, (pad, y + 10), f.get("title") or "", 64, True, max_w=w - 2 * pad) + 20
    y = _text(draw, (pad, y), f.get("subtitle") or "", 40, fill=(210, 215, 255), max_w=w - 2 * pad) + 30
    _text(draw, (pad, y), f.get("details") or "", 36, fill=(235, 237, 255), max_w=w - 2 * pad)


def _aksiya(img, draw, w, h, f, photo):
    pad = 80
    y = pad + 150
    y = _pill(draw, pad, y, f.get("badge") or "AKSIYA") + 40
    y = _text(draw, (pad, y), f.get("title") or "", 80, True, max_w=w - 2 * pad) + 10
    y = _text(draw, (pad, y), f.get("score") or "", 200 if h > 1100 else 170, True, fill=(160, 172, 255), max_w=w - 2 * pad)
    y = _text(draw, (pad, y + 10), f.get("subtitle") or "", 44, fill=(225, 228, 255), max_w=w - 2 * pad) + 30
    _text(draw, (pad, y), f.get("details") or "", 36, fill=(235, 237, 255), max_w=w - 2 * pad)


def _yangi_guruh(img, draw, w, h, f, photo):
    pad = 80
    y = pad + 150
    y = _pill(draw, pad, y, f.get("badge") or "YANGI GURUH") + 40
    y = _text(draw, (pad, y), f.get("title") or "", 86, True, max_w=w - 2 * pad) + 30
    for line in (f.get("details") or "").split("\n"):
        if not line.strip():
            continue
        draw.ellipse((pad, y + 16, pad + 18, y + 34), fill=ACCENT)
        y = _text(draw, (pad + 40, y), line.strip(), 42, max_w=w - 2 * pad - 40) + 12
    if f.get("subtitle"):
        _pill(draw, pad, y + 30, f["subtitle"], 34, fill=(255, 255, 255))


def _elon(img, draw, w, h, f, photo):
    pad = 80
    y = pad + 160
    if f.get("badge"):
        y = _pill(draw, pad, y, f["badge"]) + 40
    y = _text(draw, (pad, y), f.get("title") or "", 84, True, max_w=w - 2 * pad) + 30
    y = _text(draw, (pad, y), f.get("subtitle") or "", 46, fill=(215, 220, 255), max_w=w - 2 * pad) + 30
    _text(draw, (pad, y), f.get("details") or "", 38, fill=(235, 237, 255), max_w=w - 2 * pad)


TEMPLATES = {
    "natija": ("Bitiruvchi/o'quvchi natijasi kartochkasi: score=ball (masalan 'IELTS 7.5'), title=ism, "
               "subtitle=kurs va o'qituvchi, details=qo'shimcha, foto ixtiyoriy", _natija),
    "aksiya": ("Chegirma/aksiya: title=sarlavha, score=chegirma ('-30%'), subtitle=shart, details=muddat va aloqa", _aksiya),
    "yangi_guruh": ("Yangi guruh e'loni: title=kurs nomi, details=har qatorda bitta fakt (kunlar, vaqt, boshlanish, "
                    "joylar), subtitle=chaqiriq ('Joylar soni cheklangan')", _yangi_guruh),
    "elon": ("Umumiy e'lon/afisha/tadbir: badge, title, subtitle, details", _elon),
}


def render(template, fmt="post", fields=None, photo: bytes | None = None) -> bytes:
    if template not in TEMPLATES:
        raise ValueError("Shablon: " + ", ".join(TEMPLATES))
    w, h = SIZES.get(fmt, SIZES["post"])
    img = _background(w, h, seed=hash(template) % 1000)
    draw = ImageDraw.Draw(img)
    _logo(img, 80, 70, 110)
    _text(draw, (210, 95), "WEB STREET", 40, True, max_w=600)
    _text(draw, (212, 142), "IT ACADEMY", 24, fill=(200, 205, 255), max_w=600)
    TEMPLATES[template][1](img, draw, w, h, fields or {}, photo)
    _footer(img, draw, w, h, 80)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def preview_all():
    """Hamma shablonlar namunasi (sinov uchun)."""
    sample = {"natija": {"score": "IELTS 7.5", "title": "Aziza Karimova", "subtitle": "Ingliz tili · Sardor ustoz",
                         "details": "6 oyda 5.0 dan 7.5 gacha"},
              "aksiya": {"title": "Do'stingiz bilan keling", "score": "-30%", "subtitle": "Ikkalangizga birinchi oy",
                         "details": "1-dekabrgacha · Joylar cheklangan"},
              "yangi_guruh": {"title": "Frontend dasturlash", "details": "Du / Chor / Juma\n14:00 - 16:00\n2-dekabrdan boshlanadi\n12 ta joy",
                              "subtitle": "Sinov darsi bepul"},
              "elon": {"badge": "TADBIR", "title": "Ochiq eshiklar kuni", "subtitle": "30-noyabr, 11:00",
                       "details": "O'qituvchilar bilan tanishing, bepul sinov darsi"}}
    return {k: render(k, "post", v) for k, v in sample.items()}


__all__ = ["render", "TEMPLATES", "SIZES", "textwrap"]


def brand_overlay(image_bytes: bytes, title=None, subtitle=None, fmt="post") -> bytes:
    """AI yaratgan rasm ustiga markaz logosi va (ixtiyoriy) sarlavha qo'yadi."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = SIZES.get(fmt, SIZES["post"])
    # rasmni kerakli formatga to'ldirib kesish
    scale = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    img = img.crop((left, top, left + w, top + h))
    if title or subtitle:
        # pastki qism to'q ko'k gradient (matn o'qilishi uchun)
        grad = Image.new("L", (1, 256))
        for y in range(256):
            grad.putpixel((0, y), int(235 * (y / 255) ** 1.4))
        band_h = int(h * 0.42)
        mask = grad.resize((w, band_h))
        shade = Image.new("RGB", (w, band_h), DARK)
        img.paste(shade, (0, h - band_h), mask)
    draw = ImageDraw.Draw(img)
    _logo(img, 60, 60, 120)
    pad = 70
    y = h - pad - 60
    lines = []
    if subtitle:
        lines.append((subtitle, 40, False, (220, 225, 255)))
    if title:
        lines.insert(0, (title, 76 if h <= 1100 else 84, True, (255, 255, 255)))
    # pastdan yuqoriga joylash
    blocks = []
    for text, size, bold, color in lines:
        fnt = font(size, bold)
        wrapped = _wrap(draw, text, fnt, w - 2 * pad)
        blocks.append((wrapped, size, bold, color))
    total = sum(len(b[0]) * int(b[1] * 1.18) + 14 for b in blocks)
    y = h - pad - total
    for wrapped, size, bold, color in blocks:
        y = _text(draw, (pad, y), "\n".join(wrapped), size, bold, fill=color, max_w=w - 2 * pad) + 14
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
