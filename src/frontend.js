let mode = 'maverick'; // 'maverick' or 'goose'
let token = localStorage.getItem('realNexApiKey') || ''; // Load token from localStorage
let currentFile = null; // Store the current file being processed
let hasPromptedForRealNex = localStorage.getItem('hasPromptedForRealNex') || false; // Track if prompt has been shown
let declinedRealNexPrompt = localStorage.getItem('declinedRealNexPrompt') || false; // Track if user declined the prompt
let isSending = false; // Track if a message is being sent

// Initialize the chat widget
function initChatWidget() {
  const chatWidget = document.createElement('div');
  chatWidget.className = 'chat-widget';
  chatWidget.innerHTML = `
    <div class="chat-header">
      <div class="flex items-center">
        <img id="mode-icon" src="/maverick-icon.png" alt="Maverick Icon" onerror="this.style.display='none'; document.getElementById('maverick-svg').style.display='block';">
        <svg id="maverick-svg" style="display: none;" viewBox="0 0 24 24" fill="white">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8z"/>
        </svg>
        <span id="chat-title">Hey there! Chat with Maverick! 🚀</span>
      </div>
      <div class="flex space-x-2">
        <button id="switch-mode" class="switch-button" onclick="toggleMode()">Switch to Goose</button>
        <button id="clear-key" class="clear-key-button" onclick="clearStoredKey()" style="display: none;">Clear Key</button>
      </div>
    </div>
    <div class="chat-body" id="chat-body">
      <div id="welcome-message" class="chat-message bg-purple-100">
        I’m Maverick, your sidekick—how can I help you? You can ask me anything about RealNex, Pix-Virtual. I can also import data and more. 😊
      </div>
    </div>
    <div class="chat-input">
      <input type="text" id="chat-message" placeholder="Type your message..." onkeypress="if(event.key === 'Enter') sendMessage()">
      <button id="send-button" onclick="sendMessage()">Send</button>
    </div>
  `;
  document.body.appendChild(chatWidget);

  // Show/hide Clear Key button based on token presence
  const clearKeyButton = document.getElementById('clear-key');
  if (token && mode === 'goose') {
    clearKeyButton.style.display = 'block';
  } else {
    clearKeyButton.style.display = 'none';
  }

  // Show RealNex prompt if not already shown and not declined
  if (!hasPromptedForRealNex && !declinedRealNexPrompt) {
    setTimeout(() => {
      const chatBody = document.getElementById('chat-body');
      const promptMessage = document.createElement('div');
      promptMessage.className = 'chat-message bg-purple-100';
      promptMessage.innerHTML = `
        Do you want this to live inside RealNex? <br>
        <button onclick="handleRealNexPrompt('yes')" style="background: #14b8a6; color: white; padding: 6px 12px; border-radius: 8px; margin: 4px;">Yes</button>
        <button onclick="handleRealNexPrompt('no')" style="background: #ef4444; color: white; padding: 6px 12px; border-radius: 8px; margin: 4px;">No</button>
      `;
      chatBody.appendChild(promptMessage);
      chatBody.scrollTop = chatBody.scrollHeight;
    }, 2000); // Show after 2 seconds
  }
}

// Call initChatWidget when the script loads
document.addEventListener('DOMContentLoaded', initChatWidget);

function handleRealNexPrompt(response) {
  const chatBody = document.getElementById('chat-body');
  hasPromptedForRealNex = true;
  localStorage.setItem('hasPromptedForRealNex', true); // Mark prompt as shown

  if (response === 'yes') {
    const yesMessage = document.createElement('div');
    yesMessage.className = 'chat-message bg-teal-100';
    yesMessage.innerHTML = 'Great! You can download the Chrome extension to use this inside RealNex. <a href="#" target="_blank" style="color: white; text-decoration: underline;">Download here (coming soon)</a>';
    chatBody.appendChild(yesMessage);
  } else {
    const noMessage = document.createElement('div');
    noMessage.className = 'chat-message bg-teal-100';
    noMessage.innerText = 'No problem! You can keep using the web version right here. 😊';
    chatBody.appendChild(noMessage);
    declinedRealNexPrompt = true;
    localStorage.setItem('declinedRealNexPrompt', true); // Persist the "No" choice
  }
  chatBody.scrollTop = chatBody.scrollHeight;
}

function toggleMode() {
  const switchButton = document.getElementById('switch-mode');
  const chatTitle = document.getElementById('chat-title');
  const modeIcon = document.getElementById('mode-icon');
  const maverickSvg = document.getElementById('maverick-svg');
  const clearKeyButton = document.getElementById('clear-key');
  if (mode === 'maverick') {
    mode = 'goose';
    chatTitle.innerText = 'Let’s Scan with Goose! 📸';
    switchButton.innerText = 'Switch to Maverick';
    modeIcon.src = '/goose-icon.png';
    modeIcon.alt = 'Goose Icon';
    modeIcon.onerror = () => {
      modeIcon.style.display = 'none';
      const gooseSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      gooseSvg.setAttribute("viewBox", "0 0 24 24");
      gooseSvg.setAttribute("fill", "white");
      gooseSvg.innerHTML = '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8z"/>';
      gooseSvg.classList.add('w-6', 'h-6', 'mr-2');
      modeIcon.parentNode.insertBefore(gooseSvg, modeIcon);
    };
    maverickSvg.style.display = 'none';
    if (token) {
      setupDragDropArea();
      clearKeyButton.style.display = 'block';
    } else {
      document.getElementById('chat-body').innerHTML = `
        <div class="dynamic-form">
          <input type="text" id="token-input" placeholder="Enter your RealNex Bearer Token">
          <button onclick="validateToken()">Validate Token</button>
        </div>`;
      clearKeyButton.style.display = 'none';
    }
  } else {
    mode = 'maverick';
    chatTitle.innerText = 'Hey there! Chat with Maverick! 🚀';
    switchButton.innerText = 'Switch to Goose';
    modeIcon.src = '/maverick-icon.png';
    modeIcon.alt = 'Maverick Icon';
    modeIcon.onerror = () => {
      modeIcon.style.display = 'none';
      maverickSvg.style.display = 'block';
    };
    if (document.querySelector('svg:not(#maverick-svg)')) {
      document.querySelector('svg:not(#maverick-svg)').remove();
    }
    document.getElementById('chat-body').innerHTML = `
      <div id="welcome-message" class="chat-message bg-purple-100">
        I’m Maverick, your sidekick—how can I help you? You can ask me anything about RealNex, Pix-Virtual. I can also import data and more. 😊
      </div>`;
    clearKeyButton.style.display = 'none';

    // Show RealNex prompt again if user switches back to Maverick mode, hasn't been prompted, and hasn't declined
    if (!hasPromptedForRealNex && !declinedRealNexPrompt) {
      setTimeout(() => {
        const chatBody = document.getElementById('chat-body');
        const promptMessage = document.createElement('div');
        promptMessage.className = 'chat-message bg-purple-100';
        promptMessage.innerHTML = `
          Do you want this to live inside RealNex? <br>
          <button onclick="handleRealNexPrompt('yes')" style="background: #14b8a6; color: white; padding: 6px 12px; border-radius: 8px; margin: 4px;">Yes</button>
          <button onclick="handleRealNexPrompt('no')" style="background: #ef4444; color: white; padding: 6px 12px; border-radius: 8px; margin: 4px;">No</button>
        `;
        chatBody.appendChild(promptMessage);
        chatBody.scrollTop = chatBody.scrollHeight;
      }, 2000);
    }
  }
}

function clearStoredKey() {
  localStorage.removeItem('realNexApiKey');
  token = '';
  const chatBody = document.getElementById('chat-body');
  const clearKeyButton = document.getElementById('clear-key');
  if (mode === 'goose') {
    chatBody.innerHTML = `
      <div class="dynamic-form">
        <input type="text" id="token-input" placeholder="Enter your RealNex Bearer Token">
        <button onclick="validateToken()">Validate Token</button>
      </div>`;
    clearKeyButton.style.display = 'none';
  }
}

function setupDragDropArea() {
  document.getElementById('chat-body').innerHTML = `
    <div class="drag-drop-area" id="drag-drop-area">
      Drop a photo, PDF, or Excel file here to scan or import—super easy! 🎉
      <div class="icon-container">
        <div class="icon-label">
          <img src="/attachment-icon.png" alt="Attachment Icon" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
          <svg style="display: none;" viewBox="0 0 24 24" fill="#8b5cf6">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2l5 5h-5V4zM6 20V4h6v6h6v10H6z"/>
          </svg>
          Attachment
        </div>
        <div class="icon-label">
          <img src="/business-card-icon.png" alt="Business Card Icon" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
          <svg style="display: none;" viewBox="0 0 24 24" fill="#8b5cf6">
            <path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 14H4V6h16v12zM6 8h12v2H6V8zm0 4h12v2H6v-2z"/>
          </svg>
          Business Card
        </div>
        <div class="icon-label">
          <img src="/photo-ocr-icon.png" alt="Photo OCR Icon" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
          <svg style="display: none;" viewBox="0 0 24 24" fill="#8b5cf6">
            <path d="M21 7h-6V5c-1.1-.9-2-2-2H9c-1.1 0-2 .9-2 2v2H3c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V9c0-1.1-.9-2-2-2zM9 5h4v2H9V5zm11 14H4V9h16v10z"/>
          </svg>
          Photo OCR
        </div>
      </div>
      <input type="file" id="chat-file" accept="image/*,.pdf,.xlsx" style="display: none;">
    </div>`;
  setupDragDrop();
}

function setupDragDrop() {
  const dragDropArea = document.getElementById('drag-drop-area');
  const fileInput = document.getElementById('chat-file');

  dragDropArea.addEventListener('click', () => fileInput.click());
  dragDropArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    dragDropArea.classList.add('dragover');
  });
  dragDropArea.addEventListener('dragleave', () => dragDropArea.classList.remove('dragover'));
  dragDropArea.addEventListener('drop', (e) => {
    e.preventDefault();
    dragDropArea.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    handleFile(file);
  });
  fileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    handleFile(file);
  });
}

async function handleFile(file) {
  const chatBody = document.getElementById('chat-body');
  if (!file) return;

  currentFile = file;

  if (mode === 'maverick') {
    const message = document.createElement('div');
    message.className = 'chat-message';
    message.innerText = 'Oops! Files are only supported in Goose mode—switch over to scan or import! 😄';
    chatBody.appendChild(message);
    return;
  }

  if (!token) {
    const tokenForm = document.createElement('div');
    tokenForm.className = 'dynamic-form';
    tokenForm.innerHTML = `
      <input type="text" id="token-input" placeholder="Enter your RealNex Bearer Token">
      <button onclick="validateToken()">Validate Token</button>
    `;
    chatBody.appendChild(tokenForm);
    return;
  }

  if (file.name.endsWith('.xlsx')) {
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch('/suggest-mapping', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      if (data.suggestedMapping) {
        const mappingForm = document.createElement('div');
        mappingForm.className = 'dynamic-form';
        mappingForm.innerHTML = `
          <textarea id="mapping-input" rows="4">${JSON.stringify(data.suggestedMapping, null, 2)}</textarea>
          <button onclick="bulkImport()">Import Excel—Let’s Go! 🚀</button>
        `;
        chatBody.appendChild(mappingForm);
      } else {
        throw new Error(data.error || 'Failed to suggest mapping');
      }
    } catch (e) {
      const errorMessage = document.createElement('div');
      errorMessage.className = 'chat-message bg-red-100';
      errorMessage.innerText = 'Uh-oh! Couldn’t suggest mapping: ' + e.message;
      chatBody.appendChild(errorMessage);
    }
  } else {
    const scanForm = document.createElement('div');
    scanForm.className = 'dynamic-form';
    scanForm.innerHTML = `
      <textarea id="notes-input" rows="4" placeholder="Add some notes about this contact!"></textarea>
      <button onclick="upload()">Scan & Import—Awesome! 🎉</button>
    `;
    chatBody.appendChild(scanForm);
  }
  chatBody.scrollTop = chatBody.scrollHeight;
}

async function validateToken() {
  const tokenInput = document.getElementById('token-input');
  const tokenValue = tokenInput.value.trim();
  const chatBody = document.getElementById('chat-body');
  const clearKeyButton = document.getElementById('clear-key');

  try {
    const res = await fetch('/validate-token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: tokenValue })
    });
    const data = await res.json();
    if (data.valid) {
      token = tokenValue;
      localStorage.setItem('realNexApiKey', tokenValue); // Store the token in localStorage
      const tokenMessage = document.createElement('div');
      tokenMessage.className = 'chat-message bg-teal-100';
      tokenMessage.innerText = 'Woohoo! Token validated—ready to roll! 🎈';
      chatBody.innerHTML = `
        <div class="drag-drop-area" id="drag-drop-area">
          Drop a photo, PDF, or Excel file here to scan or import—super easy! 🎉
          <div class="icon-container">
            <div class="icon-label">
              <img src="/attachment-icon.png" alt="Attachment Icon" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
              <svg style="display: none;" viewBox="0 0 24 24" fill="#8b5cf6">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2l5 5h-5V4zM6 20V4h6v6h6v10H6z"/>
              </svg>
              Attachment
            </div>
            <div class="icon-label">
              <img src="/business-card-icon.png" alt="Business Card Icon" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
              <svg style="display: none;" viewBox="0 0 24 24" fill="#8b5cf6">
                <path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 14H4V6h16v12zM6 8h12v2H6V8zm0 4h12v2H6v-2z"/>
              </svg>
              Business Card
            </div>
            <div class="icon-label">
              <img src="/photo-ocr-icon.png" alt="Photo OCR Icon" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
              <svg style="display: none;" viewBox="0 0 24 24" fill="#8b5cf6">
                <path d="M21 7h-6V5c-1.1-.9-2-2-2H9c-1.1 0-2 .9-2 2v2H3c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V9c0-1.1-.9-2-2-2zM9 5h4v2H9V5zm11 14H4V9h16v10z"/>
              </svg>
              Photo OCR
            </div>
          </div>
          <input type="file" id="chat-file" accept="image/*,.pdf,.xlsx" style="display: none;">
        </div>`;
      chatBody.appendChild(tokenMessage);
      setupDragDrop();
      clearKeyButton.style.display = 'block';
    } else {
      const errorMessage = document.createElement('div');
      errorMessage.className = 'chat-message bg-red-100';
      errorMessage.innerText = 'Oh no! Invalid token: ' + (data.error || 'Unknown error');
      chatBody.appendChild(errorMessage);
    }
  } catch (e) {
    const errorMessage = document.createElement('div');
    errorMessage.className = 'chat-message bg-red-100';
    errorMessage.innerText = 'Yikes! Error validating token: ' + e.message;
    chatBody.appendChild(errorMessage);
  }
  chatBody.scrollTop = chatBody.scrollHeight;
}

async function sendMessage() {
  if (isSending) return; // Prevent multiple sends

  const messageInput = document.getElementById('chat-message');
  const sendButton = document.getElementById('send-button');
  const message = messageInput.value.trim();
  const chatBody = document.getElementById('chat-body');
  if (!message) return;

  // Disable button and show loading state
  isSending = true;
  sendButton.disabled = true;
  sendButton.innerText = 'Sending...';

  if (mode === 'maverick') {
    // Display user message
    const userMessage = document.createElement('div');
    userMessage.className = 'chat-message';
    userMessage.innerText = message;
    chatBody.appendChild(userMessage);

    try {
      const res = await fetch('/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message })
      });
      const data = await res.json();
      const botMessage = document.createElement('div');
      botMessage.className = 'chat-message bg-purple-100';
      botMessage.innerText = data.answer || JSON.stringify(data.error);
      chatBody.appendChild(botMessage);
    } catch (e) {
      const errorMessage = document.createElement('div');
      errorMessage.className = 'chat-message bg-red-100';
      errorMessage.innerText = 'Oops! Something went wrong: ' + e.message;
      chatBody.appendChild(errorMessage);
    }
  } else {
    // In Goose mode, prompt for token if not set
    if (!token) {
      const tokenForm = document.createElement('div');
      tokenForm.className = 'dynamic-form';
      tokenForm.innerHTML = `
        <input type="text" id="token-input" value="${message}" placeholder="Enter your RealNex Bearer Token">
        <button onclick="validateToken()">Validate Token</button>
      `;
      chatBody.appendChild(tokenForm);
    }
  }

  // Reset button state
  isSending = false;
  sendButton.disabled = false;
  sendButton.innerText = 'Send';

  messageInput.value = '';
  chatBody.scrollTop = chatBody.scrollHeight;
}

async function upload() {
  const file = currentFile;
  const notes = document.getElementById('notes-input').value;
  const chatBody = document.getElementById('chat-body');
  const formData = new FormData();
  formData.append('file', file);
  formData.append('token', token);
  formData.append('notes', notes);
  try {
    const res = await fetch('/upload-business-card', {
      method: 'POST',
      body: formData
    });
    const data = await res.json();
    const resultMessage = document.createElement('div');
    resultMessage.className = 'chat-message bg-teal-100';
    resultMessage.innerText = 'Yes! Scan successful: ' + (data.followUpEmail || JSON.stringify(data.error));
    chatBody.innerHTML = `
      <div class="drag-drop-area" id="drag-drop-area">
        Drop a photo, PDF, or Excel file here to scan or import—super easy! 🎉
        <div class="icon-container">
          <div class="icon-label">
            <img src="/attachment-icon.png" alt="Attachment Icon" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
            <svg style="display: none;" viewBox="0 0 24 24" fill="#8b5cf6">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2l5 5h-5V4zM6 20V4h6v6h6v10H6z"/>
            </svg>
            Attachment
          </div>
          <div class="icon-label">
            <img src="/business-card-icon.png" alt="Business Card Icon" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
            <svg style="display: none;" viewBox="0 0 24 24" fill="#8b5cf6">
              <path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 14H4V6h16v12zM6 8h12v2H6V8zm0 4h12v2H6v-2z"/>
            </svg>
            Business Card
          </div>
          <div class="icon-label">
            <img src="/photo-ocr-icon.png" alt="Photo OCR Icon" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
            <svg style="display: none;" viewBox="0 0 24 24" fill="#8b5cf6">
              <path d="M21 7h-6V5c-1.1-.9-2-2-2H9c-1.1 0-2 .9-2 2v2H3c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V9c0-1.1-.9-2-2-2zM9 5h4v2H9V5zm11 14H4V9h16v10z"/>
            </svg>
            Photo OCR
          </div>
        </div>
        <input type="file" id="chat-file" accept="image/*,.pdf,.xlsx" style="display: none;">
      </div>`;
    chatBody.appendChild(resultMessage);
    setupDragDrop();
  } catch (e) {
    const errorMessage = document.createElement('div');
    errorMessage.className = 'chat-message bg-red-100';
    errorMessage.innerText = 'Oh snap! Error: ' + e.message;
    chatBody.appendChild(errorMessage);
  }
  chatBody.scrollTop = chatBody.scrollHeight;
}

async function bulkImport() {
  const file = currentFile;
  const mapping = document.getElementById('mapping-input').value;
  const chatBody = document.getElementById('chat-body');
  const formData = new FormData();
  formData.append('file', file);
  formData.append('token', token);
  formData.append('mapping', mapping);
  try {
    const res = await fetch('/bulk-import', {
      method: 'POST',
      body: formData
    });
    const data = await res.json();
    const resultMessage = document.createElement('div');
    resultMessage.className = 'chat-message bg-teal-100';
    resultMessage.innerText = `Boom! Imported ${data.processed || 0} records—nice work! 🎉`;
    chatBody.innerHTML = `
      <div class="drag-drop-area" id="drag-drop-area">
        Drop a photo, PDF, or Excel file here to scan or import—super easy! 🎉
        <div class="icon-container">
          <div class="icon-label">
            <img src="/attachment-icon.png" alt="Attachment Icon" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
            <svg style="display: none;" viewBox="0 0 24 24" fill="#8b5cf6">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2l5 5h-5V4zM6 20V4h6v6h6v10H6z"/>
            </svg>
            Attachment
          </div>
          <div class="icon-label">
            <img src="/business-card-icon.png" alt="Business Card Icon" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
            <svg style="display: none;" viewBox="0 0 24 24" fill="#8b5cf6">
              <path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 14H4V6h16v12zM6 8h12v2H6V8zm0 4h12v2H6v-2z"/>
            </svg>
            Business Card
          </div>
          <div class="icon-label">
            <img src="/photo-ocr-icon.png" alt="Photo OCR Icon" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
            <svg style="display: none;" viewBox="0 0 24 24" fill="#8b5cf6">
              <path d="M21 7h-6V5c-1.1-.9-2-2-2H9c-1.1 0-2 .9-2 2v2H3c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V9c0-1.1-.9-2-2-2zM9 5h4v2H9V5zm11 14H4V9h16v10z"/>
            </svg>
            Photo OCR
          </div>
        </div>
        <input type="file" id="chat-file" accept="image/*,.pdf,.xlsx" style="display: none;">
      </div>`;
    chatBody.appendChild(resultMessage);
    setupDragDrop();
  } catch (e) {
    const errorMessage = document.createElement('div');
    errorMessage.className = 'chat-message bg-red-100';
    errorMessage.innerText = 'Whoops! Error: ' + e.message;
    chatBody.appendChild(errorMessage);
  }
  chatBody.scrollTop = chatBody.scrollHeight;
}
