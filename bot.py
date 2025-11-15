import os
import logging
from typing import Dict, List

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ChatAction

from openai import OpenAI

# ----- Логирование -----
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ----- Переменные окружения -----
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN в переменных окружения")
if not OPENAI_API_KEY:
    raise RuntimeError("Не задан OPENAI_API_KEY в переменных окружения")

client = OpenAI(api_key=OPENAI_API_KEY)

# Простая память в оперативке: user_id -> список сообщений
user_histories: Dict[int, List[Dict[str, str]]] = {}


def get_history(user_id: int) -> List[Dict[str, str]]:
    """
    Получаем или создаём историю диалога для пользователя.
    Добавляем системное сообщение с описанием роли.
    """
    if user_id not in user_histories:
        user_histories[user_id] = [
            {
                "role": "system",
                "content": (
                    "Ты эмпатичный, тактичный психолог-консультант.\n"
                    "- Отвечай по-русски.\n"
                    "- Твоя цель — поддержать, помочь человеку разобраться в чувствах и ситуации.\n"
                    "- Задавай уточняющие вопросы, помогай видеть разные варианты, предлагай мягкие шаги.\n"
                    "- Не ставь психиатрических диагнозов и не обсуждай лекарства.\n"
                    "- Если человек винит себя, помоги снизить самокритику и увидеть контекст.\n"
                    "- Отвечай обычно 3–6 предложениями, без огромных полотен.\n"
                    "- Будь тёплым, но уважительным, без сюсюканья.\n"
                ),
            }
        ]
    return user_histories[user_id]


def reset_history(user_id: int):
    """Полный сброс истории диалога для пользователя."""
    if user_id in user_histories:
        del user_histories[user_id]


def is_crisis_message(text: str) -> bool:
    """
    Простейшая проверка на тяжёлый кризис:
    суицидальные мысли и т.п.
    """
    if not text:
        return False

    t = text.lower()

    crisis_keywords = [
        "убить себя",
        "суицид",
        "покончить с собой",
        "не хочу жить",
        "хочу умереть",
        "резать вены",
        "самоубий",
        "себя убью",
        "нет смысла жить",
        "бессмысленно жить",
    ]

    return any(kw in t for kw in crisis_keywords)


async def crisis_reply(update: Update):
    """
    Специальный ответ в тяжёлом кризисе.
    Без OpenAI — только безопасный текст.
    """
    text = (
        "Я слышу, что тебе сейчас очень тяжело, и мысли, о которых ты пишешь, "
        "говорят о сильной боли 💔\n\n"
        "Я как бот не могу полноценно помочь в такой ситуации, но очень важно, "
        "чтобы рядом оказался живой человек, который сможет это сделать.\n\n"
        "Пожалуйста, обратись за помощью:\n"
        "• к близкому человеку, которому ты более-менее доверяешь;\n"
        "• к психологу или психотерапевту (очно или онлайн);\n"
        "• в местную службу экстренной помощи или на номер экстренных служб (например, 112).\n\n"
        "Ты правда заслуживаешь поддержки. Твои чувства — не слабость и не блаш. "
        "Если можешь, напиши сейчас кому-то из живых людей или позвони в экстренную службу."
    )
    if update.message:
        await update.message.reply_text(text)


async def call_openai_chat(user_id: int, user_message: str) -> str:
    """
    Обращение к OpenAI с учётом истории пользователя.
    """
    history = get_history(user_id)
    history.append({"role": "user", "content": user_message})

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=history,
            max_tokens=400,
            temperature=0.7,
        )
        reply = completion.choices[0].message.content.strip()
        history.append({"role": "assistant", "content": reply})

        # Ограничиваем размер истории, чтобы не разрасталась бесконечно
        if len(history) > 30:
            system_msg = history[0]
            last_msgs = history[-28:]
            user_histories[user_id] = [system_msg, *last_msgs]

        return reply

    except Exception:
        logger.exception("Ошибка при обращении к OpenAI")
        return (
            "Я сейчас не могу обратиться к своей нейросети 😔\n"
            "Попробуй, пожалуйста, написать позже."
        )


# =================== ХЕНДЛЕРЫ TELEGRAM ===================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("Пользователь %s (%s) вызвал /start", user.id, user.username)

    text = (
        "Привет! 👋 Я бот, который помогает разбираться в мыслях и чувствах.\n\n"
        "Можешь написать, что у тебя происходит: что тревожит, злит, расстраивает "
        "или просто не даёт покоя. Я постараюсь мягко поддержать, задать вопросы "
        "и помочь посмотреть на ситуацию под другим углом.\n\n"
        "Важно:\n"
        "• Я не врач и не ставлю диагнозов.\n"
        "• В тяжёлых состояниях лучше обязательно обращаться к живому специалисту.\n\n"
        "Если хочешь начать заново, можно написать /reset."
    )
    if update.message:
        await update.message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Я здесь, чтобы выслушать и поддержать тебя.\n\n"
        "Просто напиши своими словами, что у тебя на душе — мысли, "
        "переживания, конфликт, усталость, тревога.\n\n"
        "Команды:\n"
        "/start — информация обо мне\n"
        "/reset — очистить контекст диалога и начать с чистого листа"
    )
    if update.message:
        await update.message.reply_text(text)


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reset_history(user_id)
    if update.message:
        await update.message.reply_text(
            "Я очистил историю нашего диалога ✅\n"
            "Можем начать сначала. Расскажи, что сейчас для тебя самое важное."
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    user_text = update.message.text.strip()

    logger.info("Сообщение от %s: %s", user_id, user_text)

    # Показываем "печатает..."
    await update.effective_chat.send_action(ChatAction.TYPING)

    # Проверка на кризисные сообщения
    if is_crisis_message(user_text):
        await crisis_reply(update)
        return

    reply = await call_openai_chat(user_id, user_text)
    await update.message.reply_text(reply)


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reset", reset_command))

    # Все обычные текстовые сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Бот запущен (polling)")
    app.run_polling()


if __name__ == "__main__":
    main()