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

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

client = AsyncIOMotorClient(MONGO_URL)
db = client.miktex_db
col_channels, col_users, col_logs = db.channels, db.users, db.logs

app = Flask(__name__)
@app.route('/')
def index(): return "MIKTEX CONTROL ACTIVE"

state_data = {}

def get_format_time(s):
    if s < 60: return f"{s}с"
    return f"{s//60}м"

# --- КОМАНДЫ ---
@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    await col_users.update_one({"user_id": m.from_user.id}, {"$set": {"user_id": m.from_user.id}}, upsert=True)
    kb = [[InlineKeyboardButton(text="Мои каналы", callback_data="list")]]
    if m.from_user.id in ADMINS:
        kb.append([InlineKeyboardButton(text="АДМИН ПАНЕЛЬ", callback_data="admin_stats")])
    
    await m.answer("MIKTEX CONTROL - Разработчик MIKTEX\n\nДля привязки: добавьте бота в канал (админом) и перешлите пост из канала сюда.", 
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.message(F.forward_from_chat)
async def handle_forward(m: types.Message):
    if m.forward_from_chat.type != "channel": return
    cid = m.forward_from_chat.id
    try:
        member = await bot.get_chat_member(cid, bot.id)
        if member.status not in ["administrator", "creator"]:
            return await m.answer("Сначала сделайте бота админом в канале.")
        await col_channels.update_one(
            {"chat_id": cid},
            {"$set": {"title": m.forward_from_chat.title, "owner_id": m.from_user.id},
             "$setOnInsert": {"ad_cd": 18000, "msg_cd": 30, "total_del": 0}},
            upsert=True
        )
        await m.answer(f"Канал {m.forward_from_chat.title} успешно привязан!")
    except: await m.answer("Ошибка привязки.")

# --- МЕНЮ УПРАВЛЕНИЯ ---
@dp.callback_query(F.data == "list")
async def list_ch(cb: CallbackQuery):
    cursor = col_channels.find({"owner_id": cb.from_user.id})
    btns = []
    async for r in cursor:
        btns.append([InlineKeyboardButton(text=r['title'], callback_data=f"manage_{r['chat_id']}")])
    btns.append([InlineKeyboardButton(text="Назад", callback_data="to_start")])
    await cb.message.edit_text("Ваши ресурсы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data.startswith("manage_"))
async def manage_ch(cb: CallbackQuery):
    cid = int(cb.data.split("_")[1])
    c = await col_channels.find_one({"chat_id": cid})
    text = f"КАНАЛ: {c['title']}\n\nКД Реклама: {get_format_time(c['ad_cd'])}\nКД Текст: {get_format_time(c['msg_cd'])}\nУдалено всего: {c.get('total_del', 0)}"
    kb = [
        [InlineKeyboardButton(text="Настроить КД Рекламы", callback_data=f"set_ad_{cid}")],
        [InlineKeyboardButton(text="Настроить КД Текста", callback_data=f"set_msg_{cid}")],
        [InlineKeyboardButton(text="Назад", callback_data="list")]
    ]
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("set_"))
async def set_cd(cb: CallbackQuery):
    _, mode, cid = cb.data.split("_")
    # Пресеты времени
    times = [15, 30, 60, 300, 600, 1800, 3600, 18000]
    btns = []
    row = []
    for t in times:
        row.append(InlineKeyboardButton(text=get_format_time(t), callback_data=f"save_{mode}_{cid}_{t}"))
        if len(row) == 4:
            btns.append(row)
            row = []
    btns.append([InlineKeyboardButton(text="Ввести свое время (сек)", callback_data=f"input_{mode}_{cid}")])
    btns.append([InlineKeyboardButton(text="Назад", callback_data=f"manage_{cid}")])
    await cb.message.edit_text("Выберите время из списка или введите вручную:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data.startswith("save_"))
async def save_cd(cb: CallbackQuery):
    _, mode, cid, val = cb.data.split("_")
    field = "ad_cd" if mode == "ad" else "msg_cd"
    await col_channels.update_one({"chat_id": int(cid)}, {"$set": {field: int(val)}})
    await cb.answer("Сохранено")
    await manage_ch(cb)

@dp.callback_query(F.data.startswith("input_"))
async def input_cd(cb: CallbackQuery):
    _, mode, cid = cb.data.split("_")
    state_data[cb.from_user.id] = {"mode": mode, "cid": cid}
    await cb.message.answer("Введите количество секунд (числом):")

@dp.message(F.text)
async def handle_text(m: types.Message):
    uid = m.from_user.id
    if uid in state_data:
        if m.text.isdigit():
            d = state_data[uid]
            field = "ad_cd" if d['mode'] == "ad" else "msg_cd"
            await col_channels.update_one({"chat_id": int(d['cid'])}, {"$set": {field: int(m.text)}})
            del state_data[uid]
            await m.answer("Настройка обновлена!")
        else: await m.answer("Нужно ввести число.")

# --- АДМИНКА ---
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(cb: CallbackQuery):
    if cb.from_user.id not in ADMINS: return
    u_count = await col_users.count_documents({})
    c_count = await col_channels.count_documents({})
    await cb.message.edit_text(f"АДМИН ПАНЕЛЬ\n\nЮзеров: {u_count}\nКаналов: {c_count}", 
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="to_start")]]))

@dp.callback_query(F.data == "to_start")
async def to_start(cb: CallbackQuery): await cmd_start(cb.message)

# --- МОНИТОРИНГ ---
@dp.channel_post()
async def monitor(post: types.Message):
    cid = post.chat.id
    conf = await col_channels.find_one({"chat_id": cid})
    if not conf or not post.author_signature: return
    try:
        admins = await bot.get_chat_administrators(cid)
        for a in admins:
            if a.user.full_name == post.author_signature or a.custom_title == post.author_signature:
                if a.status == 'creator' or a.user.id == conf['owner_id']: return
                is_ad = any([post.photo, post.video, post.forward_date, post.entities])
                limit = conf['ad_cd'] if is_ad else conf['msg_cd']
                key = f"{cid}_{a.user.id}"
                last = await col_logs.find_one({"_id": key}) or {'t': 0}
                if (time.time() - last['t']) < limit:
                    await post.delete()
                    await col_channels.update_one({"chat_id": cid}, {"$inc": {"total_del": 1}})
                else:
                    await col_logs.update_one({"_id": key}, {"$set": {"t": time.time()}}, upsert=True)
    except: pass

async def run():
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(run())
