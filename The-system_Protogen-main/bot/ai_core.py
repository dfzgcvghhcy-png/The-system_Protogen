import os
import re

import requests

from protogen_personality import get_system_prompt
from database import (
    Session,
    AIMessage,
    UserMemory,
)


# ============================================================
# SETTINGS
# ============================================================

# Сколько последних сообщений использовать
# в обычной памяти разговора.
MAX_HISTORY = int(
    os.getenv(
        "AI_MEMORY_MESSAGES",
        "12",
    )
)

# Сколько долговременных фактов хранить
# для одного пользователя.
MAX_LONG_TERM_MEMORIES = int(
    os.getenv(
        "AI_LONG_TERM_MEMORIES",
        "20",
    )
)


# ============================================================
# LONG-TERM MEMORY
# ============================================================

def _extract_memories(text: str):
    """
    Извлекает простые факты, которые пользователь
    явно сообщил о себе.

    Поддерживаются:

    - имя
    - возраст
    - город
    - откуда пользователь
    - работа
    - нравится / любит
    - не любит

    Мы специально НЕ пытаемся запоминать:
    - пароли
    - токены
    - API keys
    - секретные ключи
    """

    memories = []

    patterns = [

        # ----------------------------------------------------
        # NAME
        # ----------------------------------------------------

        (
            "name",
            r"\b(?:меня зовут|зови меня|мо[её] имя)"
            r"\s+([A-Za-zА-Яа-яЁё]"
            r"[A-Za-zА-Яа-яЁё0-9_-]{1,30})",
        ),

        # ----------------------------------------------------
        # AGE
        # ----------------------------------------------------

        (
            "age",
            r"\bмне\s+(\d{1,3})"
            r"\s*(?:лет|год(?:а)?)?\b",
        ),

        # ----------------------------------------------------
        # CITY
        # ----------------------------------------------------

        (
            "city",
            r"\bя\s+(?:живу|нахожусь)"
            r"\s+в\s+"
            r"([A-Za-zА-Яа-яЁё0-9 .'-]{2,50})",
        ),

        # ----------------------------------------------------
        # FROM
        # ----------------------------------------------------

        (
            "from",
            r"\bя\s+из\s+"
            r"([A-Za-zА-Яа-яЁё0-9 .'-]{2,50})",
        ),

        # ----------------------------------------------------
        # JOB
        # ----------------------------------------------------

        (
            "job",
            r"\bя\s+работаю\s+"
            r"(.{2,100})",
        ),

        # ----------------------------------------------------
        # LIKES
        # ----------------------------------------------------

        (
            "likes",
            r"\b(?:я\s+люблю|мне\s+нравится)"
            r"\s+(.{2,100})",
        ),

        # ----------------------------------------------------
        # DISLIKES
        # ----------------------------------------------------

        (
            "dislikes",
            r"\b(?:я\s+не\s+люблю|я\s+ненавижу)"
            r"\s+(.{2,100})",
        ),
    ]

    for fact_key, pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        value = match.group(1).strip(
            " .,!?:;\"'()[]{}"
        )

        if not value:
            continue

        # Ограничиваем размер одного факта.
        value = value[:150]

        lowered = value.lower()

        # Защита от случайного сохранения
        # секретных данных.
        forbidden = (
            "password",
            "пароль",
            "token",
            "токен",
            "api_key",
            "api key",
        )

        if any(
            word in lowered
            for word in forbidden
        ):
            continue

        memories.append(
            (
                fact_key,
                value,
            )
        )

    return memories


# ============================================================
# SAVE LONG-TERM MEMORY
# ============================================================

def _save_memories(
    user_key: str,
    text: str,
):

    extracted = _extract_memories(text)

    if not extracted:
        return

    db = Session()

    try:

        for fact_key, fact_value in extracted:

            memory = (
                db.query(UserMemory)
                .filter(
                    UserMemory.user_key
                    == str(user_key),

                    UserMemory.fact_key
                    == fact_key,
                )
                .first()
            )

            if memory:

                # Если пользователь позже
                # сообщает новое значение,
                # обновляем старое.
                memory.fact_value = (
                    fact_value
                )

            else:

                db.add(
                    UserMemory(
                        user_key=str(
                            user_key
                        ),

                        fact_key=fact_key,

                        fact_value=fact_value,
                    )
                )

        # ----------------------------------------------------
        # LIMIT MEMORY
        # ----------------------------------------------------

        memories = (
            db.query(UserMemory)
            .filter(
                UserMemory.user_key
                == str(user_key)
            )
            .order_by(
                UserMemory.updated_at.desc(),
                UserMemory.id.desc(),
            )
            .all()
        )

        for old_memory in memories[
            MAX_LONG_TERM_MEMORIES:
        ]:

            db.delete(old_memory)

        db.commit()

    except Exception as e:

        db.rollback()

        print(
            "PROTOGEN LONG MEMORY SAVE ERROR:",
            type(e).__name__,
            e,
        )

    finally:

        db.close()


# ============================================================
# LOAD LONG-TERM MEMORY
# ============================================================

def _load_memories(
    user_key: str,
):

    db = Session()

    try:

        rows = (
            db.query(UserMemory)
            .filter(
                UserMemory.user_key
                == str(user_key)
            )
            .order_by(
                UserMemory.updated_at.desc(),
                UserMemory.id.desc(),
            )
            .limit(
                MAX_LONG_TERM_MEMORIES
            )
            .all()
        )

        return [
            {
                "key": row.fact_key,
                "value": row.fact_value,
            }
            for row in rows
        ]

    except Exception as e:

        print(
            "PROTOGEN LONG MEMORY LOAD ERROR:",
            type(e).__name__,
            e,
        )

        return []

    finally:

        db.close()


# ============================================================
# LOAD CHAT HISTORY
# ============================================================

def _load_history(
    user_key: str,
):
    """
    Загружает последние сообщения
    из PostgreSQL.

    Благодаря этому обычный диалог
    переживает перезапуск Railway.
    """

    db = Session()

    try:

        rows = (
            db.query(AIMessage)
            .filter(
                AIMessage.user_key
                == str(user_key)
            )
            .order_by(
                AIMessage.created_at.desc(),
                AIMessage.id.desc(),
            )
            .limit(
                MAX_HISTORY
            )
            .all()
        )

        # Сейчас записи идут от новых к старым.
        # Разворачиваем обратно для AI.
        rows.reverse()

        return [
            {
                "role": row.role,
                "content": row.content,
            }
            for row in rows
        ]

    except Exception as e:

        print(
            "PROTOGEN HISTORY LOAD ERROR:",
            type(e).__name__,
            e,
        )

        return []

    finally:

        db.close()


# ============================================================
# SAVE CHAT MESSAGE
# ============================================================

def _save_message(
    user_key: str,
    role: str,
    content: str,
):

    db = Session()

    try:

        db.add(
            AIMessage(
                user_key=str(
                    user_key
                ),

                role=role,

                content=content,
            )
        )

        db.commit()

    except Exception as e:

        db.rollback()

        print(
            "PROTOGEN MEMORY SAVE ERROR:",
            type(e).__name__,
            e,
        )

    finally:

        db.close()


# ============================================================
# BUILD MEMORY CONTEXT
# ============================================================

def _build_memory_context(
    memories,
):

    if not memories:
        return ""

    labels = {

        "name": "Имя",

        "age": "Возраст",

        "city": "Живёт в",

        "from": "Родом из",

        "job": "Работа",

        "likes": "Нравится",

        "dislikes": "Не любит",
    }

    lines = [
        "",
        "ДОЛГОВРЕМЕННАЯ ПАМЯТЬ "
        "О СОБЕСЕДНИКЕ:",
    ]

    for memory in memories:

        label = labels.get(
            memory["key"],
            memory["key"],
        )

        lines.append(
            f"- {label}: "
            f"{memory['value']}"
        )

    lines.append("")

    lines.append(
        "Используй эту информацию "
        "естественно, когда она действительно "
        "относится к разговору. "
        "Не перечисляй память без причины. "
        "Не выдумывай дополнительные факты."
    )

    return "\n".join(lines)


# ============================================================
# PROTOGEN AI
# ============================================================

def ask_protogen(
    text: str,
    user_key: str = "default",
):

    # --------------------------------------------------------
    # OPENROUTER KEY
    # --------------------------------------------------------

    api_key = os.getenv(
        "OPENROUTER_API_KEY"
    )

    if not api_key:

        return (
            "💢 У меня нет ключа нейросети. "
            "Добавьте OPENROUTER_API_KEY."
        )

    user_key = str(user_key)

    # --------------------------------------------------------
    # 1. SAVE LONG-TERM FACTS
    # --------------------------------------------------------

    _save_memories(
        user_key,
        text,
    )

    # --------------------------------------------------------
    # 2. LOAD NORMAL CHAT HISTORY
    # --------------------------------------------------------

    history = _load_history(
        user_key
    )

    # --------------------------------------------------------
    # 3. LOAD LONG-TERM MEMORY
    # --------------------------------------------------------

    memories = _load_memories(
        user_key
    )

    # --------------------------------------------------------
    # 4. BUILD AI MESSAGES
    # --------------------------------------------------------

    system_prompt = (
        get_system_prompt()
        + _build_memory_context(
            memories
        )
    )

    messages = [

        {
            "role": "system",
            "content": system_prompt,
        },

        *history,

        {
            "role": "user",
            "content": text,
        },
    ]

    # --------------------------------------------------------
    # 5. OPENROUTER REQUEST
    # --------------------------------------------------------

    try:

        response = requests.post(

            "https://openrouter.ai/api/v1/chat/completions",

            headers={

                "Authorization":
                    f"Bearer {api_key}",

                "Content-Type":
                    "application/json",

                "HTTP-Referer":
                    os.getenv(
                        "OPENROUTER_SITE_URL",
                        "",
                    ),

                "X-Title":
                    "The system_Protogen",
            },

            json={

                "model":
                    os.getenv(
                        "OPENROUTER_MODEL",
                        "openrouter/free",
                    ),

                "messages":
                    messages,
            },

            timeout=60,
        )

        data = response.json()

        answer = (
            data.get(
                "choices",
                [{}],
            )[0]
            .get(
                "message",
                {},
            )
            .get(
                "content",
                "",
            )
            .strip()
        )

        # ----------------------------------------------------
        # 6. SUCCESS
        # ----------------------------------------------------

        if answer:

            # Сохраняем сообщение пользователя.
            _save_message(
                user_key,
                "user",
                text,
            )

            # Сохраняем ответ Protogen.
            _save_message(
                user_key,
                "assistant",
                answer,
            )

            return answer

        print(
            "OPENROUTER:",
            data,
        )

    # --------------------------------------------------------
    # 7. ERROR
    # --------------------------------------------------------

    except Exception as e:

        print(
            "PROTOGEN AI ERROR:",
            type(e).__name__,
            e,
        )

    return (
        "💥 Мои нейроны сейчас устроили "
        "забастовку. Попробуй ещё раз."
    )
