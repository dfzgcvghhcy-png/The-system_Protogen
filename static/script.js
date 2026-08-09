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
    "help - команды",
    "ban - бан",
    "mute - мут",
    "stats - статистика"
];

const rightLines = [
    "[12:01] USER: привет",
    "[12:01] BOT: привет",
    "[12:02] USER: а",
    "[12:02] BOT: не понял"
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
