document.getElementById("send-btn").onclick = async function() {
    let message = document.getElementById("user-message").value;
    if (!message) return;

    let chatBox = document.getElementById("chat-box");
    let userMessage = document.createElement("p");
    userMessage.className = "user-message";
    userMessage.innerText = message;
    chatBox.appendChild(userMessage);

    let response = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message })
    });

    let result = await response.json();
    let botMessage = document.createElement("p");
    botMessage.className = "bot-message";
    botMessage.innerText = result.response || "Error processing request.";
    chatBox.appendChild(botMessage);

    // If bot asks for an API Token
    if (result.response.includes("please provide your RealNex API token")) {
        let token = prompt("Enter your RealNex API Token:");
        if (token) {
            await fetch("/set_token", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ token: token })
            });
            alert("Token saved! You can now use all features.");
        }
    }
};
