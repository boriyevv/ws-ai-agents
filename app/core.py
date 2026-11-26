"""Umumiy yordamchilar: kontekst, ism qidirish, to'lov tsikli mantig'i."""
import difflib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import config

DAY_NAMES = {1: "Dushanba", 2: "Seshanba", 3: "Chorshanba", 4: "Payshanba",
             5: "Juma", 6: "Shanba", 7: "Yakshanba"}
DAY_SHORT = {1: "Du", 2: "Se", 3: "Chor", 4: "Pay", 5: "Juma", 6: "Shanba", 7: "Yak"}
ROLE_UZ = {"owner": "Rahbar (egasi)", "manager": "Manager", "admin": "Administrator",
           "teacher": "O'qituvchi"}


class ToolError(Exception):
    """Vosita xatosi: matni agentga ko'rsatiladi."""


class Runtime:
    bot = None        # Telegram bot, ishga tushganda to'ldiriladi
    web_server = None # panel serveri
    locks: dict = {}  # bir xodimning xabarlari navbat bilan ishlanadi (Telegram va panel uchun umumiy)

    def lock(self, key):
        import asyncio
        return self.locks.setdefault(key, asyncio.Lock())


rt = Runtime()


@dataclass
class Ctx:
    staff: dict
    branch_ids: list | None          # None = hamma filial (egasi)
    perms: dict                      # {harakat: allow|needs_owner_approval|deny}
    msg_time: datetime
    chat_id: int | None = None
    bypass: bool = False             # egasi tasdiqlagan amal
    confirmed: bool = False          # foydalanuvchi "ha" degan
    readonly: bool = False           # proaktiv rejim: faqat o'qish
    was_voice: bool = False
    attachments: list = field(default_factory=list)

    @property
    def role(self):
        return self.staff["role"]

    @property
    def staff_id(self):
        return self.staff["id"]

    def level(self, action):
        if self.role == "owner":
            return "allow"
        return self.perms.get(action, "deny")


# ---------- vaqt ----------
def now():
    return datetime.now(config.TZ)


def today():
    return now().date()


def parse_date(s, default=None):
    """'2026-11-25', '25.11.2026', '25.11' ni qabul qiladi."""
    if not s:
        return default
    if isinstance(s, date):
        return s
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d.%m.%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})", s)
    if m:
        return date(today().year, int(m.group(2)), int(m.group(1)))
    raise ToolError(f"Sanani tushunmadim: {s} (format: 2026-11-25)")


async def send_tg(chat_id, text):
    """Uzun xabarlarni bo'lib yuboradi (oddiy matn, markdown'siz)."""
    text = text or "..."
    while text:
        chunk, text = text[:3900], text[3900:]
        await rt.bot.send_message(chat_id=chat_id, text=chunk)


def invite_link(prefix, code):
    return f"https://t.me/{config.BOT_USERNAME}?start={prefix}_{code}"


# ---------- ism qidirish ----------
def norm(s):
    s = (s or "").lower()
    s = re.sub(r"[’‘ʻʼ`´']", "", s)        # o'ktam == oktam
    return re.sub(r"\s+", " ", s).strip()


def fuzzy(query, items, limit=5, min_score=0.62):
    """items: [(id, name)] -> [(score, id, name)] eng yaxshilari birinchi.

    Ball darajalari: 1.0 aynan bir xil; 0.97 so'rovdagi har bir so'z ismda to'liq so'z sifatida bor
    ("Vali" -> "Vali Aliyev"); 0.84 so'zlar ism so'zlarining boshlanishi ("Ali Val" -> "Ali Valiyev");
    <=0.8 yozuv xatosi bilan o'xshash ("Alii" -> "Ali")."""
    qn = norm(query)
    if not qn:
        return []
    qtokens = qn.split()
    out = []
    for iid, name in items:
        nn = norm(name)
        ntokens = nn.split()
        if not ntokens:
            continue
        if qn == nn or sorted(qtokens) == sorted(ntokens):
            score = 1.0
        elif all(qt in ntokens for qt in qtokens):
            score = 0.97
        elif all(any(nt.startswith(qt) for nt in ntokens) for qt in qtokens):
            score = 0.84
        else:
            ratios = [max(difflib.SequenceMatcher(None, qt, nt).ratio() for nt in ntokens) for qt in qtokens]
            score = 0.8 * sum(ratios) / len(ratios) if min(ratios) >= 0.8 else 0
            score = max(score, difflib.SequenceMatcher(None, qn, nn).ratio() * 0.78)
        if score >= min_score:
            out.append((score, iid, name))
    out.sort(key=lambda x: -x[0])
    return out[:limit]


# ---------- dars va to'lov tsikli ----------
def lesson_dates(start, days, n):
    """start dan boshlab guruhning n ta dars sanasi (days: 1=Du..7=Yak)."""
    out, d = [], start
    while len(out) < n and (d - start).days < 400:
        if d.isoweekday() in days:
            out.append(d)
        d += timedelta(days=1)
    return out


def payment_state(cycle_start, days, paid, unpaid_cycles, on):
    """paid | not_yet | window | overdue

    To'lov oynasi: tsiklning 3-darsidan 6-darsigacha."""
    if unpaid_cycles and unpaid_cycles > 0:
        return "overdue"
    if paid or (unpaid_cycles and unpaid_cycles < 0):
        return "paid"
    if not cycle_start or not days:
        return "not_yet"
    ls = lesson_dates(cycle_start, list(days), 6)
    if len(ls) < 6:
        return "not_yet"
    if on < ls[2]:
        return "not_yet"
    if on <= ls[5]:
        return "window"
    return "overdue"


def roll_forward(cycle_start, paid, unpaid, on, length=30):
    """30 kunlik tsikl tugagan bo'lsa, yangi tsiklga o'tkazadi.
    Qaytaradi: (cycle_start, cycle_paid, unpaid_cycles)"""
    while cycle_start and on >= cycle_start + timedelta(days=length):
        if paid:
            if unpaid < 0:          # oldindan to'langan tsikl ishlatildi
                unpaid += 1
                paid = True
            else:
                paid = False
        else:
            unpaid += 1             # to'lanmagan tsikl qarzga aylandi
            paid = False
        cycle_start += timedelta(days=length)
    return cycle_start, paid, unpaid


def apply_payment(paid, unpaid):
    """To'lov kelganda holatni yangilaydi. Qaytaradi: (cycle_paid, unpaid_cycles)"""
    if unpaid > 0:
        return paid, unpaid - 1
    if not paid:
        return True, unpaid
    return paid, unpaid - 1        # oldindan to'lov


def fmt_money(x):
    try:
        return f"{int(x):,}".replace(",", " ") + " so'm"
    except (TypeError, ValueError):
        return "-"
