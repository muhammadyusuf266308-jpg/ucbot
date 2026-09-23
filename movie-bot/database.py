# ============================================================
#  database.py  –  Supabase Python client orqali ishlash
# ============================================================
import logging
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)

# ─── Supabase client ─────────────────────────────────────────
_client: Client = None

def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ─── Jadvallarni yaratish ────────────────────────────────────

def init_db():
    """
    Supabase da jadvallar SQL orqali yaratiladi.
    Bu funksiya ulanishni tekshiradi va loglaydi.
    Jadvallarni Supabase SQL Editor da bir marta yaratish kerak.
    """
    try:
        client = get_client()
        # Ulanishni tekshirish
        client.table("movies").select("id").limit(1).execute()
        logger.info("✅ Supabase ulanish muvaffaqiyatli.")
    except Exception as e:
        err = str(e)
        if "relation" in err and "does not exist" in err:
            logger.warning(
                "⚠️ 'movies' jadvali topilmadi!\n"
                "   Supabase SQL Editor da quyidagi SQL ni ishga tushiring:\n"
                "   (D:\\movie-bot\\supabase_schema.sql fayli)"
            )
        else:
            logger.error(f"❌ Supabase ulanish xatosi: {e}")
            raise


# ─── Kino qidirish ───────────────────────────────────────────

def search_movie(query: str) -> list[dict]:
    """
    Kino qidiradi. title, title_ru, title_en maydonlarida qidiradi.
    Supabase ilike (case-insensitive like) ishlatadi.
    """
    client = get_client()
    q = f"%{query.strip()}%"

    try:
        # title bo'yicha qidirish
        res = (
            client.table("movies")
            .select("*")
            .ilike("title", q)
            .order("year", desc=True)
            .limit(5)
            .execute()
        )
        results = res.data or []

        # title_ru bo'yicha qo'shimcha qidirish
        if len(results) < 3:
            res2 = (
                client.table("movies")
                .select("*")
                .ilike("title_ru", q)
                .order("year", desc=True)
                .limit(5)
                .execute()
            )
            for r in (res2.data or []):
                if not any(x["id"] == r["id"] for x in results):
                    results.append(r)

        # title_en bo'yicha qo'shimcha qidirish
        if len(results) < 3:
            res3 = (
                client.table("movies")
                .select("*")
                .ilike("title_en", q)
                .order("year", desc=True)
                .limit(5)
                .execute()
            )
            for r in (res3.data or []):
                if not any(x["id"] == r["id"] for x in results):
                    results.append(r)

        return results[:5]

    except Exception as e:
        logger.error(f"Qidirish xatosi: {e}")
        return []


# ─── Kino qo'shish ───────────────────────────────────────────

def add_movie(title: str, bot_code: str,
              title_ru: str = None, title_en: str = None,
              year: int = None, genre: str = None,
              description: str = None,
              channel_msg_id: int = None) -> int:
    """
    Yangi kino qo'shadi yoki mavjud bo'lsa yangilaydi.
    Qaytaradi: kino ID.
    """
    client = get_client()

    data = {
        "title":          title,
        "title_ru":       title_ru,
        "title_en":       title_en,
        "year":           year,
        "genre":          genre,
        "description":    description,
        "bot_code":       bot_code,
        "channel_msg_id": channel_msg_id,
    }

    try:
        res = (
            client.table("movies")
            .upsert(data, on_conflict="bot_code")
            .execute()
        )
        new_id = res.data[0]["id"] if res.data else 0
        logger.info(f"🎬 Saqlandi: '{title}' → {bot_code} (ID={new_id})")
        return new_id
    except Exception as e:
        logger.error(f"add_movie xatosi: {e}")
        raise


# ─── Kino mavjudligini tekshirish ────────────────────────────

def movie_exists_by_code(bot_code: str) -> bool:
    """Berilgan bot kodi bilan kino bazada borligini tekshiradi."""
    client = get_client()
    try:
        res = (
            client.table("movies")
            .select("id")
            .eq("bot_code", bot_code)
            .limit(1)
            .execute()
        )
        return len(res.data) > 0
    except Exception as e:
        logger.error(f"movie_exists xatosi: {e}")
        return False


# ─── Qidiruv logi ────────────────────────────────────────────

def log_search(user_id: int, username: str, full_name: str,
               query: str, found: bool):
    """Qidiruv natijasini logga yozadi."""
    client = get_client()
    try:
        client.table("search_log").insert({
            "user_id":   user_id,
            "username":  username,
            "full_name": full_name,
            "query":     query,
            "found":     found,
        }).execute()
    except Exception as e:
        logger.error(f"log_search xatosi: {e}")


# ─── Barcha kinolar ──────────────────────────────────────────

def get_all_movies() -> list[dict]:
    """Barcha kinolarni qaytaradi."""
    client = get_client()
    try:
        res = (
            client.table("movies")
            .select("id, title, title_ru, year, genre, bot_code")
            .order("id", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"get_all_movies xatosi: {e}")
        return []


# ─── Kino o'chirish ──────────────────────────────────────────

def delete_movie(movie_id: int) -> bool:
    """Kinoni o'chiradi."""
    client = get_client()
    try:
        res = (
            client.table("movies")
            .delete()
            .eq("id", movie_id)
            .execute()
        )
        return len(res.data) > 0
    except Exception as e:
        logger.error(f"delete_movie xatosi: {e}")
        return False


# ─── Statistika ──────────────────────────────────────────────

def get_stats() -> dict:
    """Bot statistikasini qaytaradi."""
    client = get_client()
    try:
        total_movies   = client.table("movies").select("id", count="exact").execute().count or 0
        total_searches = client.table("search_log").select("id", count="exact").execute().count or 0
        found_count    = client.table("search_log").select("id", count="exact").eq("found", True).execute().count or 0
        not_found      = client.table("search_log").select("id", count="exact").eq("found", False).execute().count or 0
    except Exception as e:
        logger.error(f"get_stats xatosi: {e}")
        total_movies = total_searches = found_count = not_found = 0

    return {
        "total_movies":   total_movies,
        "total_searches": total_searches,
        "found_count":    found_count,
        "not_found":      not_found,
    }
