# ============================================================
#  bot.py  –  Asosiy Telegram bot
#  Railway + Supabase | ForceReply qidiruv
# ============================================================
import logging
import re
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ForceReply
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

from config import (
    BOT_TOKEN, ADMIN_ID, CHANNEL_ID, GROUP_ID,
    TRIGGER_WORDS
)
from database import (
    init_db, search_movie, add_movie, log_search,
    get_all_movies, delete_movie, movie_exists_by_code, get_stats
)
from channel_parser import parse_post

# ─── Logging ─────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s │ %(levelname)s │ %(name)s │ %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

INSTAGRAM_RE = re.compile(
    r"(https?://)?(www\.)?(instagram\.com|instagr\.am)(/[^\s]*)?",
    re.IGNORECASE
)

BOT_USERNAME = "UzKinoMov1eBot"   # @ siz


# ─── Yordamchilar ────────────────────────────────────────────

def is_instagram(text: str) -> bool:
    return bool(INSTAGRAM_RE.search(text))


def clean_query(text: str) -> str:
    t = text.strip()
    colon = re.match(r"^[\w\s]{1,15}:\s*(.+)$", t)
    if colon:
        t = colon.group(1).strip()
    for word in TRIGGER_WORDS:
        t = re.sub(
            rf"^[!/]?{re.escape(word)}\s*[:,\-]?\s*", "", t, flags=re.IGNORECASE
        ).strip()
    endings = [
        r"\s+borm[ia]\??$", r"\s+bormi\??$", r"\s+kinosi\??$",
        r"\s+filmini?\??$", r"\s+seriali?\??$", r"\?+$",
    ]
    for end in endings:
        t = re.sub(end, "", t, flags=re.IGNORECASE).strip()
    return t or text.strip()


def movie_card(m: dict) -> str:
    lines = ["🎬 <b>Kino topildi!</b>\n"]
    name = m["title"]
    if m.get("title_ru"):
        name += f" / {m['title_ru']}"
    lines.append(f"🎬 <b>Nomi:</b> {name}")
    if m.get("year"):
        lines.append(f"📅 <b>Yili:</b> {m['year']}")
    if m.get("genre"):
        lines.append(f"🇺🇿 <b>Tili:</b> {m['genre']}")
    if m.get("description"):
        lines.append(f"\n{m['description']}")
    lines.append(f"\n📥 <b>Kino olish uchun botga yuboring:</b>")
    lines.append(f"<code>{m['bot_code']}</code>")
    lines.append(f"🤖 @{BOT_USERNAME}")
    return "\n".join(lines)


def mention(user) -> str:
    if user.username:
        return f"@{user.username}"
    return f'<a href="tg://user?id={user.id}">{user.full_name or "Foydalanuvchi"}</a>'


def is_our_channel(chat) -> bool:
    cid = str(CHANNEL_ID).strip().lstrip("@")
    return (
        str(chat.id) == str(CHANNEL_ID)
        or str(getattr(chat, "username", "") or "").lstrip("@") == cid
    )


def search_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔍 Kino qidirish", callback_data="search_ask")
    ]])


# ═══════════════════════════════════════════════════════════════
#  CALLBACK: "🔍 Kino qidirish" tugmasi bosilganda
# ═══════════════════════════════════════════════════════════════

async def on_search_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Foydalanuvchi 'Kino qidirish' tugmasini bosadi.
    Bot ForceReply bilan "Kino nomini yozing" deb so'raydi.
    """
    q = update.callback_query
    await q.answer()   # yuklash animatsiyasini o'chirish

    await ctx.bot.send_message(
        chat_id=q.message.chat_id,
        text=(
            "🔍 <b>Kino nomini yozing va jo'rating!</b>\n\n"
            "Masalan: <code>Spartak</code> yoki <code>Titanic 1997</code>"
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=ForceReply(
            selective=True,           # faqat shu foydalanuvchidan javob kutadi
            input_field_placeholder="Kino nomini yozing..."
        )
    )


# ═══════════════════════════════════════════════════════════════
#  GURUH XABARLARI
# ═══════════════════════════════════════════════════════════════

async def on_user_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg  = update.message
    if not msg or not msg.text:
        return

    text = msg.text.strip()
    user = update.effective_user
    chat = update.effective_chat

    if len(text) < 2:
        return

    is_private = (chat.type == "private")

    # Agar guruhda bo'lsa va GROUP_ID sozlangan bo'lsa tekshiramiz
    if not is_private and GROUP_ID:
        gid = str(GROUP_ID).lstrip("@").lower()
        chat_uname = str(getattr(chat, "username", "") or "").lstrip("@").lower()
        chat_match = (
            str(chat.id) == str(GROUP_ID)
            or (chat_uname and chat_uname == gid)
        )
        if not chat_match:
            return

    # ── Instagram linki ──────────────────────────────────────
    if is_instagram(text):
        await _handle_instagram(ctx, msg, text, user, chat)
        return

    # Guruhda bo'lsa, qachon qidirishi kerakligini tekshiramiz:
    if not is_private:
        # 1. Botning 'Kino nomini yozing' degan so'roviga Reply bo'lsa
        is_reply_to_bot = (
            msg.reply_to_message is not None
            and msg.reply_to_message.from_user is not None
            and msg.reply_to_message.from_user.is_bot
        )
        
        # 2. Xabar kalit so'z bilan boshlangan bo'lsa (kino, film, /kino, !kino, va h.k.)
        starts_with_keyword = any(
            text.lower().startswith(word.lower()) or 
            text.lower().startswith(f"/{word.lower()}") or 
            text.lower().startswith(f"!{word.lower()}")
            for word in TRIGGER_WORDS
        )

        # Agar na botga reply bo'lsa, na kalit so'z bo'lsa — oddiy suhbat deb e'tiborsiz qoldiramiz!
        if not (is_reply_to_bot or starts_with_keyword):
            return

    # ── Kino qidirish (shartlar bajarilganda) ──
    await _handle_search(ctx, msg, text, user, chat)


async def _handle_instagram(ctx, msg, text, user, chat):
    try:
        await ctx.bot.send_message(
            ADMIN_ID,
            f"📸 <b>Instagram linki</b>\n\n"
            f"👤 {mention(user)} (<code>{user.id}</code>)\n"
            f"💬 {chat.title or chat.id}\n\n"
            f"🔗 {text}",
            parse_mode=ParseMode.HTML
        )
    except TelegramError as e:
        logger.error(f"Instagram → admin: {e}")
    try:
        await msg.reply_html(
            "📩 <b>Qabul qilindi!</b>\n⏳ Tez orada yuklab beramiz! 🙏",
            disable_web_page_preview=True
        )
    except TelegramError as e:
        logger.error(f"Instagram → user: {e}")


async def _handle_search(ctx, msg, text, user, chat):
    query   = clean_query(text)
    results = search_movie(query)

    if results:
        log_search(user.id, user.username, user.full_name, query, True)
        m = results[0]

        # Kanalga o'tish tugmasi
        keyboard = None
        if m.get("channel_msg_id") and CHANNEL_ID:
            uname = str(CHANNEL_ID).lstrip("@")
            url   = f"https://t.me/{uname}/{m['channel_msg_id']}"
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("📺 Kanalga o'tish", url=url)
            ]])

        try:
            await msg.reply_html(
                movie_card(m),
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except TelegramError as e:
            logger.error(f"Movie card: {e}")

    else:
        log_search(user.id, user.username, user.full_name, query, False)

        try:
            await msg.reply_html(
                f"🔎 <b>Qidirilmoqda...</b>\n\n"
                f"<b>«{query}»</b> hozircha bazamizda yo'q.\n"
                f"Tez orada yuklab beramiz! ⏳\n\n"
                f"📺 {CHANNEL_ID}",
                disable_web_page_preview=True
            )
        except TelegramError as e:
            logger.error(f"Not found reply: {e}")

        try:
            await ctx.bot.send_message(
                ADMIN_ID,
                f"🚨 <b>Kino topilmadi!</b>\n\n"
                f"👤 {mention(user)} (<code>{user.id}</code>)\n"
                f"💬 {chat.title or chat.id}\n"
                f"🔍 So'rov: <b>«{query}»</b>\n\n"
                f"📝 Asl xabar: <i>{text}</i>\n\n"
                f"⚠️ Kanalga post qiling!",
                parse_mode=ParseMode.HTML
            )
        except TelegramError as e:
            logger.error(f"Not found → admin: {e}")


# ═══════════════════════════════════════════════════════════════
#  KANAL POSTLARI
# ═══════════════════════════════════════════════════════════════

async def on_channel_post(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    post = update.channel_post
    if not post or not is_our_channel(update.effective_chat):
        return
    text = post.text or post.caption or ""
    if not text:
        return
    parsed = parse_post(text, message_id=post.message_id)
    if not parsed:
        return
    if movie_exists_by_code(parsed["bot_code"]):
        return
    add_movie(**{k: parsed[k] for k in
                 ["title", "bot_code", "title_ru", "title_en",
                  "year", "genre", "description", "channel_msg_id"]})
    try:
        await ctx.bot.send_message(
            ADMIN_ID,
            f"✅ <b>Yangi kino qo'shildi!</b>\n🎬 {parsed['title']}\n📥 {parsed['bot_code']}",
            parse_mode=ParseMode.HTML
        )
    except TelegramError:
        pass


# ═══════════════════════════════════════════════════════════════
#  ADMIN BUYRUQLARI
# ═══════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_html(
            "👑 <b>Admin paneli</b>\n\n"
            "/panel – Guruhga qidiruv tugmasini yuborish (PIN qiling!)\n"
            "/sync – Kanaldan barcha postlarni yuklash\n"
            "/listmovies – Kinolar ro'yxati\n"
            "/delmovie &lt;ID&gt; – Kinoni o'chirish\n"
            "/stats – Statistika"
        )
    else:
        await update.message.reply_html(
            f"👋 <b>Salom!</b>\nGuruhda kino qidiring!\n📺 {CHANNEL_ID}"
        )


async def cmd_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Admin: /panel – guruhga yuboring va PIN qiling.
    Foydalanuvchilar shu tugma orqali kino qidiradi.
    """
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_html(
        "🎬 <b>Kino qidirish</b>\n\n"
        "Quyidagi tugmani bosing, kino nomini yozing\n"
        "va <b>Jo'ratish</b> tugmasini bosing! 👇",
        reply_markup=search_button()
    )


async def cmd_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    from config import API_ID, API_HASH
    if not API_ID or not API_HASH:
        await update.message.reply_html(
            "❌ API_ID va API_HASH kerak!\nmy.telegram.org/apps dan oling."
        )
        return
    msg = await update.message.reply_html(f"⏳ <b>Sinxronizatsiya...</b>\n📺 {CHANNEL_ID}")
    try:
        from telethon import TelegramClient
        saved = skipped = errors = total = 0
        async with TelegramClient("sync_session", API_ID, API_HASH) as client:
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
                                 ["title", "bot_code", "title_ru", "title_en",
                                  "year", "genre", "description", "channel_msg_id"]})
                    saved += 1
                except Exception as e:
                    errors += 1
                    logger.error(f"#{message.id}: {e}")
                if total % 100 == 0:
                    try:
                        await msg.edit_text(f"⏳ O'qildi: {total} | Saqlandi: {saved}")
                    except Exception:
                        pass
        await msg.edit_text(
            f"✅ <b>Tugadi!</b>\n\n"
            f"📦 O'qildi  : <b>{total}</b>\n"
            f"💾 Saqlandi : <b>{saved}</b>\n"
            f"⏭ O'tkazildi: <b>{skipped}</b>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await msg.edit_text(f"❌ Xato:\n<code>{e}</code>", parse_mode=ParseMode.HTML)


async def cmd_listmovies(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    movies = get_all_movies()
    if not movies:
        await update.message.reply_text("📭 Bazada kinolar yo'q.")
        return
    text = f"🎬 <b>Jami {len(movies)} ta kino:</b>\n\n"
    for m in movies[:20]:
        yr = f" ({m['year']})" if m.get("year") else ""
        text += f"<code>{m['id']:>4}</code>  {m['title']}{yr}  → <code>{m['bot_code']}</code>\n"
    if len(movies) > 20:
        text += f"\n... va yana {len(movies)-20} ta."
    await update.message.reply_html(text)


async def cmd_delmovie(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = ctx.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Format: /delmovie <ID>")
        return
    deleted = delete_movie(int(args[0]))
    await update.message.reply_text(
        f"✅ #{args[0]} o'chirildi." if deleted else f"❌ Topilmadi."
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    s = get_stats()
    rate = f"{s['found_count']/s['total_searches']*100:.1f}%" if s["total_searches"] else "—"
    await update.message.reply_html(
        f"📊 <b>Statistika</b>\n\n"
        f"🎬 Kinolar: <b>{s['total_movies']}</b>\n"
        f"🔍 Qidiruvlar: <b>{s['total_searches']}</b>\n"
        f"✅ Topildi: <b>{s['found_count']}</b>\n"
        f"❌ Topilmadi: <b>{s['not_found']}</b>\n"
        f"📈 Muvaffaqiyat: <b>{rate}</b>"
    )


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Bot xatosi: {ctx.error}", exc_info=ctx.error)


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    logger.info("🤖 Bot ishga tushmoqda...")
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # Buyruqlar
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("panel",      cmd_panel))
    app.add_handler(CommandHandler("sync",       cmd_sync))
    app.add_handler(CommandHandler("listmovies", cmd_listmovies))
    app.add_handler(CommandHandler("delmovie",   cmd_delmovie))
    app.add_handler(CommandHandler("stats",      cmd_stats))

    # Tugma bosilganda
    app.add_handler(CallbackQueryHandler(on_search_button, pattern="^search_ask$"))

    # Kanal postlari
    app.add_handler(MessageHandler(
        filters.ChatType.CHANNEL & filters.TEXT,
        on_channel_post
    ))

    # Guruh va shaxsiy chat xabarlari (kino qidirish va instagram)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        on_user_message
    ))

    app.add_error_handler(on_error)

    logger.info("✅ Polling boshlandi.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
