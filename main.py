import time, asyncio, logging, hashlib
from threading import Thread
from flask import Flask
from motor.motor_asyncio import AsyncIOMotorClient
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

# === КОНФИГУРАЦИЯ ===
ADMINS = [8128433095]
MONGO_URL = "mongodb+srv://miktexstudio:roma1111@cluster0.6damzqi.mongodb.net/"
TOKEN = "8556619747:AAFA1ZOfobW_N7dt2fhrPPBl7jTdHAPWfzc"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
bot = Bot(token=TOKEN)
dp = Dispatcher()

client = AsyncIOMotorClient(MONGO_URL)
db = client.miktex_db
col_channels, col_users, col_logs = db.channels, db.users, db.logs

app = Flask(__name__)
@app.route('/')
def health(): return "SYSTEM_ACTIVE", 200

def run_web():
    app.run(host='0.0.0.0', port=8080)

def get_content_hash(m: types.Message):
    content = m.text or m.caption or ""
    return hashlib.md5(content.encode()).hexdigest()

# === ГЛАВНОЕ МЕНЮ ===
@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    await col_users.update_one({"user_id": m.from_user.id}, {"$set": {"last_seen": time.time()}}, upsert=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Привязать канал", callback_data="add_instr")],
        [InlineKeyboardButton(text="Мои ресурсы", callback_data="list")]
    ])
    await m.answer("УПРАВЛЕНИЕ MIKTEX\nВыберите действие:", reply_markup=kb)

# === УЛУЧШЕННАЯ ПРИВЯЗКА К ВЛАДЕЛЬЦУ ===
@dp.message(F.forward_from_chat)
async def handle_registration(m: types.Message):
    if m.forward_from_chat.type != 'channel': return
    cid = m.forward_from_chat.id
    uid = m.from_user.id
    
    try:
        # Получаем список админов, чтобы найти создателя
        admins = await bot.get_chat_administrators(cid)
        creator = next((a.user.id for a in admins if a.status == 'creator'), None)
        
        if not creator:
            return await m.answer("Не удалось определить владельца канала.")

        # Проверка прав: только ты или сам создатель могут инициировать привязку
        if uid not in ADMINS and uid != creator:
            return await m.answer("Отказ: Только владелец канала может привязывать ресурс.")

        chat = await bot.get_chat(cid)
        # ВСЕГДА привязываем к creator, кто бы ни переслал пост
        await col_channels.update_one(
            {"chat_id": cid},
            {"$set": {
                "title": chat.title, 
                "owner_id": creator # Управление закрепляется за владельцем
            },
             "$setOnInsert": {"ad_cd": 18000, "msg_cd": 30}},
            upsert=True
        )
        
        response = f"Канал '{chat.title}' привязан к владельцу (ID: {creator})."
        if uid in ADMINS and uid != creator:
            response += "\n\nВы (админ бота) помогли с привязкой."
            
        await m.answer(response)
        
    except Exception as e:
        logging.error(f"Reg error: {e}")
        await m.answer("Ошибка: Бот должен быть администратором в канале.")

# === МОНИТОРИНГ ===
@dp.channel_post()
@dp.edited_channel_post()
async def monitor_logic(post: types.Message):
    conf = await col_channels.find_one({"chat_id": post.chat.id})
    if not conf: return

    # Игнор: супер-админов бота и владельца конкретного канала
    if post.author_signature:
        admins = await bot.get_chat_administrators(post.chat.id)
        for a in admins:
            if a.user.full_name == post.author_signature or a.custom_title == post.author_signature:
                if a.user.id in ADMINS or a.user.id == conf['owner_id']:
                    return

    is_ad = any([post.photo, post.video, post.forward_date, post.reply_markup,
                (post.entities and any(e.type in ['url', 'text_link'] for e in post.entities))])
    
    limit = conf['ad_cd'] if is_ad else conf['msg_cd']
    log_id = f"log_{post.chat.id}_{post.author_signature or 'anon'}"
    
    now = time.time()
    last = await col_logs.find_one({"_id": log_id})

    if last:
        if (now - last['t']) < limit or last.get('hash') == get_content_hash(post):
            try: return await post.delete()
            except TelegramBadRequest: pass

    await col_logs.update_one({"_id": log_id}, {"$set": {"t": now, "hash": get_content_hash(post)}}, upsert=True)

# === ОСТАЛЬНЫЕ КОМАНДЫ ===
@dp.callback_query(F.data == "add_instr")
async def add_instr(cb: CallbackQuery):
    await cb.message.edit_text("Перешлите пост из канала для регистрации.", 
    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="to_start")]]))

@dp.callback_query(F.data == "list")
async def list_ch(cb: CallbackQuery):
    # Пользователь видит только те каналы, где он владелец (owner_id)
    cursor = col_channels.find({"owner_id": cb.from_user.id})
    btns = [[InlineKeyboardButton(text=c['title'], callback_data=f"cfg_{c['chat_id']}")] async for c in cursor]
    
    # Если ты супер-админ, добавим кнопку просмотра всех каналов
    if cb.from_user.id in ADMINS:
        btns.append([InlineKeyboardButton(text="🔎 ВСЕ КАНАЛЫ (Админ)", callback_data="admin_all")])
        
    btns.append([InlineKeyboardButton(text="Назад", callback_data="to_start")])
    await cb.message.edit_text("Доступные ресурсы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data == "admin_all")
async def admin_all(cb: CallbackQuery):
    if cb.from_user.id not in ADMINS: return
    cursor = col_channels.find()
    btns = [[InlineKeyboardButton(text=f"⚙️ {c['title']}", callback_data=f"cfg_{c['chat_id']}")] async for c in cursor]
    btns.append([InlineKeyboardButton(text="Назад", callback_data="list")])
    await cb.message.edit_text("Все каналы системы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data.startswith("cfg_"))
async def cfg_ch(cb: CallbackQuery):
    cid = int(cb.data.split("_")[1]); c = await col_channels.find_one({"chat_id": cid})
    kb = [[InlineKeyboardButton(text="КД Реклама", callback_data=f"set_ad_{cid}"),
           InlineKeyboardButton(text="КД Текст", callback_data=f"set_msg_{cid}")],
          [InlineKeyboardButton(text="Назад", callback_data="list")]]
    await cb.message.edit_text(f"Настройки: {c['title']}\nВладелец ID: {c['owner_id']}\nРеклама: {c['ad_cd']}с\nТекст: {c['msg_cd']}с", 
    reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("set_"))
async def set_val(cb: CallbackQuery):
    _, m, cid = cb.data.split("_")
    vals = [3600, 18000, 43200, 86400] if m == "ad" else [10, 30, 60, 300]
    btns = [[InlineKeyboardButton(text=f"{v}с", callback_data=f"sv_{m}_{cid}_{v}") for v in vals]]
    btns.append([InlineKeyboardButton(text="Назад", callback_data=f"cfg_{cid}")])
    await cb.message.edit_text("Выберите время:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data.startswith("sv_"))
async def sv_val(cb: CallbackQuery):
    _, m, cid, v = cb.data.split("_")
    await col_channels.update_one({"chat_id": int(cid)}, {"$set": {"ad_cd" if m=="ad" else "msg_cd": int(v)}})
    await cb.answer("Сохранено"); await cfg_ch(cb)

@dp.callback_query(F.data == "to_start")
async def to_start(cb: CallbackQuery): await cmd_start(cb.message)

async def main():
    Thread(target=run_web, daemon=True).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
