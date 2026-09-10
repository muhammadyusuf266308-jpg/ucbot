import asyncio
import logging
from decouple import config
from supabase import create_client, Client
from aiogram import Bot, Dispatcher, F
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup, 
                           InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton)
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

# --- KLAVIATURALAR ---
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 UC Xarid qilish"), KeyboardButton(text="💰 Balans")],
            [KeyboardButton(text="💳 Balansni to'ldirish"), KeyboardButton(text="📊 Statistika")]
        ], resize_keyboard=True
    )

# --- YORDAMCHI FUNKSIYALAR ---
def is_admin(user_id):
    res = supabase.table("users").select("is_admin").eq("telegram_id", user_id).execute()
    return True if res.data and res.data[0].get("is_admin") else False

async def check_mandatory_subs(user_id):
    channels = supabase.table("mandatory_channels").select("*").execute().data
    if not channels:
        return True, None
    
    not_subbed_tg = False
    keyboard = []
    
    for ch in channels:
        if ch['platform'] == 'telegram':
            try:
                member = await bot.get_chat_member(chat_id=ch['chat_id'], user_id=user_id)
                if member.status not in ['member', 'administrator', 'creator']:
                    not_subbed_tg = True
                    keyboard.append([InlineKeyboardButton(text=f"📢 {ch['name']}", url=ch['url'])])
            except Exception:
                pass # Agar bot kanalda admin bo'lmasa xatoni o'tkazib yuboradi
        elif ch['platform'] == 'youtube':
            keyboard.append([InlineKeyboardButton(text=f"🔴 {ch['name']}", url=ch['url'])])
        elif ch['platform'] == 'instagram':
            keyboard.append([InlineKeyboardButton(text=f"📸 {ch['name']}", url=ch['url'])])
            
    # Agar hech bo'lmasa bitta Telegram kanalga obuna bo'lmagan bo'lsa yoki menyuni chiqarish kerak bo'lsa
    if not_subbed_tg or (keyboard and not not_subbed_tg and "youtube" in str(channels)):
        # Aslida, foydalanuvchini har safar YT/IG ga bosishga majbur qilmaslik uchun 
        # faqat Telegram kanalga a'zo bo'lmasa shu menyuni ko'rsatamiz.
        if not_subbed_tg:
            keyboard.append([InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data="check_sub")])
            return False, InlineKeyboardMarkup(inline_keyboard=keyboard)
            
    return True, None

# --- ASOSIY MENYU BUYRUQLARI ---
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    res = supabase.table("users").select("*").eq("telegram_id", user_id).execute()
    if not res.data:
        supabase.table("users").insert({"telegram_id": user_id, "balance": 0}).execute()
        
    sub_ok, markup = await check_mandatory_subs(user_id)
    if not sub_ok:
        return await message.answer("Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz shart:", reply_markup=markup)
        
    await message.answer(f"Xush kelibsiz, {message.from_user.first_name}!", reply_markup=main_menu())

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
    if not sub_ok: return await message.answer("Avval obuna bo'ling!", reply_markup=markup)
    
    res = supabase.table("users").select("balance").eq("telegram_id", message.from_user.id).execute()
    await message.answer(f"💰 Sizning hisobingizda: {res.data[0]['balance']:,.0f} so'm mavjud.")

# --- TO'LOV VA CHEK YUBORISH ---
@dp.message(F.text == "💳 Balansni to'ldirish")
async def topup_balance(message: Message, state: FSMContext):
    card_res = supabase.table("settings").select("value").eq("key", "card_number").execute()
    card_num = card_res.data[0]['value'] if card_res.data else "Kiritilmagan"
    
    await message.answer(f"💳 Kartaga pul o'tkazing:\n\n`{card_num}`\n\nTo'lov qilgach, to'lov chekini (rasmini) shu yerga yuboring:", parse_mode="Markdown")
    await state.set_state(PaymentState.waiting_for_receipt)

@dp.message(PaymentState.waiting_for_receipt, F.photo)
async def process_receipt(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    user_id = message.from_user.id
    
    # Barcha adminlarga yuborish
    admins = supabase.table("users").select("telegram_id").eq("is_admin", True).execute().data
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"payaccept_{user_id}"),
         InlineKeyboardButton(text="❌ Rad etish", callback_data=f"payreject_{user_id}")]
    ])
    
    for admin in admins:
        try:
            await bot.send_photo(admin['telegram_id'], photo=photo_id, caption=f"Yangi to'lov!\nFoydalanuvchi: {message.from_user.full_name} ({user_id})", reply_markup=markup)
        except Exception: pass
        
    await message.answer("✅ Chek adminga yuborildi. Tez orada balansingizga pul tushadi.")
    await state.clear()

# --- ADMIN CHEKNI TASDIQLASHI ---
@dp.callback_query(F.data.startswith("payaccept_"))
async def adm_pay_accept(call: CallbackQuery, state: FSMContext):
    target_user_id = call.data.split("_")[1]
    await state.update_data(target_user_id=target_user_id, msg_id=call.message.message_id)
    await call.message.answer(f"Foydalanuvchi {target_user_id} balansiga qancha so'm qo'shmoqchisiz? (Faqat raqam yozing):")
    await state.set_state(AdminState.waiting_for_deposit_amount)

@dp.callback_query(F.data.startswith("payreject_"))
async def adm_pay_reject(call: CallbackQuery):
    target_user_id = call.data.split("_")[1]
    await bot.send_message(target_user_id, "❌ To'lov chekingiz admin tomonidan rad etildi.")
    await call.message.edit_caption(caption="❌ Rad etilgan")

@dp.message(AdminState.waiting_for_deposit_amount)
async def adm_save_deposit(message: Message, state: FSMContext):
    amount = int(message.text)
    data = await state.get_data()
    target_id, msg_id = data.get("target_user_id"), data.get("msg_id")
    
    res = supabase.table("users").select("balance").eq("telegram_id", target_id).execute()
    new_bal = res.data[0]["balance"] + amount
    supabase.table("users").update({"balance": new_bal}).eq("telegram_id", target_id).execute()
    
    await bot.send_message(target_id, f"🎉 Balansingizga {amount:,.0f} so'm qo'shildi! Joriy balans: {new_bal:,.0f} so'm")
    await message.answer("✅ Foydalanuvchi balansi to'ldirildi.")
    try: await bot.edit_message_caption(chat_id=message.chat.id, message_id=msg_id, caption=f"✅ Tasdiqlangan: {amount} so'm")
    except Exception: pass
    await state.clear()

# --- UC XARID QILISH ---
@dp.message(F.text == "🛒 UC Xarid qilish")
async def start_buying(message: Message, state: FSMContext):
    sub_ok, markup = await check_mandatory_subs(message.from_user.id)
    if not sub_ok: return await message.answer("Avval obuna bo'ling!", reply_markup=markup)
    
    await message.answer("🎮 Iltimos, PUBG ID raqamingizni kiriting:")
    await state.set_state(PurchaseState.waiting_for_pubg_id)

@dp.message(PurchaseState.waiting_for_pubg_id)
async def process_pubg_id(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("❌ Faqat raqam kiriting:")
    await state.update_data(pubg_id=message.text)
    
    res = supabase.table("uc_prices").select("*").order("uc_amount").execute()
    keyboard = []
    for item in res.data:
        keyboard.append([InlineKeyboardButton(text=f"{item['uc_amount']} UC - {item['price']:,.0f} so'm", callback_data=f"buy_{item['uc_amount']}")])
    
    await message.answer("👇 Qaysi paketni xarid qilasiz?", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await state.set_state(None)

@dp.callback_query(F.data.startswith("buy_"))
async def process_purchase(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    uc_amount = int(callback.data.split("_")[1])
    
    price_res = supabase.table("uc_prices").select("price").eq("uc_amount", uc_amount).execute()
    if not price_res.data: return await callback.answer("Paket topilmadi.", show_alert=True)
    price = price_res.data[0]['price']
    
    data = await state.get_data()
    pubg_id = data.get("pubg_id")
    
    user_res = supabase.table("users").select("balance").eq("telegram_id", user_id).execute()
    if user_res.data[0]["balance"] < price:
        return await callback.message.edit_text(f"❌ Mablag' yetarli emas. Kerakli: {price:,.0f} so'm")
        
    new_balance = user_res.data[0]["balance"] - price
    supabase.table("users").update({"balance": new_balance}).eq("telegram_id", user_id).execute()
    supabase.table("uc_purchases").insert({"telegram_id": user_id, "pubg_id": pubg_id, "uc_amount": uc_amount, "price": price, "status": "pending"}).execute()
    
    # Adminga xabar
    admins = supabase.table("users").select("telegram_id").eq("is_admin", True).execute().data
    for admin in admins:
        try: await bot.send_message(admin['telegram_id'], f"🔥 Yangi buyurtma!\nID: `{pubg_id}`\nPaket: {uc_amount} UC", parse_mode="Markdown")
        except Exception: pass

    await callback.message.edit_text(f"✅ Buyurtma qabul qilindi!\nID: {pubg_id}\nPaket: {uc_amount} UC\nTez orada tushirib beriladi.")

# ==========================================
#              ADMIN PANEL
# ==========================================
@dp.message(Command("adminmanku"))
async def make_me_admin(message: Message):
    supabase.table("users").update({"is_admin": True}).eq("telegram_id", message.from_user.id).execute()
    await message.answer("🎉 Siz adminsiz. Panelni ochish uchun /admin yuboring.")

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id): return
        
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Narxlarni tahrirlash", callback_data="adm_prices"),
         InlineKeyboardButton(text="➕ Yangi UC paket", callback_data="adm_add_uc")],
        [InlineKeyboardButton(text="💳 Karta raqamini sozlash", callback_data="adm_card"),
         InlineKeyboardButton(text="📢 Majburiy kanal qo'shish", callback_data="adm_add_ch")],
        [InlineKeyboardButton(text="📊 Statistika", callback_data="adm_stats")]
    ])
    await message.answer("👨‍💻 Admin Panel:", reply_markup=keyboard)

# -- KARTA RAQAMI --
@dp.callback_query(F.data == "adm_card")
async def adm_set_card(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Yangi karta raqamini va ism-familiyani yozing:")
    await state.set_state(AdminState.waiting_for_card)

@dp.message(AdminState.waiting_for_card)
async def adm_save_card(message: Message, state: FSMContext):
    supabase.table("settings").upsert({"key": "card_number", "value": message.text}).execute()
    await message.answer("✅ Karta raqami saqlandi.")
    await state.clear()

# -- YANGI UC PAKET --
@dp.callback_query(F.data == "adm_add_uc")
async def adm_add_uc(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Yangi paketda qancha UC bo'ladi? (Faqat raqam):")
    await state.set_state(AdminState.waiting_for_new_uc_amount)

@dp.message(AdminState.waiting_for_new_uc_amount)
async def adm_add_uc_amount(message: Message, state: FSMContext):
    await state.update_data(new_uc=int(message.text))
    await message.answer("Bu paketning narxi qancha bo'ladi (so'mda)?")
    await state.set_state(AdminState.waiting_for_new_uc_price_val)

@dp.message(AdminState.waiting_for_new_uc_price_val)
async def adm_add_uc_price(message: Message, state: FSMContext):
    data = await state.get_data()
    supabase.table("uc_prices").insert({"uc_amount": data['new_uc'], "price": int(message.text)}).execute()
    await message.answer(f"✅ {data['new_uc']} UC paketi qo'shildi!")
    await state.clear()

# -- STATISTIKA --
@dp.message(F.text == "📊 Statistika")
@dp.callback_query(F.data == "adm_stats")
async def show_stats(event):
    msg = event.message if isinstance(event, CallbackQuery) else event
    # Faqat adminlar ko'ra olsin, yoki hammaga ochiq qilsangiz is_admin ni olib tashlang.
    res_users = supabase.table("users").select("telegram_id", count="exact").execute()
    res_purchases = supabase.table("uc_purchases").select("id", count="exact").execute()
    text = f"📊 *STATISTIKA*\n\n👥 Umumiy foydalanuvchilar: {res_users.count}\n🛍 Umumiy UC buyurtmalar: {res_purchases.count}"
    await msg.answer(text, parse_mode="Markdown")

# -- KANAL QO'SHISH (qisqacha) --
@dp.callback_query(F.data == "adm_add_ch")
async def adm_add_ch(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Kanalning username yoki ID sini kiriting (masalan: @kanal_nomi yoki -100123):")
    await state.set_state(AdminState.waiting_for_channel_id)

@dp.message(AdminState.waiting_for_channel_id)
async def adm_save_ch_id(message: Message, state: FSMContext):
    await state.update_data(ch_id=message.text)
    await message.answer("Kanal nomini yozing (knopkada chiqadi):")
    await state.set_state(AdminState.waiting_for_channel_name)

@dp.message(AdminState.waiting_for_channel_name)
async def adm_save_ch_name(message: Message, state: FSMContext):
    data = await state.get_data()
    supabase.table("mandatory_channels").insert({"chat_id": data['ch_id'], "name": message.text, "url": f"https://t.me/{data['ch_id'].replace('@', '')}"}).execute()
    await message.answer("✅ Majburiy kanal qo'shildi! Botni o'sha kanalga admin qilishni unutmang.")
    await state.clear()

# --- ISHGA TUSHIRISH ---
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
