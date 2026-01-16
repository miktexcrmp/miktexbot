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

# ТОКЕН
TOKEN = "8556619747:AAFA1ZOfobW_N7dt2fhrPPBl7jTdHAPWfzc"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
user_editing = {}

# Настройка базы данных
def get_db():
    conn = sqlite3.connect('system.db', check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

db = get_db()
cur = db.cursor()
cur.execute('''CREATE TABLE IF NOT EXISTS channels 
               (chat_id INTEGER PRIMARY KEY, title TEXT, owner_id INTEGER, 
                ad_cd INTEGER DEFAULT 18000, msg_cd INTEGER DEFAULT 30)''')
cur.execute('CREATE TABLE IF NOT EXISTS whitelist (chat_id INTEGER, user_id INTEGER, PRIMARY KEY (chat_id, user_id))')
cur.execute('CREATE TABLE IF NOT EXISTS stats (chat_id INTEGER, user_id INTEGER, last_time INTEGER DEFAULT 0, last_warn_id INTEGER DEFAULT 0, PRIMARY KEY (chat_id, user_id))')
db.commit()

# Flask сервер для Railway
app = Flask(__name__)
@app.route('/')
def home(): return "online"

def seconds_to_hms(seconds):
    if seconds < 60: return f"{seconds}с"
    if seconds < 3600: return f"{seconds // 60}м"
    return f"{seconds // 3600}ч {(seconds % 3600) // 60}м"

# Мониторинг постов
@dp.channel_post()
async def monitor(post: types.Message):
    cid = post.chat.id
    now = int(time.time())
    cur.execute("SELECT ad_cd, msg_cd FROM channels WHERE chat_id=?", (cid,))
    res = cur.fetchone()
    if not res: return

    try:
        admins = await bot.get_chat_administrators(cid)
        for a in admins:
            if a.status == 'creator': continue
            sig = post.author_signature
            if sig and (a.user.full_name == sig or a.custom_title == sig):
                uid = a.user.id
                cur.execute("SELECT 1 FROM whitelist WHERE chat_id=? AND user_id=?", (cid, uid))
                if cur.fetchone(): return

                is_ad = any([post.photo, post.video, post.forward_date, post.entities, post.caption_entities])
                limit = res[0] if is_ad else res[1]

                cur.execute("SELECT last_time, last_warn_id FROM stats WHERE chat_id=? AND user_id=?", (cid, uid))
                st = cur.fetchone() or (0, 0)
                
                wait = limit - (now - st[0])
                if wait > 0:
                    await post.delete()
                    if st[1] != 0:
                        try: await bot.delete_message(uid, st[1])
                        except: pass
                    warn = await bot.send_message(uid, f"Удалено в {post.chat.title}. Подождите {seconds_to_hms(wait)}")
                    cur.execute("INSERT OR REPLACE INTO stats (chat_id, user_id, last_time, last_warn_id) VALUES (?, ?, ?, ?)", (cid, uid, st[0], warn.message_id))
                    db.commit()
                else:
                    cur.execute("INSERT OR REPLACE INTO stats (chat_id, user_id, last_time, last_warn_id) VALUES (?, ?, ?, 0)", (cid, uid, now))
                    db.commit()
                return
    except Exception as e:
        logging.error(f"Error: {e}")

# Команды и меню
@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мои каналы", callback_data="list_all")]
    ])
    await m.answer("Система активна.", reply_markup=kb)

@dp.callback_query(F.data == "list_all")
async def list_all(cb: CallbackQuery):
    cur.execute("SELECT chat_id, title FROM channels WHERE owner_id=?", (cb.from_user.id,))
    rows = cur.fetchall()
    btns = [[InlineKeyboardButton(text=r[1], callback_data=f"manage_{r[0]}")] for r in rows]
    if not btns: return await cb.answer("Каналов нет", show_alert=True)
    await cb.message.edit_text("Ваши каналы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data.startswith("manage_"))
async def manage(cb: CallbackQuery):
    cid = int(cb.data.split("_")[1])
    cur.execute("SELECT ad_cd, msg_cd, title FROM channels WHERE chat_id=?", (cid,))
    res = cur.fetchone()
    text = f"Канал: {res[2]}\nКД Реклама: {seconds_to_hms(res[0])}\nКД Текст: {seconds_to_hms(res[1])}"
    kb = [[InlineKeyboardButton(text="КД Реклама", callback_data=f"ed_ad_{cid}"), InlineKeyboardButton(text="КД Текст", callback_data=f"ed_msg_{cid}")],
          [InlineKeyboardButton(text="Белый список", callback_data=f"w_list_{cid}")],
          [InlineKeyboardButton(text="Назад", callback_data="list_all")]]
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("ed_"))
async def ed_val(cb: CallbackQuery):
    _, mode, cid = cb.data.split("_")
    kb = [[InlineKeyboardButton(text="Минуты", callback_data=f"cust_m_{mode}_{cid}"), InlineKeyboardButton(text="Часы", callback_data=f"cust_h_{mode}_{cid}")]]
    await cb.message.edit_text("Формат:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("cust_"))
async def cust_in(cb: CallbackQuery):
    _, unit, mode, cid = cb.data.split("_")
    user_editing[cb.from_user.id] = {"m": mode, "c": cid, "u": unit}
    await cb.message.edit_text("Введите число:")

@dp.message(F.text)
async def handle_txt(m: types.Message):
    if m.from_user.id in user_editing:
        if m.text.isdigit():
            d = user_editing[m.from_user.id]
            val = int(m.text) * (60 if d['u'] == 'm' else 3600)
            cur.execute(f"UPDATE channels SET {'ad_cd' if d['m'] == 'ad' else 'msg_cd'}=? WHERE chat_id=?", (val, int(d['c'])))
            db.commit()
            del user_editing[m.from_user.id]
            await m.answer("Сохранено.")

@dp.callback_query(F.data.startswith("w_list_"))
async def w_list(cb: CallbackQuery):
    cid = int(cb.data.split("_")[1])
    admins = await bot.get_chat_administrators(cid)
    cur.execute("SELECT user_id FROM whitelist WHERE chat_id=?", (cid,))
    whited = [r[0] for r in cur.fetchall()]
    kb = [[InlineKeyboardButton(text=f"{'[Вкл]' if a.user.id in whited else '[Выкл]'} {a.user.first_name}", callback_data=f"tw_{cid}_{a.user.id}")] for a in admins if not a.user.is_bot and a.status != 'creator']
    kb.append([InlineKeyboardButton(text="Назад", callback_data=f"manage_{cid}")])
    await cb.message.edit_text("Белый список:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("tw_"))
async def tw(cb: CallbackQuery):
    _, cid, uid = cb.data.split("_")
    cur.execute("SELECT 1 FROM whitelist WHERE chat_id=? AND user_id=?", (int(cid), int(uid)))
    if cur.fetchone(): cur.execute("DELETE FROM whitelist WHERE chat_id=? AND user_id=?", (int(cid), int(uid)))
    else: cur.execute("INSERT INTO whitelist VALUES (?, ?)", (int(cid), int(uid)))
    db.commit()
    await w_list(cb)

@dp.my_chat_member()
async def updates(event: ChatMemberUpdated):
    if event.new_chat_member.status in ["administrator", "member"]:
        cur.execute("INSERT OR REPLACE INTO channels (chat_id, title, owner_id) VALUES (?, ?, ?)", (event.chat.id, event.chat.title, event.from_user.id))
        db.commit()

async def main_async():
    # Настройка порта для Railway
    port = int(os.environ.get("PORT", 8080))
    # Запуск Flask сервера в отдельном потоке
    server = Thread(target=lambda: app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False))
    server.daemon = True
    server.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, SystemExit):
        pass
