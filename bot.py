import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta
import re

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiohttp import web

# === НАЛАШТУВАННЯ ТОКЕНА ===
TELEGRAM_BOT_TOKEN = "9048278041:AAGLR_CPZP636L6-4JPi_F1bdGn3PrWk1Yc"  # 

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# === СТАНИ (FSM) ДЛЯ ДІАЛОГУ ===
class Form(StatesGroup):
    waiting_for_shopping_items = State()
    waiting_for_reminder_title = State()
    waiting_for_reminder_date = State()

# === ВЕБ-СЕРВЕР ДЛЯ RENDER ===
async def handle_ping(request):
    return web.Response(text="Bot is live!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# === БАЗА ДАНИХ ===
def init_db():
    conn = sqlite3.connect("family_data.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shopping (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            title TEXT,
            remind_date TEXT,
            is_done INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

init_db()

# === ОСНОВНЕ МЕНЮ (КНОПКИ ВНИЗУ) ===
def main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🛒 Список покупок")
    builder.button(text="➕ Додати в список")
    builder.button(text="⏰ Мої нагадування")
    builder.button(text="🔔 Додати нагадування")
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True)

# === ТАЙМЕР НАГАДУВАНЬ ===
async def check_reminders():
    while True:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn = sqlite3.connect("family_data.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id, chat_id, title FROM reminders WHERE remind_date <= ? AND is_done = 0", (now_str,))
        active_reminders = cursor.fetchall()
        
        for rem_id, chat_id, title in active_reminders:
            try:
                await bot.send_message(chat_id, f"🚨 **СІМЕЙНЕ НАГАДУВАННЯ!** 🚨\n\n📌 {title}")
                cursor.execute("UPDATE reminders SET is_done = 1 WHERE id = ?", (rem_id,))
            except Exception as e:
                logging.error(f"Помилка відправки: {e}")
        
        conn.commit()
        conn.close()
        await asyncio.sleep(30)

# === СТАРТ ТА СКАСУВАННЯ ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 **Привіт! Я ваш сімейний помічник.**\n\n"
        "Оберіть потрібну дію на кнопках внизу екрана👇",
        reply_markup=main_keyboard()
    )

# === БЛОК 1: ПОКУПКИ ===

# Натиснули "🛒 Список покупок"
@dp.message(F.text == "🛒 Список покупок")
async def show_shopping_list(message: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("family_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, item FROM shopping")
    items = cursor.fetchall()
    conn.close()
    
    if not items:
        await message.answer("🛒 Список покупок порожній!", reply_markup=main_keyboard())
        return
    
    builder = InlineKeyboardBuilder()
    for item_id, item_name in items:
        builder.button(text=f"❌ {item_name}", callback_data=f"del_shop_{item_id}")
    builder.adjust(1)
    
    await message.answer("🛒 **Ваш список покупок:**\n*(натисніть на товар, щоб викреслити)*", reply_markup=builder.as_markup())

# Викреслення товару зі списку
@dp.callback_query(F.data.startswith("del_shop_"))
async def delete_shopping_item(callback: types.CallbackQuery):
    item_id = callback.data.split("_")[2]
    conn = sqlite3.connect("family_data.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM shopping WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    
    await callback.answer("Куплено!")
    
    conn = sqlite3.connect("family_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, item FROM shopping")
    items = cursor.fetchall()
    conn.close()
    
    if not items:
        await callback.message.edit_text("🛒 Усі товари куплено! Список порожній.")
    else:
        builder = InlineKeyboardBuilder()
        for i_id, item_name in items:
            builder.button(text=f"❌ {item_name}", callback_data=f"del_shop_{i_id}")
        builder.adjust(1)
        await callback.message.edit_reply_markup(reply_markup=builder.as_markup())

# Натиснули "➕ Додати в список"
@dp.message(F.text == "➕ Додати в список")
async def start_add_shopping(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_for_shopping_items)
    await message.answer("✍️ **Напишіть товари, які потрібно купити** (можна декілька через кому):\n\n*Приклад: молоко, хліб, яйця*")

# Бот приймає написані покупки
@dp.message(Form.waiting_for_shopping_items)
async def process_shopping_items(message: types.Message, state: FSMContext):
    items = [item.strip() for item in message.text.split(",") if item.strip()]
    
    if not items:
        await message.answer("Будь ласка, напишіть хоча б один товар.")
        return

    conn = sqlite3.connect("family_data.db")
    cursor = conn.cursor()
    for item in items:
        cursor.execute("INSERT INTO shopping (item) VALUES (?)", (item,))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"✅ Додано до списку покупок ({len(items)} шт.)!", reply_markup=main_keyboard())


# === БЛОК 2: НАГАДУВАННЯ ===

# Натиснули "⏰ Мої нагадування"
@dp.message(F.text == "⏰ Мої нагадування")
async def show_reminders(message: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("family_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT title, remind_date FROM reminders WHERE chat_id = ? AND is_done = 0 ORDER BY remind_date ASC", (message.chat.id,))
    rems = cursor.fetchall()
    conn.close()
    
    if not rems:
        await message.answer("⏰ У вас немає активних нагадувань.", reply_markup=main_keyboard())
        return
    
    text = "📌 **Майбутні нагадування:**\n\n"
    for title, r_date in rems:
        text += f"📅 `{r_date}` — {title}\n"
    
    await message.answer(text, reply_markup=main_keyboard())

# Натиснули "🔔 Додати нагадування"
@dp.message(F.text == "🔔 Додати нагадування")
async def start_add_reminder(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_for_reminder_title)
    await message.answer("✍️ **Про що саме вам нагадати?**\n\n*Наприклад: Оплатити іпотеку, Запис на ТО, Купити ліки*")

# Крок 1: Отримали опис нагадування
@dp.message(Form.waiting_for_reminder_title)
async def process_reminder_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(Form.waiting_for_reminder_date)
    await message.answer(
        "📅 **Коли нагадати?**\n\n"
        "Напишіть у довільному форматі, наприклад:\n"
        "• `завтра о 10:00`\n"
        "• `через 2 години`\n"
        "• `2026-11-25 15:00`"
    )

# Крок 2: Отримали дату і зберегли
@dp.message(Form.waiting_for_reminder_date)
async def process_reminder_date(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    title = user_data.get("title")
    raw_date = message.text.strip()
    
    now = datetime.now()
    remind_time = None

    # Формат YYYY-MM-DD HH:MM
    match_date = re.match(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", raw_date)
    if match_date:
        try:
            remind_time = datetime.strptime(match_date.group(1), "%Y-%m-%d %H:%M")
        except ValueError:
            pass
    
    # "завтра о/в HH:MM"
    elif "завтра" in raw_date.lower():
        match_time = re.search(r"(\d{1,2}:\d{2})", raw_date.lower())
        if match_time:
            t_str = match_time.group(1)
            h, m = map(int, t_str.split(":"))
            remind_time = (now + timedelta(days=1)).replace(hour=h, minute=m)
        
    # "через X годин/хвилин"
    elif "через" in raw_date.lower():
        match_hours = re.search(r"(\d+)\s+год", raw_date.lower())
        match_mins = re.search(r"(\d+)\s+хв", raw_date.lower())
        if match_hours:
            hrs = int(match_hours.group(1))
            remind_time = now + timedelta(hours=hrs)
        elif match_mins:
            mins = int(match_mins.group(1))
            remind_time = now + timedelta(minutes=mins)

    if not remind_time:
        await message.answer("❌ Не вдалося розпізнати дату. Спробуйте ще раз (наприклад: `завтра о 15:00` або `2026-12-01 10:00`):")
        return

    full_date_str = remind_time.strftime("%Y-%m-%d %H:%M")
    
    conn = sqlite3.connect("family_data.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO reminders (chat_id, title, remind_date) VALUES (?, ?, ?)",
        (message.chat.id, title, full_date_str)
    )
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"🔔 **Нагадування встановлено!**\n\n📌 {title}\n📅 {full_date_str}", reply_markup=main_keyboard())


# === ЗАПУСК ===
async def main():
    logging.basicConfig(level=logging.INFO)
    await start_web_server()
    asyncio.create_task(check_reminders())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
