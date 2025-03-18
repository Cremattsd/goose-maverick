async function sendMessage() {
    const input = document.getElementById("chatInput");
    const messages = document.getElementById("chatMessages");
    const userMessage = input.value;
    input.value = "";

    messages.innerHTML += `<div class="user-message">You: ${userMessage}</div>`;

    const response = await fetch("/chat", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({message: userMessage})
    });
    const data = await response.json();
    messages.innerHTML += `<div class="bot-message">Bot: ${data.response}</div>`;
}

async function uploadFile() {
    const file = document.getElementById("fileInput").files[0];
    const token = document.getElementById("tokenInput").value;

    if (!file) {
        alert("Please select a file first.");
        return;
    }
    if (!token) {
        alert("Please provide your RealNex token.");
        return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("token", token);

    const response = await fetch("/upload", {
        method: "POST",
        body: formData
    });
    const result = await response.json();

    if (result.status === "success") {
        alert("Uploaded successfully to RealNex!");
    } else {
        alert("Upload failed: " + result.error);
    }
}
