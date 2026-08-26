(function () {
  "use strict";

  var storageKey = "meigen-fly-client-uuid";
  var uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  var pageUuid = null;

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
      }).catch(function () {
        if (button) {
          button.disabled = false;
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".mg-like-form").forEach(configure);
  });
})();
