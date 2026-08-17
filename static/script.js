const messages = document.getElementById("messages");

const commands = {
    "/help": "📖 Показывает список доступных функций",
    "/ban": "🔨 Банит пользователя в чате",
    "/mute": "🔇 Выдаёт мут пользователю",
    "/unmute": "🔊 Снимает мут с пользователя",
    "/warn": "⚠️ Выдаёт предупреждение",
    "/stats": "📊 Показывает статистику пользователя"
};

const commandsList = Object.keys(commands);

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

async function sendMessage() {
    const input = document.getElementById("input");
    const text = input.value.trim();

    if (!text) return;

    addMessage(text, "user");
    logRight(`[${getTime()}] USER: ${text}`);
    removeCommands();
    input.value = "";

    try {
        const response = await fetch("/chat", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({message: text})
        });

        const data = await response.json();
        addMessage(data.response, "bot");
        logRight(`[${getTime()}] BOT: ${data.response}`);
    } catch (error) {
        const msg = "Не удалось связаться с системой 🤖";
        addMessage(msg, "bot");
        logRight(`[${getTime()}] ERROR: ${error}`);
    }
}

function addMessage(text, type) {
    const div = document.createElement("div");
    div.className = "message " + type;
    div.innerText = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
}

function getTime() {
    return new Date().toLocaleTimeString().slice(0, 5);
}

function logRight(text) {
    const panel = document.getElementById("rightText");
    panel.innerHTML += text.replaceAll("<", "&lt;").replaceAll(">", "&gt;") + "<br>";
    panel.scrollTop = panel.scrollHeight;
}

const systemLines = [
    "SYSTEM ONLINE...",
    "Protogen core initialized",
    "Security layer: active",
    "Admin console: ready",
    ">>> waiting for input..."
];

function typeSystem(el, lines) {
    let i = 0;
    let j = 0;

    function type() {
        if (i < lines.length) {
            if (j < lines[i].length) {
                el.innerHTML += lines[i][j];
                j++;
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

document.addEventListener("DOMContentLoaded", () => {
    const left = document.getElementById("leftText");
    if (left) typeSystem(left, systemLines);

    const input = document.getElementById("input");
    if (!input) return;

    input.addEventListener("input", function () {
        const val = this.value.toLowerCase();

        if (val.startsWith("ком") || val.startsWith("/")) {
            showCommands();
        } else {
            removeCommands();
        }
    });

    input.addEventListener("keydown", function(e) {
        if (e.key === "Enter") sendMessage();
    });
});
