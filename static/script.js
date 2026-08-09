function sendMessage() {
    let input = document.getElementById("message");
    let text = input.value.trim();

    if (text === "") return;

    let chatBox = document.getElementById("chat-box");

    // сообщение пользователя
    let userMsg = document.createElement("div");
    userMsg.className = "message user";
    userMsg.innerText = text;
    chatBox.appendChild(userMsg);

    input.value = "";

    // "печатает..."
    let typing = document.createElement("div");
    typing.className = "message bot";
    typing.innerText = "печатает...";
    chatBox.appendChild(typing);

    chatBox.scrollTop = chatBox.scrollHeight;

    setTimeout(() => {
        typing.innerHTML = getBotReply(text);
        chatBox.scrollTop = chatBox.scrollHeight;
    }, 700);
}

function getBotReply(text) {
    text = text.toLowerCase();

    if (text.includes("привет")) {
        return "Привет 👋";
    }

    if (text.includes("кто ты")) {
        return "Я Protogen Bot 🤖<br>Я просто бот без AI, но умею отвечать 😎";
    }

    if (text.includes("команды")) {
        return `
        📜 Команды:<br>
        • привет<br>
        • кто ты<br>
        • команды
        `;
    }

    return "Я не понял 🤔";
}
