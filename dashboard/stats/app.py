// === app.py route for live dashboard stats ===

from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime

app = Flask(__name__)

@app.route('/dashboard/stats')
def dashboard_stats():
    try:
        # Simulated stats for now
        stats = {
            "contacts": 243,
            "companies": 76,
            "importsToday": 11,
            "lastUpload": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

// === frontend.js (dashboard + extension already integrated) ===

let mode = 'maverick';
let token = localStorage.getItem('realNexApiKey') || '';
let currentFile = null;
let hasPromptedForRealNex = localStorage.getItem('hasPromptedForRealNex') || false;
let declinedRealNexPrompt = localStorage.getItem('declinedRealNexPrompt') || false;
let isSending = false;

function initChatWidget() {
  const chatWidget = document.createElement('div');
  chatWidget.className = 'chat-widget';
  chatWidget.innerHTML = `
    <div class="chat-body" id="chat-body">
      <div class="dashboard-preview bg-gray-100">
        <h4>📊 Goose Sync Stats</h4>
        <ul id="dashboard-stats">
          <li>Contacts Synced: <span id="contacts-synced">--</span></li>
          <li>Companies Synced: <span id="companies-synced">--</span></li>
          <li>Imports Today: <span id="imports-today">--</span></li>
          <li>Last Upload: <span id="last-upload">--</span></li>
        </ul>
      </div>
    </div>`;
  document.body.appendChild(chatWidget);

  fetch('/dashboard/stats')
    .then(res => res.json())
    .then(data => {
      document.getElementById('contacts-synced').innerText = data.contacts || 0;
      document.getElementById('companies-synced').innerText = data.companies || 0;
      document.getElementById('imports-today').innerText = data.importsToday || 0;
      document.getElementById('last-upload').innerText = data.lastUpload || 'N/A';
    });
}

document.addEventListener('DOMContentLoaded', initChatWidget);

function saveReminderPrefs() {
  const enabled = document.getElementById('enable-reminders').checked;
  const filter = document.getElementById('reminder-filter').value;
  const daysBefore = parseInt(document.getElementById('reminder-days').value) || 1;
  fetch('/set-reminder-prefs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled, filter, daysBefore })
  })
    .then(res => res.json())
    .then(data => {
      const note = document.createElement('div');
      note.className = 'chat-message bg-teal-100';
      note.innerText = data.message || 'Reminder preferences saved!';
      document.getElementById('chat-body').appendChild(note);
    });
}
