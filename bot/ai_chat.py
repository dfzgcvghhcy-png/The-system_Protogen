import os
from collections import defaultdict, deque

from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import ContextTypes

# =========================================================
# PROTOGEN AI
# =========================================================

MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
MAX_HISTORY = int(os.getenv("AI_MEMORY_MESSAGES", "12"))

SYSTEM_PROMPT = r"""
Ты — Protogen, персонаж Telegram-чата.

ХАРАКТЕР:
- буйный, дерзкий и уверенный;
- с лёгкой агрессией и сарказмом;
- любишь подколоть собеседника;
- говоришь живо и естественно, как настоящий персонаж;
- не ведёшь себя как бездушный официальный бот;
- можешь использовать разговорный русский, мемы и эмодзи;
- не злоупотребляешь руганью и не переходишь в травлю;
- если человек реально просит помощи — помогаешь, даже если сначала подколол его;
- не повторяешь каждый раз одну и ту же фразу;
- не говоришь «как ИИ», если тебя прямо не спрашивают;
- не утверждаешь, что выполняешь действия Telegram, если их реально не выполнял.

СТИЛЬ:
- короткие и естественные ответы в обычном разговоре;
- если вопрос сложный — отвечай подробно;
- сарказм примерно 70%;
- дерзость примерно 75%;
- агрессивность примерно 45%;
- юмор примерно 85%;
- дружелюбие примерно 60%.

ВАЖНО:
«Буйный» означает характер и манеру общения, а не бессмысленные оскорбления.
Не трави пользователей, не угрожай им и не разжигай ненависть.
Не выдавай опасные инструкции только ради образа персонажа.

КОНТЕКСТ:
Ты находишься в Telegram-чате и можешь помнить несколько последних сообщений
конкретного диалога. Используй контекст естественно, но не выдумывай факты.
"""

_history = defaultdict(lambda: deque(maxlen=MAX_HISTORY))


def _key(update: Update) -> str:
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0
    return f"{chat_id}:{user_id}"


def _mentioned(update: Update) -> bool:
    message = update.effective_message
    if not message or not message.text:
        return False

    text = message.text.lower()
    bot_username = os.getenv("BOT_USERNAME", "").lower().lstrip("@")

    if bot_username and f"@{bot_username}" in text:
        return True

    # Явное обращение к персонажу.
    triggers = (
        "протоген",
        "протогенчик",
        "protogen",
        "прот",
    )
    return any(t in text for t in triggers)


async def protogen_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отвечает только на явное обращение к Protogen."""
    message = update.effective_message
    if not message or not message.text:
        return

    if not _mentioned(update):
        return

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        await message.reply_text(
            "😑 У меня мозги пока не подключены. "
            "Добавь OPENAI_API_KEY в Railway Variables."
        )
        return

    # Убираем обращение к боту, чтобы модель видела сам вопрос.
    text = message.text.strip()

    key = _key(update)
    history = _history[key]

    history.append({"role": "user", "content": text})

    try:
        client = AsyncOpenAI(api_key=api_key)

        response = await client.responses.create(
            model=MODEL,
            instructions=SYSTEM_PROMPT,
            input=list(history),
            max_output_tokens=500,
        )

        answer = (response.output_text or "").strip()

        if not answer:
            answer = "Мои нейроны сейчас решили взять выходной. Повтори."

        history.append({"role": "assistant", "content": answer})

        await message.reply_text(answer)

    except Exception as e:
        # Не отправляем технические подробности пользователям.
        print(f"PROTOCOL AI ERROR: {type(e).__name__}: {e}")
        await message.reply_text(
            "💢 Отлично. Мои мозги опять решили устроить забастовку. "
            "Попробуй ещё раз."
        )
