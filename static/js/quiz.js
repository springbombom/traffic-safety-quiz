(function () {
  const app = document.getElementById('quizApp');
  const attemptId = app.dataset.attemptId;
  const questions = window.QUIZ_DATA.questions;
  const answers = {};
  let index = 0;
  let lastSpoken = '';
  const els = {
    counter: document.getElementById('counter'), progress: document.getElementById('progressBar'),
    number: document.getElementById('questionNumber'), text: document.getElementById('questionText'),
    choices: document.getElementById('choices'), message: document.getElementById('message'),
    prev: document.getElementById('prevButton'), next: document.getElementById('nextButton')
  };

  function render() {
    const q = questions[index];
    els.counter.textContent = `${index + 1} / ${questions.length}`;
    els.progress.style.width = `${((index + 1) / questions.length) * 100}%`;
    els.number.textContent = `${q.number}번 질문`;
    els.text.textContent = q.text;
    els.message.textContent = '';
    els.choices.innerHTML = '';
    q.choices.forEach((choice, i) => {
      const value = i + 1;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `choice ${answers[q.id] === value ? 'selected' : ''}`;
      button.setAttribute('aria-pressed', answers[q.id] === value ? 'true' : 'false');
      button.innerHTML = `<span class="choice-number">${['①','②','③','④','⑤'][i]}</span><span>${choice}</span><span class="check">✓</span>`;
      button.addEventListener('click', () => select(value));
      els.choices.appendChild(button);
    });
    els.prev.disabled = index === 0;
    els.next.textContent = index === questions.length - 1 ? '검사 완료' : '다음 문항';
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  async function select(value) {
    const q = questions[index];
    answers[q.id] = value;
    render();
    const choice = q.choices[value - 1];
    els.message.textContent = `${choice}를 선택했습니다.`;
    SpeechGuide.speak(`선택하신 답은 ${choice}입니다.`);
    try {
      const response = await fetch(`/api/attempts/${attemptId}/answer`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({question_id:q.id, value})});
      if (!response.ok) throw new Error((await response.json()).error);
    } catch (error) {
      els.message.textContent = `저장 오류: ${error.message}. 다시 선택해 주세요.`;
      delete answers[q.id]; render();
    }
  }

  function speakQuestion() {
    const q = questions[index]; lastSpoken = q.speech_text; SpeechGuide.speak(lastSpoken);
  }
  function speakChoices() {
    const q = questions[index];
    const order = ['첫 번째', '두 번째', '세 번째', '네 번째', '다섯 번째'];
    lastSpoken = q.choices.map((choice, i) => `${order[i]}, ${choice}.`).join(' ');
    els.message.textContent = '①부터 ⑤까지 답안을 읽고 있습니다.';
    SpeechGuide.speak(lastSpoken);
  }
  document.getElementById('listenButton').addEventListener('click', speakQuestion);
  document.getElementById('repeatButton').addEventListener('click', () => { if (!lastSpoken) speakQuestion(); else SpeechGuide.speak(lastSpoken); });
  document.getElementById('choicesListenButton').addEventListener('click', speakChoices);
  document.getElementById('helpButton').addEventListener('click', () => { lastSpoken = questions[index].help_text; SpeechGuide.speak(lastSpoken); });
  document.querySelectorAll('.speed').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('.speed').forEach(b => b.classList.remove('active')); button.classList.add('active'); SpeechGuide.setRate(button.dataset.rate);
  }));
  els.prev.addEventListener('click', () => { if (index > 0) { index--; SpeechGuide.stop(); render(); } });
  els.next.addEventListener('click', async () => {
    const q = questions[index];
    if (!answers[q.id]) { els.message.textContent = '답을 하나 선택해 주세요.'; SpeechGuide.speak('답을 하나 선택해 주세요.'); return; }
    if (index < questions.length - 1) { index++; SpeechGuide.stop(); render(); return; }
    els.next.disabled = true;
    try {
      const response = await fetch(`/api/attempts/${attemptId}/complete`, {method:'POST'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      window.location.href = data.redirect;
    } catch (error) { els.next.disabled = false; els.message.textContent = error.message; SpeechGuide.speak(error.message); }
  });
  render();
  window.addEventListener('load', () => SpeechGuide.speak(`지금부터 ${window.QUIZ_DATA.name}를 시작합니다.`));
})();
