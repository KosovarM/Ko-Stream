(function () {
  const track = document.getElementById("spotlight");
  if (!track) return;

  const slides = track.querySelectorAll(".spotlight-slide");
  const dots = document.querySelectorAll(".spotlight-dots .dot");
  if (!slides.length) return;

  let timer;
  let scrolling = false;

  function currentIndex() {
    const w = track.clientWidth || 1;
    return Math.round(track.scrollLeft / w);
  }

  function syncDots() {
    const idx = Math.max(0, Math.min(slides.length - 1, currentIndex()));
    slides.forEach((s, n) => s.classList.toggle("active", n === idx));
    dots.forEach((d, n) => d.classList.toggle("active", n === idx));
    return idx;
  }

  function goTo(i, behavior) {
    const idx = ((i % slides.length) + slides.length) % slides.length;
    const slide = slides[idx];
    if (!slide) return;
    scrolling = true;
    slide.scrollIntoView({ behavior: behavior || "smooth", inline: "start", block: "nearest" });
    window.setTimeout(() => {
      scrolling = false;
      syncDots();
    }, behavior === "auto" ? 0 : 400);
  }

  function next() {
    goTo(currentIndex() + 1);
  }

  function resetTimer() {
    clearInterval(timer);
    if (slides.length < 2) return;
    timer = setInterval(next, 8000);
  }

  dots.forEach((dot) => {
    dot.addEventListener("click", () => {
      goTo(Number(dot.dataset.slide));
      resetTimer();
    });
  });

  track.addEventListener(
    "scroll",
    () => {
      if (scrolling) return;
      syncDots();
      resetTimer();
    },
    { passive: true }
  );

  syncDots();
  resetTimer();
})();
