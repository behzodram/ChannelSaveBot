## 📱 Foydalanish

1. Botga `/start` yuboring — pastda doimiy **📁 Guruhlar** va **📢 Kanallar** tugmalari paydo bo'ladi
2. Saqlamoqchi bo'lgan kanal yoki guruhdan istalgan postni botga **forward** qiling
3. Bot aniqlagan ma'lumotni ko'rsatadi va **"📁 Guruh sifatida saqlash"** yoki **"📢 Kanal sifatida saqlash"** tugmasini bosib tasdiqlaysiz
4. Agar kanal/guruh **private** bo'lsa, taklif havolasi avtomatik topilmaydi — saqlangach, elementni ochib **"🔗 Havolani o'zgartirish/qo'shish"** orqali qo'lda kiritasiz
5. Ro'yxatni ko'rish uchun istalgan vaqt pastdagi **📁 Guruhlar** / **📢 Kanallar** tugmasini bosing
6. Elementni tanlaganingizda nomi, username, turi, havolasi va (mavjud bo'lsa) rasmi bilan ochiladi — shu yerdan tahrirlash yoki o'chirish mumkin

## 🗄 Ma'lumotlar bazasi tuzilishi

`chats` jadvali (`bot.db`):

| Ustun | Turi | Tavsifi |
|---|---|---|
| `id` | INTEGER (PK) | Avtomatik ID |
| `owner_id` | INTEGER | Botdan foydalanuvchi Telegram ID'si |
| `chat_id` | INTEGER | Forward qilingan kanal/guruh Telegram ID'si |
| `chat_type` | TEXT | `group` yoki `channel` |
| `title` | TEXT | Kanal/guruh nomi |
| `username` | TEXT | Public username (bo'lmasa `NULL`) |
| `photo_file_id` | TEXT | Profil rasmining manba `file_id`'si |
| `sendable_photo_id` | TEXT | Telegramga qayta yuborish uchun keshlangan `file_id` |
| `invite_link` | TEXT | Taklif havolasi |
| `created_at` | TIMESTAMP | Qo'shilgan sana/vaqt |

## ⚠️ Texnik cheklovlar

- **Private kanal/guruh rasmi**: bot a'zo bo'lmagani uchun private chatlarning profil rasmini avtomatik ololmaydi — qo'lda rasm yuklash kerak bo'ladi
- **Private kanal/guruh havolasi**: bot a'zo/admin bo'lmagani sababli taklif havolasini o'zi yarata olmaydi (Telegram API cheklovi) — qo'lda kiritiladi
- **ChatPhoto xatosi**: kanal profilidagi rasm file_id'si to'g'ridan-to'g'ri qayta yuborib bo'lmaydigan maxsus turdagi bo'lgani uchun, bot uni avval serverdan yuklab, qaytadan jo'natadi (birinchi safar biroz sekinroq, keyingi safarlar keshlangani uchun tezroq ishlaydi)

## 🔄 Bazani yangilash (eski versiyadan o'tayotganlar uchun)

Agar avval botni `sendable_photo_id` ustuni qo'shilmagan versiyada ishlatgan bo'lsangiz, yangi versiyaga o'tishdan oldin quyidagi skriptni bir marta ishga tushiring:

```python
import sqlite3
conn = sqlite3.connect("bot.db")
conn.execute("ALTER TABLE chats ADD COLUMN sendable_photo_id TEXT")
conn.commit()
conn.close()
print("Migratsiya tugadi")
```

Yoki, agar saqlangan ma'lumotlar muhim bo'lmasa, shunchaki `bot.db` faylini o'chiring — bot qayta ishga tushganda yangi struktura bilan avtomatik yaratadi.

## 📂 Loyiha tuzilishi