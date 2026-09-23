# ============================================================
#  config.py  –  .env faylidan sozlamalarni yuklash
# ============================================================
import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ─────────────────────────────────────────────────
BOT_TOKEN  = os.environ["BOT_TOKEN"]
ADMIN_ID   = int(os.environ["ADMIN_ID"])
CHANNEL_ID = os.environ["CHANNEL_ID"]
_gid = os.environ.get("GROUP_ID", "").strip()
if _gid.lstrip("-").isdigit():
    GROUP_ID = int(_gid)
elif _gid:
    GROUP_ID = _gid
else:
    GROUP_ID = None

# ── Telethon ─────────────────────────────────────────────────
API_ID   = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")

# ── Supabase ─────────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]   # secret key ishlatamiz

# ── Qidiruv ──────────────────────────────────────────────────
TRIGGER_WORDS = [
    "kino", "film", "movie", "serial", "qidir",
    "🎬", "🎥", "📽", "🍿",
]
MIN_QUERY_LENGTH = 2
