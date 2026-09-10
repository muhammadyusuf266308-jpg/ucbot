import asyncio
import logging
from decouple import config
from supabase import create_client, Client
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- SOZLAMALAR ---
BOT_TOKEN = config("BOT_TOKEN")
SUPABASE_URL = config("SUPABASE_URL")
SUPABASE_KEY = config("SUPABASE_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO)

# --- HOLATLAR (FSM) ---
class PurchaseState(StatesGroup):
    waiting_for_pubg_id = State()

class AdminState(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_balance_amount = State()
    waiting_for_new_price = State()

# --- YORDAMCHI FUNKSIYALAR ---
def is_admin(user_id):
    res = supabase.table("users").select("is_admin").eq("telegram_id", user_id).execute()
    if res.data and res.data[0].get("is_admin"):
        return True
    return False

# --- ASOSIY BUYRUQLAR ---
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    response = supabase.table("users").select("*").eq("telegram_id", user_id).execute()
    
    if not response.data:
        supabase.table("users").insert({"telegram_id": user_id, "balance": 0}).execute()
        
    await message.answer(
        f"Assalomu alaykum, {message.from_user.first_name}!\n\n"
        "💰 /balance - Balansni ko'rish\n"
        "🛒 /buy - UC xarid qilish"
    )

@dp.message(F.text == "/balance")
async def check_balance(message: Message):
    user_id = message.from_user.id
    res = supabase.table("users").select("balance").eq("telegram_id", user_id).execute()
    if res.data:
        await message.answer(f"💰 Sizning hisobingizda: {res.data[0]['balance']:,.0f} so'm mavjud.")

# --- XARID QILISH QISMI ---
@dp.message(F.text == "/buy")
async def start_buying(message: Message, state: FSMContext):
    await message.answer("🎮 Iltimos, PUBG ID raqamingizni kiriting:")
    await state.set_state(PurchaseState.waiting_for_pubg_id)

@dp.message(PurchaseState.waiting_for_pubg_id)
async def process_pubg_id(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Noto'g'ri format! Faqat raqam kiriting:")
        return

    await state.update_data(pubg_id=message.text)
    
    # Narxlarni bazadan olamiz
    res = supabase.table("uc_prices").select("*").order("uc_amount").execute()
    keyboard = []
    for item in res.data:
        uc, price = item['uc_amount'], item['price']
        keyboard.append([InlineKeyboardButton(text=f"{uc} UC - {price:,.0f} so'm", callback_data=f"buy_{uc}")])
    
    await message.answer("👇 Quyidagi paketlardan birini tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await state.set_state(None)

@dp.callback_query(F.data.startswith("buy_"))
async def process_purchase(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    uc_amount = int(callback.data.split("_")[1])
    
    # Bazadagi joriy narxni tekshiramiz
    price_res = supabase.table("uc_prices").select("price").eq("uc_amount", uc_amount).execute()
    if not price_res.data:
        return await callback.answer("Bu paket topilmadi.", show_alert=True)
    price = price_res.data[0]['price']
    
    data = await state.get_data()
    pubg_id = data.get("pubg_id")
    if not pubg_id:
        return await callback.answer("Sessiya eskirgan. /buy ni bosing.", show_alert=True)

    user_res = supabase.table("users").select("balance").eq("telegram_id", user_id).execute()
    current_balance = user_res.data[0]["balance"]
    
    if current_balance < price:
        return await callback.message.edit_text(f"❌ Hisobingizda mablag' yetarli emas.\nKerakli: {price:,.0f} so'm")
        
    new_balance = current_balance - price
    supabase.table("users").update({"balance": new_balance}).eq("telegram_id", user_id).execute()
    
    supabase.table("uc_purchases").insert({
        "telegram_id": user_id, "pubg_id": pubg_id, "uc_amount": uc_amount, "price": price, "status": "pending"
    }).execute()
    
    await callback.message.edit_text(f"✅ Buyurtma qabul qilindi!\nID: {pubg_id}\nPaket: {uc_amount} UC\nQoldiq: {new_balance:,.0f} so'm")

# ==========================================
#              ADMIN PANEL
# ==========================================

# 1. Admin bo'lish siri
@dp.message(Command("adminmanku"))
async def make_me_admin(message: Message):
    user_id = message.from_user.id
    supabase.table("users").update({"is_admin": True}).eq("telegram_id", user_id).execute()
    await message.answer("🎉 Tabriklayman! Siz endi adminsiz. Panelni ochish uchun /admin yuboring.")

# 2. Admin menyusi
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Sizda admin huquqi yo'q.")
        
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Balans sovg'a qilish", callback_data="adm_gift")],
        [InlineKeyboardButton(text="✏️ Narxlarni tahrirlash", callback_data="adm_prices")]
    ])
    await message.answer("👨‍💻 Admin panelga xush kelibsiz!", reply_markup=keyboard)

# 3. Balans qo'shish (Sovg'a)
@dp.callback_query(F.data == "adm_gift")
async def adm_gift_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Foydalanuvchining Telegram ID raqamini kiriting:")
    await state.set_state(AdminState.waiting_for_user_id)

@dp.message(AdminState.waiting_for_user_id)
async def adm_gift_id(message: Message, state: FSMContext):
    await state.update_data(target_id=message.text)
    await message.answer("Qancha so'm qo'shmoqchisiz? (Faqat raqam yozing):")
    await state.set_state(AdminState.waiting_for_balance_amount)

@dp.message(AdminState.waiting_for_balance_amount)
async def adm_gift_amount(message: Message, state: FSMContext):
    amount = int(message.text)
    data = await state.get_data()
    target_id = int(data.get("target_id"))
    
    res = supabase.table("users").select("balance").eq("telegram_id", target_id).execute()
    if not res.data:
        return await message.answer("Bunday foydalanuvchi bazada topilmadi.")
        
    new_bal = res.data[0]["balance"] + amount
    supabase.table("users").update({"balance": new_bal}).eq("telegram_id", target_id).execute()
    
    # Adminga xabar
    await message.answer(f"✅ Foydalanuvchi ({target_id}) balansiga {amount:,.0f} so'm qo'shildi.")
    # Foydalanuvchiga xabar
    try:
        await bot.send_message(target_id, f"🎉 Admin tomonidan sizga {amount:,.0f} so'm sovg'a qilindi!\nJoriy balans: {new_bal:,.0f} so'm")
    except Exception:
        pass
    await state.set_state(None)

# 4. Narxlarni tahrirlash
@dp.callback_query(F.data == "adm_prices")
async def adm_prices_list(callback: CallbackQuery):
    res = supabase.table("uc_prices").select("*").order("uc_amount").execute()
    keyboard = []
    for item in res.data:
        uc, price = item['uc_amount'], item['price']
        keyboard.append([InlineKeyboardButton(text=f"{uc} UC ({price:,.0f} so'm) ✏️", callback_data=f"editprice_{uc}")])
    await callback.message.answer("Qaysi paket narxini o'zgartirasiz?", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@dp.callback_query(F.data.startswith("editprice_"))
async def adm_edit_price(callback: CallbackQuery, state: FSMContext):
    uc_amount = int(callback.data.split("_")[1])
    await state.update_data(edit_uc_amount=uc_amount)
    await callback.message.answer(f"{uc_amount} UC uchun yangi narxni kiriting (so'mda):")
    await state.set_state(AdminState.waiting_for_new_price)

@dp.message(AdminState.waiting_for_new_price)
async def adm_save_price(message: Message, state: FSMContext):
    new_price = int(message.text)
    data = await state.get_data()
    uc_amount = data.get("edit_uc_amount")
    
    supabase.table("uc_prices").update({"price": new_price}).eq("uc_amount", uc_amount).execute()
    await message.answer(f"✅ {uc_amount} UC narxi {new_price:,.0f} so'm etib belgilandi.")
    await state.set_state(None)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
