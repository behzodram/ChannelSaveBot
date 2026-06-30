import asyncio
import logging
import sqlite3
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
            chat_type TEXT NOT NULL,        -- 'group' yoki 'channel'
            title TEXT,
            username TEXT,
            photo_file_id TEXT,             -- ChatPhoto file_id (manba)
            sendable_photo_id TEXT,         -- sendPhoto orqali qaytgan, qayta yuborsa bo'ladigan file_id
            invite_link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def add_chat(owner_id, chat_id, chat_type, title, username, photo_file_id, invite_link=None):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO chats (owner_id, chat_id, chat_type, title, username, photo_file_id, invite_link)
        VALUES (?, ?, ?, ?, ?, ?, ?)
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


def get_chat_by_id(record_id, owner_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM chats WHERE id=? AND owner_id=?", (record_id, owner_id))
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


# ==================== KEYBOARDS ====================
def persistent_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_GROUPS), KeyboardButton(text=BTN_CHANNELS)]],
        resize_keyboard=True,
        is_persistent=True
    )


# ==================== START ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Salom!\n\n"
        "Menga kerakli kanal yoki guruhdagi istalgan xabarni <b>forward</b> qiling — "
        "men uni avtomatik saqlab qo'yaman (botni hech qayerga a'zo qilishning hojati yo'q).\n\n"
        "Saqlanganlarni ko'rish uchun pastdagi doimiy tugmalardan foydalaning 👇",
        reply_markup=persistent_kb()
    )


# ==================== RO'YXATNI KO'RSATISH ====================
@dp.message(F.text == BTN_GROUPS)
async def btn_groups(message: types.Message):
    await send_list(message, "group")


@dp.message(F.text == BTN_CHANNELS)
async def btn_channels(message: types.Message):
    await send_list(message, "channel")


async def send_list(message: types.Message, chat_type: str):
    rows = get_user_chats(message.from_user.id, chat_type)
    label = "Guruhlar" if chat_type == "group" else "Kanallar"

    if not rows:
        await message.answer(
            f"Hozircha {label.lower()} saqlanmagan.\n\n"
            f"Kerakli {('guruh' if chat_type == 'group' else 'kanal')}dan istalgan xabarni shu botga forward qiling."
        )
        return

    buttons = []
    for row in rows:
        text = row["title"] or "Nomsiz"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"item_{row['id']}")])

    await message.answer(
        f"📋 {label} ro'yxati:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


# ==================== FORWARD ORQALI QO'SHISH ====================
@dp.message(F.forward_from_chat)
async def on_forwarded(message: types.Message, state: FSMContext):
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
        chat_id=fchat.id,
        chat_type=chat_type,
        title=fchat.title,
        username=fchat.username,
        photo_file_id=photo_file_id,
        invite_link=invite_link
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
        f"Qaysi bo'limga saqlaymiz?",
        reply_markup=kb
    )


@dp.callback_query(F.data.in_(["confirm_group", "confirm_channel"]))
async def confirm_add(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    chat_type = "group" if callback.data == "confirm_group" else "channel"

    add_chat(
        owner_id=callback.from_user.id,
        chat_id=data.get("chat_id"),
        chat_type=chat_type,
        title=data.get("title"),
        username=data.get("username"),
        photo_file_id=data.get("photo_file_id"),
        invite_link=data.get("invite_link")
    )
    await state.clear()

    extra = ""
    if not data.get("invite_link"):
        extra = ("\n\n⚠️ Taklif havolasi topilmadi (kanal/guruh private). "
                 "Ro'yxatda shu elementni ochib, havolani qo'lda qo'shishingiz mumkin.")

    await callback.message.edit_text(f"✅ <b>{data.get('title')}</b> saqlandi.{extra}")
    await callback.answer()


# ==================== RASMNI XAVFSIZ YUBORISH ====================
async def get_sendable_photo(record_id: int, owner_id: int, photo_file_id: str):
    """
    ChatPhoto file_id'ni sendPhoto uchun yaroqli qiladi.
    Avval bazadagi keshlangan sendable_photo_id orqali tekshiradi (tezroq),
    bo'lmasa serverdan yuklab oladi va keshlaydi.
    """
    row = get_chat_by_id(record_id, owner_id)
    if row and row["sendable_photo_id"]:
        return row["sendable_photo_id"]  # avval qayta yuborilgan, ishlatsa bo'ladigan file_id

    try:
        file = await bot.get_file(photo_file_id)
        buffer = BytesIO()
        await bot.download_file(file.file_path, destination=buffer)
        buffer.seek(0)
        return BufferedInputFile(buffer.read(), filename="chat_photo.jpg")
    except Exception as e:
        logging.warning(f"Rasmni yuklab bo'lmadi: {e}")
        return None


# ==================== ITEM DETAIL ====================
@dp.callback_query(F.data.startswith("item_"))
async def show_item(callback: types.CallbackQuery):
    record_id = int(callback.data.split("_")[1])
    row = get_chat_by_id(record_id, callback.from_user.id)
    if not row:
        await callback.answer("Topilmadi", show_alert=True)
        return

    username_text = f"@{row['username']}" if row["username"] else "—"
    link_text = row["invite_link"] if row["invite_link"] else "❌ Hali kiritilmagan"
    caption = (
        f"<b>{row['title']}</b>\n"
        f"Username: {username_text}\n"
        f"Turi: {row['chat_type']}\n"
        f"Havola: {link_text}"
    )

    kb_buttons = []
    if row["invite_link"]:
        kb_buttons.append([InlineKeyboardButton(text="🔗 O'tish", url=row["invite_link"])])
    kb_buttons += [
        [InlineKeyboardButton(text="✏️ Username o'zgartirish", callback_data=f"edit_username_{record_id}")],
        [InlineKeyboardButton(text="🔗 Havolani o'zgartirish/qo'shish", callback_data=f"edit_link_{record_id}")],
        [InlineKeyboardButton(text="🖼 Rasmni o'zgartirish", callback_data=f"edit_photo_{record_id}")],
        [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"delete_{record_id}")],
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

    sent_as_photo = False
    if row["photo_file_id"]:
        photo_to_send = await get_sendable_photo(record_id, callback.from_user.id, row["photo_file_id"])
        if photo_to_send:
            try:
                await callback.message.delete()
                sent_msg = await callback.message.answer_photo(
                    photo=photo_to_send, caption=caption, reply_markup=kb
                )
                sent_as_photo = True
                # Agar yangi yuklab yuborilgan bo'lsa, qaytgan file_id'ni keshlab qo'yamiz
                if isinstance(photo_to_send, BufferedInputFile):
                    new_file_id = sent_msg.photo[-1].file_id
                    update_chat_field(record_id, callback.from_user.id, "sendable_photo_id", new_file_id)
            except TelegramBadRequest as e:
                logging.warning(f"Photo yuborishda xato: {e}")

    if not sent_as_photo:
        try:
            await callback.message.edit_text(caption, reply_markup=kb)
        except TelegramBadRequest:
            await callback.message.answer(caption, reply_markup=kb)

    await callback.answer()


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
        "Taklif havolasini yuboring (masalan: https://t.me/+AbCdEfGhIjK), "
        "yoki '-' (havolani o'chirish uchun):"
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
    file_id = message.photo[-1].file_id  # bu — to'g'ridan-to'g'ri foydalanuvchi yuborgan rasm, sendPhoto bilan mos
    update_chat_field(record_id, message.from_user.id, "photo_file_id", file_id)
    update_chat_field(record_id, message.from_user.id, "sendable_photo_id", file_id)  # darhol ishlatsa bo'ladi
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