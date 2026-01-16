import os, time, asyncio, logging
from threading import Thread
from flask import Flask
from motor.motor_asyncio import AsyncIOMotorClient
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# CONFIG
ADMINS = [8128433095]
MONGO_URL = "mongodb+srv://miktexstudio:roma1111@cluster0.6damzqi.mongodb.net/"
TOKEN = "8556619747:AAFA1ZOfobW_N7dt2fhrPPBl7jTdHAPWfzc"

logging.basicConfig(level=logging.INFO, format='%(message)s')
bot = Bot(token=TOKEN)
dp = Dispatcher()

# DATABASE
client = AsyncIOMotorClient(MONGO_URL)
db = client.miktex_db
col_channels, col_users, col_logs, col_blacklist = db.channels, db.users, db.logs, db.blacklist

app = Flask(__name__)
@app.route('/')
def index(): return "SYSTEM ONLINE"

# STORAGE
state_broadcast = {}
admin_cache = {}

def get_format_time(s):
    if s < 60: return f"{s}s"
    if s < 3600: return f"{s//60}m"
    return f"{s//3600}h"

# CORE COMMANDS
@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    await col_users.update_one({"user_id": m.from_user.id}, {"$set": {"user_id": m.from_user.id}}, upsert=True)
    kb = [[InlineKeyboardButton(text="Список ресурсов", callback_data="list")]]
    if m.from_user.id in ADMINS:
        kb.append([InlineKeyboardButton(text="Админ панель", callback_data="admin_main")])
    
    await m.answer("MIKTEX CONTROL\nСистема готова. Для привязки перешлите пост из канала.", 
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.message(F.forward_from_chat)
async def handle_forward(m: types.Message):
    if m.forward_from_chat.type != "channel": return
    cid = m.forward_from_chat.id
    await col_channels.update_one(
        {"chat_id": cid},
        {"$set": {"title": m.forward_from_chat.title, "owner_id": m.from_user.id, "mute_mode": False},
         "$setOnInsert": {"ad_cd": 18000, "msg_cd": 30, "total_del": 0}},
        upsert=True
    )
    await m.answer(f"Ресурс {m.forward_from_chat.title} привязан.")

# RESOURCE MANAGEMENT
@dp.callback_query(F.data == "list")
async def list_channels(cb: CallbackQuery):
    cursor = col_channels.find({"owner_id": cb.from_user.id})
    btns = []
    async for r in cursor:
        btns.append([InlineKeyboardButton(text=r['title'], callback_data=f"cfg_{r['chat_id']}")])
    btns.append([InlineKeyboardButton(text="Назад", callback_data="to_home")])
    await cb.message.edit_text("Ваши ресурсы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data.startswith("cfg_"))
async def cfg_channel(cb: CallbackQuery):
    cid = int(cb.data.split("_")[1])
    c = await col_channels.find_one({"chat_id": cid})
    m_stat = "ВКЛ" if c.get("mute_mode") else "ВЫКЛ"
    
    text = (f"КАНАЛ: {c['title']}\n"
            f"КД Реклама: {get_format_time(c['ad_cd'])}\n"
            f"КД Текст: {get_format_time(c['msg_cd'])}\n"
            f"Удалено: {c.get('total_del', 0)}\n"
            f"Тишина: {m_stat}")
    
    kb = [
        [InlineKeyboardButton(text="КД Реклама (ч)", callback_data=f"set_ad_{cid}"),
         InlineKeyboardButton(text="КД Текст (с)", callback_data=f"set_msg_{cid}")],
        [InlineKeyboardButton(text="Тишина (Toggle)", callback_data=f"mute_{cid}")],
        [InlineKeyboardButton(text="Назад", callback_data="list")]
    ]
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("mute_"))
async def toggle_mute(cb: CallbackQuery):
    cid = int(cb.data.split("_")[1])
    c = await col_channels.find_one({"chat_id": cid})
    new_state = not c.get("mute_mode", False)
    await col_channels.update_one({"chat_id": cid}, {"$set": {"mute_mode": new_state}})
    await cb.answer("Режим тишины изменен")
    await cfg_channel(cb)

# MONITORING ENGINE
@dp.channel_post()
async def filter_engine(post: types.Message):
    cid = post.chat.id
    conf = await col_channels.find_one({"chat_id": cid})
    if not conf or not post.author_signature: return
    
    if conf.get("mute_mode"):
        try: await post.delete(); return
        except: pass

    try:
        now = time.time()
        if cid not in admin_cache or now - admin_cache[cid]['t'] > 300:
            admins = await bot.get_chat_administrators(cid)
            admin_cache[cid] = {'t': now, 'list': admins}
        else: admins = admin_cache[cid]['list']

        for a in admins:
            if a.user.full_name == post.author_signature or a.custom_title == post.author_signature:
                if a.status == 'creator' or a.user.id == conf['owner_id']: return
                
                if await col_blacklist.find_one({"user_id": a.user.id}):
                    await post.delete(); return

                is_ad = any([post.photo, post.video, post.forward_date, post.entities, post.reply_markup])
                limit = conf['ad_cd'] if is_ad else conf['msg_cd']
                
                key = f"{cid}_{a.user.id}"
                last = await col_logs.find_one({"_id": key}) or {'t': 0}
                
                if (now - last['t']) < limit:
                    await post.delete()
                    await col_channels.update_one({"chat_id": cid}, {"$inc": {"total_del": 1}})
                else:
                    await col_logs.update_one({"_id": key}, {"$set": {"t": now}}, upsert=True)
                break
    except: pass

# ADMIN PANEL
@dp.callback_query(F.data == "admin_main")
async def admin_panel(cb: CallbackQuery):
    if cb.from_user.id not in ADMINS: return
    u, c = await col_users.count_documents({}), await col_channels.count_documents({})
    kb = [
        [InlineKeyboardButton(text="Рассылка", callback_data="broadcast")],
        [InlineKeyboardButton(text="Назад", callback_data="to_home")]
    ]
    await cb.message.edit_text(f"АДМИН ПАНЕЛЬ\nЮзеров: {u}\nКаналов: {c}", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "to_home")
async def to_home(cb: CallbackQuery): await cmd_start(cb.message)

async def main():
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
        
