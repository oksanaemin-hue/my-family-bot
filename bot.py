import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web

# === НАЛАШТУВАННЯ ===
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# === ФЕЙКОВИЙ ВЕБ-СЕРВЕР ДЛЯ RENDER ===
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

# === БАЗА ДАНИХ (SQLite) ===
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

# === ШЕДУЛЕР (Перевірка нагадувань) ===
async def check_reminders():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = sqlite3.connect("family_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, chat_id, title FROM reminders WHERE remind_date = ? AND is_done = 0", (now_str,))
    active_reminders = cursor.fetchall()
    
    for rem_id, chat_id, title in active_reminders:
        await bot.send_message(chat_id, f"🚨 **СІМЕЙНЕ НАГАДУВАННЯ!** 🚨\n\n📌 {title}")
        cursor.execute("UPDATE reminders SET is_done = 1 WHERE id = ?", (rem_id,))
    
    conn.commit()
    conn.close()

# === ХЕНДЛЕРИ БОТА ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привіт! Я ваш сімейний помічник.\n\n"
        "🛒 **Покупки:**\n"
        "• `/buy молоко, хліб` — додати в список\n"
        "• `/list` — переглянути список покупок\n\n"
        "⏰ **Нагадування:**\n"
        "• `/remind 2026-12-01 10:00 Сплатити іпотеку`\n"
        "• `/remind 2026-11-15 09:00 Запис на ТО авто`"
    )

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
    
    await message.answer(f"✅ Додано в список покупок ({len(items)} шт.)!")

@dp.message(Command("list"))
async def show_shopping_list(message: types.Message):
    conn = sqlite3.connect("family_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, item FROM shopping")
    items = cursor.fetchall()
    conn.close()
    
    if not items:
        await message.answer("🛒 Список покупок порожній!")
        return
    
    builder = InlineKeyboardBuilder()
    for item_id, item_name in items:
        builder.button(text=f"❌ {item_name}", callback_data=f"del_shop_{item_id}")
    builder.adjust(1)
    
    await message.answer("🛒 **Сімейний список покупок:**\n*(натисніть на товар, щоб викреслити)*", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("del_shop_"))
async def delete_shopping_item(callback: types.CallbackQuery):
    item_id = callback.data.split("_")[2]
    conn = sqlite3.connect("family_data.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM shopping WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    
    await callback.answer("Куплено!")
    await show_shopping_list(callback.message)

@dp.message(Command("remind"))
async def add_reminder(message: types.Message):
    try:
        payload = message.text.replace("/remind", "").strip().split(" ", 2)
        date_str = payload[0]
        time_str = payload[1]
        title = payload[2]
        
        full_date_str = f"{date_str} {time_str}"
        datetime.strptime(full_date_str, "%Y-%m-%d %H:%M")
        
        conn = sqlite3.connect("family_data.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reminders (chat_id, title, remind_date) VALUES (?, ?, ?)",
            (message.chat.id, title, full_date_str)
        )
        conn.commit()
        conn.close()
        
        await message.answer(f"🔔 Нагадування встановлено!\n📌 **{title}**\n📅 {full_date_str}")
    except Exception:
        await message.answer("❌ Формат: `/remind РРРР-ММ-ДД ГОД:ХВ Текст`")

# === ЗАПУСК ===
async def main():
    logging.basicConfig(level=logging.INFO)
    await start_web_server()
    scheduler.add_job(check_reminders, "interval", seconds=30)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())