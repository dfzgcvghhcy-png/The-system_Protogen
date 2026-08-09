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

    // ответ бота
    let botMsg = document.createElement("div");
    botMsg.className = "message bot";
    botMsg.innerHTML = getBotReply(text);
    chatBox.appendChild(botMsg);

    // очистка
    input.value = "";

    // скролл вниз
    chatBox.scrollTop = chatBox.scrollHeight;
}

function getBotReply(text) {
    text = text.toLowerCase();

    if (text.includes("привет")) {
        return "Привет 👋";
    }

    if (text.includes("кто ты")) {
        return "Я Protogen Bot 🤖<br>Я создан для общения и помощи.";
    }

    if (text.includes("команды")) {
        return `
        📜 Команды:<br>
        • привет<br>
        • кто ты<br>
        • команды
        `;
    }

    return "Я пока не понимаю 😅";
}
