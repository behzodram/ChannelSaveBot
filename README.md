## 📝 Litsenziya

Shaxsiy foydalanish uchun ochiq.

# 📦 Channel Saqlagich Bot (Guruh ham)

Telegram'dagi kerakli kanal va guruhlaringizni **a'zo bo'lmasdan**, shunchaki forward orqali saqlab, keyinchalik tartibli ro'yxat ko'rinishida boshqarish uchun mo'ljallangan shaxsiy bot.

## ✨ Imkoniyatlari

- 📥 **Forward orqali qo'shish** — kerakli kanal yoki guruhdan istalgan xabarni botga forward qilasiz, bot avtomatik nomi, username va (agar public bo'lsa) profil rasmini aniqlaydi
- 🚫 **A'zolik shart emas** — bot hech qaysi kanal/guruhga qo'shilishi yoki admin bo'lishi kerak emas
- 📁 **Guruhlar** va 📢 **Kanallar** uchun alohida ro'yxat, doimiy pastki tugmalar orqali bir bosishda ochiladi
- 🔗 **Taklif havolasi** — public chatlar uchun avtomatik, private chatlar uchun qo'lda kiritiladi va saqlanadi
- ✏️ **Tahrirlash** — username, rasm va havolani istalgan vaqt yangilash mumkin
- 🗑 **O'chirish** — keraksiz yozuvlarni ro'yxatdan olib tashlash
- 👤 **Har bir foydalanuvchi uchun alohida** — ma'lumotlar `owner_id` orqali ajratiladi, har kim faqat o'zi qo'shgan kanal/guruhlarni ko'radi
- 🗄 **SQLite** asosida ishonchli mahalliy saqlash

## 🛠 Texnologiyalar

| Texnologiya | Vazifasi |
|---|---|
| Python 3.13+ | Asosiy til |
| [aiogram 3.x](https://docs.aiogram.dev/) | Telegram Bot API framework |
| SQLite3 | Ma'lumotlar bazasi |

## 📋 Talablar

- Python 3.10 yoki undan yuqori
- Telegram Bot tokeni ([@BotFather](https://t.me/BotFather) orqali olinadi)

## ⚙️ O'rnatish

1. Repozitoriyani yuklab oling yoki kodni `main.py` nomi bilan saqlang

2. Kerakli kutubxonani o'rnating:
```bash
pip install aiogram
```

3. `main.py` faylida botingiz tokenini kiriting:
```python
API_TOKEN = "BOT_TOKEN_BU_YERGA"
```

4. Botni ishga tushiring:
```bash
python main.py
```

Ishga tushgach, konsolda quyidagiga o'xshash qator chiqishi kerak:# ChannelSaveBot
