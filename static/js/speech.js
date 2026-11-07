(function () {
  const audio = new Audio();
  let rateMode = 'normal';
  let playbackId = 0;
  let utterance = null;

  function stop() {
    playbackId++;
    audio.pause();
    if (utterance) {
      window.speechSynthesis.cancel();
      utterance = null;
    }
  }

  function speak(text) {
    stop();
    const id = playbackId;
    const rate = rateMode;
    audio.src = `/api/tts?rate=${encodeURIComponent(rate)}&text=${encodeURIComponent(text)}`;
    // Start playback while the browser is still handling the user's tap.
    return audio.play().catch(() => {
      if (id !== playbackId) return;
      const showError = () => {
        if (id !== playbackId) return;
        const message = document.getElementById('message');
        if (message) message.textContent = '음성 기능을 사용할 수 없습니다. 화면의 질문을 확인해 주세요.';
      };
      if (!('speechSynthesis' in window) || !('SpeechSynthesisUtterance' in window)) {
        showError();
        return;
      }
      utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'ko-KR';
      utterance.rate = rate === 'slow' ? 0.72 : 0.9;
      utterance.onerror = showError;
      window.speechSynthesis.speak(utterance);
    });
  }

  window.SpeechGuide = {
    speak,
    setRate(mode) { rateMode = mode === 'slow' ? 'slow' : 'normal'; },
    stop
  };
})();
