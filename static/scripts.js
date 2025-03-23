let currentRole = "maverick";
let tokenSaved = false;

const chatWindow = document.getElementById("chat-window");
const userInput = document.getElementById("user-input");
const sendButton = document.getElementById("send-button");
const tokenSection = document.getElementById("token-section");
const tokenInput = document.getElementById("api-token");
const fileUpload = document.getElementById("file-upload");
const botAvatar = document.getElementById("bot-avatar");
const botName = document.getElementById("bot-name");

sendButton.addEventListener("click", () => sendMessage(userInput.value));
userInput.addEventListener("keypress", (e) => {
  if (e.key === "Enter") sendMessage(userInput.value);
});

fileUpload.addEventListener("change", async () => {
  if (!tokenSaved) {
    alert("Please enter your RealNex API token before uploading.");
    return;
  }
  const file = fileUpload.files[0];
  const formData = new FormData();
  formData.append("file", file);
  formData.append("token", tokenInput.value);
  const res = await fetch("/upload", {
    method: "POST",
    body: formData
  });
  const data = await res.json();
  appendMessage("goose", data.message || data.error);
  if (data.extracted_data) {
    appendMessage("goose", data.extracted_data);
  }
});

function saveToken() {
  tokenSaved = true;
  appendMessage("goose", "Token saved. You can now upload files.");
  tokenSection.classList.add("hidden");
}

function appendMessage(sender, text) {
  const msgDiv = document.createElement("div");
  msgDiv.className = sender === "user" ? "user-message" : "bot-message";
  msgDiv.innerText = text;
  chatWindow.appendChild(msgDiv);
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

async function sendMessage(message) {
  if (!message) return;
  appendMessage("user", message);
  userInput.value = "";
  const res = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, role: currentRole })
  });
  const data = await res.json();

  if (data.switch_to === "goose") {
    currentRole = "goose";
    botName.textContent = "Goose";
    botAvatar.src = "/static/goose.png";
    if (!tokenSaved) tokenSection.classList.remove("hidden");
  }

  if (data.response) {
    appendMessage("bot", data.response);
  }
}
