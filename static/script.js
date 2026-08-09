const messages = document.getElementById("messages");

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

function addMessage(text, type) {
    const div = document.createElement("div");
    div.className = "message " + type;
    div.innerText = text;
    messages.appendChild(div);

    messages.scrollTop = messages.scrollHeight;
}

/* БОКОВЫЕ ТЕРМИНАЛЫ */
const leftLines = [
    "ERROR 0x1F4A9: System overload",
    "WARNING: Memory leak detected...",
    "FAIL: Connection to core lost",
    "CRITICAL: AI module crashed",
    ">>> rebooting system...",
    "ACCESS DENIED",
    "injecting patch...",
    "ERROR: Unknown command",
    "SYSTEM FAILURE [code: 503]",
    "restarting neural link..."
];

const rightLines = [
    "[12:01] USER: привет",
    "[12:01] BOT: ответ отправлен",
    "[12:02] ERROR: response timeout",
    "[12:02] retrying...",
    "[12:03] WARNING: high load",
    "[12:03] BOT: fallback mode",
    "[12:04] ERROR 404: brain not found",
    "[12:04] USER: а",
    "[12:04] BOT: не понял 🤔",
    "[12:05] SYSTEM: unstable..."
];
function typeEffect(el, lines) {
    let i = 0;
    let j = 0;

    function type() {
        if (i < lines.length) {
            if (j < lines[i].length) {
                el.innerHTML += lines[i][j];
                j++;
                setTimeout(type, 30);
            } else {
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

typeEffect(document.getElementById("leftText"), leftLines);
typeEffect(document.getElementById("rightText"), rightLines);
if (Math.random() < 0.02) {
    el.innerHTML += "#$%!";
}
