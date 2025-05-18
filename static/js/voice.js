window.onload = function () {
  const recognition = new webkitSpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = 'en-US';

  document.getElementById('start-voice').onclick = function () {
    recognition.start();
  };

  recognition.onresult = function (e) {
    document.getElementById('message-input').value = e.results[0][0].transcript;
  };
};
