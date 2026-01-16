import os
import sqlite3
import time
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ChatMemberUpdated
from flask import Flask
from threading import Thread

# Configuration
TOKEN = "8556619747:AAFA1ZOfobW_N7dt2fhrPPBl7jTdHAPWfzc"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()
user_editing = {}

# Database Initialization
def get_db():
    conn = sqlite3.connect('system.db', check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn

db = get_db()
cur = db.cursor()

def init_db():
    cur.execute('''CREATE TABLE IF NOT EXISTS channels 
                   (chat_id INTEGER PRIMARY KEY, title TEXT, owner_id INTEGER, 
                    ad_cd INTEGER DEFAULT 18000, msg_cd INTEGER DEFAULT 30)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS whitelist 
                   (chat_id INTEGER, user_id INTEGER, PRIMARY KEY (chat_id, user_id))''')
    cur.execute('''CREATE TABLE IF NOT EXISTS stats 
                   (chat_id INTEGER, user_id INTEGER, last_time INTEGER DEFAULT 0, 
                    last_warn_id INTEGER DEFAULT 0, PRIMARY KEY (chat_id, user_id))''')
    db.commit()

init_db()

# Web Server for Keep-Alive
app = Flask(__name__)
@app.route('/')
def home():
    return "MIKTEX CONTROL STATUS: ACTIVE"

def format_time(seconds):
    if seconds < 60: return f"{seconds}с"
    if seconds < 3600: return f"{seconds // 60}м"
    return f"{seconds // 3600}ч {(seconds % 3600) // 60}м"

# Core Logic
@dp.channel_post()
async def monitor_posts(post: types.Message):
    chat_id = post.chat.id
    timestamp = int(time.time())
    
    cur.execute("SELECT ad_cd, msg_cd FROM channels WHERE chat_id=?", (chat_id,))
    config = cur.fetchone()
    if not config:
        return

    try:
        administrators = await bot.get_chat_administrators(chat_id)
        for admin in administrators:
            if admin.status == 'creator':
                continue
                
            signature = post.author_signature
            if signature and (admin.user.full_name == signature or admin.custom_title == signature):
                user_id = admin.user.id
                
                cur.execute("SELECT 1 FROM whitelist WHERE chat_id=? AND user_id=?", (chat_id, user_id))
                if cur.fetchone():
                    return

                is_ad_content = any([
                    post.photo, post.video, post.forward_date, 
                    post.entities, post.caption_entities, 
                    post.document, post.animation, post.audio
                ])
                
                cooldown = config[0] if is_ad_content else config[1]

                cur.execute("SELECT last_time, last_warn_id FROM stats WHERE chat_id=? AND user_id=?", (chat_id, user_id))
                user_stats = cur.fetchone() or (0, 0)
                
                time_passed = timestamp - user_stats[0]
                if time_passed < cooldown:
                    remaining = cooldown - time_passed
                    try:
                        await post.delete()
                        if user_stats[1] != 0:
                            try: await bot.delete_message(user_id, user_stats[1])
                            except: pass
                            
                        warning = await bot.send_message(
                            user_id, 
                            f"MIKTEX CONTROL\n\nКанал: {post.chat.title}\nСтатус: Пост удален (КД)\nДоступно через: {format_time(remaining)}"
                        )
                        cur.execute("INSERT OR REPLACE INTO stats (chat_id, user_id, last_time, last_warn_id) VALUES (?, ?, ?, ?)", 
                                   (chat_id, user_id, user_stats[0], warning.message_id))
                        db.commit()
                    except Exception as e:
                        logger.error(f"Failed to delete post or notify: {e}")
                else:
                    cur.execute("INSERT OR REPLACE INTO stats (chat_id, user_id, last_time, last_warn_id) VALUES (?, ?, ?, 0)", 
                               (chat_id, user_id, timestamp))
                    db.commit()
                return
    except Exception as e:
        logger.error(f"Monitor error: {e}")

# Interface
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    bot_info = await bot.get_me()
    invite_link = f"https://t.me/{bot_info.username}?startchannel=true&admin=post_messages+delete_messages+invite_users"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Привязать канал", url=invite_link)],
        [InlineKeyboardButton(text="Список каналов", callback_data="list_all")]
    ])
    await message.answer("MIKTEX CONTROL Активен\nВыберите действие:", reply_markup=keyboard)

@dp.callback_query(F.data == "list_all")
async def list_channels(callback: CallbackQuery):
    cur.execute("SELECT chat_id, title FROM channels WHERE owner_id=?", (callback.from_user.id,))
    rows = cur.fetchall()
    buttons = [[InlineKeyboardButton(text=row[1], callback_data=f"manage_{row[0]}")] for row in rows]
    
    if not buttons:
        return await callback.answer("Список пуст", show_alert=True)
        
    await callback.message.edit_text("Ваши привязанные каналы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("manage_"))
async def manage_channel(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[1])
    cur.execute("SELECT ad_cd, msg_cd, title FROM channels WHERE chat_id=?", (channel_id,))
    data = cur.fetchone()
    
    text = (f"Управление: {data[2]}\n\n"
            f"Задержка рекламы: {format_time(data[0])}\n"
            f"Задержка текста: {format_time(data[1])}")
            
    keyboard = [
        [InlineKeyboardButton(text="Изм. Рекламу", callback_data=f"set_ad_{channel_id}"), 
         InlineKeyboardButton(text="Изм. Текст", callback_data=f"set_msg_{channel_id}")],
        [InlineKeyboardButton(text="Белый список", callback_data=f"white_{channel_id}")],
        [InlineKeyboardButton(text="Назад", callback_data="list_all")]
    ]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@dp.callback_query(F.data.startswith("set_"))
async def set_cooldown(callback: CallbackQuery):
    _, mode, cid = callback.data.split("_")
    keyboard = [[InlineKeyboardButton(text="Минуты", callback_data=f"in_m_{mode}_{cid}"), 
                 InlineKeyboardButton(text="Часы", callback_data=f"in_h_{mode}_{cid}")]]
    await callback.message.edit_text("Выберите формат ввода числового значения:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@dp.callback_query(F.data.startswith("in_"))
async def input_handler(callback: CallbackQuery):
    _, unit, mode, cid = callback.data.split("_")
    user_editing[callback.from_user.id] = {"mode": mode, "id": cid, "unit": unit}
    await callback.message.edit_text("Введите числовое значение для сохранения:")

@dp.message(F.text)
async def process_input(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_editing:
        if message.text.isdigit():
            state = user_editing[user_id]
            multiplier = 60 if state['unit'] == 'm' else 3600
            new_value = int(message.text) * multiplier
            column = 'ad_cd' if state['mode'] == 'ad' else 'msg_cd'
            
            cur.execute(f"UPDATE channels SET {column}=? WHERE chat_id=?", (new_value, int(state['id'])))
            db.commit()
            del user_editing[user_id]
            await message.answer("Изменения успешно применены.")
        else:
            await message.answer("Ошибка: введите целое число.")

@dp.callback_query(F.data.startswith("white_"))
async def white_list_handler(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[1])
    try:
        admins = await bot.get_chat_administrators(channel_id)
        cur.execute("SELECT user_id FROM whitelist WHERE chat_id=?", (channel_id,))
        whitelisted = [r[0] for r in cur.fetchall()]
        
        keyboard = []
        for a in admins:
            if not a.user.is_bot and a.status != 'creator':
                status_label = "Разрешен" if a.user.id in whitelisted else "Ограничен"
                keyboard.append([InlineKeyboardButton(text=f"{status_label}: {a.user.first_name}", callback_data=f"toggle_{channel_id}_{a.user.id}")])
        
        keyboard.append([InlineKeyboardButton(text="Назад", callback_data=f"manage_{channel_id}")])
        await callback.message.edit_text("Настройка исключений (Белый список):", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    except Exception:
        await callback.answer("Ошибка доступа к списку администраторов", show_alert=True)

@dp.callback_query(F.data.startswith("toggle_"))
async def toggle_white(callback: CallbackQuery):
    _, cid, uid = callback.data.split("_")
    cur.execute("SELECT 1 FROM whitelist WHERE chat_id=? AND user_id=?", (int(cid), int(uid)))
    if cur.fetchone():
        cur.execute("DELETE FROM whitelist WHERE chat_id=? AND user_id=?", (int(cid), int(uid)))
    else:
        cur.execute("INSERT INTO whitelist VALUES (?, ?)", (int(cid), int(uid)))
    db.commit()
    await white_list_handler(callback)

@dp.my_chat_member()
async def on_chat_update(event: ChatMemberUpdated):
    if event.new_chat_member.status in ["administrator", "member"]:
        cur.execute("INSERT OR REPLACE INTO channels (chat_id, title, owner_id) VALUES (?, ?, ?)", 
                   (event.chat.id, event.chat.title, event.from_user.id))
        db.commit()

async def main():
    port = int(os.environ.get("PORT", 8080))
    Thread(target=lambda: app.run(host='0.0.0.0', port=port)).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
