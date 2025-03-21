<!-- This is the full frontend HTML for the Maverick & Goose chatbot with polished UI and working business card/photo upload -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Maverick & Goose</title>
  <link rel="stylesheet" href="/static/styles.css" />
</head>
<body>
  <div class="chatbox">
    <div class="chat-header">
      <img id="avatar" src="/static/maverick-avatar.png" alt="Avatar" />
      <div>
        <div id="chat-name">Chat with Maverick</div>
        <div id="status">We’re online</div>
      </div>
      <button id="switch-bot">Switch to Goose</button>
    </div>

    <div class="messages" id="messages"></div>

    <div class="input-area">
      <div class="attachment">
        <button onclick="triggerAttachment()">📎</button>
        <input type="file" id="file-input" accept="image/*,application/pdf" style="display:none" onchange="uploadBusinessCard(event)" />
      </div>
      <input type="text" id="message-input" placeholder="Type your message..." />
      <button id="send-btn">Send</button>
    </div>
  </div>

  <script>
    let role = "maverick"; // default

    const avatar = document.getElementById("avatar");
    const chatName = document.getElementById("chat-name");
    const status = document.getElementById("status");
    const messagesDiv = document.getElementById("messages");
    const messageInput = document.getElementById("message-input");
    const sendBtn = document.getElementById("send-btn");
    const switchBtn = document.getElementById("switch-bot");

    switchBtn.addEventListener("click", () => {
      if (role === "maverick") {
        role = "goose";
        avatar.src = "/static/goose-avatar.png";
        chatName.textContent = "Chat with Goose";
        status.textContent = "Ready to process your data.";
        switchBtn.textContent = "Switch to Maverick";
      } else {
        role = "maverick";
        avatar.src = "/static/maverick-avatar.png";
        chatName.textContent = "Chat with Maverick";
        status.textContent = "We’re online";
        switchBtn.textContent = "Switch to Goose";
      }
    });

    sendBtn.addEventListener("click", sendMessage);
    messageInput.addEventListener("keypress", (e) => {
      if (e.key === "Enter") sendMessage();
    });

    async function sendMessage() {
      const message = messageInput.value.trim();
      if (!message) return;

      appendMessage("user", message);
      messageInput.value = "";

      const res = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, role })
      });

      const data = await res.json();
      appendMessage("ai", data.response);
    }

    function appendMessage(sender, text) {
      const msg = document.createElement("div");
      msg.className = `message ${sender}-message`;
      msg.innerHTML = text;
      messagesDiv.appendChild(msg);
      messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    function triggerAttachment() {
      document.getElementById("file-input").click();
    }

    async function uploadBusinessCard(event) {
      const file = event.target.files[0];
      if (!file) return;

      const formData = new FormData();
      formData.append("file", file);

      appendMessage("user", `Uploading business card: <strong>${file.name}</strong>...`);

      const response = await fetch("/upload", {
        method: "POST",
        body: formData
      });

      const data = await response.json();
      if (data.extracted_data) {
        appendMessage("ai", data.extracted_data);
      } else {
        appendMessage("ai", "Sorry, I couldn’t process that file.");
      }
    }
  </script>
</body>
</html>
