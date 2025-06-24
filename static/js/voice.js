window.onload = function () {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    console.error("Speech Recognition API not supported in this browser.");
    return;
  }

  const recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = 'en-US';

  document.getElementById('start-voice').onclick = function () {
    try {
      recognition.start();
      this.classList.add('recording');
    } catch (e) {
      console.error("Speech recognition error:", e);
      alert("Oops! Couldn’t start voice recognition. Check your microphone and browser support!");
    }
  };

  recognition.onresult = function (e) {
    const transcript = e.results[0][0].transcript;
    document.getElementById('chat-message').value = transcript;
    document.getElementById('start-voice').classList.remove('recording');
    sendMessage(); // <- assumes sendMessage() handles bot reply
  };

  recognition.onerror = function (e) {
    console.error("Speech recognition error:", e.error);
    document.getElementById('start-voice').classList.remove('recording');
    alert("Turbulence in voice recognition: " + e.error);
  };

  recognition.onend = function () {
    document.getElementById('start-voice').classList.remove('recording');
  };
};

// Text-to-Speech Response
function speak(text) {
  if (!('speechSynthesis' in window)) {
    console.warn("Text-to-speech not supported in this browser.");
    return;
  }

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'en-US';
  utterance.rate = 1;
  utterance.pitch = 1;

  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}
