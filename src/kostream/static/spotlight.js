(function () {
  const slides = document.querySelectorAll('.spotlight-slide');
  const dots = document.querySelectorAll('.spotlight-dots .dot');
  if (!slides.length) return;

  let current = 0;
  function show(i) {
    slides.forEach((s, idx) => s.classList.toggle('active', idx === i));
    dots.forEach((d, idx) => d.classList.toggle('active', idx === i));
    current = i;
  }

  dots.forEach((dot) => {
    dot.addEventListener('click', () => show(Number(dot.dataset.slide)));
  });

  setInterval(() => show((current + 1) % slides.length), 7000);
})();
