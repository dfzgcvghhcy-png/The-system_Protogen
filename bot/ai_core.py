import os
from collections import defaultdict, deque
import requests


MAX_HISTORY = int(os.getenv("AI_MEMORY_MESSAGES", "12"))

from protogen_personality import SYSTEM_PROMPT

_history = defaultdict(lambda: deque(maxlen=MAX_HISTORY))


def ask_protogen(text: str, user_key: str = "default"):
    api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        return "💢 У меня нет ключа нейросети. Добавьте OPENROUTER_API_KEY."

    history = _history[user_key]
    history.append({
        "role": "user",
        "content": text
    })

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
                        "content": SYSTEM_PROMPT
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
            return answer

        print("OPENROUTER:", data)

    except Exception as e:
        print("PROTOGEN AI ERROR:", type(e).__name__, e)

    return "💥 Мои нейроны сейчас устроили забастовку. Попробуй ещё раз."
