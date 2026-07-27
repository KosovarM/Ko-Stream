(function () {
  const track = document.getElementById("spotlight");
  if (!track) return;

  const slides = track.querySelectorAll(".spotlight-slide");
  const dots = document.querySelectorAll(".spotlight-dots .dot");
  if (!slides.length) return;

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
    const w = track.clientWidth || 0;
    if (!w) return;
    scrolling = true;
    // Scroll the track only — avoid scrollIntoView, which can jump the page.
    track.scrollTo({ left: idx * w, behavior: behavior || "smooth" });
    window.setTimeout(() => {
      scrolling = false;
      syncDots();
    }, behavior === "auto" ? 0 : 400);
  }

  dots.forEach((dot) => {
    dot.addEventListener("click", () => {
      goTo(Number(dot.dataset.slide));
    });
  });

  track.addEventListener(
    "scroll",
    () => {
      if (scrolling) return;
      syncDots();
    },
    { passive: true }
  );

  syncDots();
})();
