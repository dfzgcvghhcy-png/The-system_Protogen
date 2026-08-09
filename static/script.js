const chat = document.getElementById("chat");
const input = document.getElementById("input");

function sendMessage() {
    const text = input.value.trim();
    if (!text) return;

    addMessage("user", text);
    input.value = "";

    fetch("/chat", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ message: text })
    })
    .then(res => res.json())
    .then(data => {
        typeMessage(data.reply);
    });
}

input.addEventListener("keydown", e => {
    if (e.key === "Enter") sendMessage();
});

function addMessage(type, text) {
    const msg = document.createElement("div");
    msg.className = "msg " + type;
    msg.innerText = text;

    chat.appendChild(msg);
    chat.scrollTop = chat.scrollHeight;
}

function typeMessage(text) {
    const msg = document.createElement("div");
    msg.className = "msg bot";
    chat.appendChild(msg);

    let i = 0;

    function typing() {
        if (i < text.length) {
            msg.innerHTML += text[i];
            i++;
            setTimeout(typing, 10);
        }
    }

    typing();
}
