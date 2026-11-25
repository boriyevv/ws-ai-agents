"""Ulanishlarni tekshirish:  python -m scripts.tekshirish

Har bir xizmatga kichik sinov so'rovi yuboradi va natijani oddiy tilda chiqaradi.
Kalitlarning o'zi ekranga chiqarilmaydi.
"""
import asyncio
import io
import sys
import wave

import httpx

OK, BAD, SKIP = "✅", "❌", "➖"


def line(icon, name, text=""):
    print(f"{icon} {name}" + (f": {text}" if text else ""))


def silent_wav(seconds=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000 * seconds)
    return buf.getvalue()


async def main():
    try:
        from app import config
    except SystemExit as e:
        line(BAD, ".env", str(e))
        return
    print(f"\nWS-Tizim: ulanishlarni tekshirish\n")

    # --- baza
    try:
        import psycopg
        async with await psycopg.AsyncConnection.connect(config.DATABASE_URL, prepare_threshold=None, connect_timeout=15) as c:
            cur = await c.execute("select count(*) from pg_tables where schemaname='public'")
            n = (await cur.fetchone())[0]
            cur = await c.execute("select to_regclass('public.staff') is not null, to_regclass('public.content_plan') is not null")
            staff, latest = await cur.fetchone()
        if not staff:
            line(BAD, "Baza (Supabase)", "ulandi, lekin jadvallar yo'q: SQL Editor'da sql/setup.sql ni ishga tushiring")
        elif not latest:
            line(BAD, "Baza (Supabase)", "eski sxema: sql/yangilash_1.sql va sql/yangilash_2.sql ni ishga tushiring")
        else:
            line(OK, "Baza (Supabase)", f"{n} ta jadval")
    except Exception as e:
        msg = str(e).splitlines()[0][:200]
        hint = ""
        if "password" in msg.lower():
            hint = " -> DATABASE_URL dagi parol noto'g'ri"
        elif "could not translate host" in msg.lower() or "timeout" in msg.lower():
            hint = " -> DATABASE_URL manzili yoki internetni tekshiring (Session pooler havolasi bo'lsin)"
        line(BAD, "Baza (Supabase)", msg + hint)

    async with httpx.AsyncClient(timeout=30) as http:
        # --- Telegram
        try:
            await check_telegram(http, config)
        except Exception as e:
            line(BAD, "Telegram", f"ulanib bo'lmadi: {str(e)[:200]} (internetni tekshiring)")

        await check_rest(http, config)

    from app import video
    line(OK if video.available() else SKIP, "ffmpeg (video tahrir)", "" if video.available() else "o'rnatilmagan (ixtiyoriy)")
    print("\n❌ bo'lsa, shu qatorni nusxalab yuboring (kalitlar ko'rsatilmagan).\n")


async def check_telegram(http, config):
        r = await http.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getMe")
        if r.status_code == 200:
            line(OK, "Telegram bot", "@" + r.json()["result"]["username"])
        else:
            line(BAD, "Telegram bot", f"{r.status_code}: token noto'g'ri (BotFather'dan qayta oling)")
        line(OK if config.OWNER_TELEGRAM_ID else BAD, "Rahbar Telegram ID", str(config.OWNER_TELEGRAM_ID))

        if config.TELEGRAM_CHANNEL_ID and r.status_code == 200:
            ch = await http.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getChat",
                                params={"chat_id": config.TELEGRAM_CHANNEL_ID})
            if ch.status_code == 200:
                bot_id = r.json()["result"]["id"]
                m = await http.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getChatMember",
                                   params={"chat_id": config.TELEGRAM_CHANNEL_ID, "user_id": bot_id})
                st = m.json().get("result", {}).get("status") if m.status_code == 200 else None
                line(OK if st == "administrator" else BAD, "Telegram kanal",
                     ch.json()["result"].get("title", "") + ("" if st == "administrator" else " -> botni kanalga ADMIN qiling"))
            else:
                line(BAD, "Telegram kanal", f"topilmadi ({ch.json().get('description', '')}) -> TELEGRAM_CHANNEL_ID va bot admin ekanini tekshiring")
        else:
            line(SKIP, "Telegram kanal", "sozlanmagan (ixtiyoriy)")



async def check_rest(http, config):
        # --- Claude
        try:
            from anthropic import AsyncAnthropic
            import anthropic
            client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
            for model in dict.fromkeys([config.MODEL_FAST, config.MODEL_MAIN]):
                try:
                    resp = await client.messages.create(model=model, max_tokens=300, output_config={"effort": "low"},
                                                        messages=[{"role": "user", "content": "Salom de"}])
                    line(OK, f"Claude ({model})", resp.stop_reason)
                except anthropic.AuthenticationError:
                    line(BAD, f"Claude ({model})", "ANTHROPIC_API_KEY noto'g'ri yoki o'chirilgan")
                    break
                except anthropic.NotFoundError:
                    line(BAD, f"Claude ({model})", "model topilmadi -> .env dagi MODEL_MAIN / MODEL_FAST ni tekshiring")
                except anthropic.APIStatusError as e:
                    t = str(e)
                    if "credit" in t.lower() or "billing" in t.lower():
                        line(BAD, f"Claude ({model})", "kredit yo'q -> console.anthropic.com → Billing")
                        break
                    line(BAD, f"Claude ({model})", t[:250])
        except Exception as e:
            line(BAD, "Claude", str(e)[:250])

        # --- ElevenLabs / OpenAI ovoz
        from app import voice
        if voice.stt_enabled():
          try:
            try:
                await voice.transcribe(silent_wav(), filename="test.wav", mime="audio/wav")
                line(OK, f"Ovoz -> matn ({config.STT_PROVIDER})")
            except voice.SttError as e:
                line(BAD, f"Ovoz -> matn ({config.STT_PROVIDER})", str(e)[:300])
            except Exception as e:
                line(BAD, f"Ovoz -> matn ({config.STT_PROVIDER})", str(e)[:300])
          except Exception as e:
            line(BAD, "Ovoz -> matn", str(e)[:300])
        else:
            line(SKIP, "Ovoz -> matn", "kalit yo'q (ixtiyoriy)")

        # --- Supabase Storage
        from app import social
        if social.storage_enabled():
            try:
                url = await social.upload_public(b"ws-tizim test", "txt", "text/plain")
                g = await http.get(url)
                line(OK if g.status_code == 200 else BAD, "Fayl saqlash (Storage)",
                     "ishlayapti" if g.status_code == 200 else "yuklandi, lekin ochiq emas -> 'media' bucketni PUBLIC qiling")
            except Exception as e:
                hint = " -> Storage'da 'media' nomli bucket yarating" if "not found" in str(e).lower() else ""
                line(BAD, "Fayl saqlash (Storage)", str(e)[:250] + hint)
        else:
            line(SKIP, "Fayl saqlash (Storage)", "sozlanmagan (Instagram uchun kerak)")

        # --- Instagram
        if social.ig_configured():
            try:
                from app import db
                await db.open_pool()
                api, uid, tok = await social.ig_auth()
                ig = await http.get(f"{api}/{uid}", params={"fields": "username", "access_token": tok})
                await db.close_pool()
                if ig.status_code == 200:
                    line(OK, "Instagram", "@" + ig.json().get("username", "?"))
                else:
                    line(BAD, "Instagram", ig.json().get("error", {}).get("message", ig.text)[:250])
            except Exception as e:
                line(BAD, "Instagram", str(e)[:250])
        else:
            line(SKIP, "Instagram", "sozlanmagan (ixtiyoriy)")



if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(main())
