import os
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    session,
)
from werkzeug.security import check_password_hash


app = Flask(__name__)

# IMPORTANT:
# Set these in Railway Variables:
#   SECRET_KEY
#   ADMIN_USERNAME
#   ADMIN_PASSWORD_HASH
#
# ADMIN_PASSWORD_HASH should be generated with:
# python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('YOUR_PASSWORD'))"
app.secret_key = os.getenv("SECRET_KEY", "CHANGE_ME_IN_RAILWAY")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")


def get_response(text):
    text = (text or "").lower().strip()

    responses = {
        "привет": "Привет 👋 Я Protogen Bot — бот для управления чатом и развлечений!",
        "кто ты": "Я Protogen Bot 🤖, помогаю модерировать чат и развлекать пользователей.",
        "команды": "Команды доступны администраторам в защищённой панели.",
        "помощь": "Открой 🔐 Вход для админов, чтобы попасть в панель управления.",
        "пока": "Пока 👋",
    }

    for key in responses:
        if key in text:
            return responses[key]

    return "Я пока не знаю, как ответить на это 🤔"


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authenticated"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)

    return wrapped


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "")
    return jsonify({"response": get_response(user_message)})


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not ADMIN_PASSWORD_HASH:
            error = "Администратор ещё не настроен. Добавь ADMIN_PASSWORD_HASH в Railway Variables."
        elif username == ADMIN_USERNAME and check_password_hash(
            ADMIN_PASSWORD_HASH, password
        ):
            session.clear()
            session["admin_authenticated"] = True
            session["admin_username"] = username
            return redirect(url_for("admin_dashboard"))
        else:
            error = "Неверный логин или пароль."

    return render_template("admin_login.html", error=error)


@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template(
        "admin.html",
        username=session.get("admin_username", ADMIN_USERNAME),
    )


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
