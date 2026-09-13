import asyncio
import html
import logging

from decouple import config, Csv
from supabase import create_client, Client

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, ErrorEvent, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)

# ============================================================
#                        SOZLAMALAR
# ============================================================
BOT_TOKEN = config("BOT_TOKEN")
SUPABASE_URL = config("SUPABASE_URL")
SUPABASE_KEY = config("SUPABASE_KEY")
# Botni birinchi marta ishga tushirganda o'zingizni admin qilib olish uchun
# .env fayliga: SUPER_ADMIN_IDS=123456789,987654321
SUPER_ADMIN_IDS = set(config("SUPER_ADMIN_IDS", default="", cast=Csv(int)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("uc-bot")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


async def a_execute(query):
    """
    Supabase-py so'rovini ALOHIDA THREADDA bajaradi.
    Supabase kutubxonasi sinxron (blocking) bo'lgani uchun, agar uni to'g'ridan-to'g'ri
    chaqirsak, bitta so'rov butun botni (barcha foydalanuvchilar uchun) to'xtatib turadi.
    asyncio.to_thread yordamida bot bir vaqtning o'zida ko'plab foydalanuvchilarga
    tezkor javob bera oladi - bu botning tezligi uchun ENG MUHIM o'zgarish.
    """
    return await asyncio.to_thread(query.execute)


# ============================================================
#              XOTIRADAGI KESH (tezlik uchun)
# ============================================================
# Narxlar, karta raqami, adminlar va kanallar har bir xabarda bazadan
# qayta o'qilmaydi - xotirada saqlanadi va faqat o'zgarganda yangilanadi.
CACHE = {
    "uc_prices": [],
    "card_number": "Kiritilmagan",
    "admins": set(),
    "channels": [],
    "referral_bonus": 0,
}


async def refresh_prices():
    res = await a_execute(supabase.table("uc_prices").select("*").order("uc_amount"))
    CACHE["uc_prices"] = res.data or []


async def refresh_card():
    res = await a_execute(supabase.table("settings").select("value").eq("key", "card_number"))
    CACHE["card_number"] = res.data[0]["value"] if res.data else "Kiritilmagan"


async def refresh_admins():
    res = await a_execute(supabase.table("users").select("telegram_id").eq("is_admin", True))
    CACHE["admins"] = {row["telegram_id"] for row in (res.data or [])}
    CACHE["admins"].update(SUPER_ADMIN_IDS)


async def refresh_channels():
    res = await a_execute(supabase.table("mandatory_channels").select("*"))
    CACHE["channels"] = res.data or []


async def refresh_referral_bonus():
    res = await a_execute(supabase.table("settings").select("value").eq("key", "referral_bonus"))
    try:
        CACHE["referral_bonus"] = int(res.data[0]["value"]) if res.data else 0
    except (ValueError, TypeError):
        CACHE["referral_bonus"] = 0


async def refresh_all_cache():
    await asyncio.gather(
        refresh_prices(), refresh_card(), refresh_admins(),
        refresh_channels(), refresh_referral_bonus(),
    )


async def periodic_cache_refresh():
    while True:
        await asyncio.sleep(300)  # har 5 daqiqada
        try:
            await refresh_all_cache()
        except Exception as e:
            log.warning(f"Kesh yangilashda xato: {e}")


def is_admin(user_id: int) -> bool:
    return user_id in CACHE["admins"]


def fmt(amount) -> str:
    try:
        return f"{int(amount):,}".replace(",", " ")
    except (ValueError, TypeError):
        return str(amount)


def user_display(tg_user) -> str:
    uname = f"@{tg_user.username}" if tg_user.username else "yo'q"
    return (
        f"👤 <b>{html.escape(tg_user.full_name)}</b>\n"
        f"🔗 Username: {uname}\n"
        f"🆔 ID: <code>{tg_user.id}</code>"
    )


# ============================================================
#                    HOLATLAR (FSM)
# ============================================================
class PurchaseState(StatesGroup):
    waiting_for_pubg_id = State()


class PaymentState(StatesGroup):
    waiting_for_receipt = State()


class AdminState(StatesGroup):
    waiting_for_deposit_amount = State()
    waiting_for_new_price = State()
    waiting_for_new_uc_amount = State()
    waiting_for_new_uc_price_val = State()
    waiting_for_card = State()
    waiting_for_channel_id = State()
    waiting_for_channel_url = State()
    waiting_for_channel_name = State()
    waiting_for_user_search = State()
    waiting_for_balance_adjust = State()
    waiting_for_broadcast_message = State()


# ============================================================
#                     KLAVIATURALAR
# ============================================================
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 UC Xarid qilish"), KeyboardButton(text="💰 Balans")],
            [KeyboardButton(text="💳 Balansni to'ldirish"), KeyboardButton(text="📜 Buyurtmalarim")],
        ],
        resize_keyboard=True,
    )


def cancel_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Bekor qilish")]], resize_keyboard=True)


def admin_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Narxlarni tahrirlash", callback_data="adm_prices"),
         InlineKeyboardButton(text="➕ Yangi UC paket", callback_data="adm_add_uc")],
        [InlineKeyboardButton(text="💳 Karta raqami", callback_data="adm_card"),
         InlineKeyboardButton(text="📢 Majburiy kanallar", callback_data="adm_channels")],
        [InlineKeyboardButton(text="👤 Foydalanuvchi balansi", callback_data="adm_user_balance"),
         InlineKeyboardButton(text="📣 Xabar yuborish", callback_data="adm_broadcast")],
        [InlineKeyboardButton(text="👮 Adminlar", callback_data="adm_admins"),
         InlineKeyboardButton(text="📊 Statistika", callback_data="adm_stats")],
    ])


# ============================================================
#                  YORDAMCHI FUNKSIYALAR
# ============================================================
async def check_mandatory_subs(user_id: int):
    channels = CACHE["channels"]
    if not channels:
        return True, None

    buttons = []
    all_tg_ok = True
    for ch in channels:
        if ch["platform"] == "telegram":
            try:
                member = await bot.get_chat_member(chat_id=ch["chat_id"], user_id=user_id)
                if member.status not in ("member", "administrator", "creator"):
                    all_tg_ok = False
                    buttons.append([InlineKeyboardButton(text=f"📢 {ch['name']}", url=ch["url"])])
            except Exception as e:
                log.warning(f"Kanal tekshirishda xato ({ch['chat_id']}): {e}")
        else:
            icon = "🔴" if ch["platform"] == "youtube" else "📸"
            buttons.append([InlineKeyboardButton(text=f"{icon} {ch['name']}", url=ch["url"])])

    if not all_tg_ok:
        buttons.append([InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data="check_sub")])
        return False, InlineKeyboardMarkup(inline_keyboard=buttons)

    return True, None


async def get_user(user_id: int):
    res = await a_execute(supabase.table("users").select("*").eq("telegram_id", user_id))
    return res.data[0] if res.data else None


async def upsert_user(message: Message, referred_by: int | None = None):
    user_id = message.from_user.id
    existing = await get_user(user_id)
    if existing:
        await a_execute(
            supabase.table("users").update({
                "username": message.from_user.username,
                "full_name": message.from_user.full_name,
            }).eq("telegram_id", user_id)
        )
        return existing, False

    payload = {
        "telegram_id": user_id,
        "username": message.from_user.username,
        "full_name": message.from_user.full_name,
        "balance": 0,
    }
    if referred_by and referred_by != user_id:
        payload["referred_by"] = referred_by
    await a_execute(supabase.table("users").insert(payload))
    return payload, True


# ============================================================
#         BEKOR QILISH (istalgan holatda ishlaydi)
# Diqqat: bu handler FSM state talab qiladigan handlerlardan OLDIN
# ro'yxatdan o'tishi shart, aks holda ular matnni tutib qolishi mumkin.
# ============================================================
@dp.message(F.text == "❌ Bekor qilish")
async def cancel_any(message: Message, state: FSMContext):
    current = await state.get_state()
    if current is None:
        return
    await state.clear()
    await message.answer("Bekor qilindi.", reply_markup=main_menu())


# ============================================================
#                 ASOSIY MENYU BUYRUQLARI
# ============================================================
@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()

    referred_by = None
    if command.args and command.args.isdigit():
        referred_by = int(command.args)

    user, is_new = await upsert_user(message, referred_by)

    if is_new and referred_by and CACHE["referral_bonus"] > 0:
        ref_user = await get_user(referred_by)
        if ref_user:
            new_bal = ref_user["balance"] + CACHE["referral_bonus"]
            await a_execute(supabase.table("users").update({"balance": new_bal}).eq("telegram_id", referred_by))
            try:
                await bot.send_message(
                    referred_by,
                    f"🎉 Sizning taklifingiz bilan yangi foydalanuvchi qo'shildi!\n"
                    f"Bonus: +{fmt(CACHE['referral_bonus'])} so'm"
                )
            except Exception:
                pass

    sub_ok, markup = await check_mandatory_subs(message.from_user.id)
    if not sub_ok:
        return await message.answer(
            "Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz shart:", reply_markup=markup
        )

    await message.answer(f"Xush kelibsiz, {html.escape(message.from_user.first_name)}! 👋", reply_markup=main_menu())


@dp.callback_query(F.data == "check_sub")
async def verify_sub(call: CallbackQuery):
    sub_ok, markup = await check_mandatory_subs(call.from_user.id)
    if sub_ok:
        await call.message.delete()
        await call.message.answer("✅ Obuna tasdiqlandi. Xush kelibsiz!", reply_markup=main_menu())
    else:
        await call.answer("Siz hamma kanallarga obuna bo'lmadingiz!", show_alert=True)


@dp.message(F.text == "💰 Balans")
async def check_balance(message: Message):
    sub_ok, markup = await check_mandatory_subs(message.from_user.id)
    if not sub_ok:
        return await message.answer("Avval obuna bo'ling!", reply_markup=markup)

    user = await get_user(message.from_user.id)
    bal = user["balance"] if user else 0
    await message.answer(f"💰 Sizning hisobingizda: {fmt(bal)} so'm mavjud.")


@dp.message(F.text == "📜 Buyurtmalarim")
async def my_orders(message: Message):
    res = await a_execute(
        supabase.table("uc_purchases").select("*").eq("telegram_id", message.from_user.id)
        .order("id", desc=True).limit(10)
    )
    if not res.data:
        return await message.answer("Sizda hali buyurtmalar yo'q.")

    status_icons = {"pending": "⏳", "completed": "✅", "cancelled": "❌"}
    lines = ["📜 <b>Oxirgi buyurtmalaringiz:</b>\n"]
    for o in res.data:
        icon = status_icons.get(o["status"], "•")
        lines.append(f"{icon} {o['uc_amount']} UC — {fmt(o['price'])} so'm (PUBG ID: {o['pubg_id']})")
    await message.answer("\n".join(lines))


# ============================================================
#              TO'LOV VA CHEK YUBORISH (balans to'ldirish)
# ============================================================
@dp.message(F.text == "💳 Balansni to'ldirish")
async def topup_balance(message: Message, state: FSMContext):
    sub_ok, markup = await check_mandatory_subs(message.from_user.id)
    if not sub_ok:
        return await message.answer("Avval obuna bo'ling!", reply_markup=markup)

    card_num = CACHE["card_number"]
    await message.answer(
        f"💳 Quyidagi kartaga to'lov qiling:\n\n<code>{html.escape(card_num)}</code>\n\n"
        f"To'lov qilgach, chek (screenshot) rasmini shu yerga yuboring 👇",
        reply_markup=cancel_kb(),
    )
    await state.set_state(PaymentState.waiting_for_receipt)


@dp.message(PaymentState.waiting_for_receipt, F.photo)
async def process_receipt(message: Message, state: FSMContext):
    user = message.from_user
    photo_id = message.photo[-1].file_id

    res = await a_execute(supabase.table("topups").insert({"telegram_id": user.id, "status": "pending"}))
    topup_id = res.data[0]["id"]

    caption = (
        f"🧾 <b>Yangi to'lov cheki!</b>\n\n{user_display(user)}\n\n"
        f"So'rov ID: <code>{topup_id}</code>"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"payaccept_{topup_id}_{user.id}"),
         InlineKeyboardButton(text="❌ Rad etish", callback_data=f"payreject_{topup_id}_{user.id}")]
    ])

    if not CACHE["admins"]:
        log.warning("Hech qanday admin topilmadi - chek hech kimga yuborilmadi!")
    for admin_id in CACHE["admins"]:
        try:
            await bot.send_photo(admin_id, photo=photo_id, caption=caption, reply_markup=markup)
        except Exception as e:
            log.warning(f"Adminga yuborishda xato {admin_id}: {e}")

    await message.answer(
        "✅ Chekingiz qabul qilindi va admin ko'rib chiqmoqda. Tez orada balansingiz to'ldiriladi.",
        reply_markup=main_menu(),
    )
    await state.clear()


@dp.callback_query(F.data.startswith("payaccept_"))
async def adm_pay_accept(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Sizda ruxsat yo'q.", show_alert=True)

    _, topup_id, target_user_id = call.data.split("_")
    await state.update_data(
        topup_id=int(topup_id), target_user_id=int(target_user_id),
        msg_id=call.message.message_id, chat_id=call.message.chat.id,
    )
    await call.message.answer("Qancha summa qo'shmoqchisiz? (Faqat raqam, so'mda):")
    await state.set_state(AdminState.waiting_for_deposit_amount)
    await call.answer()


@dp.callback_query(F.data.startswith("payreject_"))
async def adm_pay_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Sizda ruxsat yo'q.", show_alert=True)

    _, topup_id, target_user_id = call.data.split("_")
    await a_execute(supabase.table("topups").update({"status": "rejected"}).eq("id", int(topup_id)))
    try:
        await bot.send_message(int(target_user_id), "❌ To'lov chekingiz admin tomonidan rad etildi.")
    except Exception:
        pass
    try:
        await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n❌ <b>Rad etilgan</b>")
    except Exception:
        pass
    await call.answer()


@dp.message(AdminState.waiting_for_deposit_amount)
async def adm_save_deposit(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        amount = int(message.text.replace(" ", ""))
        if amount <= 0:
            raise ValueError
    except ValueError:
        return await message.answer("❌ Iltimos, musbat butun son kiriting:")

    data = await state.get_data()
    target_id, topup_id = data.get("target_user_id"), data.get("topup_id")

    user = await get_user(target_id)
    if not user:
        await message.answer("❌ Foydalanuvchi topilmadi.")
        return await state.clear()

    new_bal = user["balance"] + amount
    await a_execute(supabase.table("users").update({"balance": new_bal}).eq("telegram_id", target_id))
    if topup_id:
        await a_execute(
            supabase.table("topups").update({"status": "approved", "amount": amount}).eq("id", topup_id)
        )

    try:
        await bot.send_message(
            target_id,
            f"🎉 Balansingizga {fmt(amount)} so'm qo'shildi!\n💰 Joriy balans: {fmt(new_bal)} so'm",
        )
    except Exception:
        pass

    try:
        await bot.edit_message_caption(
            chat_id=data.get("chat_id"), message_id=data.get("msg_id"),
            caption=f"✅ <b>Tasdiqlangan:</b> {fmt(amount)} so'm",
        )
    except Exception:
        pass

    await message.answer("✅ Foydalanuvchi balansi to'ldirildi.")
    await state.clear()


# ============================================================
#                     UC XARID QILISH
# ============================================================
@dp.message(F.text == "🛒 UC Xarid qilish")
async def start_buying(message: Message, state: FSMContext):
    sub_ok, markup = await check_mandatory_subs(message.from_user.id)
    if not sub_ok:
        return await message.answer("Avval obuna bo'ling!", reply_markup=markup)

    await message.answer("🎮 Iltimos, PUBG ID raqamingizni kiriting:", reply_markup=cancel_kb())
    await state.set_state(PurchaseState.waiting_for_pubg_id)


@dp.message(PurchaseState.waiting_for_pubg_id)
async def process_pubg_id(message: Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("❌ Faqat raqam kiriting:")
    await state.update_data(pubg_id=message.text)

    prices = CACHE["uc_prices"]
    if not prices:
        await message.answer("⚠️ Hozircha UC paketlari mavjud emas.", reply_markup=main_menu())
        return await state.clear()

    keyboard = [
        [InlineKeyboardButton(text=f"{p['uc_amount']} UC — {fmt(p['price'])} so'm", callback_data=f"buy_{p['id']}")]
        for p in prices
    ]
    await message.answer("👇 Qaysi paketni xarid qilasiz?", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@dp.callback_query(F.data.startswith("buy_"))
async def process_purchase(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    price_id = int(callback.data.split("_")[1])

    package = next((p for p in CACHE["uc_prices"] if p["id"] == price_id), None)
    if not package:
        return await callback.answer("Paket topilmadi yoki narx yangilandi. Qaytadan urinib ko'ring.", show_alert=True)

    uc_amount, price = package["uc_amount"], package["price"]

    data = await state.get_data()
    pubg_id = data.get("pubg_id")
    if not pubg_id:
        return await callback.answer("Sessiya tugagan. Qaytadan boshlang.", show_alert=True)

    user = await get_user(user_id)
    balance = user["balance"] if user else 0
    if balance < price:
        need = price - balance
        return await callback.message.edit_text(
            f"❌ Mablag' yetarli emas.\n💰 Balansingiz: {fmt(balance)} so'm\n"
            f"💵 Kerak: {fmt(price)} so'm\n➕ Yetishmayapti: {fmt(need)} so'm"
        )

    new_balance = balance - price
    await a_execute(supabase.table("users").update({"balance": new_balance}).eq("telegram_id", user_id))
    order_res = await a_execute(supabase.table("uc_purchases").insert({
        "telegram_id": user_id, "pubg_id": pubg_id, "uc_amount": uc_amount, "price": price, "status": "pending",
    }))
    order_id = order_res.data[0]["id"]

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Yetkazildi", callback_data=f"orderdone_{order_id}"),
         InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"ordercancel_{order_id}")]
    ])
    text = (
        f"🔥 <b>Yangi buyurtma!</b>\n\n{user_display(callback.from_user)}\n\n"
        f"🎮 PUBG ID: <code>{pubg_id}</code>\n📦 Paket: {uc_amount} UC\n💵 Narx: {fmt(price)} so'm\n"
        f"🆔 Buyurtma ID: <code>{order_id}</code>"
    )
    for admin_id in CACHE["admins"]:
        try:
            await bot.send_message(admin_id, text, reply_markup=admin_kb)
        except Exception as e:
            log.warning(f"Adminga yuborishda xato {admin_id}: {e}")

    await callback.message.edit_text(
        f"✅ Buyurtma qabul qilindi!\n\n🎮 PUBG ID: {pubg_id}\n📦 Paket: {uc_amount} UC\n"
        f"💰 Yangi balans: {fmt(new_balance)} so'm\n\nTez orada tushirib beriladi."
    )
    await state.clear()
    await callback.answer()


@dp.callback_query(F.data.startswith("orderdone_"))
async def order_done(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Sizda ruxsat yo'q.", show_alert=True)

    order_id = int(call.data.split("_")[1])
    res = await a_execute(supabase.table("uc_purchases").select("*").eq("id", order_id))
    if not res.data:
        return await call.answer("Buyurtma topilmadi.", show_alert=True)
    order = res.data[0]

    await a_execute(supabase.table("uc_purchases").update({"status": "completed"}).eq("id", order_id))
    try:
        await bot.send_message(order["telegram_id"], f"✅ Buyurtmangiz ({order['uc_amount']} UC) yetkazib berildi. Rahmat!")
    except Exception:
        pass
    await call.message.edit_text((call.message.text or "") + "\n\n✅ <b>Yetkazildi</b>")
    await call.answer()


@dp.callback_query(F.data.startswith("ordercancel_"))
async def order_cancel(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Sizda ruxsat yo'q.", show_alert=True)

    order_id = int(call.data.split("_")[1])
    res = await a_execute(supabase.table("uc_purchases").select("*").eq("id", order_id))
    if not res.data:
        return await call.answer("Buyurtma topilmadi.", show_alert=True)
    order = res.data[0]

    if order["status"] == "completed":
        return await call.answer("Bu buyurtma allaqachon yetkazilgan.", show_alert=True)

    user = await get_user(order["telegram_id"])
    if user:
        refund_balance = user["balance"] + order["price"]
        await a_execute(
            supabase.table("users").update({"balance": refund_balance}).eq("telegram_id", order["telegram_id"])
        )

    await a_execute(supabase.table("uc_purchases").update({"status": "cancelled"}).eq("id", order_id))
    try:
        await bot.send_message(
            order["telegram_id"],
            f"❌ Buyurtmangiz bekor qilindi. {fmt(order['price'])} so'm hisobingizga qaytarildi.",
        )
    except Exception:
        pass
    await call.message.edit_text((call.message.text or "") + "\n\n❌ <b>Bekor qilindi (pul qaytarildi)</b>")
    await call.answer()


# ==========================================
#              ADMIN PANEL
# ==========================================
@dp.message(Command("adminmanku"))
async def make_me_admin(message: Message):
    if message.from_user.id not in SUPER_ADMIN_IDS:
        return await message.answer("⛔ Bu buyruq faqat super-adminlar uchun (.env dagi SUPER_ADMIN_IDS).")
    await a_execute(supabase.table("users").update({"is_admin": True}).eq("telegram_id", message.from_user.id))
    await refresh_admins()
    await message.answer("🎉 Siz adminsiz. Panelni ochish uchun /admin yuboring.")


@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("👨‍💻 Admin Panel:", reply_markup=admin_menu_kb())


@dp.message(Command("addadmin"))
async def add_admin_cmd(message: Message, command: CommandObject):
    if message.from_user.id not in SUPER_ADMIN_IDS:
        return
    if not command.args or not command.args.isdigit():
        return await message.answer("Foydalanish: /addadmin 123456789")
    new_admin_id = int(command.args)
    user = await get_user(new_admin_id)
    if not user:
        return await message.answer("❌ Bunday foydalanuvchi bazada topilmadi (avval botga /start bosishi kerak).")
    await a_execute(supabase.table("users").update({"is_admin": True}).eq("telegram_id", new_admin_id))
    await refresh_admins()
    await message.answer(f"✅ {new_admin_id} endi admin.")


@dp.message(Command("deladmin"))
async def del_admin_cmd(message: Message, command: CommandObject):
    if message.from_user.id not in SUPER_ADMIN_IDS:
        return
    if not command.args or not command.args.isdigit():
        return await message.answer("Foydalanish: /deladmin 123456789")
    target = int(command.args)
    await a_execute(supabase.table("users").update({"is_admin": False}).eq("telegram_id", target))
    await refresh_admins()
    await message.answer(f"✅ {target} admin ro'yxatidan olib tashlandi.")


@dp.callback_query(F.data == "adm_admins")
async def adm_admins_list(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q.", show_alert=True)
    lines = [f"• <code>{a}</code>" + (" (super)" if a in SUPER_ADMIN_IDS else "") for a in CACHE["admins"]]
    text = "👮 <b>Adminlar:</b>\n\n" + ("\n".join(lines) if lines else "yo'q")
    text += "\n\nQo'shish: /addadmin ID\nOlib tashlash: /deladmin ID\n(faqat super-adminlar uchun)"
    await call.message.answer(text)
    await call.answer()


# -- KARTA RAQAMI --
@dp.callback_query(F.data == "adm_card")
async def adm_set_card(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q.", show_alert=True)
    await call.message.answer(
        f"Joriy karta: <code>{html.escape(CACHE['card_number'])}</code>\n\nYangi karta raqami va ism-familiyani yozing:",
        reply_markup=cancel_kb(),
    )
    await state.set_state(AdminState.waiting_for_card)
    await call.answer()


@dp.message(AdminState.waiting_for_card)
async def adm_save_card(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await a_execute(supabase.table("settings").upsert({"key": "card_number", "value": message.text}))
    await refresh_card()
    await message.answer("✅ Karta raqami saqlandi.", reply_markup=main_menu())
    await state.clear()


# -- NARXLARNI TAHRIRLASH --
@dp.callback_query(F.data == "adm_prices")
async def adm_prices(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q.", show_alert=True)
    prices = CACHE["uc_prices"]
    if not prices:
        await call.message.answer("Hozircha paketlar yo'q. \"➕ Yangi UC paket\" orqali qo'shing.")
        return await call.answer()
    kb = [
        [InlineKeyboardButton(text=f"✏️ {p['uc_amount']} UC — {fmt(p['price'])} so'm",
                               callback_data=f"adm_editprice_{p['id']}"),
         InlineKeyboardButton(text="🗑", callback_data=f"adm_delprice_{p['id']}")]
        for p in prices
    ]
    await call.message.answer("Tahrirlash yoki o'chirish uchun paketni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()


@dp.callback_query(F.data.startswith("adm_editprice_"))
async def adm_edit_price_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q.", show_alert=True)
    price_id = int(call.data.split("_")[2])
    await state.update_data(edit_price_id=price_id)
    await call.message.answer("Yangi narxni kiriting (so'mda):", reply_markup=cancel_kb())
    await state.set_state(AdminState.waiting_for_new_price)
    await call.answer()


@dp.message(AdminState.waiting_for_new_price)
async def adm_edit_price_save(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        new_price = int(message.text.replace(" ", ""))
        if new_price <= 0:
            raise ValueError
    except ValueError:
        return await message.answer("❌ Musbat butun son kiriting:")

    data = await state.get_data()
    price_id = data.get("edit_price_id")
    await a_execute(supabase.table("uc_prices").update({"price": new_price}).eq("id", price_id))
    await refresh_prices()
    await message.answer("✅ Narx yangilandi.", reply_markup=main_menu())
    await state.clear()


@dp.callback_query(F.data.startswith("adm_delprice_"))
async def adm_del_price(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q.", show_alert=True)
    price_id = int(call.data.split("_")[2])
    await a_execute(supabase.table("uc_prices").delete().eq("id", price_id))
    await refresh_prices()
    await call.message.edit_text("🗑 Paket o'chirildi.")
    await call.answer()


# -- YANGI UC PAKET --
@dp.callback_query(F.data == "adm_add_uc")
async def adm_add_uc(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q.", show_alert=True)
    await call.message.answer("Yangi paketda qancha UC bo'ladi? (Faqat raqam):", reply_markup=cancel_kb())
    await state.set_state(AdminState.waiting_for_new_uc_amount)
    await call.answer()


@dp.message(AdminState.waiting_for_new_uc_amount)
async def adm_add_uc_amount(message: Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("❌ Faqat raqam kiriting:")
    await state.update_data(new_uc=int(message.text))
    await message.answer("Bu paketning narxi qancha bo'ladi (so'mda)?")
    await state.set_state(AdminState.waiting_for_new_uc_price_val)


@dp.message(AdminState.waiting_for_new_uc_price_val)
async def adm_add_uc_price(message: Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("❌ Faqat raqam kiriting:")
    data = await state.get_data()
    await a_execute(supabase.table("uc_prices").insert({"uc_amount": data["new_uc"], "price": int(message.text)}))
    await refresh_prices()
    await message.answer(f"✅ {data['new_uc']} UC paketi qo'shildi!", reply_markup=main_menu())
    await state.clear()


# -- MAJBURIY KANALLAR --
@dp.callback_query(F.data == "adm_channels")
async def adm_channels(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q.", show_alert=True)
    kb = [[InlineKeyboardButton(text=f"🗑 {c['name']}", callback_data=f"adm_delch_{c['id']}")] for c in CACHE["channels"]]
    kb.append([InlineKeyboardButton(text="➕ Yangi kanal qo'shish", callback_data="adm_add_ch")])
    await call.message.answer("📢 Majburiy kanallar:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()


@dp.callback_query(F.data.startswith("adm_delch_"))
async def adm_del_ch(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q.", show_alert=True)
    ch_id = int(call.data.split("_")[2])
    await a_execute(supabase.table("mandatory_channels").delete().eq("id", ch_id))
    await refresh_channels()
    await call.message.edit_text("🗑 Kanal o'chirildi.")
    await call.answer()


@dp.callback_query(F.data == "adm_add_ch")
async def adm_add_ch(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q.", show_alert=True)
    await call.message.answer("Platformani tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Telegram", callback_data="chplatform_telegram"),
         InlineKeyboardButton(text="YouTube", callback_data="chplatform_youtube"),
         InlineKeyboardButton(text="Instagram", callback_data="chplatform_instagram")]
    ]))
    await call.answer()


@dp.callback_query(F.data.startswith("chplatform_"))
async def adm_ch_platform(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q.", show_alert=True)
    platform = call.data.split("_")[1]
    await state.update_data(platform=platform)
    if platform == "telegram":
        await call.message.answer(
            "Kanal ID/username ni kiriting (masalan @kanal yoki -100123...):\n\n"
            "⚠️ Botni o'sha kanalga ADMIN qilib qo'yishni unutmang, aks holda obunani tekshira olmaydi.",
            reply_markup=cancel_kb(),
        )
        await state.set_state(AdminState.waiting_for_channel_id)
    else:
        await call.message.answer("Kanal/sahifa havolasini kiriting (https://...):", reply_markup=cancel_kb())
        await state.set_state(AdminState.waiting_for_channel_url)
    await call.answer()


@dp.message(AdminState.waiting_for_channel_id)
async def adm_save_ch_id(message: Message, state: FSMContext):
    await state.update_data(ch_id=message.text.strip())
    await message.answer("Kanal nomini yozing (tugmada shu nom chiqadi):")
    await state.set_state(AdminState.waiting_for_channel_name)


@dp.message(AdminState.waiting_for_channel_url)
async def adm_save_ch_url(message: Message, state: FSMContext):
    await state.update_data(ch_url=message.text.strip())
    await message.answer("Kanal nomini yozing (tugmada shu nom chiqadi):")
    await state.set_state(AdminState.waiting_for_channel_name)


@dp.message(AdminState.waiting_for_channel_name)
async def adm_save_ch_name(message: Message, state: FSMContext):
    data = await state.get_data()
    platform = data["platform"]
    if platform == "telegram":
        ch_id = data["ch_id"]
        url = f"https://t.me/{ch_id.replace('@', '')}"
        await a_execute(supabase.table("mandatory_channels").insert(
            {"platform": "telegram", "chat_id": ch_id, "name": message.text, "url": url}
        ))
    else:
        await a_execute(supabase.table("mandatory_channels").insert(
            {"platform": platform, "chat_id": "", "name": message.text, "url": data["ch_url"]}
        ))
    await refresh_channels()
    await message.answer("✅ Majburiy kanal qo'shildi!", reply_markup=main_menu())
    await state.clear()


# -- FOYDALANUVCHI BALANSINI QO'LDA O'ZGARTIRISH --
@dp.callback_query(F.data == "adm_user_balance")
async def adm_user_balance_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q.", show_alert=True)
    await call.message.answer("Foydalanuvchining Telegram ID sini kiriting:", reply_markup=cancel_kb())
    await state.set_state(AdminState.waiting_for_user_search)
    await call.answer()


@dp.message(AdminState.waiting_for_user_search)
async def adm_user_search(message: Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("❌ Faqat ID (raqam) kiriting:")
    target_id = int(message.text)
    user = await get_user(target_id)
    if not user:
        await message.answer("❌ Bunday foydalanuvchi topilmadi.", reply_markup=main_menu())
        return await state.clear()

    uname = f"@{user['username']}" if user.get("username") else "yo'q"
    await state.update_data(target_id=target_id)
    await message.answer(
        f"👤 {html.escape(user.get('full_name') or '')}\nUsername: {uname}\n"
        f"💰 Balans: {fmt(user['balance'])} so'm\n\n"
        f"Yangi qiymatni kiriting:\n"
        f"• <code>+5000</code> — qo'shish\n"
        f"• <code>-2000</code> — ayirish\n"
        f"• <code>10000</code> — to'liq shu summaga o'rnatish"
    )
    await state.set_state(AdminState.waiting_for_balance_adjust)


@dp.message(AdminState.waiting_for_balance_adjust)
async def adm_balance_adjust(message: Message, state: FSMContext):
    text = message.text.strip().replace(" ", "")
    data = await state.get_data()
    target_id = data["target_id"]
    user = await get_user(target_id)
    if not user:
        await message.answer("❌ Foydalanuvchi topilmadi.")
        return await state.clear()

    try:
        if text.startswith("+") or text.startswith("-"):
            new_balance = user["balance"] + int(text)
        else:
            new_balance = int(text)
        if new_balance < 0:
            raise ValueError
    except ValueError:
        return await message.answer("❌ Noto'g'ri format. Masalan: +5000, -2000 yoki 10000")

    await a_execute(supabase.table("users").update({"balance": new_balance}).eq("telegram_id", target_id))
    try:
        await bot.send_message(target_id, f"ℹ️ Balansingiz o'zgartirildi. Joriy balans: {fmt(new_balance)} so'm")
    except Exception:
        pass
    await message.answer(f"✅ Yangi balans: {fmt(new_balance)} so'm", reply_markup=main_menu())
    await state.clear()


# -- XABAR YUBORISH (BROADCAST) --
@dp.callback_query(F.data == "adm_broadcast")
async def adm_broadcast_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q.", show_alert=True)
    await call.message.answer(
        "Barcha foydalanuvchilarga yuboriladigan xabarni yuboring (matn, rasm va h.k.):",
        reply_markup=cancel_kb(),
    )
    await state.set_state(AdminState.waiting_for_broadcast_message)
    await call.answer()


@dp.message(AdminState.waiting_for_broadcast_message)
async def adm_broadcast_send(message: Message, state: FSMContext):
    res = await a_execute(supabase.table("users").select("telegram_id"))
    users = res.data or []
    await message.answer(f"⏳ {len(users)} foydalanuvchiga yuborilmoqda...", reply_markup=main_menu())
    await state.clear()

    sent, failed = 0, 0
    for u in users:
        try:
            await message.copy_to(u["telegram_id"])
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # Telegram flood-limitiga tushmaslik uchun

    await message.answer(f"✅ Yuborildi: {sent}\n❌ Yuborilmadi: {failed}")


# -- STATISTIKA --
@dp.callback_query(F.data == "adm_stats")
async def show_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q.", show_alert=True)

    res_users = await a_execute(supabase.table("users").select("telegram_id", count="exact"))
    res_purchases = await a_execute(supabase.table("uc_purchases").select("id", count="exact"))
    res_completed = await a_execute(
        supabase.table("uc_purchases").select("price", count="exact").eq("status", "completed")
    )
    total_revenue = sum(p["price"] for p in (res_completed.data or []))
    res_topups = await a_execute(
        supabase.table("topups").select("id", count="exact").eq("status", "approved")
    )

    text = (
        f"📊 <b>STATISTIKA</b>\n\n"
        f"👥 Umumiy foydalanuvchilar: {res_users.count}\n"
        f"🛍 Umumiy UC buyurtmalar: {res_purchases.count}\n"
        f"✅ Yakunlangan buyurtmalar: {res_completed.count}\n"
        f"💰 Yakunlangan buyurtmalardan tushum: {fmt(total_revenue)} so'm\n"
        f"💳 Tasdiqlangan to'lovlar: {res_topups.count}"
    )
    await call.message.answer(text)
    await call.answer()


# ============================================================
#                   GLOBAL XATOLIKLAR
# ============================================================
@dp.errors()
async def error_handler(event: ErrorEvent):
    log.exception("Kutilmagan xatolik yuz berdi", exc_info=event.exception)
    return True


# ============================================================
#                    ISHGA TUSHIRISH
# ============================================================
async def main():
    await refresh_all_cache()
    asyncio.create_task(periodic_cache_refresh())
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("Bot ishga tushdi.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
