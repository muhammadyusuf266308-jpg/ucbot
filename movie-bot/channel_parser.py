# ============================================================
#  channel_parser.py  –  UzKinoMoviie kanal post formati
# ============================================================
"""
Kanal post formati:

🎬 Nomi: Spartak: Arena xudolari (barcha qismi)
🇺🇿 Tili: O'zbek tilida
📺 Sifati: 1080p
📅 Yili: 2011
🇺🇸 Davlat: AQSH
⭐ Reyting: IMDb: 8.5 KinoPoisk: 8.3

Kod:237

🤖 Botimiz: @UzKinoMov1eBot
📢 Kanalimiz: https://t.me/UzKinoMoviie
"""
import re
import logging

logger = logging.getLogger(__name__)

# Yil aniqlovchi: 1900-2099
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

# Kod aniqlovchi: "Kod:237" yoki "Kod: 237" yoki "kod:237"
_KOD_RE  = re.compile(r"(?i)kod\s*[:\-]?\s*(\d+)")

# Emoji + "Kalit:" formati
_FIELD_RE = re.compile(
    r"^(?:[\U00010000-\U0010ffff\u2600-\u26FF\u2700-\u27BF"
    r"\U0001F300-\U0001F9FF\U0001FA00-\U0001FA9F"
    r"\U00002702-\U000027B0\U0001F1E0-\U0001F1FF]*\s*)?"
    r"([^:\n]{1,30}):\s*(.+)$"
)


def parse_post(text: str, message_id: int = None) -> dict | None:
    """
    Kanal postini tahlil qiladi.
    Qaytaradi: dict yoki None.
    """
    if not text or len(text.strip()) < 3:
        return None

    result = {
        "title":          None,
        "title_ru":       None,
        "title_en":       None,
        "year":           None,
        "genre":          None,   # Tili
        "description":    None,   # Sifat + Davlat + Reyting
        "bot_code":       None,   # Kod:237
        "channel_msg_id": message_id,
    }

    extra = {}   # Qo'shimcha maydonlar uchun
    first_plain = None

    lines = [l.strip() for l in text.strip().splitlines()]

    for line in lines:
        if not line:
            continue

        # ── Kod:237 aniqlovchi ───────────────────────────────
        kod_m = _KOD_RE.search(line)
        if kod_m and len(line) < 30:   # faqat qisqa qatorlarda
            result["bot_code"] = f"Kod:{kod_m.group(1)}"
            continue

        # ── Bot/Kanal linkini o'tkazib yuborish ─────────────
        if any(skip in line.lower() for skip in
               ["botimiz", "kanalimiz", "t.me/", "http", "@uzkinomov"]):
            continue

        # ── "Kalit: Qiymat" formatini tahlil qilish ─────────
        m = _FIELD_RE.match(line)
        if m:
            raw_key = m.group(1).strip()
            val     = m.group(2).strip()
            key     = _normalize_key(raw_key)

            if key in ("nomi", "title", "kino"):
                _set(result, "title", val)
            elif key in ("tili", "til", "language", "lang"):
                _set(result, "genre", val)          # Til → genre
            elif key in ("yili", "yil", "year"):
                yr = _YEAR_RE.search(val)
                if yr:
                    result["year"] = int(yr.group())
            elif key in ("sifati", "sifat", "quality"):
                extra["sifat"] = val
            elif key in ("davlat", "country", "mamlakat"):
                extra["davlat"] = val
            elif key in ("reyting", "rating", "imdb"):
                extra["reyting"] = val
            elif key in ("janr", "genre"):
                extra["janr"] = val
            # Qolganlarni e'tiborsiz qoldirish
            continue

        # ── Oddiy qator ─────────────────────────────────────
        skip = (
            line.startswith("http")
            or line.startswith("@")
            or re.match(r"^\d+$", line)
        )
        if not skip and first_plain is None:
            first_plain = line

    # ── Nomni aniqlash ───────────────────────────────────────
    if not result["title"]:
        if first_plain:
            result["title"] = first_plain
        elif message_id:
            result["title"] = f"Kino #{message_id}"
        else:
            return None

    # ── Tavsif: Sifat + Davlat + Reyting ────────────────────
    desc_parts = []
    if extra.get("sifat"):
        desc_parts.append(f"📺 Sifati: {extra['sifat']}")
    if extra.get("davlat"):
        desc_parts.append(f"🌍 Davlat: {extra['davlat']}")
    if extra.get("janr"):
        desc_parts.append(f"🎭 Janr: {extra['janr']}")
    if extra.get("reyting"):
        desc_parts.append(f"⭐ Reyting: {extra['reyting']}")
    if desc_parts:
        result["description"] = "\n".join(desc_parts)

    # ── Bot kodi avtomatik ───────────────────────────────────
    if not result["bot_code"]:
        if message_id:
            result["bot_code"] = f"Kod:{message_id}"
        else:
            return None

    logger.info(
        f"✅ Post #{message_id}: '{result['title']}' → {result['bot_code']}"
    )
    return result


def _normalize_key(raw: str) -> str:
    """Emoji va bo'sh joylarni olib, kichik harfga o'tkazadi."""
    # Emoji lar va unicode belgilarini olib tashlash
    clean = re.sub(
        r"[\U00010000-\U0010ffff\u2600-\u26FF\u2700-\u27BF"
        r"\U0001F300-\U0001F9FF\U0001FA00-\U0001FA9F"
        r"\U00002702-\U000027B0\U0001F1E0-\U0001F1FF]+",
        "", raw
    ).strip().lower()
    return clean


def _set(d: dict, key: str, val: str):
    if not d.get(key):
        d[key] = val.strip()
