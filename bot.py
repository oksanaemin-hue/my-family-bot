import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiohttp import web

# === НАЛАШТУВАННЯ ТОКЕНА ===
TELEGRAM_BOT_TOKEN = "9048278041:AAGLR_CPZP636L6-4JPi_F1bdGn3PrWk1Yc" # 

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

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

# === КЛАВІАТУРА МЕНЮ ===
def main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🛒 Список покупок")
    builder.button(text="⏰ Мої нагадування")
    builder.button(text="❓ Допомога")
    builder.adjust(2, 1)
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

# === ХЕНДЛЕРИ ===

@dp.message(Command("start"))
@dp.message(F.text == "❓ Допомога")
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 **Привіт! Я ваш сімейний помічник.**\n\n"
        "Користуйтеся кнопками внизу екрана або командами:\n\n"
        "🛒 **Покупки:**\n"
        "• `/buy молоко, хліб, сир` — додати в список\n"
        "• Натисніть кнопку **«🛒 Список покупок»**, щоб переглянути або викреслити товари.\n\n"
        "⏰ **Нагадування (іпотека, ТО, страховка):**\n"
        "• `/remind завтра о 10:00 Оплатити іпотеку`\n"
        "• `/remind 2026-11-25 15:00 ТО авто`\n"
        "• `/remind через 2 години Вимкнути духовку`",
        reply_markup=main_keyboard()
    )

# Додавання покупок
@dp.message(Command("buy"))
async def add_shopping(message: types.Message):
    text = message.text.replace("/buy", "").strip()
    if not text:
        await message.answer("Вкажіть покупки через кому. Приклад: `/buy молоко, яйця`")
        return
    
    items = [item.strip() for item in text.split(",") if item.strip()]
    conn = sqlite3.connect("family_data.db")
    cursor = conn.cursor()
    for item in items:
        cursor.execute("INSERT INTO shopping (item) VALUES (?)", (item,))
    conn.commit()
    conn.close()
    
    await message.answer(f"✅ Додано в список покупок ({len(items)} шт.)!", reply_markup=main_keyboard())

@dp.message(F.text == "🛒 Список покупок")
@dp.message(Command("list"))
async def show_shopping_list(message: types.Message):
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
    
    await message.answer("🛒 **Список покупок:**\n*(натисніть на товар, щоб викреслити)*", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("del_shop_"))
async def delete_shopping_item(callback: types.CallbackQuery):
    item_id = callback.data.split("_")[2]
    conn = sqlite3.connect("family_data.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM shopping WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    
    await callback.answer("Куплено!")
    
    # Оновлення списку
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

# Перегляд активних нагадувань
@dp.message(F.text == "⏰ Мої нагадування")
async def show_reminders(message: types.Message):
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

# Зручне додавання нагадувань
@dp.message(Command("remind"))
async def add_reminder(message: types.Message):
    raw_text = message.text.replace("/remind", "").strip()
    if not raw_text:
        await message.answer("❌ Введіть текст нагадування!\nПриклад: `/remind завтра о 15:00 Оплатити іпотеку`")
        return
    
    now = datetime.now()
    remind_time = None
    title = raw_text

    # Формат YYYY-MM-DD HH:MM
    match_date = re.match(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s+(.*)", raw_text)
    if match_date:
        remind_time = datetime.strptime(match_date.group(1), "%Y-%m-%d %H:%M")
        title = match_date.group(2)
    
    # "завтра о/в HH:MM"
    elif "завтра" in raw_text.lower():
        match_time = re.search(r"завтра\s+(?:о|в)?\s*(\d{1,2}:\d{2})\s+(.*)", raw_text.lower())
        if match_time:
            t_str = match_time.group(1)
            title = match_time.group(2)
            h, m = map(int, t_str.split(":"))
            remind_time = (now + timedelta(days=1)).replace(hour=h, minute=m)
        
    # "через X годин/хвилин"
    elif "через" in raw_text.lower():
        match_hours = re.search(r"через\s+(\d+)\s+год", raw_text.lower())
        match_mins = re.search(r"через\s+(\d+)\s+хв", raw_text.lower())
        if match_hours:
            hrs = int(match_hours.group(1))
            remind_time = now + timedelta(hours=hrs)
            title = re.sub(r"через\s+\d+\s+год[а-я]*", "", raw_text, flags=re.IGNORECASE).strip()
        elif match_mins:
            mins = int(match_mins.group(1))
            remind_time = now + timedelta(minutes=mins)
            title = re.sub(r"через\s+\d+\s+хв[а-я]*", "", raw_text, flags=re.IGNORECASE).strip()

    if not remind_time:
        await message.answer(
            "❌ Не вдалося розпізнати час.\nВикористовуйте формати:\n"
            "• `/remind 2026-12-01 10:00 Іпотека`\n"
            "• `/remind завтра о 15:00 Купити квитки`\n"
            "• `/remind через 2 год Вимкнути газ`"
        )
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
    
    await message.answer(f"🔔 Нагадування встановлено!\n📌 **{title}**\n📅 {full_date_str}", reply_markup=main_keyboard())

# === ЗАПУСК ===
async def main():
    logging.basicConfig(level=logging.INFO)
    await start_web_server()
    asyncio.create_task(check_reminders())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())