import os
import json
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes,
    filters, ConversationHandler, CallbackQueryHandler
)

# Загрузка .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Константы состояний анкеты
QUESTION1, QUESTION2, QUESTION3 = range(3)

# Файлы
USER_DATA_FILE = "submitted_users.json"
ACCEPTED_USERS_FILE = "accepted_users.json"
LOG_FILE = "bot.log"


def load_json_file(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
            return {int(k): datetime.fromisoformat(v) for k, v in raw.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_json_file(data: dict, file_path):
    serializable = {str(k): v.isoformat() for k, v in data.items()}
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)


def clean_old_submissions(data: dict, hours=None):
    if hours is None:
        return data
    now = datetime.now()
    return {
        uid: ts for uid, ts in data.items()
        if now - ts < timedelta(hours=hours)
    }

# Логирование в консоль и файл
logger = logging.getLogger()
logger.setLevel(logging.INFO)
if logger.hasHandlers():
    logger.handlers.clear()

log_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("✅ Начать", callback_data="start_survey")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_survey")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        'Привет, это анкета для скаутов в агентство "хз".\n\nНажми "Начать", чтобы приступить:',
        reply_markup=reply_markup
    )
    logger.info(f"Пользователь {update.effective_user.id} использовал /start")
    return ConversationHandler.END


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user = query.from_user
    await query.answer()
    logger.info(f"Пользователь {user.id} нажал кнопку: {query.data}")

    await query.edit_message_reply_markup(reply_markup=None)

    if query.data == "start_survey":
        user_id = user.id
        now = datetime.now()

        submitted_users = context.application.bot_data.get("submitted_users", {})
        last_time = submitted_users.get(user_id)

        if last_time and (now - last_time) < timedelta(hours=12):
            await query.message.reply_text("Вы уже проходили анкету. Повторная попытка будет доступна через 12 часов.")
            logger.info(f"Пользователь {user_id} попытался пройти анкету повторно слишком рано")
            return ConversationHandler.END

        context.user_data.clear()
        await query.message.reply_text("Твой возраст?")
        logger.info(f"{user_id} начал заполнять анкету")
        return QUESTION1

    elif query.data == "cancel_survey":
        await query.message.reply_text("Анкета отменена.")
        logger.info(f"Пользователь {user.id} отменил анкету")
        return ConversationHandler.END


async def question1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text
    context.user_data['Возраст'] = text
    await update.message.reply_text("Сколько готов уделять времени в день?")
    logger.info(f"{user_id} ответил на ВОЗРАСТ: {text}")
    return QUESTION2


async def question2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text
    context.user_data['Время в день'] = text
    await update.message.reply_text("Есть ли опыт в этой сфере?")
    logger.info(f"{user_id} ответил на ВРЕМЯ В ДЕНЬ: {text}")
    return QUESTION3


async def question3(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    text = update.message.text
    context.user_data['Опыт'] = text

    submitted_users = context.application.bot_data.get("submitted_users", {})
    submitted_users[user.id] = datetime.now()
    context.application.bot_data["submitted_users"] = submitted_users
    save_json_file(submitted_users, USER_DATA_FILE)

    await update.message.reply_text("Спасибо, ожидай, с тобой свяжутся")
    logger.info(f"{user.id} завершил анкету. Опыт: {text}")

    answers = context.user_data
    result_text = (
        f"\U0001F4E9 Новая анкета от @{user.username or 'неизвестно'} (ID: {user.id}):\n\n" +
        "\n".join(f"{k}: {v}" for k, v in answers.items())
    )

    keyboard = [[
        InlineKeyboardButton("✅ Принять анкету", callback_data=f"accept_{user.id}"),
        InlineKeyboardButton("❌ Отклонить анкету", callback_data=f"decline_{user.id}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=ADMIN_ID, text=result_text, reply_markup=reply_markup)
    logger.info(f"Анкета пользователя {user.id} отправлена админу")
    return ConversationHandler.END


async def admin_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    logger.info(f"Админ нажал кнопку: {data}")

    if data.startswith("accept_"):
        user_id = int(data.split("_")[1])
        accepted_users = context.application.bot_data.get("accepted_users", {})
        accepted_users[user_id] = datetime.now()
        context.application.bot_data["accepted_users"] = accepted_users
        save_json_file(accepted_users, ACCEPTED_USERS_FILE)

        try:
            await context.bot.send_message(chat_id=user_id, text="Ваша анкета принята, связь в тг @ollkyy")
        except Exception as e:
            logger.warning(f"Ошибка при отправке пользователю {user_id}: {e}")

        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text(query.message.text + "\n\n✅ Анкета принята")
        logger.info(f"Анкета пользователя {user_id} принята")

    elif data.startswith("decline_"):
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text(query.message.text + "\n\n❌ Анкета отклонена")
        logger.info(f"Анкета пользователя отклонена")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Анкета отменена.")
    logger.info(f"Пользователь {update.effective_user.id} отменил анкету командой /cancel")
    return ConversationHandler.END


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Команда доступна только администратору.")
        return

    accepted_users = context.application.bot_data.get("accepted_users", {})
    if not accepted_users:
        await update.message.reply_text("Нет принятых анкет.")
        return

    message = "✅ Принятые анкеты:\n"
    for uid, ts in accepted_users.items():
        try:
            user = await context.bot.get_chat(uid)
            username = f"@{user.username}" if user.username else "(без username)"
        except Exception:
            username = "(недоступен)"
        message += f"- {username} | ID {uid} (принята {ts.strftime('%Y-%m-%d %H:%M')})\n"

    await update.message.reply_text(message)
    logger.info("Команда /status выполнена")


async def log_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message:
        logger.info(f"[MSG] {user.id} (@{user.username}): {update.message.text}")
    elif update.callback_query:
        logger.info(f"[CALLBACK] {user.id} (@{user.username}): {update.callback_query.data}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Произошла ошибка: {context.error}", exc_info=True)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    submitted_users = clean_old_submissions(load_json_file(USER_DATA_FILE), hours=None)
    accepted_users = load_json_file(ACCEPTED_USERS_FILE)

    app.bot_data["submitted_users"] = submitted_users
    app.bot_data["accepted_users"] = accepted_users

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(button_handler, pattern=r"^(start_survey|cancel_survey)$")
        ],
        states={
            QUESTION1: [MessageHandler(filters.TEXT & ~filters.COMMAND, question1)],
            QUESTION2: [MessageHandler(filters.TEXT & ~filters.COMMAND, question2)],
            QUESTION3: [MessageHandler(filters.TEXT & ~filters.COMMAND, question3)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(admin_button_handler, pattern=r"^(accept|decline)_"))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.ALL, log_all_messages), group=1)
    app.add_error_handler(error_handler)

    logger.info("Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
