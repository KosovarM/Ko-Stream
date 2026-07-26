(function () {
  const slides = document.querySelectorAll('.spotlight-slide');
  const dots = document.querySelectorAll('.spotlight-dots .dot');
  const prevBtn = document.getElementById('spotlight-prev');
  const nextBtn = document.getElementById('spotlight-next');
  if (!slides.length) return;

  let current = 0;
  let timer;

  function show(i) {
    const idx = ((i % slides.length) + slides.length) % slides.length;
    slides.forEach((s, n) => s.classList.toggle('active', n === idx));
    dots.forEach((d, n) => d.classList.toggle('active', n === idx));
    current = idx;
  }

  function next() { show(current + 1); }
  function prev() { show(current - 1); }

  function resetTimer() {
    clearInterval(timer);
    timer = setInterval(next, 8000);
  }

  dots.forEach((dot) => {
    dot.addEventListener('click', () => {
      show(Number(dot.dataset.slide));
      resetTimer();
    });
  });

  prevBtn?.addEventListener('click', () => { prev(); resetTimer(); });
  nextBtn?.addEventListener('click', () => { next(); resetTimer(); });

  resetTimer();
})();
