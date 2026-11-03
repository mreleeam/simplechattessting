(function () {
  "use strict";

  function build(options) {
    var wrap = document.createElement("div");
    wrap.className = "modal-backdrop";

    var modal = document.createElement("div");
    modal.className = "modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");

    var title = document.createElement("h2");
    title.className = "modal-title";
    title.textContent = options.title || "Confirm";
    modal.appendChild(title);

    var body = document.createElement("p");
    body.className = "modal-body";
    body.textContent = options.message || "";
    modal.appendChild(body);

    var inputEl = null;
    if (options.input) {
      inputEl = document.createElement("textarea");
      inputEl.className = "modal-input";
      inputEl.value = options.inputValue || "";
      inputEl.rows = 4;
      inputEl.maxLength = 4000;
      modal.appendChild(inputEl);
    }

    var actions = document.createElement("div");
    actions.className = "modal-actions";

    var cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "btn";
    cancel.textContent = options.cancelText || "CANCEL";

    var confirm = document.createElement("button");
    confirm.type = "button";
    confirm.className = "btn " + (options.danger ? "btn-error" : "btn-primary");
    confirm.textContent = options.confirmText || "CONFIRM";

    actions.appendChild(cancel);
    actions.appendChild(confirm);
    modal.appendChild(actions);
    wrap.appendChild(modal);
    document.body.appendChild(wrap);

    requestAnimationFrame(function () { wrap.classList.add("modal-visible"); });
    (inputEl || confirm).focus();
    if (inputEl) {
      inputEl.setSelectionRange(inputEl.value.length, inputEl.value.length);
    }

    function close(result) {
      wrap.classList.remove("modal-visible");
      setTimeout(function () {
        if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
      }, 150);
      document.removeEventListener("keydown", onKey);
      if (options.onResult) options.onResult(result);
    }

    function onKey(e) {
      if (e.key === "Escape") close(null);
      if (e.key === "Enter" && !e.shiftKey && !inputEl) close(true);
    }

    confirm.addEventListener("click", function () {
      close(inputEl ? inputEl.value : true);
    });
    cancel.addEventListener("click", function () { close(null); });
    wrap.addEventListener("click", function (e) {
      if (e.target === wrap) close(null);
    });
    document.addEventListener("keydown", onKey);
  }

  window.confirmModal = function (options) {
    if (typeof options === "string") options = { message: options };
    build(options);
  };

  window.promptModal = function (options) {
    options.input = true;
    build(options);
  };

  document.addEventListener("submit", function (e) {
    var form = e.target;
    var msg = form.getAttribute("data-confirm");
    if (!msg) return;
    if (form.dataset.confirmed === "1") return;
    e.preventDefault();
    build({
      title: form.getAttribute("data-confirm-title") || "Confirm",
      message: msg,
      confirmText: form.getAttribute("data-confirm-ok") || "CONFIRM",
      cancelText: form.getAttribute("data-confirm-cancel") || "CANCEL",
      danger: form.getAttribute("data-confirm-danger") === "1",
      onResult: function (ok) {
        if (ok !== true) return;
        form.dataset.confirmed = "1";
        form.submit();
      }
    });
  });
})();
