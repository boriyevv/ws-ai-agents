"""Ovoz: ovozli xabarni matnga (STT) va javobni ovozga (TTS) aylantirish."""
import re

import httpx

from . import config


class SttError(RuntimeError):
    """Ovoz xizmati xatosi: matni foydalanuvchiga tushunarli qilib ko'rsatiladi."""


def _check(r, who):
    if r.status_code < 300:
        return
    body = r.text[:300]
    if r.status_code == 401:
        hint = ("kalit noto'g'ri, o'chirilgan yoki unda Speech to Text ruxsati yo'q. .env dagi kalitni va "
                "ElevenLabs'dagi ruxsatlarni tekshiring")
    elif r.status_code == 402 or "quota" in body.lower() or "credit" in body.lower():
        hint = "kredit/limit tugagan"
    else:
        hint = "xizmat xatosi"
    raise SttError(f"{who} {r.status_code}: {hint}. Javob: {body}")


async def transcribe(audio: bytes, filename="voice.ogg", mime="audio/ogg") -> str:
    """O'zbekcha ovozni matnga aylantiradi. Provayder .env dagi STT_PROVIDER bilan tanlanadi."""
    if config.STT_PROVIDER == "openai":
        if not config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY to'ldirilmagan")
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                files={"file": (filename, audio, mime)},
                data={"model": config.OPENAI_STT_MODEL, "language": "uz",
                      "prompt": "O'quv markaz: guruh, davomat, kelmadi, to'lov, qarzdor, filial, o'quvchi, ota-ona."},
            )
        _check(r, "OpenAI")
        return r.json().get("text", "").strip()

    # elevenlabs (standart)
    if not config.ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY to'ldirilmagan")
    data = {"model_id": config.ELEVENLABS_STT_MODEL}
    if config.STT_LANGUAGE:
        data["language_code"] = config.STT_LANGUAGE
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": config.ELEVENLABS_API_KEY},
            files={"file": (filename, audio, mime)},
            data=data,
        )
    _check(r, "ElevenLabs")
    return r.json().get("text", "").strip()


def stt_enabled():
    if config.STT_PROVIDER == "openai":
        return bool(config.OPENAI_API_KEY)
    return bool(config.ELEVENLABS_API_KEY)


def _speakable(text, limit=700):
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_`#>|]", "", text)
    text = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\ufe0f]", "", text)   # emoji
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > 200 else cut


async def synthesize(text: str) -> bytes | None:
    """Matnni o'zbekcha ovozga aylantiradi (bepul edge-tts). Xato bo'lsa None."""
    try:
        import edge_tts
    except ImportError:
        return None
    spoken = _speakable(text)
    if not spoken:
        return None
    try:
        comm = edge_tts.Communicate(spoken, config.TTS_VOICE)
        buf = bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        return bytes(buf) or None
    except Exception:
        return None


async def transcribe_timed(audio: bytes, filename="audio.mp3", mime="audio/mpeg"):
    """Subtitr uchun: [(boshlanish_soniya, tugash_soniya, matn), ...]. Vaqt belgisi bo'lmasa bo'sh ro'yxat."""
    if config.STT_PROVIDER == "openai":
        if not config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY to'ldirilmagan")
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post("https://api.openai.com/v1/audio/transcriptions",
                             headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                             files={"file": (filename, audio, mime)},
                             data={"model": "whisper-1", "language": "uz", "response_format": "verbose_json",
                                   "timestamp_granularities[]": "segment"})
        _check(r, "OpenAI")
        return [(s["start"], s["end"], s["text"].strip()) for s in r.json().get("segments", []) if s.get("text")]
    if not config.ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY to'ldirilmagan")
    data = {"model_id": config.ELEVENLABS_STT_MODEL}
    if config.STT_LANGUAGE:
        data["language_code"] = config.STT_LANGUAGE
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post("https://api.elevenlabs.io/v1/speech-to-text", headers={"xi-api-key": config.ELEVENLABS_API_KEY},
                         files={"file": (filename, audio, mime)}, data=data)
    _check(r, "ElevenLabs")
    words = [w for w in r.json().get("words", []) if w.get("type", "word") == "word" and w.get("start") is not None]
    return group_words([(w["start"], w["end"], w["text"]) for w in words])


def group_words(words, max_words=5, max_gap=0.8):
    """So'zlarni subtitr qatorlariga birlashtiradi (har qatorda 5 tagacha so'z)."""
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w[0] - cur[-1][1] > max_gap):
            out.append((cur[0][0], cur[-1][1], " ".join(x[2].strip() for x in cur)))
            cur = []
        cur.append(w)
    if cur:
        out.append((cur[0][0], cur[-1][1], " ".join(x[2].strip() for x in cur)))
    return out
