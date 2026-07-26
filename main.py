# main.py
import asyncio
import json
import os
import logging
from datetime import datetime
from flask import Flask, request
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram import F
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import threading

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN", "8510661599:AAHS65zDE4p-8A2CX1N9t-7h0p8Ix4MgW3Y")
BLOGGER_ID = int(os.getenv("BLOGGER_ID", "8695107966"))
ADMIN_CHANNEL_ID = os.getenv("ADMIN_CHANNEL_ID", "-1004321519689")
PAYMENT_LINK = os.getenv("PAYMENT_LINK", "https://crm2.webpay.by/pub/mail/click.php?tag=crm.eyJ1cm4iOiI2NDk4MzAtQ1hIQTNJIn0%3D&url=https%3A%2F%2Fisnastc.w-p.by%2F&sign=3f77f7ddcfa8d700501d5d92b164e2efeb404a99d5121ea3f1675e067b6f7e67")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "qwzzsx")
BLOGGER_USERNAME = os.getenv("BLOGGER_USERNAME", "shooting_consultant")
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL", "https://consultations-5ct.onrender.com") + "/webhook"
PORT = int(os.getenv("PORT", 10000))

# ================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Используем Supabase вместо JSON файлов
# Бесплатно: https://supabase.com
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Если нет Supabase, используем словарь в памяти (не сохраняется при перезапуске)
db = {}
panel_message_id = None

# ========== РАБОТА С БАЗОЙ ==========
def load_db():
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            from supabase import create_client
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            response = supabase.table("clients").select("*").execute()
            data = {}
            for row in response.data:
                data[str(row["user_id"])] = {
                    "username": row["username"],
                    "payment_date": row.get("payment_date"),
                    "confirm_date": row.get("confirm_date"),
                    "active": row.get("active", False),
                    "request_message_id": row.get("request_message_id"),
                    "tariff_type": row.get("tariff_type", "with_feedback")
                }
            return data
        except Exception as e:
            logger.error(f"Ошибка загрузки из Supabase: {e}")
            return {}
    return db

def save_db(data):
    global db
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            from supabase import create_client
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            for user_id_str, client_data in data.items():
                supabase.table("clients").upsert({
                    "user_id": int(user_id_str),
                    "username": client_data.get("username", ""),
                    "payment_date": client_data.get("payment_date"),
                    "confirm_date": client_data.get("confirm_date"),
                    "active": client_data.get("active", False),
                    "request_message_id": client_data.get("request_message_id"),
                    "tariff_type": client_data.get("tariff_type", "with_feedback")
                }).execute()
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения в Supabase: {e}")
            return False
    db = data
    return True

def load_panel_id():
    global panel_message_id
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            from supabase import create_client
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            response = supabase.table("settings").select("value").eq("key", "panel_message_id").execute()
            if response.data:
                return response.data[0]["value"]
        except Exception as e:
            logger.error(f"Ошибка загрузки panel_id: {e}")
            return None
    return panel_message_id

def save_panel_id(message_id):
    global panel_message_id
    panel_message_id = message_id
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            from supabase import create_client
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            supabase.table("settings").upsert({
                "key": "panel_message_id",
                "value": message_id
            }).execute()
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения panel_id: {e}")
            return False
    return True

def add_client(user_id: int, username: str, tariff_type: str = "with_feedback"):
    data = load_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    user_id_str = str(user_id)
    
    if user_id_str not in data:
        data[user_id_str] = {
            "username": username,
            "payment_date": now,
            "confirm_date": None,
            "active": False,
            "request_message_id": None,
            "tariff_type": tariff_type
        }
    else:
        data[user_id_str]["tariff_type"] = tariff_type
        data[user_id_str]["username"] = username
    
    return save_db(data)

def confirm_client(user_id: int):
    data = load_db()
    user_id_str = str(user_id)
    
    if user_id_str in data:
        now = datetime.now()
        data[user_id_str]["active"] = True
        data[user_id_str]["confirm_date"] = now.strftime("%Y-%m-%d %H:%M")
        save_db(data)
        return data[user_id_str]
    return None

def reject_client(user_id: int):
    data = load_db()
    user_id_str = str(user_id)
    if user_id_str in data:
        data[user_id_str]["active"] = False
        save_db(data)
        return True
    return False

def reset_client(user_id: int):
    data = load_db()
    user_id_str = str(user_id)
    if user_id_str in data:
        data[user_id_str] = {
            "username": data[user_id_str].get("username", f"User_{user_id}"),
            "payment_date": None,
            "confirm_date": None,
            "active": False,
            "request_message_id": None,
            "tariff_type": "with_feedback"
        }
        return save_db(data)
    return False

# ========== КНОПКИ ==========
def main_keyboard():
    kb = [
        [InlineKeyboardButton(text="❓ Есть вопросы", callback_data="faq_show")],
        [InlineKeyboardButton(text="💰 Оплатить", callback_data="pay")],
        [InlineKeyboardButton(text="🆘 Служба поддержки", url=f"tg://resolve?domain={SUPPORT_USERNAME}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def waiting_keyboard():
    kb = [[InlineKeyboardButton(text="🆘 Служба поддержки", url=f"tg://resolve?domain={SUPPORT_USERNAME}")]]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_consultation_keyboard():
    kb = [
        [InlineKeyboardButton(text="📩 Получить консультацию", url=f"tg://resolve?domain={BLOGGER_USERNAME}")],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def back_to_menu_keyboard():
    kb = [[InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_main")]]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_tariff_keyboard():
    kb = [
        [InlineKeyboardButton(text="📝 Консультация без обратной связи", callback_data="tariff_without_feedback")],
        [InlineKeyboardButton(text="📝 Консультация с обратной связью", callback_data="tariff_with_feedback")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_admin_panel_keyboard():
    kb = [
        [InlineKeyboardButton(text="🔄 Сбросить клиента", callback_data="admin_reset_list")],
        [InlineKeyboardButton(text="🔄 Обновить панель", callback_data="admin_refresh_panel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_reset_list_keyboard(clients: list, page: int = 0, per_page: int = 5):
    kb = []
    start = page * per_page
    end = start + per_page
    page_clients = clients[start:end]
    total_pages = (len(clients) + per_page - 1) // per_page
    
    for user_id, data in page_clients:
        username = data.get("username", f"User_{user_id}")
        status = "✅" if data.get("active") else "⏳"
        tariff = "без ОС" if data.get("tariff_type") == "without_feedback" else "с ОС"
        kb.append([InlineKeyboardButton(
            text=f"{status} @{username} ({tariff}) ID:{user_id}",
            callback_data=f"admin_reset_confirm_{user_id}"
        )])
    
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"admin_reset_page_{page-1}"))
        nav_buttons.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="admin_noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"admin_reset_page_{page+1}"))
        if nav_buttons:
            kb.append(nav_buttons)
    
    kb.append([InlineKeyboardButton(text="🏠 Главная панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_confirm_reset_keyboard(user_id: int):
    kb = [
        [InlineKeyboardButton(text="✅ Да, сбросить", callback_data=f"admin_reset_execute_{user_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_reset_list")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ========== FAQ ==========
FAQ_QUESTIONS = {
    "faq_how": {"text": "Как проходит консультация?", "callback": "faq_how"},
    "faq_who": {"text": "Кому подходит?", "callback": "faq_who"},
    "faq_format": {"text": "Формат и цена", "callback": "faq_format"},
    "faq_where": {"text": "Другой вопрос", "callback": "faq_where"},
}

FAQ_ANSWERS = {
    "faq_how": "**Как проходит консультация?**\n\nКонсультация проводится в удобном формате:\n\n• Онлайн: видеозвонок на платформе Telegram.\n• Офлайн: в моей студии по адресу: г. Минск, пр. Независимости, 58/6.\n\nВыберите удобный для вас вариант!",
    "faq_who": "**Кому подходит** 🌟\n\n1. Для всех кто ведет или хочет вести блог:\n\n2. Для своих семейных или личных съемок для личного архива, с сильным эмоциональным посылом.\n\n3. Для контент-креаторов\n\n💡 Я помогу вам разобраться в тонкостях съемки и создавать сильные видеопроекты со смыслом!",
    "faq_format": "**Формат и цена**\n\nЧто мы сделаем за 2 часа интенсивной работы?\n✅ Разберем мой метод съемки (чтобы ты поняла механику процесса).\n✅ Выявим твои «слепые зоны»: чего именно тебе не хватает для крутого результата.\n✅ Я дам тебе только те инструменты, которыми пользуюсь сама и которые нужны именно тебе.\n✅ при желании поддержу после встречи: В течение 30 дней я останусь с тобой. Ты будешь присылать мне свои ролики, а я разбирать их: показывать сильные стороны и честно говорить, что можно улучшить.\n\n**Цена консультаций:**\n\n1️⃣ **Консультация без обратной связи**\n  – Продолжительность: 2 часа\n  – Стоимость: 🇧🇾 165 BYN / 🇷🇺 4 500 RUB / 🇪🇺 50 EUR\n\n2️⃣ **Консультация с обратной связью**\n  – Продолжительность: 2 часа + 1 месяц обратной связи\n  – Описание: После консультации вы присылаете свои ролики, и я предоставляю обратную связь по каждому из них: что получилось хорошо, что можно улучшить и рекомендации для дальнейшего развития.\n  – Стоимость: 🇧🇾 350 BYN / 🇷🇺 9 500 RUB / 🇪🇺 106 EUR",
    "faq_where": "**Другой вопрос**\n\nЕсли вы не нашли ответ на ваш вопрос - напишите его сюда:\n\n👤 @qwzzsx",
}

def get_faq_keyboard(answered_questions: set):
    kb = []
    for key, q in FAQ_QUESTIONS.items():
        if key not in answered_questions:
            answered_str = ",".join(sorted(answered_questions))
            callback_data = f"faq_answer_{key}|{answered_str}" if answered_str else f"faq_answer_{key}"
            kb.append([InlineKeyboardButton(text=q['text'], callback_data=callback_data)])
    kb.append([InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ========== ОБНОВЛЕНИЕ ПАНЕЛИ ==========
async def update_admin_panel():
    try:
        text = (
            "📊 **ПАНЕЛЬ УПРАВЛЕНИЯ**\n"
            f"Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        panel_id = load_panel_id()
        
        if panel_id:
            try:
                await bot.edit_message_text(
                    text,
                    chat_id=ADMIN_CHANNEL_ID,
                    message_id=panel_id,
                    parse_mode="Markdown",
                    reply_markup=get_admin_panel_keyboard()
                )
                return
            except:
                panel_id = None
        
        msg = await bot.send_message(
            ADMIN_CHANNEL_ID,
            text,
            parse_mode="Markdown",
            reply_markup=get_admin_panel_keyboard()
        )
        save_panel_id(msg.message_id)
    except Exception as e:
        logger.error(f"Ошибка в update_admin_panel: {e}")

# ========== ВСЕ ХЭНДЛЕРЫ ==========
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "👋 Привет! Я Таня. Если ты здесь, значит, тебе откликается мой визуальный язык и я тебе тут рада! Но у меня есть одна важная мысль: я не хочу учить тебя снимать «как я». Я хочу помочь тебе найти ТВОЙ стиль и дать инструменты, которые нужны именно тебе.\n\n"
        "Я приглашаю тебя на личную консультацию, в которой за 2 часа интенсивной работы?\n"
        "✅ Разберем мой метод съемки (чтобы ты поняла механику процесса).\n"
        "✅ Выявим твои «слепые зоны»: чего именно тебе не хватает для крутого результата.\n"
        "✅ Я дам тебе только те инструменты, которыми пользуюсь сама и которые нужны именно тебе.\n"
        "✅ при желании поддержу после встречи: В течение 30 дней я останусь с тобой. Ты будешь присылать мне свои ролики, а я разбирать их: показывать сильные стороны и честно говорить, что можно улучшить.\n\n"
        "Ведь результат дает не теория, а практика 🚀",
        reply_markup=main_keyboard()
    )

@dp.callback_query(F.data == "faq_show")
async def faq_show(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📚 **Выбери интересующий вопрос:**\n\nНажми на вопрос, чтобы узнать ответ.",
        parse_mode="Markdown",
        reply_markup=get_faq_keyboard(set())
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("faq_answer_"))
async def faq_answer(callback: types.CallbackQuery):
    try:
        parts = callback.data.replace("faq_answer_", "").split("|")
        question_key = parts[0]
        answered = set()
        if len(parts) > 1 and parts[1]:
            answered = set(parts[1].split(","))
        answered.add(question_key)
        answer_text = FAQ_ANSWERS.get(question_key, "Ответ не найден")
        if len(answered) == len(FAQ_QUESTIONS):
            await callback.message.edit_text(
                f"{answer_text}\n\n📌 **Другие вопросы:**",
                parse_mode="Markdown",
                reply_markup=back_to_menu_keyboard()
            )
        else:
            await callback.message.edit_text(
                f"{answer_text}\n\n📌 **Другие вопросы:**",
                parse_mode="Markdown",
                reply_markup=get_faq_keyboard(answered)
            )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в faq_answer: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "👋 Привет! Я Таня. Если ты здесь, значит, тебе откликается мой визуальный язык и я тебе тут рада! Но у меня есть одна важная мысль: я не хочу учить тебя снимать «как я». Я хочу помочь тебе найти ТВОЙ стиль и дать инструменты, которые нужны именно тебе.\n\n"
        "Я приглашаю тебя на личную консультацию, в которой за 2 часа интенсивной работы?\n"
        "✅ Разберем мой метод съемки (чтобы ты поняла механику процесса).\n"
        "✅ Выявим твои «слепые зоны»: чего именно тебе не хватает для крутого результата.\n"
        "✅ Я дам тебе только те инструменты, которыми пользуюсь сама и которые нужны именно тебе.\n"
        "✅ при желании поддержу после встречи: В течение 30 дней я останусь с тобой. Ты будешь присылать мне свои ролики, а я разбирать их: показывать сильные стороны и честно говорить, что можно улучшить.\n\n"
        "Ведь результат дает не теория, а практика 🚀",
        reply_markup=main_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "pay")
async def pay_start(callback: types.CallbackQuery):
    data = load_db()
    user_id_str = str(callback.from_user.id)
    if user_id_str in data and data[user_id_str].get("active", False):
        await callback.message.edit_text(
            "⚠️ Вы уже оплатили консультацию.\nЕсли у вас есть вопросы, воспользуйтесь FAQ или свяжитесь со мной.",
            parse_mode="Markdown",
            reply_markup=get_consultation_keyboard()
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        "📋 **Выберите формат консультации:**\n\n"
        "1️⃣ **Консультация без обратной связи**\n  – Продолжительность: 2 часа\n  – Стоимость: 🇧🇾 165 BYN / 🇷🇺 4 500 RUB / 🇪🇺 50 EUR\n\n"
        "2️⃣ **Консультация с обратной связью**\n  – Продолжительность: 2 часа + 1 месяц обратной связи\n  – Стоимость: 🇧🇾 350 BYN / 🇷🇺 9 500 RUB / 🇪🇺 106 EUR",
        parse_mode="Markdown",
        reply_markup=get_tariff_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("tariff_"))
async def tariff_selected(callback: types.CallbackQuery):
    try:
        tariff_type = callback.data.replace("tariff_", "")
        user_id = callback.from_user.id
        username = callback.from_user.username or callback.from_user.full_name
        add_client(user_id, username, tariff_type)
        tariff_names = {"without_feedback": "без обратной связи", "with_feedback": "с обратной связью"}
        tariff_name = tariff_names.get(tariff_type, "с обратной связью")
        await callback.message.edit_text(
            f"💳 **Вы выбрали: Консультация {tariff_name}**\n\n"
            "📸 Для подтверждения оплаты пришли, пожалуйста, **скриншот чека** после перевода.\n\n"
            f"💳 [Перейти к оплате]({PAYMENT_LINK})\n\n"
            "⚠ Отправь именно фото чека одним сообщением.",
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в tariff_selected: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)

@dp.message(F.photo)
async def handle_check(message: types.Message):
    try:
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.full_name
        user_id_str = str(user_id)
        data = load_db()
        
        if user_id_str in data and data[user_id_str].get("active", False):
            await message.answer("⚠️ Вы уже оплатили консультацию.", reply_markup=get_consultation_keyboard())
            return
        
        if user_id_str not in data:
            add_client(user_id, username, "with_feedback")
            data = load_db()
        
        tariff_type = data.get(user_id_str, {}).get("tariff_type", "with_feedback")
        tariff_name = "без обратной связи" if tariff_type == "without_feedback" else "с обратной связью"
        
        caption = (
            f"📩 **НОВАЯ ЗАЯВКА!**\n\n"
            f"👤 Клиент: @{username}\n"
            f"🆔 ID: `{user_id}`\n"
            f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
            f"📌 Тариф: {tariff_name}\n\n"
            f"Проверьте поступление оплаты и подтвердите заявку."
        )
        
        sent_message = await bot.send_photo(
            ADMIN_CHANNEL_ID,
            photo=message.photo[-1].file_id,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"admin_confirm_{user_id}")],
                [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin_reject_{user_id}")]
            ])
        )
        
        data = load_db()
        if user_id_str in data:
            data[user_id_str]["request_message_id"] = sent_message.message_id
            save_db(data)
        
        await update_admin_panel()
        await message.answer(
            "✅ Спасибо! Я получила чек. Как только оплата подтвердится, я свяжусь с тобой для согласования консультации.\n\nОбычно это занимает до 30 минут в рабочее время.",
            reply_markup=waiting_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка в handle_check: {e}")
        await message.answer("⚠️ Произошла ошибка. Попробуйте еще раз.")

@dp.callback_query(F.data.startswith("admin_confirm_"))
async def admin_confirm(callback: types.CallbackQuery):
    if callback.from_user.id != BLOGGER_ID:
        await callback.answer("❌ Только блогер может подтверждать оплату.", show_alert=True)
        return
    try:
        user_id = int(callback.data.split("_")[2])
        client = confirm_client(user_id)
        if client:
            await bot.send_message(
                user_id,
                "✅ Оплата подтверждена! Я свяжусь с тобой в ближайшее время для согласования консультации.",
                parse_mode="Markdown",
                reply_markup=get_consultation_keyboard()
            )
            await callback.message.edit_caption(
                caption=f"{callback.message.caption}\n\n✅ **ПОДТВЕРЖДЕНО!**",
                parse_mode="Markdown"
            )
            await callback.message.edit_reply_markup(reply_markup=None)
            await update_admin_panel()
            await callback.answer("✅ Оплата подтверждена!")
        else:
            await callback.answer("❌ Клиент не найден", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка в admin_confirm: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("admin_reject_"))
async def admin_reject(callback: types.CallbackQuery):
    if callback.from_user.id != BLOGGER_ID:
        await callback.answer("❌ Только блогер может отклонять оплату.", show_alert=True)
        return
    try:
        user_id = int(callback.data.split("_")[2])
        reject_client(user_id)
        await bot.send_message(
            user_id,
            "❌ К сожалению, оплата не подтверждена. Проверь правильность перевода и попробуй снова.\n\nЕсли у тебя возникли вопросы, свяжись со мной напрямую.",
            reply_markup=back_to_menu_keyboard()
        )
        await callback.message.edit_caption(
            caption=f"{callback.message.caption}\n\n❌ **ОТКЛОНЕНО!**",
            parse_mode="Markdown"
        )
        await callback.message.edit_reply_markup(reply_markup=None)
        await update_admin_panel()
        await callback.answer("❌ Оплата отклонена")
    except Exception as e:
        logger.error(f"Ошибка в admin_reject: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)

@dp.callback_query(F.data == "admin_reset_list")
async def admin_reset_list(callback: types.CallbackQuery):
    if callback.from_user.id != BLOGGER_ID:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return
    data = load_db()
    if not data:
        await callback.message.edit_text(
            "📭 **Нет клиентов для сброса**",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Главная панель", callback_data="admin_panel")]
            ])
        )
        await callback.answer()
        return
    clients = [(uid, d) for uid, d in data.items()]
    clients.sort(key=lambda x: (0 if x[1].get("active") else 1, x[1].get("payment_date", "")))
    if not hasattr(admin_reset_list, "cache"):
        admin_reset_list.cache = {}
    admin_reset_list.cache["reset_clients"] = clients
    await callback.message.edit_text(
        "🔄 **Выберите клиента для сброса:**\n\nПосле сброса клиент сможет отправить новый чек.",
        parse_mode="Markdown",
        reply_markup=get_reset_list_keyboard(clients, 0)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_reset_page_"))
async def admin_reset_page(callback: types.CallbackQuery):
    if callback.from_user.id != BLOGGER_ID:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return
    page = int(callback.data.split("_")[3])
    if not hasattr(admin_reset_list, "cache") or "reset_clients" not in admin_reset_list.cache:
        await callback.answer("Ошибка, попробуйте снова", show_alert=True)
        return
    clients = admin_reset_list.cache["reset_clients"]
    await callback.message.edit_text(
        "🔄 **Выберите клиента для сброса:**\n\nПосле сброса клиент сможет отправить новый чек.",
        parse_mode="Markdown",
        reply_markup=get_reset_list_keyboard(clients, page)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_reset_confirm_"))
async def admin_reset_confirm(callback: types.CallbackQuery):
    if callback.from_user.id != BLOGGER_ID:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return
    user_id = int(callback.data.split("_")[3])
    data = load_db()
    user_id_str = str(user_id)
    if user_id_str not in data:
        await callback.answer("❌ Клиент не найден", show_alert=True)
        return
    username = data[user_id_str].get("username", f"User_{user_id}")
    await callback.message.edit_text(
        f"⚠️ **Вы уверены, что хотите сбросить клиента?**\n\n👤 @{username} (ID: {user_id})\n\nПосле сброса клиент сможет отправить новый чек.",
        parse_mode="Markdown",
        reply_markup=get_confirm_reset_keyboard(user_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_reset_execute_"))
async def admin_reset_execute(callback: types.CallbackQuery):
    if callback.from_user.id != BLOGGER_ID:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return
    try:
        user_id = int(callback.data.split("_")[3])
        user_id_str = str(user_id)
        data = load_db()
        if user_id_str not in data:
            await callback.answer("❌ Клиент не найден", show_alert=True)
            return
        username = data[user_id_str].get("username", f"User_{user_id}")
        reset_client(user_id)
        await bot.send_message(
            user_id,
            "🔄 Твой профиль был сброшен.\nТы можешь отправить новый чек для оплаты.\n\nЕсли у тебя есть вопросы, свяжись со мной.",
            reply_markup=main_keyboard()
        )
        request_msg_id = data.get(user_id_str, {}).get("request_message_id")
        if request_msg_id:
            try:
                await bot.edit_message_caption(
                    chat_id=ADMIN_CHANNEL_ID,
                    message_id=request_msg_id,
                    caption=f"🔄 **СБРОШЕНО!**\nКлиент @{username} (ID: {user_id}) сброшен.\nМожет отправить новый чек."
                )
            except:
                pass
        await callback.message.edit_text(
            f"✅ **Клиент сброшен!**\n\n👤 @{username} (ID: {user_id})\nТеперь клиент может отправить новый чек.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Сбросить другого", callback_data="admin_reset_list")],
                [InlineKeyboardButton(text="🏠 Главная панель", callback_data="admin_panel")]
            ])
        )
        await update_admin_panel()
        await callback.answer("✅ Клиент сброшен")
    except Exception as e:
        logger.error(f"Ошибка в admin_reset_execute: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)

@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id != BLOGGER_ID:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return
    await update_admin_panel()
    await callback.answer("🔄 Панель обновлена")

@dp.callback_query(F.data == "admin_refresh_panel")
async def admin_refresh_panel(callback: types.CallbackQuery):
    if callback.from_user.id != BLOGGER_ID:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return
    await update_admin_panel()
    await callback.answer("🔄 Панель обновлена")

@dp.callback_query(F.data == "admin_noop")
async def admin_noop(callback: types.CallbackQuery):
    await callback.answer()

@dp.message(Command("panel"))
async def panel_command(message: types.Message):
    if message.from_user.id != BLOGGER_ID:
        await message.answer("❌ Доступ запрещен.")
        return
    await update_admin_panel()
    await message.answer("✅ Панель управления обновлена в канале!")

@dp.message(Command("reset"))
async def reset_command(message: types.Message):
    if message.from_user.id != BLOGGER_ID:
        await message.answer("❌ Доступ запрещен.")
        return
    data = load_db()
    if not data:
        await message.answer("📭 Нет клиентов для сброса.")
        return
    text = "🔄 **Выберите клиента для сброса:**\n\n"
    clients = [(uid, d) for uid, d in data.items()]
    clients.sort(key=lambda x: (0 if x[1].get("active") else 1, x[1].get("payment_date", "")))
    kb = []
    for user_id, d in clients:
        username = d.get("username", f"User_{user_id}")
        status = "✅" if d.get("active") else "⏳"
        tariff = "без ОС" if d.get("tariff_type") == "without_feedback" else "с ОС"
        kb.append([InlineKeyboardButton(
            text=f"{status} @{username} ({tariff}) ID:{user_id}",
            callback_data=f"admin_reset_confirm_{user_id}"
        )])
    kb.append([InlineKeyboardButton(text="🏠 Главная панель", callback_data="admin_panel")])
    await message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# ========== WEBHOOK SETUP ==========
async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)
    await update_admin_panel()
    logger.info(f"Webhook установлен: {WEBHOOK_URL}")

# ========== FLASK APP ==========
app = Flask(__name__)

@app.route('/')
def health():
    return "OK", 200

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    # Запускаем бота в отдельном потоке через aiohttp
    from aiohttp import web
    import asyncio
    
    async def start_bot():
        await on_startup()
        # Создаем aiohttp приложение
        app_web = web.Application()
        # Настраиваем вебхук
        webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
        webhook_requests_handler.register(app_web, path="/webhook")
        setup_application(app_web, dp, bot=bot)
        # Запускаем сервер
        runner = web.AppRunner(app_web)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
        await site.start()
        logger.info(f"Сервер запущен на порту {PORT}")
        # Держим процесс живым
        await asyncio.Event().wait()
    
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
