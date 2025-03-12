// File Upload
document.getElementById("upload-btn").onclick = async function() {
    let fileInput = document.getElementById("file-input");
    if (fileInput.files.length === 0) {
        alert("Please select a file to upload.");
        return;
    }

    let formData = new FormData();
    formData.append("file", fileInput.files[0]);

    let response = await fetch("/upload", { method: "POST", body: formData });
    let result = await response.json();
    alert(result.message || result.error);
};

// AI Chatbot
document.getElementById("send-btn").onclick = async function() {
    let messageInput = document.getElementById("user-message");
    let message = messageInput.value.trim();
    if (!message) return;

    // Append user message
    let chatBox = document.getElementById("chat-box");
    let userMessage = document.createElement("div");
    userMessage.classList.add("message", "user");
    userMessage.innerText = message;
    chatBox.appendChild(userMessage);

    // Send message to backend
    let response = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message })
    });

    let result = await response.json();

    // Append bot response
    let botMessage = document.createElement("div");
    botMessage.classList.add("message", "bot");
    botMessage.innerText = result.response || "Sorry, I didn't understand that.";
    chatBox.appendChild(botMessage);

    // Scroll to latest message
    chatBox.scrollTop = chatBox.scrollHeight;

    // Clear input field
    messageInput.value = "";
};
