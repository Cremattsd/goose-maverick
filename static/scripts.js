// ✅ Save API Key to Server
function saveApiKey() {
    const apiKey = document.getElementById("api-key").value;

    if (!apiKey) {
        alert("Please enter an API key.");
        return;
    }

    fetch("/set_api_key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey })
    })
    .then(response => response.json())
    .then(data => alert(data.message))
    .catch(error => console.error("Error:", error));
}

// ✅ Send User Message to AI
function sendMessage() {
    const message = document.getElementById("user-message").value;

    if (!message) {
        alert("Please enter a message.");
        return;
    }

    fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message })
    })
    .then(response => response.json())
    .then(data => {
        document.getElementById("chat-response").innerText = data.response;
    })
    .catch(error => console.error("Error:", error));
}
