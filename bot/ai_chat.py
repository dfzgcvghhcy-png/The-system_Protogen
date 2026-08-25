import re

from telegram import Update
from telegram.ext import ContextTypes

from ai_core import ask_protogen


def mentioned(text: str):
    # AI responds only to explicit triggers written with ///.
    # Examples: ///Протя, ///Протоген, ///Protogen
    # Ordinary mentions such as "Протоген" are ignored.
    triggers = (
        "протя",
        "протоген",
        "протогенчик",
        "protogen",
        "прот",
    )

    pattern = r"///(?:" + "|".join(re.escape(x) for x in triggers) + r")\b"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


async def protogen_ai_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.effective_message

    if not message or not message.text:
        return

    print("🔥 PROTOGEN AI RECEIVED:", message.text)

    if not mentioned(message.text):
        return

    chat_id = (
        update.effective_chat.id
        if update.effective_chat
        else 0
    )

    user_id = (
        update.effective_user.id
        if update.effective_user
        else 0
    )

    key = f"{chat_id}:{user_id}"

    try:
        answer = ask_protogen(
            message.text,
            key
        )

        await message.reply_text(answer)

    except Exception as e:
        print("AI CHAT ERROR:", e)

        await message.reply_text(
            "💥 Протоген завис. Мои нейроны ушли на перезагрузку."
        )
