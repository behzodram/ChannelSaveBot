import asyncio
import logging
import sqlite3
import secrets
import re
from io import BytesIO
from datetime import datetime, timedelta

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

BTN_GROUPS    = "📁 Guruhlar"
BTN_CHANNELS  = "📢 Kanallar"
BTN_BOTS      = "🤖 Botlar"
BTN_MY_CODE   = "🔑 Kodlarim"
BTN_OPEN_CODE = "🔍 Kod orqali ko'rish"

TYPE_LABELS         = {"group": "Guruhlar", "channel": "Kanallar", "bot": "Botlar"}
TYPE_LABEL_SINGULAR = {"group": "guruh",    "channel": "kanal",    "bot": "bot"}

DURATION_PRESETS = [
    ("⏱ 1 soat",  60),
    ("⏱ 6 soat",  360),
    ("⏱ 12 soat", 720),
    ("📅 1 kun",   1440),
    ("📅 3 kun",   4320),
    ("📅 7 kun",   10080),
]


# ==================== DATABASE ====================
def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            chat_id INTEGER,
            chat_type TEXT NOT NULL,
            title TEXT,
            username TEXT,
            photo_file_id TEXT,
            sendable_photo_id TEXT,
            invite_link TEXT,
            is_public INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS share_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            code TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS saved_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            viewer_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            share_uuid TEXT NOT NULL,
            custom_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(viewer_id, share_uuid)
        )
    """)
    conn.commit()
    conn.close()


# ---------- share_codes ----------
def _generate_unique_code() -> str:
    conn = db_connect()
    cur = conn.cursor()
    while True:
        code = secrets.token_hex(8)
        cur.execute("SELECT 1 FROM share_codes WHERE code=?", (code,))
        if not cur.fetchone():
            conn.close()
            return code


def create_share_code(owner_id: int, minutes: int) -> str:
    code = _generate_unique_code()
    expires_at = (datetime.utcnow() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    conn = db_connect()
    conn.execute(
        "INSERT INTO share_codes (owner_id, code, expires_at) VALUES (?, ?, ?)",
        (owner_id, code, expires_at)
    )
    conn.commit()
    conn.close()
    return code


def get_user_codes(owner_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM share_codes WHERE owner_id=? ORDER BY created_at DESC", (owner_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_code_record_by_id(code_id: int, owner_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM share_codes WHERE id=? AND owner_id=?", (code_id, owner_id))
    row = cur.fetchone()
    conn.close()
    return row


def get_owner_by_code(code: str):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT owner_id FROM share_codes WHERE code=? AND expires_at > datetime('now')", (code,)
    )
    row = cur.fetchone()
    conn.close()
    return row["owner_id"] if row else None


def is_code_valid(code: str) -> bool:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM share_codes WHERE code=? AND expires_at > datetime('now')", (code,)
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def delete_share_code(code_id: int, owner_id: int):
    conn = db_connect()
    conn.execute("DELETE FROM share_codes WHERE id=? AND owner_id=?", (code_id, owner_id))
    conn.commit()
    conn.close()


def delete_expired_codes(owner_id: int):
    conn = db_connect()
    conn.execute(
        "DELETE FROM share_codes WHERE owner_id=? AND expires_at <= datetime('now')", (owner_id,)
    )
    conn.commit()
    conn.close()


def format_remaining(expires_at_str: str) -> str:
    try:
        exp = datetime.strptime(expires_at_str, "%Y-%m-%d %H:%M:%S")
        diff = exp - datetime.utcnow()
        if diff.total_seconds() <= 0:
            return "⛔ Muddati tugagan"
        s = int(diff.total_seconds())
        days, s = divmod(s, 86400)
        hours, s = divmod(s, 3600)
        minutes = s // 60
        if days > 0:
            return f"⏳ {days} kun {hours} soat qoldi"
        elif hours > 0:
            return f"⏳ {hours} soat {minutes} daqiqa qoldi"
        else:
            return f"⏳ {minutes} daqiqa qoldi"
    except Exception:
        return "⏳ ?"


# ---------- saved_codes ----------
def save_code_for_viewer(viewer_id, owner_id, share_uuid):
    conn = db_connect()
    conn.execute(
        "INSERT OR IGNORE INTO saved_codes (viewer_id, owner_id, share_uuid) VALUES (?, ?, ?)",
        (viewer_id, owner_id, share_uuid)
    )
    conn.commit()
    conn.close()


def get_saved_codes(viewer_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM saved_codes WHERE viewer_id=? ORDER BY id DESC", (viewer_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_saved_code_by_id(saved_id, viewer_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM saved_codes WHERE id=? AND viewer_id=?", (saved_id, viewer_id))
    row = cur.fetchone()
    conn.close()
    return row


def update_saved_code_name(saved_id, viewer_id, name):
    conn = db_connect()
    conn.execute(
        "UPDATE saved_codes SET custom_name=? WHERE id=? AND viewer_id=?", (name, saved_id, viewer_id)
    )
    conn.commit()
    conn.close()


def delete_saved_code(saved_id, viewer_id):
    conn = db_connect()
    conn.execute("DELETE FROM saved_codes WHERE id=? AND viewer_id=?", (saved_id, viewer_id))
    conn.commit()
    conn.close()


# ---------- chats ----------
def add_chat(owner_id, chat_id, chat_type, title, username, photo_file_id, invite_link=None):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO chats (owner_id, chat_id, chat_type, title, username,
                           photo_file_id, invite_link, is_public)
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
    cur.execute(
        "SELECT * FROM chats WHERE id=? AND owner_id=? AND is_public=1", (record_id, owner_id)
    )
    row = cur.fetchone()
    conn.close()
    return row


def update_chat_field(record_id, owner_id, field, value):
    conn = db_connect()
    conn.execute(
        f"UPDATE chats SET {field}=? WHERE id=? AND owner_id=?", (value, record_id, owner_id)
    )
    conn.commit()
    conn.close()


def delete_chat(record_id, owner_id):
    conn = db_connect()
    conn.execute("DELETE FROM chats WHERE id=? AND owner_id=?", (record_id, owner_id))
    conn.commit()
    conn.close()


# ==================== YORDAMCHI: LINK → USERNAME ====================
def extract_username_from_text(text: str) -> str | None:
    """
    Quyidagi formatlardan username ajratib oladi:
      https://t.me/username
      t.me/username
      @username
      username (faqat harf/raqam/_)
    """
    text = text.strip()
    # t.me/username yoki https://t.me/username
    m = re.match(r"(?:https?://)?t\.me/([A-Za-z0-9_]{4,})", text)
    if m:
        return m.group(1)
    # @username
    m = re.match(r"@([A-Za-z0-9_]{4,})", text)
    if m:
        return m.group(1)
    # Faqat username
    m = re.match(r"^([A-Za-z0-9_]{4,})$", text)
    if m:
        return m.group(1)
    return None


# ==================== STATES ====================
class EditStates(StatesGroup):
    waiting_username    = State()
    waiting_photo       = State()
    waiting_invite_link = State()


class SharedCodeStates(StatesGroup):
    waiting_new_code = State()
    waiting_rename   = State()


class ShareCodeStates(StatesGroup):
    waiting_custom_duration = State()


class AddGroupStates(StatesGroup):
    waiting_link = State()


# ==================== KEYBOARDS ====================
def persistent_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_GROUPS),   KeyboardButton(text=BTN_CHANNELS)],
            [KeyboardButton(text=BTN_BOTS)],
            [KeyboardButton(text=BTN_MY_CODE),  KeyboardButton(text=BTN_OPEN_CODE)],
        ],
        resize_keyboard=True,
        is_persistent=True
    )


def duration_kb():
    buttons = []
    row = []
    for label, minutes in DURATION_PRESETS:
        row.append(InlineKeyboardButton(text=label, callback_data=f"dur_{minutes}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="✏️ O'zim kiriting", callback_data="dur_custom")])
    buttons.append([InlineKeyboardButton(text="⬅️ Orqaga",         callback_data="back_mycode")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def codes_list_kb(rows):
    buttons = []
    for row in rows:
        remaining = format_remaining(row["expires_at"])
        icon  = "✅" if "⛔" not in remaining else "⛔"
        short = row["code"][:8] + "..."
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {short}  |  {remaining}",
            callback_data=f"mycode_{row['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="➕ Yangi kod yaratish", callback_data="createcode")])
    if rows:
        buttons.append([InlineKeyboardButton(
            text="🗑 Muddati o'tganlarni tozalash", callback_data="clean_expired"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==================== START ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Salom!\n\n"
        "📁 <b>Guruh</b> qo'shish uchun — guruhning public linkini yuboring "
        "(<code>t.me/groupname</code> yoki <code>@groupname</code>)\n"
        "📢 <b>Kanal</b> qo'shish uchun — kanaldan istalgan xabarni <b>forward</b> qiling\n"
        "🤖 <b>Bot</b> qo'shish uchun — botdan istalgan xabarni <b>forward</b> qiling\n\n"
        "Har bir saqlangan element 🔒 <b>shaxsiy</b> bo'lib qo'shiladi.\n\n"
        "Pastdagi tugmalardan foydalaning 👇",
        reply_markup=persistent_kb()
    )


# ==================== 📁 GURUHLAR ====================
@dp.message(F.text == BTN_GROUPS)
async def btn_groups(message: types.Message, state: FSMContext):
    rows = get_user_chats(message.from_user.id, "group")

    # Guruhlar ro'yxati + "Yangi qo'shish" tugmasi
    buttons = []
    for row in rows:
        mark = "🌐" if row["is_public"] else "🔒"
        buttons.append([InlineKeyboardButton(
            text=f"{mark} {row['title'] or 'Nomsiz'}",
            callback_data=f"item_{row['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="➕ Yangi guruh qo'shish", callback_data="add_group")])

    if rows:
        await message.answer(
            "📋 Guruhlar ro'yxati  (🌐 = ommaviy, 🔒 = shaxsiy):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    else:
        await message.answer(
            "Hozircha guruh saqlanmagan.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )


@dp.callback_query(F.data == "add_group")
async def add_group_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AddGroupStates.waiting_link)
    await callback.message.edit_text(
        "📎 Guruhning public linkini yuboring:\n\n"
        "Qabul qilinadi:\n"
        "• <code>https://t.me/groupname</code>\n"
        "• <code>t.me/groupname</code>\n"
        "• <code>@groupname</code>\n"
        "• <code>groupname</code>\n\n"
        "⚠️ Faqat public (username'li) guruhlar qo'shilishi mumkin."
    )
    await callback.answer()


@dp.message(StateFilter(AddGroupStates.waiting_link))
async def add_group_link(message: types.Message, state: FSMContext):
    await state.clear()

    username = extract_username_from_text(message.text or "")
    if not username:
        await message.answer(
            "❌ Noto'g'ri format. Guruhning public linkini yuboring:\n"
            "<code>t.me/groupname</code> yoki <code>@groupname</code>",
            reply_markup=persistent_kb()
        )
        return

    # Telegram API orqali guruh ma'lumotini olamiz
    await message.answer("🔍 Tekshirilmoqda...")
    try:
        chat = await bot.get_chat(f"@{username}")
    except TelegramBadRequest:
        await message.answer(
            f"❌ <code>@{username}</code> topilmadi yoki bu guruh mavjud emas.\n"
            f"Faqat public guruhlar qo'shilishi mumkin.",
            reply_markup=persistent_kb()
        )
        return
    except Exception as e:
        logging.warning(f"get_chat xatosi: {e}")
        await message.answer("❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.", reply_markup=persistent_kb())
        return

    # Bot faqat group/supergroup qabul qiladi
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.answer(
            f"❌ <code>@{username}</code> — bu guruh emas "
            f"(turi: {chat.type}). Faqat guruhlar bu bo'limga qo'shiladi.\n\n"
            f"Kanal bo'lsa — 📢 Kanallar bo'limiga forward orqali qo'shing.",
            reply_markup=persistent_kb()
        )
        return

    photo_file_id = None
    if chat.photo:
        photo_file_id = chat.photo.big_file_id

    invite_link = f"https://t.me/{username}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Ha, saqlash", callback_data="confirm_group_link")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_add")],
    ])
    # Ma'lumotlarni state'ga yozamiz
    await state.update_data(
        chat_id=chat.id,
        chat_type="group",
        title=chat.title,
        username=username,
        photo_file_id=photo_file_id,
        invite_link=invite_link
    )
    # State'ni qaytadan set qilamiz — confirm uchun
    await state.set_state(AddGroupStates.waiting_link)

    await message.answer(
        f"Aniqlandi:\n"
        f"<b>{chat.title}</b>\n"
        f"Username: @{username}\n"
        f"Havola: {invite_link}\n"
        f"Rasm: {'topildi ✅' if photo_file_id else 'topilmadi'}\n\n"
        f"Guruhlar ro'yxatiga qo'shamizmi?",
        reply_markup=kb
    )


@dp.callback_query(F.data == "confirm_group_link")
async def confirm_group_link(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    if not data.get("title"):
        await callback.answer("Ma'lumot topilmadi, qaytadan urinib ko'ring.", show_alert=True)
        return

    add_chat(
        owner_id=callback.from_user.id,
        chat_id=data.get("chat_id"),
        chat_type="group",
        title=data.get("title"),
        username=data.get("username"),
        photo_file_id=data.get("photo_file_id"),
        invite_link=data.get("invite_link")
    )
    await callback.message.edit_text(
        f"✅ <b>{data.get('title')}</b> guruhlar ro'yxatiga saqlandi (🔒 shaxsiy holatda)."
    )
    await callback.answer()


@dp.callback_query(F.data == "cancel_add")
async def cancel_add(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Bekor qilindi.")
    await callback.answer()


# ==================== 📢 KANALLAR (forward orqali) ====================
@dp.message(F.forward_from_chat)
async def on_forwarded_chat(message: types.Message, state: FSMContext):
    fchat = message.forward_from_chat

    # Faqat kanallar — guruhlar endi link orqali qo'shiladi
    if fchat.type != ChatType.CHANNEL:
        await message.answer(
            "ℹ️ Guruhlar forward orqali emas, balki public link orqali qo'shiladi.\n\n"
            "📁 <b>Guruhlar</b> tugmasini bosing va u yerdan <b>➕ Yangi guruh qo'shish</b> ni tanlang.",
            reply_markup=persistent_kb()
        )
        return

    photo_file_id = None
    invite_link   = None
    if fchat.username:
        try:
            full = await bot.get_chat(f"@{fchat.username}")
            if full.photo:
                photo_file_id = full.photo.big_file_id
        except Exception:
            pass
        invite_link = f"https://t.me/{fchat.username}"

    await state.update_data(
        chat_id=fchat.id, chat_type="channel", title=fchat.title,
        username=fchat.username, photo_file_id=photo_file_id, invite_link=invite_link
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Kanal sifatida saqlash", callback_data="confirm_channel")],
        [InlineKeyboardButton(text="❌ Bekor qilish",           callback_data="cancel_add")],
    ])
    username_text = f"@{fchat.username}" if fchat.username else "yo'q (private)"
    link_text     = invite_link or "topilmadi (keyin qo'lda qo'shasiz)"
    await message.answer(
        f"Aniqlandi:\n<b>{fchat.title}</b>\nUsername: {username_text}\n"
        f"Taklif havolasi: {link_text}\n"
        f"Rasm: {'topildi ✅' if photo_file_id else 'topilmadi'}\n\n"
        f"Saqlaymizmi? (default: 🔒 shaxsiy)",
        reply_markup=kb
    )


# ==================== 🤖 BOT (forward orqali) ====================
@dp.message(F.forward_from, F.forward_from.is_bot == True)
async def on_forwarded_bot(message: types.Message, state: FSMContext):
    fuser = message.forward_from
    photo_file_id = None
    if fuser.username:
        try:
            full = await bot.get_chat(f"@{fuser.username}")
            if full.photo:
                photo_file_id = full.photo.big_file_id
        except Exception:
            pass

    invite_link = f"https://t.me/{fuser.username}" if fuser.username else None
    title       = fuser.full_name or fuser.username or "Nomsiz bot"

    await state.update_data(
        chat_id=fuser.id, chat_type="bot", title=title,
        username=fuser.username, photo_file_id=photo_file_id, invite_link=invite_link
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Bot sifatida saqlash", callback_data="confirm_bot")],
        [InlineKeyboardButton(text="❌ Bekor qilish",         callback_data="cancel_add")],
    ])
    await message.answer(
        f"Aniqlandi:\n<b>{title}</b>\n"
        f"Username: {'@' + fuser.username if fuser.username else 'yoq'}\n"
        f"Taklif havolasi: {invite_link or 'topilmadi'}\n"
        f"Rasm: {'topildi ✅' if photo_file_id else 'topilmadi'}\n\n"
        f"Saqlaymizmi? (default: 🔒 shaxsiy)",
        reply_markup=kb
    )


@dp.callback_query(F.data.in_(["confirm_channel", "confirm_bot"]))
async def confirm_add(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    chat_type = {"confirm_channel": "channel", "confirm_bot": "bot"}[callback.data]
    add_chat(
        owner_id=callback.from_user.id, chat_id=data.get("chat_id"), chat_type=chat_type,
        title=data.get("title"), username=data.get("username"),
        photo_file_id=data.get("photo_file_id"), invite_link=data.get("invite_link")
    )
    await state.clear()
    extra = "\n\n⚠️ Taklif havolasi topilmadi. Ro'yxatda elementni ochib qo'lda qo'shing." \
            if not data.get("invite_link") else ""
    await callback.message.edit_text(
        f"✅ <b>{data.get('title')}</b> saqlandi (🔒 shaxsiy holatda).{extra}"
    )
    await callback.answer()


# ==================== RO'YXAT (KANAL VA BOT) ====================
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
        buttons.append([InlineKeyboardButton(
            text=f"{mark} {row['title'] or 'Nomsiz'}",
            callback_data=f"item_{row['id']}"
        )])
    await message.answer(
        f"📋 {label} ro'yxati  (🌐 = ommaviy, 🔒 = shaxsiy):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


# ==================== RO'YXAT (KOD ORQALI) ====================
@dp.callback_query(F.data.startswith("shmenu_"))
async def shared_menu(callback: types.CallbackQuery):
    _, chat_type, owner_id_str = callback.data.split("_")
    owner_id = int(owner_id_str)
    rows     = get_public_chats(owner_id, chat_type)
    label    = TYPE_LABELS[chat_type]
    if not rows:
        await callback.message.edit_text(f"Bu foydalanuvchida ommaviy {label.lower()} mavjud emas.")
        await callback.answer()
        return
    buttons = [[InlineKeyboardButton(
        text=row["title"] or "Nomsiz",
        callback_data=f"sitem_{row['id']}_{owner_id}"
    )] for row in rows]
    await callback.message.edit_text(
        f"📋 Ommaviy {label.lower()} ro'yxati:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


# ==================== 🔑 KODLARIM ====================
@dp.message(F.text == BTN_MY_CODE)
async def my_codes_menu(message: types.Message):
    rows = get_user_codes(message.from_user.id)
    text = (
        "🔑 <b>Mening kodlarim</b>\n\n✅ = faol  |  ⛔ = muddati tugagan\n\n"
        "Yaratgan kodingizni boshqalarga bering — ular sizning ommaviy "
        "kanal/guruh/botlaringizni ko'ra oladi."
        if rows else
        "🔑 <b>Mening kodlarim</b>\n\nHali hech qanday kod yaratilmagan."
    )
    await message.answer(text, reply_markup=codes_list_kb(rows))


@dp.callback_query(F.data == "back_mycode")
async def back_mycode(callback: types.CallbackQuery):
    rows = get_user_codes(callback.from_user.id)
    text = "🔑 <b>Mening kodlarim</b>\n\n✅ = faol  |  ⛔ = muddati tugagan" \
           if rows else "🔑 <b>Mening kodlarim</b>\n\nHali hech qanday kod yaratilmagan."
    await callback.message.edit_text(text, reply_markup=codes_list_kb(rows))
    await callback.answer()


@dp.callback_query(F.data == "clean_expired")
async def clean_expired(callback: types.CallbackQuery):
    delete_expired_codes(callback.from_user.id)
    rows = get_user_codes(callback.from_user.id)
    text = "🔑 <b>Mening kodlarim</b>\n\n✅ = faol  |  ⛔ = muddati tugagan" \
           if rows else "🔑 <b>Mening kodlarim</b>\n\nHali hech qanday kod yaratilmagan."
    await callback.message.edit_text(text, reply_markup=codes_list_kb(rows))
    await callback.answer("✅ Muddati o'tganlar tozalandi")


@dp.callback_query(F.data.startswith("mycode_"))
async def show_code_detail(callback: types.CallbackQuery):
    code_id = int(callback.data.split("_")[1])
    row     = get_code_record_by_id(code_id, callback.from_user.id)
    if not row:
        await callback.answer("Topilmadi", show_alert=True)
        return
    remaining = format_remaining(row["expires_at"])
    is_active = "⛔" not in remaining
    try:
        exp     = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S")
        exp_str = exp.strftime("%d.%m.%Y %H:%M") + " (UTC)"
    except Exception:
        exp_str = row["expires_at"]
    text = (
        f"🔑 <b>Kod</b>\n\n<code>{row['code']}</code>\n\n"
        f"Holati: {'✅ Faol' if is_active else '⛔ Muddati tugagan'}\n"
        f"Tugash vaqti: {exp_str}\n{remaining}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Kodni o'chirish", callback_data=f"delemycode_{code_id}")],
        [InlineKeyboardButton(text="⬅️ Orqaga",          callback_data="back_mycode")],
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("delemycode_"))
async def delete_my_code(callback: types.CallbackQuery):
    code_id = int(callback.data.split("_")[1])
    delete_share_code(code_id, callback.from_user.id)
    rows = get_user_codes(callback.from_user.id)
    text = "🔑 <b>Mening kodlarim</b>\n\n✅ = faol  |  ⛔ = muddati tugagan" \
           if rows else "🔑 <b>Mening kodlarim</b>\n\nHali hech qanday kod yaratilmagan."
    await callback.message.edit_text(text, reply_markup=codes_list_kb(rows))
    await callback.answer("🗑 Kod o'chirildi")


# ==================== KOD YARATISH ====================
@dp.callback_query(F.data == "createcode")
async def create_code_start(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "⏱ <b>Kod qancha muddatga ishlashini tanlang:</b>",
        reply_markup=duration_kb()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("dur_"))
async def select_duration(callback: types.CallbackQuery, state: FSMContext):
    value = callback.data[4:]
    if value == "custom":
        await state.set_state(ShareCodeStates.waiting_custom_duration)
        await callback.message.edit_text(
            "✏️ <b>Muddatni kiriting:</b>\n\n"
            "• Faqat son → <b>soat</b>  (<code>3</code> = 3 soat)\n"
            "• Son + <code>d</code> → <b>daqiqa</b>  (<code>30d</code> = 30 daqiqa)\n"
            "• Son + <code>k</code> → <b>kun</b>  (<code>2k</code> = 2 kun)\n\n"
            "Maksimal: 30 kun"
        )
        await callback.answer()
        return

    minutes   = int(value)
    code      = create_share_code(callback.from_user.id, minutes)
    remaining = format_remaining(
        (datetime.utcnow() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    )
    await callback.message.edit_text(
        f"✅ <b>Yangi kod yaratildi!</b>\n\nKod: <code>{code}</code>\n\n{remaining}\n\n"
        f"Bu kodni boshqalarga bering — ular sizning ommaviy kanal/guruh/botlaringizni ko'ra oladi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Kodlarim ro'yxatiga", callback_data="back_mycode")]
        ])
    )
    await callback.answer()


@dp.message(StateFilter(ShareCodeStates.waiting_custom_duration))
async def custom_duration_finish(message: types.Message, state: FSMContext):
    await state.clear()
    text = message.text.strip().lower()
    try:
        if text.endswith("d"):
            minutes = int(text[:-1].strip())
        elif text.endswith("k"):
            minutes = int(text[:-1].strip()) * 1440
        else:
            minutes = int(text) * 60
        if minutes <= 0:
            raise ValueError
        if minutes > 43200:
            await message.answer("⚠️ Maksimal muddat 30 kun.", reply_markup=persistent_kb())
            return
    except ValueError:
        await message.answer(
            "❌ Noto'g'ri format. Masalan: <code>3</code>, <code>30d</code>, <code>2k</code>",
            reply_markup=persistent_kb()
        )
        return

    code      = create_share_code(message.from_user.id, minutes)
    remaining = format_remaining(
        (datetime.utcnow() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    )
    await message.answer(
        f"✅ <b>Yangi kod yaratildi!</b>\n\nKod: <code>{code}</code>\n\n{remaining}\n\n"
        f"Bu kodni boshqalarga bering — ular sizning ommaviy kanal/guruh/botlaringizni ko'ra oladi.",
        reply_markup=persistent_kb()
    )


# ==================== 🔍 KOD ORQALI KO'RISH ====================
@dp.message(F.text == BTN_OPEN_CODE)
async def open_code_menu(message: types.Message):
    rows    = get_saved_codes(message.from_user.id)
    buttons = []
    for row in rows:
        valid = is_code_valid(row["share_uuid"])
        icon  = "📂" if valid else "⛔"
        label = row["custom_name"] or f"Kod: {row['share_uuid'][:8]}..."
        buttons.append([InlineKeyboardButton(text=f"{icon} {label}", callback_data=f"savedcode_{row['id']}")])
    buttons.append([InlineKeyboardButton(text="➕ Yangi kod kiritish", callback_data="newcode")])
    text = "🔍 <b>Saqlangan kodlar</b>\n\n📂 = faol  |  ⛔ = muddati tugagan" \
           if rows else "🔍 Hali hech qanday kod saqlanmagan."
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data == "newcode")
async def new_code_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SharedCodeStates.waiting_new_code)
    await callback.message.edit_text("Ko'rmoqchi bo'lgan foydalanuvchining 16 xonali kodini yuboring:")
    await callback.answer()


@dp.message(StateFilter(SharedCodeStates.waiting_new_code))
async def new_code_finish(message: types.Message, state: FSMContext):
    code = message.text.strip()
    await state.clear()

    owner_id = get_owner_by_code(code)
    if not owner_id:
        await message.answer(
            "❌ Bunday kod topilmadi yoki muddati tugagan.", reply_markup=persistent_kb()
        )
        return
    if owner_id == message.from_user.id:
        await message.answer("❌ Bu sizning o'z kodingiz.", reply_markup=persistent_kb())
        return

    save_code_for_viewer(message.from_user.id, owner_id, code)
    rows      = get_saved_codes(message.from_user.id)
    saved_row = next((r for r in rows if r["share_uuid"] == code), None)

    rename_btn = [InlineKeyboardButton(text="✏️ Nom berish", callback_data=f"renamecode_{saved_row['id']}")] \
                 if saved_row else []
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Guruhlar", callback_data=f"shmenu_group_{owner_id}")],
        [InlineKeyboardButton(text="📢 Kanallar", callback_data=f"shmenu_channel_{owner_id}")],
        [InlineKeyboardButton(text="🤖 Botlar",   callback_data=f"shmenu_bot_{owner_id}")],
        rename_btn,
    ])
    await message.answer("✅ Kod to'g'ri va saqlandi. Qaysi bo'limni ko'rmoqchisiz?", reply_markup=kb)
    await message.answer("Asosiy menyu:", reply_markup=persistent_kb())


@dp.callback_query(F.data.startswith("savedcode_"))
async def open_saved_code(callback: types.CallbackQuery):
    saved_id  = int(callback.data.split("_")[1])
    saved_row = get_saved_code_by_id(saved_id, callback.from_user.id)
    if not saved_row:
        await callback.answer("Topilmadi", show_alert=True)
        return

    owner_id = saved_row["owner_id"]
    label    = saved_row["custom_name"] or f"Kod: {saved_row['share_uuid'][:8]}..."
    valid    = is_code_valid(saved_row["share_uuid"])

    if not valid:
        await callback.message.edit_text(
            f"⛔ <b>{label}</b>\n\nBu kodning muddati tugagan.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🗑 Ro'yxatdan olib tashlash", callback_data=f"removecode_{saved_id}")],
                [InlineKeyboardButton(text="⬅️ Orqaga",                   callback_data="back_saved_list")],
            ])
        )
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Guruhlar", callback_data=f"shmenu_group_{owner_id}")],
        [InlineKeyboardButton(text="📢 Kanallar", callback_data=f"shmenu_channel_{owner_id}")],
        [InlineKeyboardButton(text="🤖 Botlar",   callback_data=f"shmenu_bot_{owner_id}")],
        [InlineKeyboardButton(text="✏️ Nomini o'zgartirish",    callback_data=f"renamecode_{saved_id}")],
        [InlineKeyboardButton(text="🗑 Ro'yxatdan olib tashlash", callback_data=f"removecode_{saved_id}")],
        [InlineKeyboardButton(text="⬅️ Orqaga",                   callback_data="back_saved_list")],
    ])
    await callback.message.edit_text(
        f"📂 <b>{label}</b>\n\nQaysi bo'limni ko'rmoqchisiz?", reply_markup=kb
    )
    await callback.answer()


@dp.callback_query(F.data == "back_saved_list")
async def back_saved_list(callback: types.CallbackQuery):
    rows    = get_saved_codes(callback.from_user.id)
    buttons = []
    for row in rows:
        valid = is_code_valid(row["share_uuid"])
        icon  = "📂" if valid else "⛔"
        label = row["custom_name"] or f"Kod: {row['share_uuid'][:8]}..."
        buttons.append([InlineKeyboardButton(text=f"{icon} {label}", callback_data=f"savedcode_{row['id']}")])
    buttons.append([InlineKeyboardButton(text="➕ Yangi kod kiritish", callback_data="newcode")])
    text = "🔍 <b>Saqlangan kodlar</b>\n\n📂 = faol  |  ⛔ = muddati tugagan" \
           if rows else "🔍 Hali hech qanday kod saqlanmagan."
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("renamecode_"))
async def rename_code_start(callback: types.CallbackQuery, state: FSMContext):
    saved_id  = int(callback.data.split("_")[1])
    saved_row = get_saved_code_by_id(saved_id, callback.from_user.id)
    if not saved_row:
        await callback.answer("Topilmadi", show_alert=True)
        return
    await state.update_data(saved_id=saved_id)
    await state.set_state(SharedCodeStates.waiting_rename)
    await callback.message.answer("Bu kod uchun yangi nom kiriting:")
    await callback.answer()


@dp.message(StateFilter(SharedCodeStates.waiting_rename))
async def rename_code_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    update_saved_code_name(data["saved_id"], message.from_user.id, message.text.strip())
    await message.answer(f"✅ Nom yangilandi: <b>{message.text.strip()}</b>", reply_markup=persistent_kb())
    await state.clear()


@dp.callback_query(F.data.startswith("removecode_"))
async def remove_code(callback: types.CallbackQuery):
    saved_id = int(callback.data.split("_")[1])
    delete_saved_code(saved_id, callback.from_user.id)
    rows    = get_saved_codes(callback.from_user.id)
    buttons = []
    for row in rows:
        valid = is_code_valid(row["share_uuid"])
        icon  = "📂" if valid else "⛔"
        label = row["custom_name"] or f"Kod: {row['share_uuid'][:8]}..."
        buttons.append([InlineKeyboardButton(text=f"{icon} {label}", callback_data=f"savedcode_{row['id']}")])
    buttons.append([InlineKeyboardButton(text="➕ Yangi kod kiritish", callback_data="newcode")])
    text = "🔍 <b>Saqlangan kodlar</b>" if rows else "🔍 Hali hech qanday kod saqlanmagan."
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer("🗑 Ro'yxatdan olib tashlandi")


# ==================== ITEM DETAIL (EGASI) ====================
@dp.callback_query(F.data.startswith("item_"))
async def show_item(callback: types.CallbackQuery):
    record_id = int(callback.data.split("_")[1])
    row       = get_chat_by_id(record_id, callback.from_user.id)
    if not row:
        await callback.answer("Topilmadi", show_alert=True)
        return

    username_text = f"@{row['username']}" if row["username"] else "—"
    link_text     = row["invite_link"] or "❌ Hali kiritilmagan"
    visibility    = "🌐 Ommaviy" if row["is_public"] else "🔒 Shaxsiy"
    caption = (
        f"<b>{row['title']}</b>\n"
        f"Username: {username_text}\n"
        f"Turi: {TYPE_LABEL_SINGULAR.get(row['chat_type'], row['chat_type'])}\n"
        f"Holati: {visibility}\n"
        f"Havola: {link_text}"
    )
    toggle_text = "🔒 Shaxsiy qilish" if row["is_public"] else "🌐 Ommaviy qilish"
    kb_buttons  = []
    if row["invite_link"]:
        kb_buttons.append([InlineKeyboardButton(text="🔗 O'tish", url=row["invite_link"])])
    kb_buttons += [
        [InlineKeyboardButton(text=toggle_text,                      callback_data=f"toggle_{record_id}")],
        [InlineKeyboardButton(text="✏️ Username o'zgartirish",       callback_data=f"edit_username_{record_id}")],
        [InlineKeyboardButton(text="🔗 Havolani o'zgartirish/qo'shish", callback_data=f"edit_link_{record_id}")],
        [InlineKeyboardButton(text="🖼 Rasmni o'zgartirish",         callback_data=f"edit_photo_{record_id}")],
        [InlineKeyboardButton(text="🗑 O'chirish",                   callback_data=f"delete_{record_id}")],
    ]
    await _render_item(callback, row, record_id, callback.from_user.id,
                       caption, InlineKeyboardMarkup(inline_keyboard=kb_buttons))


# ==================== ITEM DETAIL (KO'RUVCHI) ====================
@dp.callback_query(F.data.startswith("sitem_"))
async def show_shared_item(callback: types.CallbackQuery):
    _, record_id_str, owner_id_str = callback.data.split("_")
    record_id, owner_id = int(record_id_str), int(owner_id_str)
    row = get_public_chat_by_id(record_id, owner_id)
    if not row:
        await callback.answer("Topilmadi yoki endi ommaviy emas", show_alert=True)
        return
    username_text = f"@{row['username']}" if row["username"] else "—"
    link_text     = row["invite_link"] or "❌ Mavjud emas"
    caption = (
        f"<b>{row['title']}</b>\n"
        f"Username: {username_text}\n"
        f"Turi: {TYPE_LABEL_SINGULAR.get(row['chat_type'], row['chat_type'])}\n"
        f"Havola: {link_text}"
    )
    kb_buttons = []
    if row["invite_link"]:
        kb_buttons.append([InlineKeyboardButton(text="🔗 O'tish", url=row["invite_link"])])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons) if kb_buttons else None
    await _render_item(callback, row, record_id, owner_id, caption, kb)


async def _render_item(callback, row, record_id, owner_id, caption, kb):
    sent_as_photo = False
    if row["photo_file_id"]:
        photo = await get_sendable_photo(record_id, owner_id, row["photo_file_id"])
        if photo:
            try:
                await callback.message.delete()
                sent_msg = await callback.message.answer_photo(
                    photo=photo, caption=caption, reply_markup=kb
                )
                sent_as_photo = True
                if isinstance(photo, BufferedInputFile):
                    update_chat_field(record_id, owner_id, "sendable_photo_id",
                                      sent_msg.photo[-1].file_id)
            except TelegramBadRequest as e:
                logging.warning(f"Photo yuborishda xato: {e}")
    if not sent_as_photo:
        try:
            await callback.message.edit_text(caption, reply_markup=kb)
        except TelegramBadRequest:
            await callback.message.answer(caption, reply_markup=kb)
    await callback.answer()


# ==================== RASMNI XAVFSIZ YUBORISH ====================
async def get_sendable_photo(record_id: int, owner_id: int, photo_file_id: str):
    row = get_chat_by_id(record_id, owner_id)
    if row and row["sendable_photo_id"]:
        return row["sendable_photo_id"]
    try:
        file = await bot.get_file(photo_file_id)
        buf  = BytesIO()
        await bot.download_file(file.file_path, destination=buf)
        buf.seek(0)
        return BufferedInputFile(buf.read(), filename="photo.jpg")
    except Exception as e:
        logging.warning(f"Rasmni yuklab bo'lmadi: {e}")
        return None


# ==================== TOGGLE PUBLIC/PRIVATE ====================
@dp.callback_query(F.data.startswith("toggle_"))
async def toggle_visibility(callback: types.CallbackQuery):
    record_id = int(callback.data.split("_")[1])
    row       = get_chat_by_id(record_id, callback.from_user.id)
    if not row:
        await callback.answer("Topilmadi", show_alert=True)
        return
    new_value = 0 if row["is_public"] else 1
    update_chat_field(record_id, callback.from_user.id, "is_public", new_value)
    await callback.answer("🌐 Endi ommaviy" if new_value else "🔒 Endi shaxsiy")
    callback.data = f"item_{record_id}"
    await show_item(callback)


# ==================== EDIT USERNAME ====================
@dp.callback_query(F.data.startswith("edit_username_"))
async def edit_username_start(callback: types.CallbackQuery, state: FSMContext):
    record_id = int(callback.data.split("_")[2])
    await state.update_data(record_id=record_id)
    await state.set_state(EditStates.waiting_username)
    await callback.message.answer(
        "Yangi username kiriting (masalan: @groupname) yoki '-' (bo'sh qilish uchun):"
    )
    await callback.answer()


@dp.message(StateFilter(EditStates.waiting_username))
async def edit_username_finish(message: types.Message, state: FSMContext):
    data        = await state.get_data()
    new_username = None if message.text.strip() == "-" else message.text.replace("@", "").strip()
    update_chat_field(data["record_id"], message.from_user.id, "username", new_username)
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
    data     = await state.get_data()
    new_link = None if message.text.strip() == "-" else message.text.strip()
    update_chat_field(data["record_id"], message.from_user.id, "invite_link", new_link)
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
    data    = await state.get_data()
    file_id = message.photo[-1].file_id
    update_chat_field(data["record_id"], message.from_user.id, "photo_file_id",    file_id)
    update_chat_field(data["record_id"], message.from_user.id, "sendable_photo_id", file_id)
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