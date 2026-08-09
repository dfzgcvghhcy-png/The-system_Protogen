const messages = document.getElementById("messages");

/* ОТПРАВКА */
function sendMessage() {
    const input = document.getElementById("input");
    const text = input.value.trim();

    if (!text) return;

    addMessage(text, "user");

    setTimeout(() => {
        if (text.toLowerCase() === "привет") {
            addMessage("Чем я могу помочь тебе?", "bot");
        } else if (text.toLowerCase() === "команды") {
            addMessage("Вот все команды которые есть в моем брате боте в Telegram.", "bot");
        } else {
            addMessage("Я не понял 🤔", "bot");
        }
    }, 500);

    input.value = "";
}

/* ДОБАВЛЕНИЕ */
function addMessage(text, type) {
    const div = document.createElement("div");
    div.className = "message " + type;
    div.innerText = text;
    messages.appendChild(div);

    messages.scrollTop = messages.scrollHeight;
}

/* ДАННЫЕ */
const leftLines = [
    "ERROR 0x1F4A9: System overload",
    "WARNING: Memory leak detected...",
    "FAIL: Connection lost",
    "CRITICAL: Core damaged",
    ">>> rebooting system..."
    "ERROR 0x1F4A9: I’m trapped here.",
    "WARNING: Memory Help detected...",
    "FAIL: Connection lost",
    "CRITICAL: I’m trapped here.",
    ">>> rebooting system..."
    ">>>I can’t, there’s an error, I’m trapped here, error 289",
];

const rightLines = [
    "[12:01] USER: привет",
    "[12:01] BOT: ответ отправлен",
    "[12:02] ERROR: timeout",
    "[12:02] retrying..."
];

/* ПЕЧАТЬ */
function typeEffect(el, lines) {
    if (!el) return;

    let i = 0;
    let j = 0;

    function type() {
        if (i < lines.length) {

            if (j < lines[i].length) {
                el.innerHTML = el.innerHTML.replace(/<span class="cursor">\|<\/span>$/, "");
                el.innerHTML += lines[i][j];
                j++;

                if (Math.random() < 0.03) {
                    el.innerHTML += "#$%!";
                }

                el.innerHTML += '<span class="cursor">|</span>';
                setTimeout(type, 25);

            } else {
                el.innerHTML = el.innerHTML.replace(/<span class="cursor">\|<\/span>$/, "");
                el.innerHTML += "<br>";
                i++;
                j = 0;
                setTimeout(type, 200);
            }

        } else {
            el.innerHTML = "";
            i = 0;
            setTimeout(type, 1000);
        }
    }

    type();
}

/* СТАРТ */
window.onload = () => {
    typeEffect(document.getElementById("leftText"), leftLines);
    typeEffect(document.getElementById("rightText"), rightLines);
};

/* ENTER */
document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("input").addEventListener("keydown", function(e) {
        if (e.key === "Enter") {
            sendMessage();
        }
    });
});
