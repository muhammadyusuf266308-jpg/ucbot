# ============================================================
#  sync_channel.py  –  Mavjud kanal postlarini bir marta yuklash
#  (Railway da emas, lokal terminalda ishlatiladi)
# ============================================================
"""
Ishlatish:
    python sync_channel.py

.env da API_ID, API_HASH, CHANNEL_ID, DATABASE_URL to'ldirilgan bo'lsin.
"""
import asyncio
import logging
import sys

logging.basicConfig(
    format="%(asctime)s │ %(levelname)s │ %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def sync_all():
    from config import API_ID, API_HASH, CHANNEL_ID
    from database import init_db, add_movie, movie_exists_by_code
    from channel_parser import parse_post

    if not API_ID or not API_HASH:
        logger.error(
            "❌ .env da API_ID va API_HASH to'ldirilmagan!\n"
            "   https://my.telegram.org/apps"
        )
        sys.exit(1)

    try:
        from telethon import TelegramClient
    except ImportError:
        logger.error("❌ pip install telethon")
        sys.exit(1)

    init_db()

    client = TelegramClient("sync_session", API_ID, API_HASH)
    await client.start()
    logger.info(f"✅ Ulandi. '{CHANNEL_ID}' o'qilmoqda...")

    total = saved = skipped = errors = 0

    try:
        async for message in client.iter_messages(CHANNEL_ID, reverse=True):
            total += 1
            text = message.text or message.message or ""
            if not text:
                skipped += 1
                continue

            parsed = parse_post(text, message_id=message.id)
            if not parsed:
                skipped += 1
                continue

            if movie_exists_by_code(parsed["bot_code"]):
                skipped += 1
                continue

            try:
                add_movie(**{k: parsed[k] for k in
                             ["title","bot_code","title_ru","title_en",
                              "year","genre","description","channel_msg_id"]})
                saved += 1
            except Exception as e:
                errors += 1
                logger.error(f"#{message.id}: {e}")

            if total % 50 == 0:
                logger.info(f"  Progress: {total} o'qildi, {saved} saqlandi")
    finally:
        await client.disconnect()

    print(f"""
{'='*50}
✅ TUGADI
{'='*50}
📦 O'qildi  : {total}
💾 Saqlandi : {saved}
⏭ O'tkazildi: {skipped}
❌ Xatolar  : {errors}
{'='*50}""")


if __name__ == "__main__":
    asyncio.run(sync_all())
