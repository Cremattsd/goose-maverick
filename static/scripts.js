document.addEventListener("DOMContentLoaded", () => {
  let currentRole = "maverick";
  let savedToken = localStorage.getItem("realnexToken") || "";

  const chatWindow = document.getElementById("chat-window");
  const userInput = document.getElementById("user-input");
  const fileUpload = document.getElementById("file-upload");
  const toggleRoleButton = document.getElementById("toggle-role");
  const tokenBar = document.getElementById("token-bar");
  const apiTokenInput = document.getElementById("api-token");
  const botName = document.getElementById("bot-name");

  if (savedToken) apiTokenInput.value = savedToken;

  toggleRoleButton.addEventListener("click", () => {
    currentRole = currentRole === "maverick" ? "goose" : "maverick";
    botName.textContent = currentRole.charAt(0).toUpperCase() + currentRole.slice(1);
    toggleRoleButton.textContent = `Switch to ${currentRole === "maverick" ? "Goose" : "Maverick"}`;
    if (currentRole === "goose" && !savedToken) {
      tokenBar.classList.remove("hidden");
    } else {
      tokenBar.classList.add("hidden");
    }
  });

  window.storeToken = () => {
    const token = apiTokenInput.value.trim();
    if (token) {
      savedToken = token;
      localStorage.setItem("realnexToken", token);
      tokenBar.classList.add("hidden");
      addBotMessage("Token saved. Ready to import.");
    }
  };

  window.triggerUpload = () => {
    fileUpload.click();
  };

  window.sendMessage = () => {
    const message = userInput.value.trim();
    if (!message) return;

    addUserMessage(message);
    userInput.value = "";

    fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, role: currentRole })
    })
      .then(res => res.json())
      .then(data => {
        addBotMessage(data.response);
      })
      .catch(err => {
        addBotMessage("Something went wrong.");
        console.error(err);
      });
  };

  function addUserMessage(text) {
    const msg = document.createElement("div");
    msg.className = "message user-message";
    msg.innerHTML = `
      <img src="https://cdn-icons-png.flaticon.com/512/1144/1144760.png" alt="User" class="avatar" />
      <div class="bubble">${text}</div>
    `;
    chatWindow.appendChild(msg);
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }

  function addBotMessage(text) {
    const msg = document.createElement("div");
    msg.className = "message bot-message";
    const avatar = currentRole === "maverick" ? "maverick.JPG" : "goose.PNG";
    msg.innerHTML = `
      <img src="/static/${avatar}" alt="${currentRole}" class="avatar" />
      <div class="bubble">${text}</div>
    `;
    chatWindow.appendChild(msg);
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }
});
