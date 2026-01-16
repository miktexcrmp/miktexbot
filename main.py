import os
import time
import asyncio
import logging
from threading import Thread
from flask import Flask
from motor.motor_asyncio import AsyncIOMotorClient
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    CallbackQuery, 
    KeyboardButton, 
    ReplyKeyboardMarkup, 
    KeyboardButtonRequestChat,
    ChatAdministratorRights
)

# Настройки
ADMINS = [8128433095] 
MONGO_URL = "mongodb+srv://miktexstudio:roma1111@cluster0.6damzqi.mongodb.net/" 
TOKEN = "8556619747:AAFA1ZOfobW_N7dt2fhrPPBl7jTdHAPWfzc"

logging.basicConfig(level=logging.INFO, format='%(message)s')
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Кэш и временные данные
user_editing = {}
alert_cooldown = {}

# БД
client = AsyncIOMotorClient(MONGO_URL)
db = client.miktex_db
col_channels = db.channels
col_users = db.users
col_logs = db.logs

app = Flask(__name__)

@app.route('/')
def index():
    return "MIKTEX CONTROL - SYSTEM BY MIKTEX"

async def sync_user(user: types.User):
    await col_users.update_one(
        {"user_id": user.id},
        {"$set": {"user_id": user.id, "name": user.full_name}},
        upsert=True
    )

def time_format(seconds):
    if seconds < 60: return f"{seconds}с"
    if seconds < 3600: return f"{seconds // 60}м"
    return f"{seconds // 3600}ч {(seconds % 3600) // 60}м"

@dp.message(Command("start"))
async def start_cmd(m: types.Message):
    await sync_user(m.from_user)
    
    # Кнопка привязки своего канала
    kb_reply = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(
            text="Привязать ресурс", 
            request_chat=KeyboardButtonRequestChat(
                request_id=1, 
                chat_is_channel=True,
                chat_is_created=True, # Только свои
                bot_is_member=True,
                bot_administrator_rights=ChatAdministratorRights(
                    can_delete_messages=True,
                    is_anonymous=False
                )
            )
        )]],
        resize_keyboard=True
    )
    
    kb_inline = [[InlineKeyboardButton(text="Мои ресурсы", callback_data="list_all")]]
    if m.from_user.id in ADMINS:
        kb_inline.append([InlineKeyboardButton(text="Панель управления", callback_data="admin_panel")])
    
    await m.answer("MIKTEX CONTROL - Разработчик MIKTEX", reply_markup=kb_reply)
    await m.answer("Выберите действие:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_inline))

@dp.message(F.chat_shared)
async def chat_shared_proc(m: types.Message):
    cid = m.chat_shared.chat_id
    try:
        chat = await bot.get_chat(cid)
        await col_channels.update_one(
            {"chat_id": cid},
            {"$set": {"title": chat.title, "owner_id": m.from_user.id},
             "$setOnInsert": {"ad_cd": 18000, "msg_cd": 30, "del_stat": 0}},
            upsert=True
        )
        await m.answer(f"Ресурс {chat.title} подключен.")
    except:
        await m.answer("Ошибка доступа к каналу.")

@dp.callback_query(F.data == "list_all")
async def show_list(cb: CallbackQuery):
    cursor = col_channels.find({"owner_id": cb.from_user.id})
    btns = []
    async for row in cursor:
        btns.append([InlineKeyboardButton(text=row['title'], callback_data=f"cfg_{row['chat_id']}")])
    
    if not btns:
        return await cb.message.edit_text("Список пуст.", 
                                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="back")]]))
    
    btns.append([InlineKeyboardButton(text="Назад", callback_data="back")])
    await cb.message.edit_text("Ваши ресурсы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data.startswith("cfg_"))
async def cfg_view(cb: CallbackQuery):
    cid = int(cb.data.split("_")[1])
    data = await col_channels.find_one({"chat_id": cid})
    
    text = (f"Ресурс: {data['title']}\n\n"
            f"КД Реклама: {time_format(data['ad_cd'])}\n"
            f"КД Текст: {time_format(data['msg_cd'])}\n"
            f"Удалено: {data.get('del_stat', 0)}")
    
    kb = [
        [InlineKeyboardButton(text="КД Реклама", callback_data=f"set_ad_{cid}"),
         InlineKeyboardButton(text="КД Текст", callback_data=f"set_msg_{cid}")],
        [InlineKeyboardButton(text="Назад", callback_data="list_all")]
    ]
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("set_"))
async def set_init(cb: CallbackQuery):
    _, mode, cid = cb.data.split("_")
    kb = [[InlineKeyboardButton(text="Минуты", callback_data=f"ut_m_{mode}_{cid}"),
           InlineKeyboardButton(text="Часы", callback_data=f"ut_h_{mode}_{cid}")]]
    await cb.message.edit_text("Выберите единицу:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("ut_"))
async def set_val_req(cb: CallbackQuery):
    _, unit, mode, cid = cb.data.split("_")
    user_editing[cb.from_user.id] = {"m": mode, "c": cid, "u": unit}
    await cb.message.edit_text(f"Введите число ({'минуты' if unit=='m' else 'часы'}):")

@dp.message(F.text)
async def text_handler(m: types.Message):
    uid = m.from_user.id
    if uid in user_editing:
        if m.text.isdigit():
            dt = user_editing[uid]
            sec = int(m.text) * (60 if dt['u'] == 'm' else 3600)
            field = 'ad_cd' if dt['m'] == 'ad' else 'msg_cd'
            await col_channels.update_one({"chat_id": int(dt['c'])}, {"$set": {field: sec}})
            del user_editing[uid]
            await m.answer("Обновлено.")

@dp.callback_query(F.data == "back")
async def back_to_start(cb: CallbackQuery):
    await start_cmd(cb.message)

@dp.channel_post()
async def filter_monitor(post: types.Message):
    cid = post.chat.id
    config = await col_channels.find_one({"chat_id": cid})
    if not config: return
    
    try:
        admins = await bot.get_chat_administrators(cid)
        for a in admins:
            if post.author_signature and (a.user.full_name == post.author_signature or a.custom_title == post.author_signature):
                if a.status == 'creator' or a.user.id == config['owner_id']: return
                
                is_ad = any([post.photo, post.video, post.forward_date, post.entities])
                limit = config['ad_cd'] if is_ad else config['msg_cd']
                
                log_key = f"{cid}_{a.user.id}"
                last_p = await col_logs.find_one({"_id": log_key}) or {'t': 0}
                
                if (time.time() - last_p['t']) < limit:
                    await post.delete()
                    await col_channels.update_one({"chat_id": cid}, {"$inc": {"del_stat": 1}})
                    if time.time() - alert_cooldown.get(log_key, 0) > 60:
                        await bot.send_message(a.user.id, f"Удалено в {post.chat.title}. КД.")
                        alert_cooldown[log_id] = time.time()
                else:
                    await col_logs.update_one({"_id": log_key}, {"$set": {"t": time.time()}}, upsert=True)
    except: pass

async def start_app():
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(start_app())
  
