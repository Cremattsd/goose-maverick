// frontend-full.js — Full Chat + Dashboard Launcher + Goose File Handler

document.addEventListener('DOMContentLoaded', () => {
  const container = document.createElement('div');
  container.id = 'chat-widget';
  container.style = 'position:fixed; bottom:20px; right:20px; background:white; width:320px; box-shadow:0 2px 8px rgba(0,0,0,0.1); border-radius:12px; padding:12px; z-index:9999; font-family:sans-serif; resize:both; overflow:auto;';

  container.innerHTML = `
    <strong>Maverick:</strong> <span id="welcome-text">Hi! I’m Maverick, your chat assistant. Ask me anything about RealNex, RealBlasts, Featured Property Email Marketing, Training, Webinars, and more! 😊</span><br><br>
    <input type="text" id="chat-input" placeholder="Ask Maverick..." style="width:100%; padding:6px; border-radius:6px;">
    <button id="send-btn" style="width:100%; margin-top:8px; padding:6px 0; background:#6366f1; color:white; border:none; border-radius:6px;">Send</button>
    <div id="response-box" style="margin-top:10px; max-height:200px; overflow-y:auto;"></div>
    <hr style="margin:16px 0">
    <label for="file-upload">📎 Drop file here or <strong>click</strong> to upload</label>
    <input type="file" id="file-upload" accept="image/*,.pdf" style="display:none;">
    <div id="upload-status" style="font-size:0.9em; color:#555; margin-top:8px;"></div>
  `;

  document.body.appendChild(container);

  const input = document.getElementById('chat-input');
  const button = document.getElementById('send-btn');
  const responseBox = document.getElementById('response-box');
  const fileInput = document.getElementById('file-upload');
  const status = document.getElementById('upload-status');

  button.onclick = async () => {
    const message = input.value.trim();
    if (!message) return;
    input.value = '';

    const res = await fetch('/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message })
    });
    const data = await res.json();

    const bubble = document.createElement('div');
    bubble.innerHTML = `<strong>Maverick:</strong> ${data.message || data.error}`;
    responseBox.appendChild(bubble);
    responseBox.scrollTop = responseBox.scrollHeight;

    if (data.action === 'show_dashboard') {
      window.open('/static/dashboard/index.html', '_blank');
    }
  };

  container.addEventListener('dragover', (e) => {
    e.preventDefault();
    container.style.background = '#eef';
  });
  container.addEventListener('dragleave', () => {
    container.style.background = 'white';
  });
  container.addEventListener('drop', (e) => {
    e.preventDefault();
    container.style.background = 'white';
    const file = e.dataTransfer.files[0];
    if (file) handleFileUpload(file);
  });

  fileInput.onchange = () => {
    const file = fileInput.files[0];
    if (file) handleFileUpload(file);
  };

  function handleFileUpload(file) {
    const formData = new FormData();
    formData.append('file', file);
    status.textContent = 'Uploading...';

    fetch('/upload', {
      method: 'POST',
      body: formData
    })
      .then(res => res.json())
      .then(data => {
        status.innerHTML = `<strong>Goose:</strong> ${data.message}<br><em>${data.ocrText || ''}</em>`;
      })
      .catch(err => {
        status.textContent = 'Upload failed: ' + err.message;
      });
  }
});
