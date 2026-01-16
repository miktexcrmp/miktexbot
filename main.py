import os, time, asyncio, logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
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

cluster = AsyncIOMotorClient(MONGO_URL)
db = cluster.miktex_db
channels_col = db.channels
whitelist_col = db.whitelist
stats_col = db.stats

app = Flask(__name__)
@app.route('/')
def home(): return "MIKTEX CONTROL - Разработчик MIKTEX"

def format_time(seconds):
    if seconds < 60: return f"{seconds} сек"
    if seconds < 3600: return f"{seconds // 60} мин"
    return f"{seconds // 3600} ч {(seconds % 3600) // 60} мин"

async def get_creator_id(chat_id):
    try:
        admins = await bot.get_chat_administrators(chat_id)
        for a in admins:
            if a.status == 'creator': return a.user.id
    except: pass
    return None

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
                
                if a.status == 'creator' or uid == conf['owner_id']:
                    return

                if await whitelist_col.find_one({"chat_id": cid, "user_id": uid}):
                    return
                
                is_ad = any([post.photo, post.video, post.forward_date, post.entities, post.caption_entities, post.document, post.reply_markup])
                limit = conf['ad_cd'] if is_ad else conf['msg_cd']
                
                st = await stats_col.find_one({"chat_id": cid, "user_id": uid}) or {"last_time": 0, "last_warn_id": 0}
                wait = limit - (now - st['last_time'])
                
                if wait > 0:
                    await post.delete()
                    if st['last_warn_id'] != 0:
                        try: await bot.delete_message(uid, st['last_warn_id'])
                        except: pass
                    warn = await bot.send_message(uid, f"MIKTEX CONTROL\nКанал: {post.chat.title}\nСтатус: Удалено (Лимит)\nЖдать: {format_time(wait)}")
                    await stats_col.update_one({"chat_id": cid, "user_id": uid}, {"$set": {"last_time": st['last_time'], "last_warn_id": warn.message_id}}, upsert=True)
                else:
                    await stats_col.update_one({"chat_id": cid, "user_id": uid}, {"$set": {"last_time": now, "last_warn_id": 0}}, upsert=True)
                return
    except: pass

@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Мои каналы", callback_data="list_all")]])
    await m.answer(f"MIKTEX CONTROL - Разработчик MIKTEX\n\nВаш ID: {m.from_user.id}\nДля привязки: добавьте бота в канал как админа и перешлите пост сюда.", reply_markup=kb)

@dp.message(F.forward_from_chat)
async def register(m: types.Message):
    cid = m.forward_from_chat.id
    requester = m.from_user.id
    creator_id = await get_creator_id(cid)

    if requester not in ADMINS and requester != creator_id:
        return await m.answer("Ошибка: Добавить канал может только его Создатель.")

    owner = creator_id if creator_id else requester
    await channels_col.update_one(
        {"chat_id": cid}, 
        {"$set": {"title": m.forward_from_chat.title, "owner_id": owner}, "$setOnInsert": {"ad_cd": 18000, "msg_cd": 30}}, 
        upsert=True
    )
    await m.answer(f"MIKTEX CONTROL\nКанал успешно привязан.\nВладелец: {owner}")

@dp.callback_query(F.data == "list_all")
async def list_all(cb: CallbackQuery):
    cursor = channels_col.find({"owner_id": cb.from_user.id})
    btns = []
    async for r in cursor:
        btns.append([InlineKeyboardButton(text=r['title'], callback_data=f"manage_{r['chat_id']}")] )
    
    if not btns:
        return await cb.message.edit_text("У тебя нету канала, привяжи его. Для этого перешли пост из своего канала сюда.", 
                                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="back_start")]]))
    
    await cb.message.edit_text("Ваши каналы под защитой:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data == "back_start")
async def back_start(cb: CallbackQuery):
    await cmd_start(cb.message)

@dp.callback_query(F.data.startswith("manage_"))
async def manage(cb: CallbackQuery):
    cid = int(cb.data.split("_")[1])
    res = await channels_col.find_one({"chat_id": cid})
    text = f"MIKTEX CONTROL | {res['title']}\n\nКД Реклама: {format_time(res['ad_cd'])}\nКД Текст: {format_time(res['msg_cd'])}"
    kb = [[InlineKeyboardButton(text="КД Реклама", callback_data=f"set_ad_{cid}"), InlineKeyboardButton(text="КД Текст", callback_data=f"set_msg_{cid}")],
          [InlineKeyboardButton(text="Белый список", callback_data=f"white_{cid}")],
          [InlineKeyboardButton(text="Назад", callback_data="list_all")]]
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("set_"))
async def set_val(cb: CallbackQuery):
    _, mode, cid = cb.data.split("_")
    kb = [[InlineKeyboardButton(text="Минуты", callback_data=f"in_m_{mode}_{cid}"), InlineKeyboardButton(text="Часы", callback_data=f"in_h_{mode}_{cid}")]]
    await cb.message.edit_text("Выберите формат времени:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("in_"))
async def input_val(cb: CallbackQuery):
    _, unit, mode, cid = cb.data.split("_")
    user_editing[cb.from_user.id] = {"m": mode, "c": cid, "u": unit}
    await cb.message.edit_text("Введите число:")

@dp.message(F.text)
async def handle_text(m: types.Message):
    uid = m.from_user.id
    if uid in user_editing:
        if m.text.isdigit():
            d = user_editing[uid]
            val = int(m.text) * (60 if d['u'] == 'm' else 3600)
            col = 'ad_cd' if d['m'] == 'ad' else 'msg_cd'
            await channels_col.update_one({"chat_id": int(d['c'])}, {"$set": {col: val}})
            del user_editing[uid]
            await m.answer("Настройки сохранены.")
        else: await m.answer("Ошибка: введите число.")

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
        await cb.message.edit_text("Белый список администраторов:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except: await cb.answer("Ошибка доступа.", show_alert=True)

@dp.callback_query(F.data.startswith("tw_"))
async def toggle(cb: CallbackQuery):
    _, cid, uid = cb.data.split("_")
    cid, uid = int(cid), int(uid)
    if await whitelist_col.find_one({"chat_id": cid, "user_id": uid}):
        await whitelist_col.delete_one({"chat_id": cid, "user_id": uid})
    else:
        await whitelist_col.insert_one({"chat_id": cid, "user_id": uid})
    await white(cb)

async def start_bot():
    port = int(os.environ.get("PORT", 8080))
    Thread(target=lambda: app.run(host='0.0.0.0', port=port)).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(start_bot())
        
