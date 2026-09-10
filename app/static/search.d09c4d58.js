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

    // 変換中のkeyupはhtmxへ渡さない。htmxはトリガー評価の時点で changed 用に
    // 入力値を記録するため、htmx:beforeRequestで中断するだけでは変換中の値が
    // 「送信済み」として残り、同じ値で確定したときに二度と送られなくなる。
    input.addEventListener(
      "keyup",
      function (event) {
        if (composing) {
          event.stopPropagation();
        }
      },
      true
    );
    // composition開始前に予約済みだったリクエストが変換中に発火した場合の保険。
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
