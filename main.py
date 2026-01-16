import os, time, asyncio, logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, 
                           KeyboardButton, ReplyKeyboardMarkup, KeyboardButtonRequestChat)
from flask import Flask
from threading import Thread
from motor.motor_asyncio import AsyncIOMotorClient

# CONFIGURATION
ADMINS = [8128433095] 
MONGO_URL = "mongodb+srv://miktexstudio:roma1111@cluster0.6damzqi.mongodb.net/" 
TOKEN = "8556619747:AAFA1ZOfobW_N7dt2fhrPPBl7jTdHAPWfzc"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
user_editing = {}
broadcast_mode = {}

cluster = AsyncIOMotorClient(MONGO_URL)
db = cluster.miktex_db
channels_col = db.channels
whitelist_col = db.whitelist
stats_col = db.stats
users_col = db.users

app = Flask(__name__)
@app.route('/')
def home(): return "MIKTEX CONTROL - Active"

async def auto_collect_user(user: types.User):
    await users_col.update_one({"user_id": user.id}, {"$set": {"user_id": user.id, "name": user.full_name}}, upsert=True)

def format_time(seconds):
    if seconds < 60: return f"{seconds} сек"
    if seconds < 3600: return f"{seconds // 60} мин"
    return f"{seconds // 3600} ч {(seconds % 3600) // 60} мин"

@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    await auto_collect_user(m.from_user)
    
    # Кнопка для выбора канала пользователем
    request_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(
                text="Выбрать канал для привязки", 
                request_chat=KeyboardButtonRequestChat(request_id=1, chat_is_channel=True)
            )]
        ],
        resize_keyboard=True
    )
    
    inline_kb = [[InlineKeyboardButton(text="Мои каналы", callback_data="list_all")]]
    if m.from_user.id in ADMINS:
        inline_kb.append([InlineKeyboardButton(text="АДМИН ПАНЕЛЬ", callback_data="admin_main")])
    
    await m.answer("MIKTEX CONTROL\n\n1. Нажмите кнопку ниже\n2. Выберите ваш канал\n3. Обязательно добавьте бота в админы и дайте права на Удаление сообщений.", 
                   reply_markup=request_kb)
    await m.answer("Управление:", reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_kb))

@dp.message(F.chat_shared)
async def on_chat_shared(m: types.Message):
    await auto_collect_user(m.from_user)
    chat_id = m.chat_shared.chat_id
    
    try:
        # Проверка, добавлен ли бот и есть ли права
        chat = await bot.get_chat(chat_id)
        member = await bot.get_chat_member(chat_id, bot.id)
        
        if not member.can_delete_messages:
            return await m.answer(f"ВНИМАНИЕ: В канале {chat.title} не выданы права на удаление сообщений. Работа бота невозможна.")

        await channels_col.update_one(
            {"chat_id": chat_id}, 
            {"$set": {"title": chat.title, "owner_id": m.from_user.id}, 
             "$setOnInsert": {"ad_cd": 18000, "msg_cd": 30}}, 
            upsert=True
        )
        await m.answer(f"Канал {chat.title} успешно привязан.")
        
    except Exception:
        await m.answer("Ошибка: Бот не найден в канале. Сначала добавьте бота в канал как администратора с правом удаления сообщений.")

# --- ОСТАЛЬНАЯ ЛОГИКА (АДМИНКА И МОНИТОРИНГ) ---

@dp.callback_query(F.data == "admin_main")
async def admin_main(cb: CallbackQuery):
    if cb.from_user.id not in ADMINS: return
    u_count = await users_col.count_documents({})
    c_count = await channels_col.count_documents({})
    text = f"ГЛОБАЛЬНОЕ УПРАВЛЕНИЕ\n\nЮзеров: {u_count}\nКаналов: {c_count}"
    kb = [
        [InlineKeyboardButton(text="Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="Все каналы (GOD MODE)", callback_data="admin_all_channels")],
        [InlineKeyboardButton(text="Назад", callback_data="back_start")]
    ]
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "admin_all_channels")
async def admin_all_channels(cb: CallbackQuery):
    if cb.from_user.id not in ADMINS: return
    cursor = channels_col.find()
    btns = []
    async for r in cursor:
        btns.append([InlineKeyboardButton(text=r['title'], callback_data=f"manage_{r['chat_id']}")] )
    btns.append([InlineKeyboardButton(text="Назад", callback_data="admin_main")])
    await cb.message.edit_text("Все каналы системы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data == "list_all")
async def list_all(cb: CallbackQuery):
    cursor = channels_col.find({"owner_id": cb.from_user.id})
    btns = []
    async for r in cursor:
        btns.append([InlineKeyboardButton(text=r['title'], callback_data=f"manage_{r['chat_id']}")] )
    if not btns:
        return await cb.message.edit_text("Каналы не привязаны.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="back_start")]]))
    await cb.message.edit_text("Ваши каналы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data.startswith("manage_"))
async def manage(cb: CallbackQuery):
    cid = int(cb.data.split("_")[1])
    res = await channels_col.find_one({"chat_id": cid})
    if not res: return
    text = f"УПРАВЛЕНИЕ: {res['title']}\n\nКД Реклама: {format_time(res['ad_cd'])}\nКД Текст: {format_time(res['msg_cd'])}"
    kb = [[InlineKeyboardButton(text="КД Реклама", callback_data=f"set_ad_{cid}"), InlineKeyboardButton(text="КД Текст", callback_data=f"set_msg_{cid}")],
          [InlineKeyboardButton(text="Белый список", callback_data=f"white_{cid}")],
          [InlineKeyboardButton(text="Назад", callback_data="list_all" if cb.from_user.id not in ADMINS else "admin_all_channels")]]
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "back_start")
async def back_start(cb: CallbackQuery):
    await cmd_start(cb.message)

@dp.message()
async def handle_all(m: types.Message):
    await auto_collect_user(m.from_user)
    uid = m.from_user.id
    if uid in broadcast_mode:
        del broadcast_mode[uid]
        users = users_col.find()
        success = 0
        async for user in users:
            try:
                await m.copy_to(user['user_id'])
                success += 1
                await asyncio.sleep(0.05)
            except: pass
        await m.answer(f"Рассылка завершена. Успешно: {success}")
        return
    if uid in user_editing:
        if m.text and m.text.isdigit():
            d = user_editing[uid]
            val = int(m.text) * (60 if d['u'] == 'm' else 3600)
            col = 'ad_cd' if d['m'] == 'ad' else 'msg_cd'
            await channels_col.update_one({"chat_id": int(d['c'])}, {"$set": {col: val}})
            del user_editing[uid]
            await m.answer("Настройки сохранены.")
        return

@dp.callback_query(F.data.startswith("set_"))
async def set_val(cb: CallbackQuery):
    _, mode, cid = cb.data.split("_")
    kb = [[InlineKeyboardButton(text="Минуты", callback_data=f"in_m_{mode}_{cid}"), InlineKeyboardButton(text="Часы", callback_data=f"in_h_{mode}_{cid}")]]
    await cb.message.edit_text("Единица времени:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("in_"))
async def input_val(cb: CallbackQuery):
    _, unit, mode, cid = cb.data.split("_")
    user_editing[cb.from_user.id] = {"m": mode, "c": cid, "u": unit}
    await cb.message.edit_text("Введите число:")

@dp.callback_query(F.data.startswith("white_"))
async def white(cb: CallbackQuery):
    cid = int(cb.data.split("_")[1])
    try:
        admins = await bot.get_chat_administrators(cid)
        kb = []
        for a in admins:
            if not a.user.is_bot and a.status != 'creator':
                is_w = await whitelist_col.find_one({"chat_id": cid, "user_id": a.user.id})
                status = "БЕЛЫЙ" if is_w else "КД"
                kb.append([InlineKeyboardButton(text=f"{a.user.first_name}: {status}", callback_data=f"tw_{cid}_{a.user.id}")])
        kb.append([InlineKeyboardButton(text="Назад", callback_data=f"manage_{cid}")])
        await cb.message.edit_text("Белый список:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except: pass

@dp.callback_query(F.data.startswith("tw_"))
async def toggle(cb: CallbackQuery):
    _, cid, uid = cb.data.split("_")
    cid, uid = int(cid), int(uid)
    if await whitelist_col.find_one({"chat_id": cid, "user_id": uid}):
        await whitelist_col.delete_one({"chat_id": cid, "user_id": uid})
    else:
        await whitelist_col.insert_one({"chat_id": cid, "user_id": uid})
    await white(cb)

@dp.channel_post()
async def monitor(post: types.Message):
    cid, now = post.chat.id, int(time.time())
    conf = await channels_col.find_one({"chat_id": cid})
    if not conf: return
    try:
        admins = await bot.get_chat_administrators(cid)
        for a in admins:
            sig = post.author_signature
            if sig and (a.user.full_name == sig or a.custom_title == sig):
                uid = a.user.id
                if a.status == 'creator' or uid == conf['owner_id']: return
                if await whitelist_col.find_one({"chat_id": cid, "user_id": uid}): return
                is_ad = any([post.photo, post.video, post.forward_date, post.entities, post.caption_entities, post.document, post.reply_markup])
                limit = conf['ad_cd'] if is_ad else conf['msg_cd']
                st = await stats_col.find_one({"chat_id": cid, "user_id": uid}) or {"last_time": 0, "last_warn_id": 0}
                wait = limit - (now - st['last_time'])
                if wait > 0:
                    await post.delete()
                    if st['last_warn_id'] != 0:
                        try: await bot.delete_message(uid, st['last_warn_id'])
                        except: pass
                    warn = await bot.send_message(uid, f"MIKTEX CONTROL\nКанал: {post.chat.title}\nУдалено (КД)\nЖдать: {format_time(wait)}")
                    await stats_col.update_one({"chat_id": cid, "user_id": uid}, {"$set": {"last_time": st['last_time'], "last_warn_id": warn.message_id}}, upsert=True)
                else:
                    await stats_col.update_one({"chat_id": cid, "user_id": uid}, {"$set": {"last_time": now, "last_warn_id": 0}}, upsert=True)
    except: pass

async def start_bot():
    port = int(os.environ.get("PORT", 8080))
    Thread(target=lambda: app.run(host='0.0.0.0', port=port)).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(start_bot())


