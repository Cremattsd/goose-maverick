// === app.py: Now supports dashboard phrase detection ===

from flask import Flask, request, jsonify, send_from_directory, send_file
from datetime import datetime, timedelta
import random, os, json

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
ERROR_LOG = 'errors.log'
METRIC_LOG = 'dashboard_metrics.json'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DASHBOARD_PHRASES = [
    "show me the dashboard", "open the dashboard", "dashboard please",
    "launch dashboard", "give me an update", "open goose dashboard",
    "pull my metrics", "sync update", "how are my stats", "check my data"
]

@app.route('/dashboard/stats')
def dashboard_stats():
    ...  # (same as before)

@app.route('/dashboard/errors')
def dashboard_errors():
    ...  # (same as before)

@app.route('/dashboard/download')
def dashboard_download():
    ...  # (same as before)

@app.route('/ask', methods=['POST'])
def ask():
    try:
        user_message = request.json.get("message", "").lower()
        if any(phrase in user_message for phrase in DASHBOARD_PHRASES):
            return jsonify({
                "action": "show_dashboard",
                "message": "Pulling up your Goose Sync Dashboard now 📊"
            })
        # fallback if not a dashboard request
        return jsonify({
            "message": "Hi! I’m Maverick. Ask me anything about RealNex, RealBlasts, or sync activity."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

...  # (rest of app.py remains unchanged)


// === frontend.js: Now auto-triggers dashboard from chat + draggable widget ===

function initChatWidget() {
  const chatWidget = document.createElement('div');
  chatWidget.id = 'chat-widget';
  chatWidget.className = 'chat-widget';
  chatWidget.style.position = 'fixed';
  chatWidget.style.bottom = '20px';
  chatWidget.style.right = '20px';
  chatWidget.style.zIndex = '9999';
  chatWidget.style.background = 'white';
  chatWidget.style.border = '1px solid #ccc';
  chatWidget.style.boxShadow = '0 4px 8px rgba(0,0,0,0.2)';
  chatWidget.style.padding = '10px';
  chatWidget.style.borderRadius = '12px';
  chatWidget.style.width = '300px';
  chatWidget.style.resize = 'both';
  chatWidget.style.overflow = 'auto';
  chatWidget.innerHTML = `
    <div id="chat-body">
      <div><strong>Maverick:</strong> Hi! I’m Maverick. Ask me anything about RealNex, RealBlasts, or sync stats. 📊</div>
      <input type="text" id="chat-input" placeholder="Ask Maverick..." style="width:100%;margin-top:10px;">
      <button onclick="sendMessage()" style="margin-top:5px;width:100%;">Ask</button>
    </div>`;
  document.body.appendChild(chatWidget);
  makeWidgetDraggable(chatWidget);
  loadStats();
  loadErrors();
  setInterval(loadStats, 60000);
}

document.addEventListener('DOMContentLoaded', initChatWidget);

function makeWidgetDraggable(el) {
  el.onmousedown = function (e) {
    let offsetX = e.clientX - el.getBoundingClientRect().left;
    let offsetY = e.clientY - el.getBoundingClientRect().top;
    function mouseMoveHandler(e) {
      el.style.left = e.clientX - offsetX + 'px';
      el.style.top = e.clientY - offsetY + 'px';
      el.style.bottom = 'unset';
      el.style.right = 'unset';
      el.style.position = 'absolute';
    }
    function mouseUpHandler() {
      document.removeEventListener('mousemove', mouseMoveHandler);
      document.removeEventListener('mouseup', mouseUpHandler);
    }
    document.addEventListener('mousemove', mouseMoveHandler);
    document.addEventListener('mouseup', mouseUpHandler);
  };
}

function sendMessage() {
  const input = document.getElementById('chat-input');
  const message = input.value.trim();
  if (!message) return;

  fetch('/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message })
  })
    .then(res => res.json())
    .then(data => {
      const chatBody = document.getElementById('chat-body');
      if (data.action === 'show_dashboard') {
        loadStats();
        loadErrors();
        alert(data.message);
      } else {
        const response = document.createElement('div');
        response.innerHTML = `<strong>Maverick:</strong> ${data.message}`;
        chatBody.appendChild(response);
      }
    });
  input.value = '';
}

window.sendMessage = sendMessage;
