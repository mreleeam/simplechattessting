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

    if (options.message) {
      var body = document.createElement("p");
      body.className = "modal-body";
      body.textContent = options.message;
      modal.appendChild(body);
    }

    var inputEl = null;
    if (options.input) {
      inputEl = document.createElement("textarea");
      inputEl.className = "modal-input";
      inputEl.value = options.inputValue || "";
      inputEl.rows = 4;
      inputEl.maxLength = 4000;
      modal.appendChild(inputEl);
    }

    if (options.htmlContent) {
      var contentEl = document.createElement("div");
      contentEl.className = "modal-content";
      contentEl.innerHTML = options.htmlContent;
      modal.appendChild(contentEl);
    }

    var formEl = null;
    if (options.fields) {
      formEl = document.createElement("form");
      formEl.method = "post";
      formEl.action = options.action || "";
      formEl.className = "modal-form";

      if (options.csrf) {
        var csrfInput = document.createElement("input");
        csrfInput.type = "hidden";
        csrfInput.name = "csrfmiddlewaretoken";
        csrfInput.value = options.csrf;
        formEl.appendChild(csrfInput);
      }

      options.fields.forEach(function (f) {
        var label = document.createElement("label");
        label.className = "form-label";

        var labelText = document.createElement("span");
        labelText.textContent = f.label || f.name;
        label.appendChild(labelText);

        var input = document.createElement("input");
        input.type = f.type || "text";
        input.name = f.name;
        input.required = !!f.required;
        input.autocomplete = "off";
        if (f.placeholder) input.placeholder = f.placeholder;
        if (f.maxLength) input.maxLength = f.maxLength;
        if (f.min !== undefined) input.min = f.min;
        if (f.max !== undefined) input.max = f.max;

        label.appendChild(input);
        formEl.appendChild(label);
      });

      modal.appendChild(formEl);
    }

    var actions = document.createElement("div");
    actions.className = "modal-actions";

    var cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "btn";
    cancel.textContent = options.cancelText || (options.confirmText ? "CANCEL" : "CLOSE");

    var confirm = null;
    if (options.confirmText !== null) {
      confirm = document.createElement("button");
      confirm.type = "button";
      confirm.className = "btn " + (options.danger ? "btn-error" : "btn-primary");
      confirm.textContent = options.confirmText || "CONFIRM";
    }

    actions.appendChild(cancel);
    if (confirm) actions.appendChild(confirm);
    modal.appendChild(actions);
    wrap.appendChild(modal);
    document.body.appendChild(wrap);

    requestAnimationFrame(function () { wrap.classList.add("modal-visible"); });

    var focusTarget = confirm || cancel;
    if (formEl) {
      var firstField = formEl.querySelector("input:not([type=hidden])");
      if (firstField) focusTarget = firstField;
    } else if (inputEl) {
      focusTarget = inputEl;
    } else if (options.focusSelector) {
      var custom = wrap.querySelector(options.focusSelector);
      if (custom) focusTarget = custom;
    }
    focusTarget.focus();

    if (inputEl) {
      inputEl.setSelectionRange(inputEl.value.length, inputEl.value.length);
    }

    if (options.onOpen) options.onOpen(wrap);

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
      if (e.key === "Enter" && !e.shiftKey && !inputEl && !formEl) close(true);
    }

    if (confirm) {
      confirm.addEventListener("click", function () {
        if (formEl) {
          formEl.submit();
          return;
        }
        close(inputEl ? inputEl.value : true);
      });
    }

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

  window.formModal = function (options) {
    build(options);
  };

  window.contentModal = function (options) {
    build(options);
  };

  window.getCSRF = function () {
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : "";
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
