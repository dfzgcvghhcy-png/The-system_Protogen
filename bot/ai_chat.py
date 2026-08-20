from telegram import Update
from telegram.ext import ContextTypes

from ai_core import ask_protogen


def mentioned(text: str):
    text = text.lower()

    triggers = (
        "протоген",
        "протогенчик",
        "protogen",
        "прот",
    )

    return any(x in text for x in triggers)


async def protogen_ai_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message

    if not message or not message.text:
        return

    if not mentioned(message.text):
        return

    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0

    key = f"{chat_id}:{user_id}"

    answer = ask_protogen(
        message.text,
        key
    )

    await message.reply_text(answer)
