// Shared quiz component. Markup contract:
// <div class="quiz" data-explain-right="…" data-explain-wrong="…">
//   <p class="q">Question?</p>
//   <div class="opts">
//     <button>wrong</button>
//     <button data-correct>right</button>
//   </div>
//   <p class="feedback"></p>
// </div>
// Immediate feedback; retrieval practice first, explanation after the attempt.
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".quiz button");
  if (!btn || btn.disabled) return;
  const quiz = btn.closest(".quiz");
  const feedback = quiz.querySelector(".feedback");
  const correct = btn.hasAttribute("data-correct");
  if (correct) {
    btn.classList.add("correct");
    quiz.querySelectorAll("button").forEach((b) => (b.disabled = true));
    feedback.textContent = "✓ " + (quiz.dataset.explainRight || "Correct.");
  } else {
    btn.classList.add("wrong");
    btn.disabled = true;
    feedback.textContent = "✗ " + (quiz.dataset.explainWrong || "Not that one — try again.");
  }
});
