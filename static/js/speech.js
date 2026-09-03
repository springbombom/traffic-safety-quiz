(function () {
  let rateMode = 'normal';
  let audio = null;

  function localBrowserSpeak(text) {
    return new Promise((resolve, reject) => {
       if (audio) {
      audio.pause();
      audio.currentTime = 0;
      audio = null;
    }
      if (!('speechSynthesis' in window)) return reject(new Error('unsupported'));
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'ko-KR';
      utterance.rate = rateMode === 'slow' ? 0.72 : 0.9;
      const voices = window.speechSynthesis.getVoices();
      const korean = voices.find(v => v.lang && v.lang.toLowerCase().startsWith('ko'));
      if (korean) utterance.voice = korean;
      utterance.onend = resolve;
     utterance.onerror = (event) => {
  if (event.error === 'canceled' || event.error === 'interrupted') {
    resolve();
    return;
  }

  reject(new Error(event.error || 'speech-error'));
};
      window.speechSynthesis.speak(utterance);
    });
  }

  async function serverSpeak(text) {
    if (audio) { audio.pause(); audio = null; }
    audio = new Audio(`/api/tts?rate=${encodeURIComponent(rateMode)}&text=${encodeURIComponent(text)}`);
    await audio.play();
  }

  async function speak(text) {
  try {
    await localBrowserSpeak(text);
  } catch (_) {
    const message = document.getElementById('message');

    if (message) {
      message.textContent =
        '이 브라우저에서는 음성을 재생할 수 없습니다. Chrome 또는 Safari에서 열어 주세요.';
    }
  }
}

  window.SpeechGuide = {
    speak,
    setRate(mode) { rateMode = mode === 'slow' ? 'slow' : 'normal'; },
    stop() {
      if ('speechSynthesis' in window) window.speechSynthesis.cancel();
      if (audio) audio.pause();
    }
  };
})();
