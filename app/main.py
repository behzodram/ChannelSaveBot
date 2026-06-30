import asyncio
import logging
import sqlite3
import secrets
from io import BytesIO

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest

from config import API_TOKEN
DB_PATH = "data.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

BTN_GROUPS = "📁 Guruhlar"
BTN_CHANNELS = "📢 Kanallar"
BTN_BOTS = "🤖 Botlar"
BTN_MY_CODE = "🔑 Mening kodim"
BTN_OPEN_CODE = "🔍 Kod orqali ko'rish"

TYPE_LABELS = {"group": "Guruhlar", "channel": "Kanallar", "bot": "Botlar"}
TYPE_LABEL_SINGULAR = {"group": "guruh", "channel": "kanal", "bot": "bot"}


# ==================== DATABASE ====================
def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            share_uuid TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            chat_id INTEGER,
            chat_type TEXT NOT NULL,        -- 'group' | 'channel' | 'bot'
            title TEXT,
            username TEXT,
            photo_file_id TEXT,
            sendable_photo_id TEXT,
            invite_link TEXT,
            is_public INTEGER NOT NULL DEFAULT 0,   -- 0 = private (default), 1 = public
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def generate_uuid16() -> str:
    return secrets.token_hex(8)  # 16 ta hex belgi


def get_or_create_user_uuid(telegram_id: int) -> str:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT share_uuid FROM users WHERE telegram_id=?", (telegram_id,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row["share_uuid"]

    while True:
        new_uuid = generate_uuid16()
        cur.execute("SELECT 1 FROM users WHERE share_uuid=?", (new_uuid,))
        if not cur.fetchone():
            break

    cur.execute("INSERT INTO users (telegram_id, share_uuid) VALUES (?, ?)", (telegram_id, new_uuid))
    conn.commit()
    conn.close()
    return new_uuid


def get_owner_by_uuid(share_uuid: str):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT telegram_id FROM users WHERE share_uuid=?", (share_uuid,))
    row = cur.fetchone()
    conn.close()
    return row["telegram_id"] if row else None


def add_chat(owner_id, chat_id, chat_type, title, username, photo_file_id, invite_link=None):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO chats (owner_id, chat_id, chat_type, title, username, photo_file_id, invite_link, is_public)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
    """, (owner_id, chat_id, chat_type, title, username, photo_file_id, invite_link))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


def get_user_chats(owner_id, chat_type):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM chats WHERE owner_id=? AND chat_type=? ORDER BY id DESC",
        (owner_id, chat_type)
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_public_chats(owner_id, chat_type):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM chats WHERE owner_id=? AND chat_type=? AND is_public=1 ORDER BY id DESC",
        (owner_id, chat_type)
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_chat_by_id(record_id, owner_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM chats WHERE id=? AND owner_id=?", (record_id, owner_id))
    row = cur.fetchone()
    conn.close()
    return row


def get_public_chat_by_id(record_id, owner_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM chats WHERE id=? AND owner_id=? AND is_public=1", (record_id, owner_id))
    row = cur.fetchone()
    conn.close()
    return row


def update_chat_field(record_id, owner_id, field, value):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(f"UPDATE chats SET {field}=? WHERE id=? AND owner_id=?", (value, record_id, owner_id))
    conn.commit()
    conn.close()


def delete_chat(record_id, owner_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM chats WHERE id=? AND owner_id=?", (record_id, owner_id))
    conn.commit()
    conn.close()


# ==================== STATES ====================
class EditStates(StatesGroup):
    waiting_username = State()
    waiting_photo = State()
    waiting_invite_link = State()


class ViewStates(StatesGroup):
    waiting_uuid_code = State()


# ==================== KEYBOARDS ====================
def persistent_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_GROUPS), KeyboardButton(text=BTN_CHANNELS)],
            [KeyboardButton(text=BTN_BOTS)],
            [KeyboardButton(text=BTN_MY_CODE), KeyboardButton(text=BTN_OPEN_CODE)],
        ],
        resize_keyboard=True,
        is_persistent=True
    )


# ==================== START ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    get_or_create_user_uuid(message.from_user.id)
    await message.answer(
        "Salom!\n\n"
        "📁/📢 Kanal yoki guruhdagi istalgan xabarni, 🤖 esa botning istalgan xabarini "
        "menga <b>forward</b> qiling — men uni avtomatik saqlab qo'yaman.\n\n"
        "Har bir saqlangan element <b>shaxsiy (private)</b> bo'lib qo'shiladi — uni faqat siz ko'rasiz. "
        "Xohlagan elementni \"ommaviy\" qilib, o'z kodingiz orqali boshqalarga ko'rsatishingiz mumkin.\n\n"
        "Pastdagi doimiy tugmalardan foydalaning 👇",
        reply_markup=persistent_kb()
    )


# ==================== MENING KODIM ====================
@dp.message(F.text == BTN_MY_CODE)
async def my_code(message: types.Message):
    uuid_code = get_or_create_user_uuid(message.from_user.id)
    await message.answer(
        f"🔑 Sizning shaxsiy kodingiz:\n\n<code>{uuid_code}</code>\n\n"
        f"Bu kodni boshqa kishiga bersangiz, u sizning <b>faqat ommaviy qilingan</b> "
        f"kanal/guruh/botlaringizni ko'ra oladi (tahrirlay yoki o'chira olmaydi).",
    )


# ==================== KOD ORQALI KO'RISH ====================
@dp.message(F.text == BTN_OPEN_CODE)
async def open_code_start(message: types.Message, state: FSMContext):
    await state.set_state(ViewStates.waiting_uuid_code)
    await message.answer("Ko'rmoqchi bo'lgan foydalanuvchining 16 xonali kodini yuboring:")


@dp.message(StateFilter(ViewStates.waiting_uuid_code))
async def open_code_finish(message: types.Message, state: FSMContext):
    code = message.text.strip()
    await state.clear()

    owner_id = get_owner_by_uuid(code)
    if not owner_id:
        await message.answer("❌ Bunday kod topilmadi. Kodni tekshirib qaytadan urinib ko'ring.", reply_markup=persistent_kb())
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Guruhlar", callback_data=f"shmenu_group_{owner_id}")],
        [InlineKeyboardButton(text="📢 Kanallar", callback_data=f"shmenu_channel_{owner_id}")],
        [InlineKeyboardButton(text="🤖 Botlar", callback_data=f"shmenu_bot_{owner_id}")],
    ])
    await message.answer("✅ Kod to'g'ri. Qaysi bo'limni ko'rmoqchisiz?", reply_markup=kb)
    await message.answer("Asosiy menyu:", reply_markup=persistent_kb())


# ==================== RO'YXATNI KO'RSATISH (O'ZINIKI) ====================
@dp.message(F.text == BTN_GROUPS)
async def btn_groups(message: types.Message):
    await send_list(message, "group")


@dp.message(F.text == BTN_CHANNELS)
async def btn_channels(message: types.Message):
    await send_list(message, "channel")


@dp.message(F.text == BTN_BOTS)
async def btn_bots(message: types.Message):
    await send_list(message, "bot")


async def send_list(message: types.Message, chat_type: str):
    rows = get_user_chats(message.from_user.id, chat_type)
    label = TYPE_LABELS[chat_type]

    if not rows:
        await message.answer(
            f"Hozircha {label.lower()} saqlanmagan.\n\n"
            f"Kerakli {TYPE_LABEL_SINGULAR[chat_type]}dan istalgan xabarni shu botga forward qiling."
        )
        return

    buttons = []
    for row in rows:
        mark = "🌐" if row["is_public"] else "🔒"
        text = f"{mark} {row['title'] or 'Nomsiz'}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"item_{row['id']}")])

    await message.answer(
        f"📋 {label} ro'yxati  (🌐 = ommaviy, 🔒 = shaxsiy):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


# ==================== RO'YXATNI KO'RSATISH (BOSHQA USER, KOD ORQALI) ====================
@dp.callback_query(F.data.startswith("shmenu_"))
async def shared_menu(callback: types.CallbackQuery):
    _, chat_type, owner_id_str = callback.data.split("_")
    owner_id = int(owner_id_str)
    rows = get_public_chats(owner_id, chat_type)
    label = TYPE_LABELS[chat_type]

    if not rows:
        await callback.message.edit_text(f"Bu foydalanuvchida ommaviy {label.lower()} mavjud emas.")
        await callback.answer()
        return

    buttons = []
    for row in rows:
        text = row["title"] or "Nomsiz"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"sitem_{row['id']}_{owner_id}")])

    await callback.message.edit_text(
        f"📋 Ommaviy {label.lower()} ro'yxati:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


# ==================== FORWARD: KANAL / GURUH ====================
@dp.message(F.forward_from_chat)
async def on_forwarded_chat(message: types.Message, state: FSMContext):
    fchat = message.forward_from_chat
    chat_type = "channel" if fchat.type == ChatType.CHANNEL else "group"

    photo_file_id = None
    invite_link = None
    if fchat.username:
        try:
            full_chat = await bot.get_chat(f"@{fchat.username}")
            if full_chat.photo:
                photo_file_id = full_chat.photo.big_file_id
        except Exception:
            pass
        invite_link = f"https://t.me/{fchat.username}"

    await state.update_data(
        chat_id=fchat.id, chat_type=chat_type, title=fchat.title,
        username=fchat.username, photo_file_id=photo_file_id, invite_link=invite_link
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Guruh sifatida saqlash", callback_data="confirm_group")],
        [InlineKeyboardButton(text="📢 Kanal sifatida saqlash", callback_data="confirm_channel")],
    ])
    username_text = f"@{fchat.username}" if fchat.username else "yo'q (private)"
    link_text = invite_link if invite_link else "topilmadi (keyin qo'lda qo'shasiz)"
    await message.answer(
        f"Aniqlandi:\n<b>{fchat.title}</b>\nUsername: {username_text}\n"
        f"Taklif havolasi: {link_text}\n"
        f"Rasm: {'topildi ✅' if photo_file_id else 'topilmadi'}\n\n"
        f"Qaysi bo'limga saqlaymiz? (default: shaxsiy/private)",
        reply_markup=kb
    )


# ==================== FORWARD: BOT ====================
@dp.message(F.forward_from, F.forward_from.is_bot == True)
async def on_forwarded_bot(message: types.Message, state: FSMContext):
    fuser = message.forward_from

    photo_file_id = None
    if fuser.username:
        try:
            full_chat = await bot.get_chat(f"@{fuser.username}")
            if full_chat.photo:
                photo_file_id = full_chat.photo.big_file_id
        except Exception:
            pass

    invite_link = f"https://t.me/{fuser.username}" if fuser.username else None
    title = fuser.full_name or fuser.username or "Nomsiz bot"

    await state.update_data(
        chat_id=fuser.id, chat_type="bot", title=title,
        username=fuser.username, photo_file_id=photo_file_id, invite_link=invite_link
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Bot sifatida saqlash", callback_data="confirm_bot")],
    ])
    username_text = f"@{fuser.username}" if fuser.username else "yo'q"
    link_text = invite_link if invite_link else "topilmadi"
    await message.answer(
        f"Aniqlandi:\n<b>{title}</b>\nUsername: {username_text}\n"
        f"Taklif havolasi: {link_text}\n"
        f"Rasm: {'topildi ✅' if photo_file_id else 'topilmadi'}\n\n"
        f"Saqlaymizmi? (default: shaxsiy/private)",
        reply_markup=kb
    )


@dp.callback_query(F.data.in_(["confirm_group", "confirm_channel", "confirm_bot"]))
async def confirm_add(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    chat_type_map = {"confirm_group": "group", "confirm_channel": "channel", "confirm_bot": "bot"}
    chat_type = chat_type_map[callback.data]

    add_chat(
        owner_id=callback.from_user.id, chat_id=data.get("chat_id"), chat_type=chat_type,
        title=data.get("title"), username=data.get("username"),
        photo_file_id=data.get("photo_file_id"), invite_link=data.get("invite_link")
    )
    await state.clear()

    extra = ""
    if not data.get("invite_link"):
        extra = "\n\n⚠️ Taklif havolasi topilmadi. Ro'yxatda elementni ochib qo'lda qo'shing."

    await callback.message.edit_text(
        f"✅ <b>{data.get('title')}</b> saqlandi (🔒 shaxsiy holatda).{extra}"
    )
    await callback.answer()


# ==================== RASMNI XAVFSIZ YUBORISH ====================
async def get_sendable_photo(record_id: int, owner_id: int, photo_file_id: str):
    row = get_chat_by_id(record_id, owner_id)
    if row and row["sendable_photo_id"]:
        return row["sendable_photo_id"]
    try:
        file = await bot.get_file(photo_file_id)
        buffer = BytesIO()
        await bot.download_file(file.file_path, destination=buffer)
        buffer.seek(0)
        return BufferedInputFile(buffer.read(), filename="chat_photo.jpg")
    except Exception as e:
        logging.warning(f"Rasmni yuklab bo'lmadi: {e}")
        return None


# ==================== ITEM DETAIL (O'ZINIKI — TO'LIQ HUQUQ) ====================
@dp.callback_query(F.data.startswith("item_"))
async def show_item(callback: types.CallbackQuery):
    record_id = int(callback.data.split("_")[1])
    row = get_chat_by_id(record_id, callback.from_user.id)
    if not row:
        await callback.answer("Topilmadi", show_alert=True)
        return

    username_text = f"@{row['username']}" if row["username"] else "—"
    link_text = row["invite_link"] if row["invite_link"] else "❌ Hali kiritilmagan"
    type_label = TYPE_LABEL_SINGULAR.get(row["chat_type"], row["chat_type"])
    visibility = "🌐 Ommaviy" if row["is_public"] else "🔒 Shaxsiy"
    caption = (
        f"<b>{row['title']}</b>\n"
        f"Username: {username_text}\n"
        f"Turi: {type_label}\n"
        f"Holati: {visibility}\n"
        f"Havola: {link_text}"
    )

    toggle_text = "🔒 Shaxsiy qilish" if row["is_public"] else "🌐 Ommaviy qilish"
    kb_buttons = []
    if row["invite_link"]:
        kb_buttons.append([InlineKeyboardButton(text="🔗 O'tish", url=row["invite_link"])])
    kb_buttons += [
        [InlineKeyboardButton(text=toggle_text, callback_data=f"toggle_{record_id}")],
        [InlineKeyboardButton(text="✏️ Username o'zgartirish", callback_data=f"edit_username_{record_id}")],
        [InlineKeyboardButton(text="🔗 Havolani o'zgartirish/qo'shish", callback_data=f"edit_link_{record_id}")],
        [InlineKeyboardButton(text="🖼 Rasmni o'zgartirish", callback_data=f"edit_photo_{record_id}")],
        [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"delete_{record_id}")],
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

    await _render_item(callback, row, record_id, callback.from_user.id, caption, kb)


# ==================== ITEM DETAIL (BOSHQA USER — FAQAT KO'RISH) ====================
@dp.callback_query(F.data.startswith("sitem_"))
async def show_shared_item(callback: types.CallbackQuery):
    _, record_id_str, owner_id_str = callback.data.split("_")
    record_id, owner_id = int(record_id_str), int(owner_id_str)

    row = get_public_chat_by_id(record_id, owner_id)
    if not row:
        await callback.answer("Topilmadi yoki endi ommaviy emas", show_alert=True)
        return

    username_text = f"@{row['username']}" if row["username"] else "—"
    link_text = row["invite_link"] if row["invite_link"] else "❌ Mavjud emas"
    type_label = TYPE_LABEL_SINGULAR.get(row["chat_type"], row["chat_type"])
    caption = (
        f"<b>{row['title']}</b>\n"
        f"Username: {username_text}\n"
        f"Turi: {type_label}\n"
        f"Havola: {link_text}"
    )

    kb_buttons = []
    if row["invite_link"]:
        kb_buttons.append([InlineKeyboardButton(text="🔗 O'tish", url=row["invite_link"])])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons) if kb_buttons else None

    await _render_item(callback, row, record_id, owner_id, caption, kb)


async def _render_item(callback, row, record_id, owner_id, caption, kb):
    """Rasm bilan yoki rasmsiz elementni chiqarish (umumiy yordamchi funksiya)."""
    sent_as_photo = False
    if row["photo_file_id"]:
        photo_to_send = await get_sendable_photo(record_id, owner_id, row["photo_file_id"])
        if photo_to_send:
            try:
                await callback.message.delete()
                sent_msg = await callback.message.answer_photo(photo=photo_to_send, caption=caption, reply_markup=kb)
                sent_as_photo = True
                if isinstance(photo_to_send, BufferedInputFile):
                    new_file_id = sent_msg.photo[-1].file_id
                    update_chat_field(record_id, owner_id, "sendable_photo_id", new_file_id)
            except TelegramBadRequest as e:
                logging.warning(f"Photo yuborishda xato: {e}")

    if not sent_as_photo:
        try:
            await callback.message.edit_text(caption, reply_markup=kb)
        except TelegramBadRequest:
            await callback.message.answer(caption, reply_markup=kb)

    await callback.answer()


# ==================== PUBLIC/PRIVATE TOGGLE ====================
@dp.callback_query(F.data.startswith("toggle_"))
async def toggle_visibility(callback: types.CallbackQuery):
    record_id = int(callback.data.split("_")[1])
    row = get_chat_by_id(record_id, callback.from_user.id)
    if not row:
        await callback.answer("Topilmadi", show_alert=True)
        return

    new_value = 0 if row["is_public"] else 1
    update_chat_field(record_id, callback.from_user.id, "is_public", new_value)
    await callback.answer("🌐 Endi ommaviy" if new_value else "🔒 Endi shaxsiy", show_alert=False)

    # Yangilangan holatni qayta ko'rsatish uchun show_item logikasini qayta chaqiramiz
    callback.data = f"item_{record_id}"
    await show_item(callback)


# ==================== EDIT USERNAME ====================
@dp.callback_query(F.data.startswith("edit_username_"))
async def edit_username_start(callback: types.CallbackQuery, state: FSMContext):
    record_id = int(callback.data.split("_")[2])
    await state.update_data(record_id=record_id)
    await state.set_state(EditStates.waiting_username)
    await callback.message.answer("Yangi username kiriting (masalan: @mychannel) yoki '-' (bo'sh qilish uchun):")
    await callback.answer()


@dp.message(StateFilter(EditStates.waiting_username))
async def edit_username_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    record_id = data["record_id"]
    new_username = None if message.text.strip() == "-" else message.text.replace("@", "").strip()
    update_chat_field(record_id, message.from_user.id, "username", new_username)
    await message.answer("✅ Username yangilandi.", reply_markup=persistent_kb())
    await state.clear()


# ==================== EDIT INVITE LINK ====================
@dp.callback_query(F.data.startswith("edit_link_"))
async def edit_link_start(callback: types.CallbackQuery, state: FSMContext):
    record_id = int(callback.data.split("_")[2])
    await state.update_data(record_id=record_id)
    await state.set_state(EditStates.waiting_invite_link)
    await callback.message.answer(
        "Taklif havolasini yuboring (masalan: https://t.me/+AbCdEfGhIjK), yoki '-' (o'chirish uchun):"
    )
    await callback.answer()


@dp.message(StateFilter(EditStates.waiting_invite_link))
async def edit_link_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    record_id = data["record_id"]
    new_link = None if message.text.strip() == "-" else message.text.strip()
    update_chat_field(record_id, message.from_user.id, "invite_link", new_link)
    await message.answer("✅ Taklif havolasi yangilandi.", reply_markup=persistent_kb())
    await state.clear()


# ==================== EDIT PHOTO ====================
@dp.callback_query(F.data.startswith("edit_photo_"))
async def edit_photo_start(callback: types.CallbackQuery, state: FSMContext):
    record_id = int(callback.data.split("_")[2])
    await state.update_data(record_id=record_id)
    await state.set_state(EditStates.waiting_photo)
    await callback.message.answer("Yangi rasmni yuboring:")
    await callback.answer()


@dp.message(StateFilter(EditStates.waiting_photo), F.photo)
async def edit_photo_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    record_id = data["record_id"]
    file_id = message.photo[-1].file_id
    update_chat_field(record_id, message.from_user.id, "photo_file_id", file_id)
    update_chat_field(record_id, message.from_user.id, "sendable_photo_id", file_id)
    await message.answer("✅ Rasm yangilandi.", reply_markup=persistent_kb())
    await state.clear()


# ==================== DELETE ====================
@dp.callback_query(F.data.startswith("delete_"))
async def delete_item(callback: types.CallbackQuery):
    record_id = int(callback.data.split("_")[1])
    delete_chat(record_id, callback.from_user.id)
    await callback.message.answer("🗑 O'chirildi.", reply_markup=persistent_kb())
    await callback.answer()


# ==================== RUN ====================
async def main():
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())