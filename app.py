from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# простые ответы (без AI)
def get_response(text):
    text = text.lower()

    if "привет" in text:
        return "Привет 👋"
    elif "как дела" in text:
        return "Нормально 😎"
    elif "пока" in text:
        return "Пока 👋"
    else:
        return "Я пока без AI 😅"

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
