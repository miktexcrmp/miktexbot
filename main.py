import os, time, asyncio, logging
from threading import Thread
from flask import Flask
from motor.motor_asyncio import AsyncIOMotorClient
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# --- CONFIG ---
ADMINS = [8128433095]
MONGO_URL = "mongodb+srv://miktexstudio:roma1111@cluster0.6damzqi.mongodb.net/"
TOKEN = "8556619747:AAFA1ZOfobW_N7dt2fhrPPBl7jTdHAPWfzc"

logging.basicConfig(level=logging.INFO, format='%(message)s')
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- DATABASE ---
client = AsyncIOMotorClient(MONGO_URL)
db = client.miktex_db
col_channels, col_users, col_logs = db.channels, db.users, db.logs
col_history, col_blacklist = db.history, db.blacklist

app = Flask(__name__)
@app.route('/')
def index(): return "MIKTEX CONTROL - MEGA VERSION ONLINE"

# --- CACHE & STATES ---
admin_cache = {}
state_data = {} # Для хранения состояния ввода (ад, текст, канал)

def get_format_time(s):
    if s < 60: return f"{s}s"
    if s < 3600: return f"{s//60}m"
    return f"{s//3600}h"

# --- CORE LOGIC ---

@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    await col_users.update_one({"user_id": m.from_user.id}, {"$set": {"user_id": m.from_user.id}}, upsert=True)
    kb = [
        [InlineKeyboardButton(text="Мои ресурсы", callback_data="list")],
        [InlineKeyboardButton(text="Глобальный ЧС", callback_data="g_ban_list")]
    ]
    if m.from_user.id in ADMINS:
        kb.append([InlineKeyboardButton(text="АДМИН ПАНЕЛЬ", callback_data="admin_main")])
    
    await m.answer("MIKTEX CONTROL - Система активна\nПерешлите пост из канала для привязки.", 
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.message(F.forward_from_chat)
async def handle_forward(m: types.Message):
    if m.forward_from_chat.type != "channel": return
    cid = m.forward_from_chat.id
    await col_channels.update_one(
        {"chat_id": cid},
        {"$set": {"title": m.forward_from_chat.title, "owner_id": m.from_user.id, "mute": False},
         "$setOnInsert": {"ad_cd": 18000, "msg_cd": 30, "total": 0}},
        upsert=True
    )
    await m.answer(f"Канал {m.forward_from_chat.title} успешно подключен.")

# --- MANAGEMENT ---

@dp.callback_query(F.data == "list")
async def list_ch(cb: CallbackQuery):
    cursor = col_channels.find({"owner_id": cb.from_user.id})
    btns = []
    async for r in cursor:
        btns.append([InlineKeyboardButton(text=r['title'], callback_data=f"cfg_{r['chat_id']}")])
    btns.append([InlineKeyboardButton(text="Назад", callback_data="back_to_start")])
    await cb.message.edit_text("Ваши каналы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data.startswith("cfg_"))
async def cfg_ch(cb: CallbackQuery):
    cid = int(cb.data.split("_")[1])
    c = await col_channels.find_one({"chat_id": cid})
    m_stat = "АКТИВЕН" if c.get("mute") else "ВЫКЛ"
    
    text = (f"РЕСУРС: {c['title']}\n"
            f"КД Реклама: {get_format_time(c['ad_cd'])}\n"
            f"КД Текст: {get_format_time(c['msg_cd'])}\n"
            f"Удалено: {c.get('total', 0)}\n"
            f"Режим тишины: {m_stat}")
    
    kb = [
        [InlineKeyboardButton(text="КД Реклама (часы)", callback_data=f"set_ad_{cid}"),
         InlineKeyboardButton(text="КД Текст (секунды)", callback_data=f"set_msg_{cid}")],
        [InlineKeyboardButton(text="Тишина (Вкл/Выкл)", callback_data=f"mute_toggle_{cid}")],
        [InlineKeyboardButton(text="Назад", callback_data="list")]
    ]
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("set_"))
async def set_cd(cb: CallbackQuery):
    _, mode, cid = cb.data.split("_")
    btns, row = [], []
    # Реклама в часах, сообщения в секундах
    vals = [1, 2, 6, 12, 24] if mode == "ad" else [10, 15, 20, 30, 45, 60]
    for v in vals:
        sec = v * 3600 if mode == "ad" else v
        label = f"{v}ч" if mode == "ad" else f"{v}с"
        row.append(InlineKeyboardButton(text=label, callback_data=f"save_{mode}_{cid}_{sec}"))
        if len(row) == 3: btns.append(row); row = []
    if row: btns.append(row)
    btns.append([InlineKeyboardButton(text="Свое значение", callback_data=f"input_{mode}_{cid}")])
    btns.append([InlineKeyboardButton(text="Назад", callback_data=f"cfg_{cid}")])
    await cb.message.edit_text(f"Выберите лимит ({'часы' if mode=='ad' else 'секунды'}):", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data.startswith("save_"))
async def save_val(cb: CallbackQuery):
    _, mode, cid, val = cb.data.split("_")
    field = "ad_cd" if mode == "ad" else "msg_cd"
    await col_channels.update_one({"chat_id": int(cid)}, {"$set": {field: int(val)}})
    await cb.answer("Настройка сохранена")
    await cfg_ch(cb)

@dp.callback_query(F.data.startswith("input_"))
async def input_val(cb: CallbackQuery):
    _, mode, cid = cb.data.split("_")
    state_data[cb.from_user.id] = {"mode": mode, "cid": cid}
    await cb.message.answer(f"Введите число ({'часы' if mode=='ad' else 'секунды'}):")

@dp.message(F.text & ~F.text.startswith('/'))
async def process_input(m: types.Message):
    uid = m.from_user.id
    if uid in state_data:
        if m.text.isdigit():
            d = state_data[uid]
            val = int(m.text)
            if d['mode'] == "ad": val *= 3600
            field = "ad_cd" if d['mode'] == "ad" else "msg_cd"
            await col_channels.update_one({"chat_id": int(d['cid'])}, {"$set": {field: val}})
            del state_data[uid]
            await m.answer("Успешно обновлено!")
        else: await m.answer("Введите число.")

@dp.callback_query(F.data.startswith("mute_toggle_"))
async def toggle_mute(cb: CallbackQuery):
    cid = int(cb.data.split("_")[2])
    c = await col_channels.find_one({"chat_id": cid})
    new_state = not c.get("mute", False)
    await col_channels.update_one({"chat_id": cid}, {"$set": {"mute": new_state}})
    await cb.answer("Статус режима тишины изменен")
    await cfg_ch(cb)

# --- MONITORING ENGINE ---

@dp.channel_post()
async def filter_engine(post: types.Message):
    cid = post.chat.id
    conf = await col_channels.find_one({"chat_id": cid})
    if not conf or not post.author_signature: return
    
    if conf.get("mute"):
        try: await post.delete(); return
        except: pass

    try:
        now = time.time()
        # Кэширование списка админов (5 минут), чтобы бот не "моросил"
        if cid not in admin_cache or now - admin_cache[cid]['t'] > 300:
            admins = await bot.get_chat_administrators(cid)
            admin_cache[cid] = {'t': now, 'list': admins}
        else: admins = admin_cache[cid]['list']

        for a in admins:
            if a.user.full_name == post.author_signature or a.custom_title == post.author_signature:
                if a.status == 'creator' or a.user.id == conf['owner_id']: return
                
                # Глобальный ЧС
                if await col_blacklist.find_one({"user_id": a.user.id}):
                    await post.delete(); return

                is_ad = any([post.photo, post.video, post.forward_date, post.entities, post.reply_markup])
                limit = conf['ad_cd'] if is_ad else conf['msg_cd']
                
                key = f"{cid}_{a.user.id}"
                last_doc = await col_logs.find_one({"_id": key}) or {'t': 0}
                
                if (now - last_doc['t']) < limit:
                    await post.delete()
                    await col_channels.update_one({"chat_id": cid}, {"$inc": {"total": 1}})
                    await col_history.insert_one({"cid": cid, "admin": a.user.full_name, "t": now, "type": "ad" if is_ad else "msg"})
                else:
                    await col_logs.update_one({"_id": key}, {"$set": {"t": now}}, upsert=True)
                break
    except Exception as e:
        logging.error(f"Error in filter: {e}")

# --- ADMIN PANEL ---

@dp.callback_query(F.data == "admin_main")
async def admin_main(cb: CallbackQuery):
    if cb.from_user.id not in ADMINS: return
    u, c = await col_users.count_documents({}), await col_channels.count_documents({})
    kb = [
        [InlineKeyboardButton(text="Рассылка", callback_data="broadcast")],
        [InlineKeyboardButton(text="Назад", callback_data="back_to_start")]
    ]
    await cb.message.edit_text(f"АДМИН ПАНЕЛЬ\nЮзеров: {u}\nКаналов: {c}", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "back_to_start")
async def to_start(cb: CallbackQuery): await cmd_start(cb.message)

async def start():
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(start())
