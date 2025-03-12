document.getElementById("send-btn").onclick = async function() {
    let message = document.getElementById("user-message").value;
    let response = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message })
    });
    let result = await response.json();
    document.getElementById("chat-response").innerText = result.response || result.error;
};

document.getElementById("upload-btn").onclick = async function() {
    let fileInput = document.getElementById("file-input");
    let formData = new FormData();
    formData.append("file", fileInput.files[0]);

    let response = await fetch("/upload", { method: "POST", body: formData });
    let result = await response.json();
    document.getElementById("upload-status").innerText = result.message || result.error;
};

document.getElementById("submit-token").onclick = async function() {
    let token = document.getElementById("token").value;
    let response = await fetch("/submit_token", {
        method: "POST",
        body: new URLSearchParams({ token: token }),
        headers: { "Content-Type": "application/x-www-form-urlencoded" }
    });

    let result = await response.json();
    alert(result.message || result.error);
};
