const messages = document.getElementById("messages");

/* ОТПРАВКА */
function sendMessage() {
    const input = document.getElementById("input");
    const text = input.value.trim();

    if (!text) return;

    addMessage(text, "user");

    setTimeout(() => {
        if (text.toLowerCase() === "привет") {
            addMessage("Привет 👋", "bot");
        } else if (text.toLowerCase() === "команды") {
            addMessage("привет, команды, помощь", "bot");
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

/* ДАННЫЕ ТЕРМИНАЛА */
const leftLines = [
    "ERROR 0x1F4A9: System overload",
    "WARNING: Memory leak detected...",
    "FAIL: Connection lost",
    "CRITICAL: Core damaged",
    ">>> rebooting system...",
    "ACCESS DENIED",
    "injecting patch..."
];

const rightLines = [
    "[12:01] USER: привет",
    "[12:01] BOT: ответ отправлен",
    "[12:02] ERROR: timeout",
    "[12:02] retrying...",
    "[12:03] BOT: fallback mode",
    "[12:04] USER: а",
    "[12:04] BOT: не понял 🤔"
];

/* ПЕЧАТАЮЩИЙСЯ ЭФФЕКТ */
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
