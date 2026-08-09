from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

def get_response(text):
    text = text.lower()

    responses = {
        "привет": "Привет 👋 Я Protogen Bot — бот для управления чатом и развлечений!",
        "кто ты": "Я Protogen Bot 🤖, помогаю модерировать чат и развлекать пользователей.",
        "команды": "Вот мои команды:\n/start\n/help\n/ban\n/mute\n/unmute",
        "помощь": "Напиши 'команды', чтобы увидеть список доступных команд.",
        "пока": "Пока 👋"
    }

    # проверка по ключевым словам
    for key in responses:
        if key in text:
            return responses[key]

    return "Я не понял 😅 Напиши 'команды'"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message")
    response = get_response(user_message)
    return jsonify({"response": response})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
