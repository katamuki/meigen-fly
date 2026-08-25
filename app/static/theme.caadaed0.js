(function () {
  "use strict";

  var savedTheme;
  try {
    savedTheme = window.localStorage.getItem("theme");
  } catch (_error) {
    savedTheme = null;
  }
  if (savedTheme === "light" || savedTheme === "dark") {
    document.documentElement.dataset.theme = savedTheme;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var toggle = document.querySelector(".mg-theme-toggle");
    if (!toggle) {
      return;
    }
    toggle.addEventListener("click", function () {
      var explicitTheme = document.documentElement.dataset.theme;
      var dark = explicitTheme
        ? explicitTheme === "dark"
        : window.matchMedia("(prefers-color-scheme: dark)").matches;
      var nextTheme = dark ? "light" : "dark";
      document.documentElement.dataset.theme = nextTheme;
      try {
        window.localStorage.setItem("theme", nextTheme);
      } catch (_error) {
        // Theme switching still works when storage is unavailable.
      }
    });
  });
})();
