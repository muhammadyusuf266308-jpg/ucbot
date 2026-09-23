# 🎬 Kino Telegram Boti

**Railway + Supabase** uchun moslashtirilgan Telegram kino qidiruv boti.

---

## ⚡ Tez ishga tushirish

### 1. Supabase bazasi yaratish
1. [supabase.com](https://supabase.com) → yangi loyiha yarating
2. **Settings → Database → Connection string → URI** ni nusxalang
3. URI ko'rinishi: `postgresql://postgres:[parol]@db.[ref].supabase.co:5432/postgres`

### 2. Telegram sozlamalari
| Nima kerak | Qayerdan |
|---|---|
| `BOT_TOKEN` | @BotFather → `/newbot` |
| `ADMIN_ID` | @userinfobot → `/start` |
| `API_ID` / `API_HASH` | [my.telegram.org/apps](https://my.telegram.org/apps) |

### 3. .env fayl yaratish (lokal uchun)
```bash
cp .env.example .env
# .env faylni to'ldiring
```

### 4. O'rnatish va ishga tushirish
```powershell
pip install -r requirements.txt
python bot.py
```

---

## 🚂 Railway ga deploy qilish

### 1. GitHub ga yuklash
```bash
git init
git add .
git commit -m "initial"
git remote add origin https://github.com/SIZMINGIT/movie-bot.git
git push -u origin main
```

### 2. Railway da loyiha ochish
1. [railway.app](https://railway.app) → **New Project → Deploy from GitHub**
2. Reponi tanlang

### 3. Environment Variables qo'shish
Railway → loyiha → **Variables** bo'limiga:

```
BOT_TOKEN      = 1234567890:AAHxxx...
ADMIN_ID       = 123456789
CHANNEL_ID     = @mening_kanalim
GROUP_ID       =                    (bo'sh qoldirsa bo'ladi)
API_ID         = 12345678
API_HASH       = abcdef1234...
DATABASE_URL   = postgresql://postgres:...@db...supabase.co:5432/postgres
```

### 4. Deploy
Railway avtomatik `Procfile` ni o'qib botni ishga tushiradi. ✅

---

## 📺 Kanalda post formati

Kanalga post qo'shganda bot **avtomatik** DB ga saqlaydi:

```
🎬 Kino nomi
🇷🇺 Rus nomi
🇬🇧 Ingliz nomi
📅 2024
🎭 Drama, Action
📝 Qisqa tavsif

/movie001
```

> **Minimal variant** (faqat 2 qator yetarli):
> ```
> Titanic
> 
> /movie042
> ```

**Muhim:** `/movie001` — bu bot kodi, **majburiy** va **noyob** bo'lishi kerak!

---

## 🔄 Mavjud kanal postlarini yuklash

Kanalda allaqachon postlar bo'lsa, ularni bir marta yuklab olish:

```powershell
# Lokal terminalda:
python sync_channel.py
```

Yoki botga `/sync` buyrug'ini yuboring (admin sifatida).

---

## 👑 Admin buyruqlari

| Buyruq | Tavsif |
|---|---|
| `/sync` | Kanaldan barcha postlarni yuklash |
| `/listmovies` | Kinolar ro'yxati |
| `/delmovie 5` | Kino o'chirish (ID bo'yicha) |
| `/stats` | Statistika |

---

## 📁 Fayl tuzilmasi

```
movie-bot/
├── .env              ← To'ldiring! (gitignore da)
├── .env.example      ← Namuna
├── .gitignore
├── Procfile          ← Railway/Heroku
├── railway.toml      ← Railway sozlamalari
├── requirements.txt
├── bot.py            ← Asosiy bot
├── config.py         ← .env yuklash
├── database.py       ← Supabase/PostgreSQL
├── channel_parser.py ← Post tahlilchi
└── sync_channel.py   ← Bir martalik yuklash
```

---

## ❓ Savollar

**Guruh ID ni qanday bilaman?**
Botni guruhga qo'shing, `/start` yuboring. Log da `Chat=XXXXXX` chiqadi.

**Bot kanalda postlarni ko'ra olmaydi?**
Botni kanalga **admin** sifatida qo'shing.

**Railway da `sync_session` fayli muammo qiladi?**
`/sync` buyrug'i lokal qurilmada ishlatish uchun mo'ljallangan. Railway da faqat `on_channel_post` ishlaydi (yangi postlar uchun).
