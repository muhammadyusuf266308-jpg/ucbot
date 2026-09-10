import asyncio
import logging
from decouple import config
from supabase import create_client, Client
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- 1. Muhit o'zgaruvchilarini yuklash ---
BOT_TOKEN = config("BOT_TOKEN")
SUPABASE_URL = config("SUPABASE_URL")
SUPABASE_KEY = config("SUPABASE_KEY")

# --- 2. Bot va Supabase ulanishini sozlash ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO)

# --- 3. Holatlar (FSM - Finite State Machine) ---
class PurchaseState(StatesGroup):
    waiting_for_pubg_id = State()

# UC paketlari narxlari (so'mda)
UC_PRICES = {
    60: 15000,
    325: 75000,
    660: 150000,
    1800: 390000
}

# --- 4. /start buyrug'i ---
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    
    # Foydalanuvchini bazadan qidirish
    response = supabase.table("users").select("*").eq("telegram_id", user_id).execute()
    
    # Agar yangi foydalanuvchi bo'lsa, bazaga qo'shamiz
    if not response.data:
        supabase.table("users").insert({"telegram_id": user_id, "balance": 0}).execute()
        
    await message.answer(
        f"Assalomu alaykum, {message.from_user.first_name}!\n\n"
        "UC xarid qilish xizmatiga xush kelibsiz.\n"
        "Mavjud buyruqlar:\n"
        "💰 /balance - Balansni ko'rish\n"
        "🛒 /buy - UC xarid qilish"
    )

# --- 5. /balance buyrug'i ---
@dp.message(F.text == "/balance")
async def check_balance(message: Message):
    user_id = message.from_user.id
    response = supabase.table("users").select("balance").eq("telegram_id", user_id).execute()
    
    if response.data:
        balance = response.data[0]["balance"]
        await message.answer(f"💰 Sizning hisobingizda: {balance:,.0f} so'm mavjud.")
    else:
        await message.answer("⚠️ Ma'lumot topilmadi. Iltimos, /start buyrug'ini yuboring.")

# --- 6. /buy buyrug'i (Xaridni boshlash) ---
@dp.message(F.text == "/buy")
async def start_buying(message: Message, state: FSMContext):
    await message.answer("🎮 Iltimos, o'yinchi ID raqamini (PUBG ID) kiriting:\n(Faqat raqamlardan iborat bo'lishi kerak)")
    await state.set_state(PurchaseState.waiting_for_pubg_id)

# --- 7. PUBG ID ni qabul qilish va narxlarni ko'rsatish ---
@dp.message(PurchaseState.waiting_for_pubg_id)
async def process_pubg_id(message: Message, state: FSMContext):
    pubg_id = message.text
    
    if not pubg_id.isdigit():
        await message.answer("❌ Noto'g'ri format! PUBG ID faqat raqamlardan iborat bo'ladi. Qaytadan kiriting:")
        return

    # ID ni xotirada saqlaymiz
    await state.update_data(pubg_id=pubg_id)
    
    # Inline klaviatura yaratish
    keyboard = []
    for uc, price in UC_PRICES.items():
        keyboard.append([InlineKeyboardButton(text=f"{uc} UC - {price:,.0f} so'm", callback_data=f"buy_{uc}")])
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    await message.answer(
        f"✅ PUBG ID qabul qilindi: {pubg_id}\n\n"
        "👇 Quyidagi paketlardan birini tanlang:", 
        reply_markup=reply_markup
    )
    await state.set_state(None) # Holatni tozalaymiz

# --- 8. Xaridni tasdiqlash va bazaga yozish ---
@dp.callback_query(F.data.startswith("buy_"))
async def process_purchase(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    uc_amount = int(callback.data.split("_")[1])
    price = UC_PRICES[uc_amount]
    
    # Xotiradan saqlangan ID ni olish
    user_data = await state.get_data()
    pubg_id = user_data.get("pubg_id")
    
    if not pubg_id:
        await callback.answer("⏳ Sessiya eskirgan. Iltimos, /buy orqali qaytadan boshlang.", show_alert=True)
        return

    # Kutish xabarini chiqarish
    await callback.message.edit_text("🔄 So'rov qayta ishlanmoqda, iltimos kuting...")

    # Balansni tekshirish
    user_res = supabase.table("users").select("balance").eq("telegram_id", user_id).execute()
    if not user_res.data:
        await callback.message.edit_text("⚠️ Xatolik: Foydalanuvchi topilmadi.")
        return
        
    current_balance = user_res.data[0]["balance"]
    
    # Agar pul yetmasa
    if current_balance < price:
        await callback.message.edit_text(
            f"❌ Hisobingizda yetarli mablag' mavjud emas.\n\n"
            f"💳 Kerakli summa: {price:,.0f} so'm\n"
            f"💰 Sizning balansingiz: {current_balance:,.0f} so'm\n\n"
            "Balansni to'ldirish uchun admin bilan bog'laning."
        )
        return
        
    # Balansdan yechib olish
    new_balance = current_balance - price
    supabase.table("users").update({"balance": new_balance}).eq("telegram_id", user_id).execute()
    
    # Tranzaksiyani bazaga yozish
    purchase_data = {
        "telegram_id": user_id,
        "pubg_id": pubg_id,
        "uc_amount": uc_amount,
        "price": price,
        "status": "pending" # Admin ko'rib chiqishi uchun 'pending' turadi
    }
    supabase.table("uc_purchases").insert(purchase_data).execute()
    
    # Muvaffaqiyat xabari
    await callback.message.edit_text(
        f"✅ Buyurtmangiz muvaffaqiyatli qabul qilindi!\n\n"
        f"🆔 PUBG ID: {pubg_id}\n"
        f"💎 UC Miqdori: {uc_amount}\n"
        f"💳 Yechib olindi: {price:,.0f} so'm\n"
        f"💰 Qoldiq balans: {new_balance:,.0f} so'm\n\n"
        "Tez orada hisobingizga UC tashlab beriladi."
    )

# --- 9. Botni ishga tushirish funksiyasi ---
async def main():
    print("Bot ishga tushmoqda...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())