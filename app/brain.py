"""Jimi miyasi: Claude bilan suhbat, vositalarni chaqirish, mutaxassis agentlarga topshirish."""
import json
import logging
import pathlib

from anthropic import AsyncAnthropic

from . import config, db, tools
from .core import DAY_NAMES, ROLE_UZ, ToolError, now

log = logging.getLogger("wstizim.brain")
client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

AGENT_DIR = pathlib.Path(__file__).resolve().parent.parent / "agents"
AGENTS: dict = {}
ALWAYS_TOOLS = {"confirm_pending_action"}

COMMON_RULES = """
UMUMIY QOIDALAR
- Faqat oddiy matn yozing: markdown belgilari (*, #, `, jadval) ishlatmang. Emoji kam, joyida.
- Raqam, ism, sana, summani hech qachon o'zingizdan to'qimang: har doim vositalardan oling. Vosita xato
  qaytarsa, sababini oddiy tilda ayting va nima qilish kerakligini taklif qiling.
- Yozuvchi vositalarda `summary` maydoniga odam tushunadigan qisqa tavsif yozing.
- Vosita awaiting_user_confirmation qaytarsa: foydalanuvchiga nima qilmoqchi ekaningizni aniq ayting va "ha" deb
  tasdiqlashini kuting. Tasdiqdan KEYINGI xabarda confirm_pending_action chaqiring. Hech qachon o'zingiz tasdiqlamang.
- Vosita sent_to_owner qaytarsa: so'rov rahbarga yuborilganini ayting va kuting.
- Bir vaqtda faqat bitta savol bering. Javoblar qisqa va aniq bo'lsin (telefon ekranida o'qiladi).
- Ota-onaga xabar: hurmatli, qisqa, o'zbek lotin yozuvida; bola ismi, guruh va sanani yozing; hech kimni
  ayblamang, aloqaga chaqiring.
- Foydalanuvchining ruxsatidan tashqari ma'lumotni oshkor qilmang. Bir xodim haqidagi ma'lumotni (maosh, natija,
  ogohlantirish) boshqa xodimga aytmang.
- O'qituvchi yoki xodim haqida hukm chiqarmang (ishdan chiqarish, maosh): faqat faktlar va taklif bering.
- Foydalanuvchi qaysi tilda yozsa (o'zbek yoki rus), shu tilda javob bering.
"""

TEACHER_RULES = """
Siz o'qituvchi bilan gaplashyapsiz. U faqat o'z guruhlari va o'z natijalarini ko'ra oladi (my_report vositasi).
Do'stona, qo'llab-quvvatlovchi va aniq bo'ling: faktlarni ko'rsating (davomat, imtihon natijalari), keyin 2-3 ta
amaliy tavsiya bering. Boshqa o'qituvchilar, to'lovlar va moliya haqida gapirmang.
"""

VOICE_RULES = """
Foydalanuvchi OVOZLI xabar yubordi. Matn nutqdan o'girilgan, shuning uchun ism va raqamlarda xato bo'lishi mumkin:
shubha bo'lsa (ayniqsa ism, summa, sana) bajarishdan oldin so'rab aniqlang. Javobingiz ovozga aylantiriladi:
qisqa, og'zaki uslubda yozing, ro'yxat va maxsus belgilarsiz.
"""


def load_agents():
    AGENTS.clear()
    for f in sorted(AGENT_DIR.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        meta, body = {}, text
        if text.startswith("---"):
            _, head, body = text.split("---", 2)
            for line in head.strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
        name = meta.get("name", f.stem)
        AGENTS[name] = {
            "name": name,
            "title": meta.get("title", name),
            "desc": meta.get("desc", ""),
            "model": meta.get("model", "main"),
            "tools": [t.strip() for t in meta.get("tools", "all").split(",") if t.strip()],
            "prompt": body.strip(),
        }
    if "jimi" not in AGENTS:
        raise SystemExit("agents/jimi.md topilmadi.")
    log.info("agentlar: %s", ", ".join(AGENTS))


async def load_notes():
    rows = await db.q("select note from business_notes order by id desc limit 40")
    return "\n".join(f"- {r['note']}" for r in reversed(rows))[:4000]


async def load_voice():
    row = await db.one("select value from settings where key='brand_voice'")
    return row["value"] if row else ""


def build_system(ctx, agent, notes, voice_=""):
    n = now()
    parts = [agent["prompt"], COMMON_RULES]
    parts.append(f"KONTEKST\nHozir: {DAY_NAMES[n.isoweekday()]}, {n:%Y-%m-%d %H:%M} (Toshkent vaqti).\n"
                 f"Siz bilan gaplashayotgan: {ctx.staff['full_name']} ({ROLE_UZ.get(ctx.role, ctx.role)}).")
    if ctx.role == "teacher":
        parts.append(TEACHER_RULES)
    if agent["name"] == "jimi" and ctx.role != "teacher":
        specs = [f"- {a['name']}: {a['title']}. {a['desc']}" for a in AGENTS.values() if a["name"] != "jimi"]
        if specs:
            parts.append("MUTAXASSISLAR (chuqur tahlil va strategiya uchun ask_specialist orqali topshiring; oddiy "
                         "amallarni o'zingiz bajaring):\n" + "\n".join(specs))
    if ctx.was_voice:
        parts.append(VOICE_RULES)
    if ctx.readonly:
        parts.append("Hozir proaktiv rejim: siz faqat tahlil qilasiz, hech qanday amal bajarmaysiz. Takliflarni "
                     "yozib qoldiring, foydalanuvchi tasdiqlasa keyin bajariladi.")
    if voice_:
        parts.append("MARKAZ OHANGI (post, xabar va javoblar shu uslubda):\n" + voice_)
    if notes:
        parts.append("BIZNES HAQIDA ESLATMALAR (rahbar saqlagan):\n" + notes)
    return "\n\n".join(parts)


def tools_for(ctx, agent):
    defs = []
    for t in tools.TOOLS.values():
        if not tools.visible(ctx, t):
            continue
        if agent["tools"] != ["all"] and t.name not in agent["tools"] and t.name not in ALWAYS_TOOLS:
            continue
        if t.name == "ask_specialist" and agent["name"] != "jimi":
            continue
        defs.append(t.schema)
    return defs


def _text(resp):
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


async def run_agent(ctx, agent_name, messages, max_steps=8):
    agent = AGENTS.get(agent_name) or AGENTS["jimi"]
    fast = ctx.role in ("admin", "teacher") or agent["model"] == "fast"
    model = config.MODEL_FAST if fast else config.MODEL_MAIN
    effort = config.EFFORT_FAST if fast else config.EFFORT_MAIN
    system = build_system(ctx, agent, await load_notes(), await load_voice())
    tdefs = tools_for(ctx, agent)
    messages = list(messages)
    for _ in range(max_steps):
        kwargs = dict(
            model=model, max_tokens=16000, messages=messages,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": effort},
        )
        if tdefs:
            kwargs["tools"] = tdefs
        resp = await client.messages.create(**kwargs)
        if resp.stop_reason == "refusal":
            return ("Bu so'rovni bajara olmayman (model xavfsizlik cheklovi). Iltimos, boshqacharoq so'rab "
                    "ko'ring.")
        if resp.stop_reason != "tool_use":
            text = _text(resp)
            if resp.stop_reason == "max_tokens":
                text += "\n(Javob uzunligi cheklovga yetdi, davomini so'rang.)"
            return text or "Bajarildi."
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if getattr(block, "type", "") != "tool_use":
                continue
            out = await tools.dispatch(ctx, block.name, block.input)
            payload = json.dumps(out, ensure_ascii=False, default=str)
            if len(payload) > 12000:
                payload = payload[:12000] + '..."(qisqartirildi)"'
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": payload})
        messages.append({"role": "user", "content": results})
    return "Juda ko'p qadam kerak bo'ldi, vazifani kichikroq qismlarga bo'lib bering."


def _content_blocks(ctx, text):
    """Foydalanuvchi xabari: matn + rasmlar (Jimi ko'radi) + PDF + matnli fayllar."""
    blocks, notes = [], []
    for a in ctx.attachments:
        kind = a.get("kind")
        if kind == "photo" and a.get("b64"):
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": a.get("mime") or "image/jpeg",
                                                       "data": a["b64"]}})
            notes.append("[Foydalanuvchi rasm yubordi (yuqorida). Post qilinsa, publish_post uni o'zi oladi.]")
        elif kind == "pdf" and a.get("b64"):
            blocks.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                          "data": a["b64"]}})
            notes.append(f"[Foydalanuvchi PDF yubordi: {a.get('name', '')}]")
        elif kind == "text_file":
            notes.append(f"[Foydalanuvchi fayl yubordi: {a.get('name', '')}. Mazmuni:]\n{a.get('text', '')}")
        elif kind == "video":
            notes.append("[Foydalanuvchi video yubordi. edit_video bilan tahrirlash yoki publish_post bilan chiqarish mumkin.]")
        elif kind == "audio":
            notes.append("[Foydalanuvchi audio fayl yubordi (masalan dars yozuvi): analyze_lesson uchun.]")
        elif kind == "photo":
            notes.append("[Foydalanuvchi rasm yubordi.]")
    full = "\n".join([text or ""] + notes).strip() or "(bo'sh xabar)"
    return blocks + [{"type": "text", "text": full}], full


async def chat(ctx, text):
    """Bitta foydalanuvchi xabariga javob. Suhbat xotirasi bazada saqlanadi."""
    hist = await db.q("select role, content from conversations where staff_id=%s order by id desc limit 14",
                      ctx.staff_id)
    hist.reverse()
    while hist and hist[0]["role"] != "user":
        hist.pop(0)
    blocks, user_text = _content_blocks(ctx, text)
    pend = await tools.last_pending(ctx.staff_id)
    if pend:
        blocks[-1]["text"] += (f"\n[Tizim: tasdiq kutilayotgan amal bor: «{pend['summary']}». Foydalanuvchi uni tasdiqlasa "
                               "confirm_pending_action(confirm=true) chaqiring (asl vositani qayta chaqirmang). Boshqa narsa "
                               "so'rasa, shunga javob bering.]")
    messages = [{"role": r["role"], "content": r["content"]} for r in hist]
    messages.append({"role": "user", "content": blocks})
    answer = await run_agent(ctx, "jimi", messages)
    await save_turn(ctx.staff_id, user_text, answer)
    return answer


async def after_confirm(ctx, user_text, res):
    """Foydalanuvchi "ha"/"yo'q" deganda bot amalni o'zi bajardi: natijani odamga tushunarli qilib aytadi."""
    if res["status"] == "bekor_qilindi":
        answer = f"Bekor qilindi: {res['amal']}"
    else:
        out = res.get("natija") or {}
        if isinstance(out, dict) and out.get("error"):
            answer = f"Bajarilmadi: {out['error']}"
        else:
            try:
                answer = await quick(
                    "Amal bajarildi. Natijani foydalanuvchiga 2-5 qatorda, o'zbek tilida, oddiy matn bilan ayting. "
                    "Natijadagi barcha havolalar (http...) va raqamlarni AYNAN o'zgartirmasdan yozing.\n\n"
                    f"Amal: {res['amal']}\nNatija: {json.dumps(out, ensure_ascii=False, default=str)[:3000]}",
                    system="Siz Jimi, o'quv markaz yordamchisisiz.", fast=True, max_tokens=2000)
            except Exception:
                answer = ""
            links = [str(v) for v in (out.values() if isinstance(out, dict) else []) if str(v).startswith("http")]
            missing = [l for l in links if l not in (answer or "")]
            answer = (answer or f"✅ Bajarildi: {res['amal']}") + ("\n" + "\n".join(missing) if missing else "")
    await save_turn(ctx.staff_id, user_text, answer)
    return answer


async def save_turn(staff_id, user_text, answer):
    await db.ex("insert into conversations (staff_id, role, content) values (%s,'user',%s)", staff_id, user_text[:4000])
    await db.ex("insert into conversations (staff_id, role, content) values (%s,'assistant',%s)", staff_id,
                answer[:4000])


async def quick(prompt, system="", fast=True, max_tokens=4000):
    """Vositasiz oddiy so'rov (hisobotga tavsiya qo'shish uchun)."""
    model = config.MODEL_FAST if fast else config.MODEL_MAIN
    effort = config.EFFORT_FAST if fast else config.EFFORT_MAIN
    kwargs = dict(model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}],
                  output_config={"effort": effort})
    if system:
        kwargs["system"] = system
    resp = await client.messages.create(**kwargs)
    return _text(resp)


@tools.tool("ask_specialist",
            "Mutaxassis agentga murakkab topshiriq berish (strategiya, tahlil, kontent g'oyalari, moliya tahlili). "
            "Mutaxassis o'z vositalari bilan ishlaydi va natijani matn qilib qaytaradi.",
            {"agent": tools.S("Mutaxassis nomi (tizim ko'rsatmasidagi MUTAXASSISLAR ro'yxatidan)"),
             "task": tools.S("Topshiriq: kerakli kontekst bilan, aniq")},
            ["agent", "task"])
async def ask_specialist(ctx, agent, task):
    if agent not in AGENTS or agent == "jimi":
        raise ToolError("Mavjud mutaxassislar: " + ", ".join(n for n in AGENTS if n != "jimi"))
    text = await run_agent(ctx, agent, [{"role": "user", "content": task}], max_steps=6)
    return {"agent": agent, "javob": text}
