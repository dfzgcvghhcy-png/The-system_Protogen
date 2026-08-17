const messages=document.getElementById("messages");
async function sendMessage(){
 const input=document.getElementById("input"),text=input.value.trim();if(!text)return;
 const add=(t,c)=>{const d=document.createElement("div");d.className="message "+c;d.innerText=t;messages.appendChild(d);messages.scrollTop=messages.scrollHeight;};
 add(text,"user");input.value="";
 try{const r=await fetch("/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message:text})});const d=await r.json();add(d.response,"bot");}
 catch(e){add("Не удалось связаться с системой 🤖","bot");}
}
document.getElementById("input")?.addEventListener("keydown",e=>{if(e.key==="Enter")sendMessage()});