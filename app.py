from flask import Flask, request, jsonify, render_template
import requests
import os

app = Flask(__name__)

API_URL = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.2"

HF_TOKEN = os.getenv("HF_TOKEN")

headers = {}
if HF_TOKEN:
    headers["Authorization"] = f"Bearer {HF_TOKEN}"


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message")

    try:
        response = requests.post(
            API_URL,
            headers=headers,
            json={"inputs": user_message}
        )

        result = response.json()

        if isinstance(result, list):
            ai_text = result[0].get("generated_text", "...")
        else:
            ai_text = str(result)

        return jsonify({"reply": ai_text})

    except Exception as e:
        return jsonify({"reply": f"Ошибка: {str(e)}"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
