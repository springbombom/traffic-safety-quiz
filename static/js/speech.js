(function () {
  let rateMode = 'normal';
  let audio = null;
  let requestId = 0;

  function stopAudio() {
    if (audio) {
      audio.pause();
      audio.currentTime = 0;
      audio = null;
    }
  }

  function localBrowserSpeak(text, id) {
    return new Promise((resolve, reject) => {
      if (!('speechSynthesis' in window)) {
        reject(new Error('unsupported'));
        return;
      }

      stopAudio();
      window.speechSynthesis.cancel();

      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'ko-KR';
      utterance.rate = rateMode === 'slow' ? 0.72 : 0.9;

      const voices = window.speechSynthesis.getVoices();
      const koreanVoice = voices.find(
        voice =>
          voice.lang &&
          voice.lang.toLowerCase().startsWith('ko')
      );

      if (koreanVoice) {
        utterance.voice = koreanVoice;
      }

      utterance.onend = resolve;

      utterance.onerror = event => {
        if (
          id !== requestId ||
          event.error === 'canceled' ||
          event.error === 'interrupted'
        ) {
          resolve();
          return;
        }

        reject(new Error(event.error || 'speech-error'));
      };

      window.speechSynthesis.speak(utterance);
    });
  }

  async function serverSpeak(text, id) {
    if (id !== requestId) {
      return;
    }

    stopAudio();

    const nextAudio = new Audio(
      `/api/tts?rate=${encodeURIComponent(rateMode)}&text=${encodeURIComponent(text)}`
    );

    audio = nextAudio;
    await nextAudio.play();
  }

  async function speak(text) {
    const id = ++requestId;

    try {
      await localBrowserSpeak(text, id);
    } catch (_) {
      if (id !== requestId) {
        return;
      }

      try {
        await serverSpeak(text, id);
      } catch (_) {
        const message = document.getElementById('message');

        if (message) {
          message.textContent =
            '음성을 재생하지 못했습니다. 다시 눌러 주세요.';
        }
      }
    }
  }

  function stop() {
    requestId += 1;

    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }

    stopAudio();
  }

  window.SpeechGuide = {
    speak,

    setRate(mode) {
      rateMode = mode === 'slow' ? 'slow' : 'normal';
    },

    stop
  };
})();
