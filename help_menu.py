"""/start, /help (interactive, with buttons), Telegram command menus, /id, /ping."""
import time
from datetime import datetime

from telegram import (
    BotCommand, BotCommandScopeAllChatAdministrators, BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonCommands,
    MenuButtonWebApp, Update, WebAppInfo,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core import esc, is_group, mention, name, reply, resolve_target, site_url


# Each section: (title, [(command, description), ...])
HELP_SECTIONS = {
    "mod": ("🛡 Модерация", [
        ("/warn [причина]", "предупреждение (ответом, @username или ID)"),
        ("/unwarn · /clearwarns", "снять один / все варны"),
        ("/warns", "сколько варнов у тебя или у участника"),
        ("/mute [срок] [причина]", "мут: <code>30m</code>, <code>2ч</code>, <code>1d</code>, <code>навсегда</code>"),
        ("/unmute", "снять мут"),
        ("/ban [срок] [причина]", "бан, без срока — навсегда"),
        ("/unban · /kick", "разбан · исключить"),
        ("/del · /purge · /clear 20", "удалить сообщение · с этого места · последние N"),
        ("/report [причина]", "пожаловаться модераторам (ответом)"),
        ("Гб · /gb", "голосование сообщества за бан (ответом); <b>Гб инфо</b>, <b>Гб стоп</b>"),
        ("Без слеша", "ответь на сообщение словом <b>мут 10м</b>, <b>бан</b>, <b>варн</b>, <b>кик</b>, <b>размут</b>"),
    ]),
    "info": ("📊 Инфо", [
        ("/me", "моя карточка: уровень, репутация, варны"),
        ("/id", "Telegram ID (свой или того, кому отвечаешь)"),
        ("/stats · /top", "статистика чата · топ активности"),
        ("/level · /levels", "уровень и топ по XP"),
        ("/achievements · /streak", "достижения · серия активности"),
        ("/daily · /dailyquest", "ежедневная награда и задание"),
        ("/week", "итоги недели чата (по воскресеньям приходят сами)"),
        ("Кто админ · Моя стата", "без слеша"),
    ]),
    "social": ("⭐ Сообщество", [
        ("/rules · /welcome", "правила и приветствие (админ может изменить)"),
        ("/plus · /minus", "± репутация (ответом)"),
        ("/reputation · /rating", "репутация · рейтинг"),
        ("/star · /stars · /mystars", "звёзды"),
        ("/rewards · /reward", "награды"),
        ("/ticket · /mytickets", "обращение в поддержку"),
        ("/appeal", "обжаловать наказание"),
    ]),
    "fun": ("🎮 Развлечения", [
        ("/dice · /8ball · /random 1 100", "кубик · шар · случайное число"),
        ("/choose a | b | c", "выбрать вариант"),
        ("/ship", "совместимость (ответом)"),
        ("/rp обнять", "РП-действие (ответом)"),
        ("/weather Москва", "погода"),
        ("/ai вопрос или ///Протоген", "спросить AI-Протогена"),
    ]),
    "tools": ("🧰 Инструменты", [
        ("/timer 10m текст", "напоминание"),
        ("/note имя текст · /notes", "мои заметки"),
        ("/bookmark · /bookmarks", "закладки (ответом)"),
        ("/schedule · /schedules", "запланированные посты (модераторы)"),
    ]),
    "filters": ("🧩 Фильтры", [
        ("/filter слово ответ", "автоответ; фраза в кавычках: <code>/filter \"как дела\" Норм!</code>"),
        ("/filters · /stop слово", "список · удалить автоответ"),
        ("/banword слово …", "запрещённые слова: удаление + варн (<code>казин*</code> — любое окончание)"),
        ("/banwords · /unbanword", "список · удалить"),
    ]),
    "admin": ("👑 Управление", [
        ("/panel", "панель модерации в чате"),
        ("/menu", "открыть Web-панель в Telegram"),
        ("/setmod · /delmod · /mods", "модераторы Protogen"),
        ("/modnote · /modnotes", "внутренние заметки"),
        ("/raidmode on|off", "режим защиты от рейда"),
        ("/settings", "настройки ЭТОГО чата кнопками: AutoMod, капча, новички, лимиты"),
        ("/setlog", "лог-канал: все наказания дублируются туда"),
        ("/backup", "бэкап базы в личку (только Создатель; сам — каждый день)"),
    ]),
}


def _help_keyboard(active=None):
    buttons = [InlineKeyboardButton(("• " if key == active else "") + title, callback_data=f"help_{key}")
               for key, (title, _) in HELP_SECTIONS.items()]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    url = site_url()
    if url:
        rows.append([InlineKeyboardButton("🌐 Все команды на сайте", url=url + "/commands")])
    if active:
        rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="help_main")])
    return InlineKeyboardMarkup(rows)


def _main_help_text():
    return (
        "🤖 <b>PROTOGEN // ПОМОЩЬ</b>\n\n"
        "Выбери раздел кнопкой ниже.\n\n"
        "⚡ <b>Самое нужное:</b>\n"
        "• ответь на сообщение <code>/mute 30m</code> или просто <b>мут 30м</b>\n"
        "• <code>/ban @username 1d спам</code>\n"
        "• <code>/warn</code> — после лимита варнов бот сам выдаст мут\n"
        "• <code>/report</code> — позвать модераторов\n"
        "• <code>/me</code> — твоя карточка"
    )


def _section_text(key):
    title, items = HELP_SECTIONS[key]
    lines = [f"<b>{title}</b>", ""]
    for cmd, desc in items:
        lines.append(f"<code>{esc(cmd)}</code>\n   {desc}" if cmd.startswith("/") else f"<b>{esc(cmd)}</b>\n   {desc}")
    return "\n".join(lines)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = (context.args[0].lower() if context.args else "").lstrip("/")
    if arg in HELP_SECTIONS:
        return await reply(update, _section_text(arg), reply_markup=_help_keyboard(arg))
    await reply(update, _main_help_text(), reply_markup=_help_keyboard())


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    key = (query.data or "").removeprefix("help_")
    await query.answer()
    if key == "main" or key not in HELP_SECTIONS:
        text_value, markup = _main_help_text(), _help_keyboard()
    else:
        text_value, markup = _section_text(key), _help_keyboard(key)
    try:
        await query.edit_message_text(text_value, parse_mode=ParseMode.HTML, reply_markup=markup,
                                      disable_web_page_preview=True)
    except Exception:
        pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_username = context.bot.username
    url = site_url()
    if is_group(update):
        return await reply(update,
                           f"🐾 Protogen на связи, {name(user)}!\n"
                           "Команды: /help · Пожаловаться: /report · Моя карточка: /me")
    rows = [
        [InlineKeyboardButton("➕ Добавить в группу",
                              url=f"https://t.me/{bot_username}?startgroup=protogen"
                                  "&admin=delete_messages+restrict_members+pin_messages+invite_users")],
        [InlineKeyboardButton("📖 Команды", callback_data="help_main")],
    ]
    if url:
        rows.append([InlineKeyboardButton("🎛 Панель управления", web_app=WebAppInfo(url=url + "/miniapp")),
                     InlineKeyboardButton("🌐 Сайт", url=url)])
    await reply(update,
                f"🐾 <b>Привет, {name(user)}!</b>\n\n"
                "Я <b>The system_Protogen</b> — страж и помощник для Telegram-чатов.\n\n"
                "🛡 Модерация: варны, муты, баны — ответом, по @username или словами «мут 10м»\n"
                "🤖 AutoMod: флуд, спам-ссылки, капс, рейды\n"
                "⚡ Уровни, репутация, достижения, ежедневные задания\n"
                "🌐 Web-панель со статистикой и настройками\n\n"
                "<b>Как начать:</b> добавь меня в группу кнопкой ниже и выдай права администратора "
                "(удаление сообщений и блокировка участников).",
                reply_markup=InlineKeyboardMarkup(rows))


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = site_url()
    if not url:
        return await reply(update, "⚠️ Адрес сайта не настроен (переменная SITE_URL).")
    if update.effective_chat.type == "private":
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🎛 Открыть панель", web_app=WebAppInfo(url=url + "/miniapp"))]])
    else:
        # Web App buttons work only in private chats; in groups we give a deep link.
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🎛 Открыть панель", url=f"https://t.me/{context.bot.username}?start=panel")],
                                       [InlineKeyboardButton("🌐 Сайт", url=url + "/admin")]])
    await reply(update, "🤖 <b>PROTOGEN // CONTROL CENTER</b>", reply_markup=markup)


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target, _ = resolve_target(update, context.args)
    lines = []
    if target is not None and getattr(target, "id", None):
        lines.append(f"👤 {mention(target)}: <code>{target.id}</code>")
    lines.append(f"🙋 Твой ID: <code>{update.effective_user.id}</code>")
    if update.effective_chat:
        lines.append(f"💬 ID чата: <code>{update.effective_chat.id}</code>")
    await reply(update, "\n".join(lines))


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    started = time.monotonic()
    message = await reply(update, "🏓 Понг...")
    delay = int((time.monotonic() - started) * 1000)
    uptime = datetime.utcnow() - context.bot_data.get("started_at", datetime.utcnow())
    hours, rem = divmod(int(uptime.total_seconds()), 3600)
    try:
        await message.edit_text(f"🏓 <b>Понг!</b> {delay} мс · аптайм {hours} ч {rem // 60} мин",
                                parse_mode=ParseMode.HTML)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# The "/" menu inside Telegram
# ---------------------------------------------------------------------------

_PRIVATE = [
    ("start", "Главное меню"), ("help", "Все команды"), ("menu", "Панель управления"),
    ("ai", "Спросить AI-Протогена"), ("weather", "Погода"), ("timer", "Напоминание"),
    ("id", "Мой Telegram ID"), ("ping", "Проверить, жив ли бот"),
]
_GROUP = [
    ("help", "Все команды с кнопками"), ("me", "Моя карточка"), ("report", "Пожаловаться (ответом)"),
    ("rules", "Правила чата"), ("level", "Мой уровень"), ("top", "Топ активности"),
    ("daily", "Ежедневная награда"), ("week", "Итоги недели"), ("plus", "+ репутация (ответом)"), ("warns", "Мои варны"),
    ("appeal", "Обжаловать наказание"), ("ai", "Спросить AI-Протогена"), ("id", "Узнать ID"),
]
_ADMINS = _GROUP[:3] + [
    ("warn", "Варн (ответом / @user)"), ("mute", "Мут: /mute 30m причина"), ("unmute", "Снять мут"),
    ("ban", "Бан: /ban 1d причина"), ("unban", "Разбан"), ("kick", "Кик"),
    ("del", "Удалить сообщение"), ("purge", "Удалить с этого места"), ("panel", "Панель модерации"),
    ("setmod", "Назначить модератора"), ("settings", "Настройки чата (кнопки)"), ("filter", "Автоответ"),
    ("banword", "Запрещённое слово"), ("setlog", "Лог-канал"), ("gb", "Голосование за бан"), ("raidmode", "Режим защиты от рейда"),
] + _GROUP[3:]


async def install_command_menus(application):
    bot = application.bot
    try:
        await bot.set_my_commands([BotCommand(c, d) for c, d in _PRIVATE], scope=BotCommandScopeAllPrivateChats())
        await bot.set_my_commands([BotCommand(c, d) for c, d in _GROUP], scope=BotCommandScopeAllGroupChats())
        await bot.set_my_commands([BotCommand(c, d) for c, d in _ADMINS], scope=BotCommandScopeAllChatAdministrators())
        await bot.set_my_short_description("Страж и помощник для чатов: модерация, AutoMod, уровни, Web-панель.")
        print("📋 Telegram command menus installed")
    except Exception as exc:
        print(f"COMMAND MENU ERROR: {type(exc).__name__}: {exc}")

    # The "Панель управления" button next to the input field is stored by Telegram itself.
    # Re-point it at the current site on every start, so a host move never leaves it broken.
    url = site_url()
    try:
        if url:
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
                text="Панель управления", web_app=WebAppInfo(url=url + "/miniapp")))
            print(f"🎛 Menu button → {url}/miniapp")
        else:
            await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception as exc:
        print(f"MENU BUTTON ERROR: {type(exc).__name__}: {exc}")
