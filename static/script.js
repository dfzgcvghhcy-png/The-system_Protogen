const messages = document.getElementById("messages");

/* ===================== КОМАНДЫ ===================== */

const commandsList = [
    "/help",
    "/ban",
    "/mute",
    "/unmute",
    "/warn",
    "/stats"
];

function showCommands() {
    removeCommands();

    const container = document.createElement("div");
    container.className = "commands-box";
    container.id = "commandsBox";

    commandsList.forEach(cmd => {
        const btn = document.createElement("div");
        btn.className = "command-item";
        btn.innerText = cmd;

        btn.onclick = () => {
            document.getElementById("input").value = cmd;
            removeCommands();
        };

        container.appendChild(btn);
    });

    document.querySelector(".input-area").appendChild(container);
}

function removeCommands() {
    const old = document.getElementById("commandsBox");
    if (old) old.remove();
}

/* ===================== ЧАТ ===================== */

function sendMessage() {
    const input = document.getElementById("input");
    const text = input.value.trim();

    if (!text) return;

    addMessage(text, "user");
    logRight(`[${getTime()}] USER: ${text}`);

    removeCommands();

    setTimeout(() => {
        let response = "";

        if (text.toLowerCase() === "привет") {
            response = "Привет 👋";
        } else if (text.toLowerCase() === "команды") {
            response = "Выбери команду ниже 👇";
            showCommands();
        } else if (commandsList.includes(text)) {
            response = `Команда ${text} выполнена ✅`;
        } else {
            response = "Я не понял 🤔";
        }

        addMessage(response, "bot");
        logRight(`[${getTime()}] BOT: ${response}`);

    }, 400);

    input.value = "";
}

function addMessage(text, type) {
    const div = document.createElement("div");
    div.className = "message " + type;
    div.innerText = text;
    messages.appendChild(div);

    messages.scrollTop = messages.scrollHeight;
}

/* ===================== ЛОГИ ===================== */

function getTime() {
    return new Date().toLocaleTimeString().slice(0,5);
}

function logRight(text) {
    const panel = document.getElementById("rightText");
    panel.innerHTML += text + "<br>";
    panel.scrollTop = panel.scrollHeight;
}

/* ===================== ТЕРМИНАЛ (SYSTEM) ===================== */

const systemLines = [
    "ERROR 0x1F4A9: System overload",
    "WARNING: Memory leak detected...",
    "FAIL: Connection lost",
    "CRITICAL: Core damaged",
    ">>> rebooting system..."
];

function typeSystem(el, lines) {
    let i = 0;
    let j = 0;

    function type() {
        if (i < lines.length) {

            if (j < lines[i].length) {
                el.innerHTML += lines[i][j];
                j++;

                if (Math.random() < 0.03) {
                    el.innerHTML += "#$%!";
                }

                setTimeout(type, 25);

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

/* ===================== СОБЫТИЯ ===================== */

document.addEventListener("DOMContentLoaded", () => {

    // запуск SYSTEM
    const left = document.getElementById("leftText");
    if (left) typeSystem(left, systemLines);

    // ввод
    const input = document.getElementById("input");

    input.addEventListener("input", function () {
        const val = this.value.toLowerCase();

        if (val.startsWith("ком")) {
            showCommands();
        } else {
            removeCommands();
        }
    });

    input.addEventListener("keydown", function(e) {
        if (e.key === "Enter") {
            sendMessage();
        }
    });
});
