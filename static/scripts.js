document.getElementById("send-btn").onclick = async function() {
    let message = document.getElementById("user-message").value;

    if (!message) {
        alert("Please enter a question!");
        return;
    }

    let responseBox = document.getElementById("chat-response");
    responseBox.style.display = "block";
    responseBox.innerHTML = "<strong>Loading...</strong>";

    let response = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message })
    });

    let result = await response.json();
    responseBox.innerHTML = result.response || `<span class="text-danger">${result.error}</span>`;
};
