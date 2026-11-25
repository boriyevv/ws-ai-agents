"""Sozlamalar: hammasi .env fayldan o'qiladi."""
import os
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv o'rnatilmagan bo'lsa ham ishlayversin
    pass


def _get(name, default=None, required=False):
    val = os.getenv(name, default)
    if required and not val:
        raise SystemExit(f"XATO: .env faylda {name} to'ldirilmagan. README.md ni qarang.")
    return val


# ---- Majburiy ----
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN", required=True)
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY", required=True)
DATABASE_URL = _get("DATABASE_URL", required=True)
OWNER_TELEGRAM_ID = int(_get("OWNER_TELEGRAM_ID", required=True))
OWNER_NAME = _get("OWNER_NAME", "Rahbar")

# ---- Modellar (arzon va tez / kuchli) ----
MODEL_MAIN = _get("MODEL_MAIN", "claude-sonnet-5-5")   # egasi va managerlar uchun
MODEL_FAST = _get("MODEL_FAST", "claude-haiku-5-5")    # adminlar, o'qituvchilar, hisobotlar uchun
EFFORT_MAIN = _get("EFFORT_MAIN", "medium")
EFFORT_FAST = _get("EFFORT_FAST", "low")

# ---- Vaqt ----
TZ = ZoneInfo(_get("TIMEZONE", "Asia/Tashkent"))
MORNING_HOUR = int(_get("MORNING_HOUR", "8"))

# ---- Ovoz (ixtiyoriy) ----
STT_PROVIDER = _get("STT_PROVIDER", "elevenlabs")       # elevenlabs | openai
ELEVENLABS_API_KEY = _get("ELEVENLABS_API_KEY")
ELEVENLABS_STT_MODEL = _get("ELEVENLABS_STT_MODEL", "scribe_v1")
STT_LANGUAGE = _get("STT_LANGUAGE", "uzb")
OPENAI_API_KEY = _get("OPENAI_API_KEY")
OPENAI_STT_MODEL = _get("OPENAI_STT_MODEL", "gpt-4o-transcribe")
TTS_VOICE = _get("TTS_VOICE", "uz-UZ-SardorNeural")      # ayol ovozi: uz-UZ-MadinaNeural
VOICE_REPLIES = _get("VOICE_REPLIES", "true").lower() == "true"

# ---- Kontent (ixtiyoriy) ----
TELEGRAM_CHANNEL_ID = _get("TELEGRAM_CHANNEL_ID")        # masalan @markaz_kanal yoki -100123...
IG_USER_ID = _get("IG_USER_ID")
META_API_VERSION = _get("META_API_VERSION", "v27.0")    # Graph API Explorer'dagi joriy versiya
IG_ACCESS_TOKEN = _get("IG_ACCESS_TOKEN")
SUPABASE_URL = _get("SUPABASE_URL")                      # rasm yuklash uchun
SUPABASE_SERVICE_KEY = _get("SUPABASE_SERVICE_KEY")
SUPABASE_BUCKET = _get("SUPABASE_BUCKET", "media")

CENTER_PHONE = _get("CENTER_PHONE", "")
CENTER_NAME = _get("CENTER_NAME", "Web Street IT Academy")

# ---- Marketing integratsiyalari (ixtiyoriy) ----
META_AD_ACCOUNT_ID = _get("META_AD_ACCOUNT_ID")          # act_123... (Meta Ads Manager)
META_ACCESS_TOKEN = _get("META_ACCESS_TOKEN")            # bo'sh bo'lsa IG_ACCESS_TOKEN ishlatiladi
META_CURRENCY = _get("META_CURRENCY", "USD")             # reklama hisobi valyutasi (USD yoki UZS)
N8N_WEBHOOK_URL = _get("N8N_WEBHOOK_URL")                # YouTube Shorts / TikTok uchun n8n yoki Make webhook
N8N_WEBHOOK_SECRET = _get("N8N_WEBHOOK_SECRET", "")
HOOK_SECRET = _get("HOOK_SECRET", "")                    # n8n/Make dan lid qabul qilish uchun maxfiy kalit
TELEGRAM_DISCUSSION_ID = _get("TELEGRAM_DISCUSSION_ID")  # kanal izohlari guruhi (-100...)

# ---- Kompyuter paneli (brauzerda ochiladi) ----
PANEL_ENABLED = _get("PANEL_ENABLED", "true").lower() == "true"
_cloud_port = os.getenv("PORT")                          # Railway kabi hostinglar o'zi beradi
PANEL_PORT = int(_cloud_port or _get("PANEL_PORT") or "8080")   # hosting PORT bersa, o'sha ustun
PANEL_HOST = _get("PANEL_HOST", "0.0.0.0" if _cloud_port else "127.0.0.1")
PANEL_URL = (_get("PANEL_URL") or f"http://localhost:{PANEL_PORT}").rstrip("/")

# Bot ishga tushganda to'ldiriladi
BOT_USERNAME = _get("BOT_USERNAME", "")
