(function () {
  "use strict";

  // ADR 016 forbids inline JS and DOM event attributes, so the two behaviours
  // htmx attributes cannot express live here: the IME rule (no request while a
  // composition is open) and the 429 notice (wait, never retry automatically).
  document.addEventListener("DOMContentLoaded", function () {
    var form = document.querySelector(".mg-search--hero");
    if (!form) {
      return;
    }
    var input = form.querySelector("input[name='q']");
    var notice = document.getElementById("search-notice");
    if (!input) {
      return;
    }
    var composing = false;

    input.addEventListener("compositionstart", function () {
      composing = true;
    });
    input.addEventListener("compositionend", function () {
      composing = false;
      // 確定した値で改めて500msのdebounceをやり直す。
      input.dispatchEvent(new Event("keyup", { bubbles: true }));
    });

    form.addEventListener("htmx:beforeRequest", function (event) {
      if (composing) {
        event.preventDefault();
      }
    });
    form.addEventListener("htmx:afterRequest", function (event) {
      if (!notice) {
        return;
      }
      var xhr = event.detail.xhr;
      if (xhr && xhr.status === 429) {
        var retryAfter = parseInt(xhr.getResponseHeader("Retry-After"), 10);
        notice.textContent =
          "アクセスが集中しています。" +
          (retryAfter > 0 ? retryAfter + "秒ほど" : "しばらく") +
          "待ってから、もう一度入力してください。";
        notice.hidden = false;
      } else if (event.detail.successful) {
        notice.hidden = true;
      }
    });
  });
})();
