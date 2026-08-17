const input=document.getElementById("input");
const button=document.getElementById("sendBtn");
const messages=document.getElementById("messages");

function addMessage(text, cls="user-message"){
    const item=document.createElement("div");
    item.className=`message ${cls}`;
    item.textContent=text;
    messages.appendChild(item);
    messages.scrollTop=messages.scrollHeight;
}

async function sendMessage(){
    const text=input.value.trim();
    if(!text)return;
    addMessage(text,"user-message");
    input.value="";
    button.disabled=true;
    try{
        const response=await fetch("/chat",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({message:text})
        });
        const data=await response.json();
        addMessage(data.response || "Система не дала ответа 🤖","bot-message");
    }catch(e){
        addMessage("Не удалось связаться с системой. Проверь, запущен ли сервер.","bot-message");
    }finally{
        button.disabled=false;
        input.focus();
    }
}

button.addEventListener("click",sendMessage);
input.addEventListener("keydown",e=>{if(e.key==="Enter")sendMessage()});
