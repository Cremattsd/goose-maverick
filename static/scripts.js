document.getElementById("submit-token").onclick = async function() {
    let token = document.getElementById("token").value;
    let response = await fetch("/set_token", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: "token=" + encodeURIComponent(token)
    });

    let result = await response.json();
    alert(result.success || result.error);
};

document.getElementById("send-message").onclick = async function() {
    let message = document.getElementById("user-message").value;
    let response = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message })
    });

    let result = await response.json();
    document.getElementById("chat-response").innerText = result.response || result.error;
};
