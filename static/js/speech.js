(function () {
  let rateMode = 'normal';
  let activeUtterance = null;

  function speak(text) {
    const message = document.getElementById('message');

    if (!('speechSynthesis' in window)) {
      if (message) {
        message.textContent = '이 브라우저에서는 음성을 지원하지 않습니다.';
      }
      return;
    }

    // 현재 읽고 있는 음성을 먼저 중단합니다.
    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'ko-KR';
    utterance.rate = rateMode === 'slow' ? 0.72 : 0.9;

    // 휴대전화에 설치된 한국어 음성을 선택합니다.
    const voices = window.speechSynthesis.getVoices();
    const koreanVoice = voices.find(
      voice =>
        voice.lang &&
        voice.lang.toLowerCase().startsWith('ko')
    );

    if (koreanVoice) {
      utterance.voice = koreanVoice;
    }

    activeUtterance = utterance;

    utterance.onend = () => {
      if (activeUtterance === utterance) {
        activeUtterance = null;
      }
    };

    utterance.onerror = event => {
      // 음성 교체 과정에서 발생하는 정상적인 중단은 무시합니다.
      if (
        event.error === 'canceled' ||
        event.error === 'interrupted'
      ) {
        return;
      }

      if (message) {
        message.textContent =
          '음성을 재생하지 못했습니다. 질문 듣기 버튼을 다시 눌러 주세요.';
      }
    };

    window.speechSynthesis.speak(utterance);
  }

  function stop() {
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }

    activeUtterance = null;
  }

  window.SpeechGuide = {
    speak,

    setRate(mode) {
      rateMode = mode === 'slow' ? 'slow' : 'normal';
    },

    stop
  };
})();
