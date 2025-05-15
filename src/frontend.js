let mode = 'maverick'; 2
let token = localStorage.getItem('realNexApiKey') || '';
let currentFile = null;
let hasPromptedForRealNex = localStorage.getItem('hasPromptedForRealNex') || false;
let declinedRealNexPrompt = localStorage.getItem('declinedRealNexPrompt') || false;
let isSending = false;

function initChatWidget() {
  const chatWidget = document.createElement('div');
  chatWidget.className = 'chat-widget';
  chatWidget.innerHTML = `
    <div class="chat-header">
      <div class="flex items-center">
        <img id="mode-icon" src="/maverick-icon.png" alt="Maverick Icon">
        <span id="chat-title">RealNex, Real Blasts, Webinars, or more — ask away! 🤖</span>
      </div>
      <div class="flex space-x-2">
        <button id="switch-mode" class="switch-button" onclick="toggleMode()">Switch to Goose</button>
        <button id="clear-key" class="clear-key-button" onclick="clearStoredKey()" style="display: none;">Clear Key</button>
      </div>
    </div>
    <div class="chat-body" id="chat-body">
      <div id="welcome-message" class="chat-message bg-purple-100">
        RealNex, RealNex Webinars, Real Blasts, or more — ask away!
      </div>
    </div>
    <div class="chat-input">
      <input type="text" id="chat-message" placeholder="Type your message..." onkeypress="if(event.key === 'Enter') sendMessage()">
      <button id="send-button" onclick="sendMessage()">Send</button>
    </div>
  `;
  document.body.appendChild(chatWidget);

  const clearKeyButton = document.getElementById('clear-key');
  if (token && mode === 'goose') clearKeyButton.style.display = 'block';
  else clearKeyButton.style.display = 'none';

  if (!hasPromptedForRealNex && !declinedRealNexPrompt) {
    setTimeout(() => {
      const chatBody = document.getElementById('chat-body');
      const promptMessage = document.createElement('div');
      promptMessage.className = 'chat-message bg-purple-100';
      promptMessage.innerHTML = `
        Do you want this to live inside RealNex? <br>
        <button onclick="handleRealNexPrompt('yes')">Yes</button>
        <button onclick="handleRealNexPrompt('no')">No</button>`;
      chatBody.appendChild(promptMessage);
      chatBody.scrollTop = chatBody.scrollHeight;
    }, 2000);
  }
}

document.addEventListener('DOMContentLoaded', initChatWidget);

// All other chat logic remains unchanged (sendMessage, toggleMode, handleFile, etc.)
// This update only adjusts the intro message and welcome flow
