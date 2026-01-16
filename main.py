import os, time, asyncio, logging
from threading import Thread
from flask import Flask
from motor.motor_asyncio import AsyncIOMotorClient
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, KeyboardButtonRequestChat

# CONFIG
ADMINS = [8128433095]
MONGO_URL = "mongodb+srv://miktexstudio:roma1111@cluster0.6damzqi.mongodb.net/"
TOKEN = "8556619747:AAFA1ZOfobW_N7dt2fhrPPBl7jTdHAPWfzc"

logging.basicConfig(level=logging.INFO, format='%(message)s')
bot = Bot(token=TOKEN)
dp = Dispatcher()

client = AsyncIOMotorClient(MONGO_URL)
db = client.miktex_db
col_channels, col_users, col_logs = db.channels, db.users, db.logs

app = Flask(__name__)
@app.route('/')
def index(): return "SYSTEM_ONLINE"

def get_format_time(s):
    if s < 60: return f"{int(s)}s"
    if s < 3600: return f"{int(s//60)}m"
    return f"{int(s//3600)}h"

# ГЛАВНОЕ МЕНЮ
@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    await col_users.update_one({"user_id": m.from_user.id}, {"$set": {"user_id": m.from_user.id}}, upsert=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Привязать канал", callback_data="show_keyboard")],
        [InlineKeyboardButton(text="Мои каналы", callback_data="list")]
    ])
    await m.answer("MIKTEX CONTROL\nВыберите действие:", reply_markup=kb)

# ВЫЗОВ КЛАВИАТУРЫ ВЫБОРА
@dp.callback_query(F.data == "show_keyboard")
async def show_keyboard(cb: CallbackQuery):
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(
            text="Выбрать канал",
            request_chat=KeyboardButtonRequestChat(
                request_id=1,
                chat_is_channel=True,
                bot_is_member=True,
                bot_administrator_rights=types.ChatAdministratorRights(can_delete_messages=True)
            )
        )]
    ], resize_keyboard=True, one_time_keyboard=True)
    
    await cb.message.answer("Используйте кнопку выбора внизу:", reply_markup=kb)
    await cb.answer()

# ОБРАБОТКА ВЫБРАННОГО КАНАЛА
@dp.message(F.chat_shared)
async def chat_shared_handler(m: types.Message):
    chat_id = m.chat_shared.chat_id
    try:
        member = await bot.get_chat_member(chat_id, m.from_user.id)
        if member.status != 'creator':
            return await m.answer("Ошибка: Только владелец может привязать этот канал.", reply_markup=types.ReplyKeyboardRemove())
        
        chat = await bot.get_chat(chat_id)
        await col_channels.update_one(
            {"chat_id": chat_id},
            {"$set": {"title": chat.title, "owner_id": m.from_user.id},
             "$setOnInsert": {"ad_cd": 18000, "msg_cd": 30}},
            upsert=True
        )
        await m.answer(f"Канал {chat.title} привязан.", reply_markup=types.ReplyKeyboardRemove())
    except Exception:
        await m.answer("Ошибка: Проверьте права бота в канале.", reply_markup=types.ReplyKeyboardRemove())

# УПРАВЛЕНИЕ
@dp.callback_query(F.data == "list")
async def list_ch(cb: CallbackQuery):
    cursor = col_channels.find({"owner_id": cb.from_user.id})
    btns = []
    async for r in cursor:
        btns.append([InlineKeyboardButton(text=r['title'], callback_data=f"cfg_{r['chat_id']}")])
    btns.append([InlineKeyboardButton(text="Назад", callback_data="to_start")])
    await cb.message.edit_text("Ваши каналы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data.startswith("cfg_"))
async def cfg_ch(cb: CallbackQuery):
    cid = int(cb.data.split("_")[1])
    c = await col_channels.find_one({"chat_id": cid})
    text = (f"КАНАЛ: {c['title']}\n"
            f"КД Реклама: {get_format_time(c['ad_cd'])}\n"
            f"КД Текст: {get_format_time(c['msg_cd'])}")
    kb = [[InlineKeyboardButton(text="Реклама (ч)", callback_data=f"set_ad_{cid}"),
           InlineKeyboardButton(text="Текст (с)", callback_data=f"set_msg_{cid}")],
          [InlineKeyboardButton(text="Назад", callback_data="list")]]
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("set_"))
async def set_vals(cb: CallbackQuery):
    _, mode, cid = cb.data.split("_")
    vals = [1, 2, 6, 12, 24] if mode == "ad" else [10, 15, 20, 30, 45, 60]
    row = [InlineKeyboardButton(text=f"{v}{'h' if mode=='ad' else 's'}", 
           callback_data=f"sv_{mode}_{cid}_{v * 3600 if mode=='ad' else v}") for v in vals]
    await cb.message.edit_text("Установка лимита:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[row, [InlineKeyboardButton(text="Назад", callback_data=f"cfg_{cid}")]]))

@dp.callback_query(F.data.startswith("sv_"))
async def save_vals(cb: CallbackQuery):
    _, mode, cid, val = cb.data.split("_")
    await col_channels.update_one({"chat_id": int(cid)}, {"$set": {"ad_cd" if mode == "ad" else "msg_cd": int(val)}})
    await cb.answer("Сохранено")
    await cfg_ch(cb)

# МОНИТОРИНГ
@dp.channel_post()
async def monitor(post: types.Message):
    cid = post.chat.id
    conf = await col_channels.find_one({"chat_id": cid})
    if not conf: return
    
    try:
        now = time.time()
        target_id = None
        
        if post.author_signature:
            admins = await bot.get_chat_administrators(cid)
            for a in admins:
                if a.user.full_name == post.author_signature or a.custom_title == post.author_signature:
                    if a.status == 'creator' or a.user.id == conf['owner_id']: return
                    target_id = a.user.id
                    break
        
        if not target_id and post.sender_chat and post.sender_chat.id == cid:
            target_id = "anonymous_admin"

        if target_id:
            is_ad = any([post.photo, post.video, post.forward_date, post.entities])
            limit = conf['ad_cd'] if is_ad else conf['msg_cd']
            key = f"{cid}_{target_id}"
            last = await col_logs.find_one({"_id": key}) or {'t': 0}
            
            if (now - last['t']) < limit:
                await post.delete()
                if target_id != "anonymous_admin":
                    try:
                        rem = get_format_time(limit - (now - last['t']))
                        await bot.send_message(target_id, f"Удалено в {post.chat.title}. Ожидание: {rem}")
                    except: pass
            else:
                await col_logs.update_one({"_id": key}, {"$set": {"t": now}}, upsert=True)
    except: pass

@dp.callback_query(F.data == "to_start")
async def to_start(cb: CallbackQuery): await cmd_start(cb.message)

async def main():
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
