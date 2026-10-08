(function () {
  "use strict";

  var storageKey = "meigen-fly-client-uuid";
  var uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  var pageUuid = null;
  // Pages are shared CDN HTML, so this browser remembers its own likes.
  var likedKey = "meigen-fly-liked-quotes";
  var likedLimit = 500;

  function generateUuid() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    if (!window.crypto || typeof window.crypto.getRandomValues !== "function") {
      return null;
    }
    var bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    var hex = Array.from(bytes, function (byte) {
      return byte.toString(16).padStart(2, "0");
    }).join("");
    return hex.slice(0, 8) + "-" + hex.slice(8, 12) + "-" + hex.slice(12, 16) + "-" + hex.slice(16, 20) + "-" + hex.slice(20);
  }

  function clientUuid() {
    var value = null;
    try {
      value = window.localStorage.getItem(storageKey);
    } catch (_error) {
      value = null;
    }
    if (!uuidPattern.test(value || "")) {
      value = pageUuid || generateUuid();
      if (value) {
        pageUuid = value;
        try {
          window.localStorage.setItem(storageKey, value);
        } catch (_error) {
          // The in-memory value still supports this page when storage is blocked.
        }
      }
    } else {
      pageUuid = value;
    }
    return value;
  }

  function likedQuotes() {
    try {
      var value = JSON.parse(window.localStorage.getItem(likedKey) || "[]");
      return Array.isArray(value) ? value : [];
    } catch (_error) {
      return [];
    }
  }

  function rememberLiked(quoteId) {
    var ids = likedQuotes().filter(function (id) {
      return id !== quoteId;
    });
    ids.push(quoteId);
    try {
      window.localStorage.setItem(likedKey, JSON.stringify(ids.slice(-likedLimit)));
    } catch (_error) {
      // Without storage the liked state lasts only for this page.
    }
  }

  function markLiked(form, count) {
    var button = form.querySelector("button");
    if (!button) {
      return;
    }
    button.classList.add("is-liked");
    button.setAttribute("aria-pressed", "true");
    if (count) {
      var label = button.querySelector(".count") || button.lastChild;
      button.dataset.likeCount = count;
      label.textContent = Number(count).toLocaleString("en-US");
    }
  }

  function configure(form) {
    var uuid = clientUuid();
    if (uuid && !form.elements.client_uuid) {
      var hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = "client_uuid";
      hidden.value = uuid;
      form.appendChild(hidden);
    }
    form.addEventListener("submit", function (event) {
      var current = form.querySelector("button");
      if (current && current.classList.contains("is-liked")) {
        // Likes cannot be undone, so a second press sends nothing.
        event.preventDefault();
        return;
      }
      if (!form.elements.client_uuid) {
        return;
      }
      event.preventDefault();
      var button = form.querySelector("button");
      if (button) {
        button.disabled = true;
      }
      window.fetch(form.action, {
        method: "POST",
        body: new URLSearchParams(new FormData(form)),
        credentials: "same-origin",
        headers: { Accept: "text/html" }
      }).then(function (response) {
        if (!response.ok) {
          throw new Error("like request failed");
        }
        return response.text();
      }).then(function (html) {
        var wrapper = document.createElement("div");
        wrapper.innerHTML = html.trim();
        var replacement = wrapper.firstElementChild;
        form.replaceWith(replacement);
        configure(replacement);
        var liked = replacement.querySelector("button");
        if (liked) {
          liked.classList.add("is-pop");
        }
        var quoteId = replacement.dataset.likeQuoteId;
        rememberLiked(quoteId);
        document.querySelectorAll('.mg-like-form[data-like-quote-id="' + quoteId + '"]').forEach(function (other) {
          if (other !== replacement) {
            markLiked(other, liked && liked.dataset.likeCount);
          }
        });
      }).catch(function () {
        if (button) {
          button.disabled = false;
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var liked = likedQuotes();
    document.querySelectorAll(".mg-like-form").forEach(function (form) {
      if (liked.indexOf(form.dataset.likeQuoteId) !== -1) {
        markLiked(form, null);
      }
      configure(form);
    });
  });
})();
