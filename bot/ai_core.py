import os
from collections import defaultdict, deque

import requests

from protogen_personality import get_system_prompt
from database import Session, AIMessage


MAX_HISTORY = int(os.getenv("AI_MEMORY_MESSAGES", "12"))

# Быстрый кэш текущего процесса. Настоящая память хранится в PostgreSQL.
_history = defaultdict(lambda: deque(maxlen=MAX_HISTORY))


def _load_history(user_key: str):
    """Загрузить последние сообщения пользователя из PostgreSQL."""
    db = Session()
    try:
        rows = (
            db.query(AIMessage)
            .filter(AIMessage.user_key == str(user_key))
            .order_by(AIMessage.created_at.desc(), AIMessage.id.desc())
            .limit(MAX_HISTORY)
            .all()
        )

        messages = [
            {"role": row.role, "content": row.content}
            for row in reversed(rows)
        ]

        history = _history[user_key]
        history.clear()
        history.extend(messages)
        return history
    finally:
        db.close()


def _save_message(user_key: str, role: str, content: str):
    """Сохранить сообщение Protogen в PostgreSQL."""
    db = Session()
    try:
        db.add(
            AIMessage(
                user_key=str(user_key),
                role=role,
                content=content,
            )
        )
        db.commit()
    except Exception as e:
        db.rollback()
        print("PROTOGEN MEMORY SAVE ERROR:", type(e).__name__, e)
    finally:
        db.close()


def ask_protogen(text: str, user_key: str = "default"):
    api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        return "💢 У меня нет ключа нейросети. Добавьте OPENROUTER_API_KEY."

    user_key = str(user_key)

    # Теперь память переживает перезапуск Railway.
    history = _load_history(user_key)

    # Добавляем новое сообщение в память до запроса.
    history.append({
        "role": "user",
        "content": text
    })

    _save_message(user_key, "user", text)

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", ""),
                "X-Title": "The system_Protogen",
            },
            json={
                "model": os.getenv(
                    "OPENROUTER_MODEL",
                    "openrouter/free"
                ),
                "messages": [
                    {
                        "role": "system",
                        "content": get_system_prompt()
                    },
                    *list(history)
                ],
            },
            timeout=60,
        )

        data = response.json()

        answer = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        if answer:
            history.append({
                "role": "assistant",
                "content": answer
            })

            _save_message(user_key, "assistant", answer)
            return answer

        print("OPENROUTER:", data)

    except Exception as e:
        print("PROTOGEN AI ERROR:", type(e).__name__, e)

    return "💥 Мои нейроны сейчас устроили забастовку. Попробуй ещё раз."
