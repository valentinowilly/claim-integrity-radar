// Theme before the first paint (same rule as src/theme/theme.ts): the saved choice, else the device setting.
(function () {
  var theme = null;
  try { theme = window.localStorage.getItem("cir:theme"); } catch (e) { /* storage unavailable */ }
  if (theme !== "light" && theme !== "dark") {
    theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.dataset.theme = theme;
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta && theme === "dark") meta.setAttribute("content", "#0b1311");
})();
