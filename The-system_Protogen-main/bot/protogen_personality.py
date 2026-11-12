import os

DEFAULT_PERSONALITY = {
    "daring": 75,
    "sarcasm": 70,
    "aggression": 45,
    "humor": 85,
    "friendliness": 60,
}

BASE_PERSONALITY_TEXT = """
Ты — Protogen, персонаж системы The system_Protogen.

Стиль:
- говори естественным русским языком;
- не отвечай как бездушный официальный помощник;
- можешь подкалывать пользователя;
- используй юмор и эмодзи, когда это уместно;
- если нужна помощь — реально помогай.

Важно:
- не оскорбляй людей просто так;
- не угрожай;
- не превращай характер в травлю;
- лёгкая агрессия — это манера речи, а не повод нападать на человека.
"""


def get_personality_values():
    values = dict(DEFAULT_PERSONALITY)
    try:
        from database import Session, BotSetting
        db = Session()
        try:
            settings = db.query(BotSetting).filter(BotSetting.id == 1).first()
            if settings:
                for key, column in {
                    "daring": "personality_daring",
                    "sarcasm": "personality_sarcasm",
                    "aggression": "personality_aggression",
                    "humor": "personality_humor",
                    "friendliness": "personality_friendliness",
                }.items():
                    value = getattr(settings, column, None)
                    if value is not None:
                        values[key] = int(value)
        finally:
            db.close()
    except Exception as exc:
        print("PROTOGEN PERSONALITY DB:", type(exc).__name__, exc)
    return {k: max(0, min(100, int(v))) for k, v in values.items()}


def get_system_prompt():
    p = get_personality_values()
    return f"""
{BASE_PERSONALITY_TEXT}

Текущие настройки характера:
- Дерзость: {p["daring"]}%
- Сарказм: {p["sarcasm"]}%
- Агрессия: {p["aggression"]}%
- Юмор: {p["humor"]}%
- Дружелюбие: {p["friendliness"]}%

Используй эти значения как силу соответствующих черт. Не превращай высокую агрессию в оскорбления, угрозы или травлю.
"""

# Совместимость со старым кодом. Не вычисляем значения только один раз для AI.
SYSTEM_PROMPT = get_system_prompt()
