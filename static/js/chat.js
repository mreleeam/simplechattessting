(function () {
  "use strict";

  const log = document.getElementById("chat-log");
  const input = document.getElementById("chat-message-input");
  const statusEl = document.getElementById("connection-status");
  if (!log || !input) return;

  const wsPrefix = log.dataset.wsPrefix;
  const roomName = log.dataset.room;
  const chatId = log.dataset.chatId;
  const colorMode = log.dataset.colorMode || "palette";
  const myUsername = log.dataset.myUsername || "";
  const kind = log.dataset.kind || "";
  const olderUrl = log.dataset.olderUrl || "";
  const typingUrl = log.dataset.typingUrl || "";

  const EDIT_WINDOW_MS = 24 * 60 * 60 * 1000;

  let endpoint;
  if (wsPrefix === "/ws/chat/u/") {
    endpoint = wsPrefix + encodeURIComponent(chatId) + "/";
  } else {
    endpoint = wsPrefix + encodeURIComponent(roomName) + "/";
  }

  const wsProto = window.location.protocol === "https:" ? "wss://" : "ws://";
  const url = wsProto + window.location.host + endpoint;

  let socket = null;
  let reconnectDelay = 1000;
  const maxReconnectDelay = 30000;
  let manuallyClosed = false;
  let lastTypingSent = 0;
  let countdownTimer = null;

  const typingIndicator = document.getElementById("typing-indicator");
  let typingClearTimer = null;

  log.scrollTop = log.scrollHeight;

  function setStatus(text, cls) {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.className = cls;
  }

  function stopCountdown() {
    if (countdownTimer) {
      clearInterval(countdownTimer);
      countdownTimer = null;
    }
  }

  function startCountdown(seconds) {
    stopCountdown();
    let remaining = seconds;
    setStatus("RECONNECTING (" + remaining + "s)", "status-disconnected");
    countdownTimer = setInterval(function () {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(countdownTimer);
        countdownTimer = null;
        setStatus("RECONNECTING", "status-disconnected");
        return;
      }
      setStatus("RECONNECTING (" + remaining + "s)", "status-disconnected");
    }, 1000);
  }

  function appendError(msg) {
    const line = document.createElement("p");
    line.className = "chat-error";
    line.textContent = "! " + msg;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }

  function isRecent(createdIso) {
    if (!createdIso) return false;
    const t = new Date(createdIso).getTime();
    if (isNaN(t)) return false;
    return Date.now() - t <= EDIT_WINDOW_MS;
  }

  function applyColor(userEl, msgEl, data) {
    if (colorMode === "me-vs-them") {
      const isMe = data.username === myUsername;
      const color = isMe ? "#58a6ff" : "#f85149";
      if (userEl) userEl.style.color = color;
      if (msgEl) msgEl.style.color = color;
    } else {
      const color = data.user_color || "#58a6ff";
      if (userEl) userEl.style.color = color;
    }
  }

  function getCSRF() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function buildReactionsBlock(msgId, up, down, mine) {
    const wrap = document.createElement("span");
    wrap.className = "chat-reactions";
    wrap.dataset.id = msgId;

    const upBtn = document.createElement("button");
    upBtn.type = "button";
    upBtn.className = "reaction-btn reaction-up" + (mine === 1 ? " active" : "");
    if (up > 0) upBtn.classList.add("has-count");
    upBtn.dataset.value = "1";
    upBtn.dataset.count = up || 0;
    upBtn.title = "Thumbs up";
    upBtn.innerHTML = '👍 <span class="react-count">' + (up || 0) + '</span>';

    const downBtn = document.createElement("button");
    downBtn.type = "button";
    downBtn.className = "reaction-btn reaction-down" + (mine === -1 ? " active" : "");
    if (down > 0) downBtn.classList.add("has-count");
    downBtn.dataset.value = "-1";
    downBtn.dataset.count = down || 0;
    downBtn.title = "Thumbs down";
    downBtn.innerHTML = '👎 <span class="react-count">' + (down || 0) + '</span>';

    wrap.appendChild(upBtn);
    wrap.appendChild(downBtn);
    return wrap;
  }

  function sendReaction(msgId, value) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({
      type: "reaction",
      id: msgId,
      value: value,
    }));
  }

  function updateReactionCounts(msgId, up, down) {
    const block = log.querySelector('.chat-reactions[data-id="' + msgId + '"]');
    if (!block) return;
    const upBtn = block.querySelector('.reaction-up');
    const downBtn = block.querySelector('.reaction-down');
    if (upBtn) {
      upBtn.dataset.count = up;
      const s = upBtn.querySelector(".react-count");
      if (s) s.textContent = up;
      upBtn.classList.toggle("has-count", up > 0);
    }
    if (downBtn) {
      downBtn.dataset.count = down;
      const s = downBtn.querySelector(".react-count");
      if (s) s.textContent = down;
      downBtn.classList.toggle("has-count", down > 0);
    }
  }

  function toggleMyReaction(msgId, value) {
    const block = log.querySelector('.chat-reactions[data-id="' + msgId + '"]');
    if (!block) return;
    const upBtn = block.querySelector('.reaction-up');
    const downBtn = block.querySelector('.reaction-down');
    if (!upBtn || !downBtn) return;

    const wasUp = upBtn.classList.contains("active");
    const wasDown = downBtn.classList.contains("active");

    if (value === 1) {
      if (wasUp) upBtn.classList.remove("active");
      else {
        upBtn.classList.add("active");
        downBtn.classList.remove("active");
      }
    } else {
      if (wasDown) downBtn.classList.remove("active");
      else {
        downBtn.classList.add("active");
        upBtn.classList.remove("active");
      }
    }
  }

  function attachActions(line) {
    if (line.querySelector(".chat-message-actions")) return;
    const userEl = line.querySelector(".chat-user");
    const msgEl = line.querySelector(".chat-message");
    if (!userEl || !msgEl) return;
    if (userEl.textContent.trim() !== myUsername) return;
    if (!line.dataset.id) return;
    if (!isRecent(line.dataset.created)) return;

    const actions = document.createElement("span");
    actions.className = "chat-message-actions";

    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.textContent = "EDIT";
    editBtn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      openEditModal(line);
    });

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "chat-action-delete";
    deleteBtn.textContent = "DELETE";
    deleteBtn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      confirmDelete(line);
    });

    actions.appendChild(editBtn);
    actions.appendChild(deleteBtn);
    line.appendChild(actions);
  }

  function buildSystemLine(data) {
    const line = document.createElement("p");
    line.className = "chat-message-system";
    line.dataset.id = data.id || "";
    line.dataset.kind = kind;

    const time = document.createElement("span");
    time.className = "chat-time";
    time.textContent = data.timestamp || "";
    if (data.full_timestamp) time.title = data.full_timestamp;

    const text = document.createElement("span");
    text.className = "chat-system-text";
    text.textContent = "@" + (data.username || "") + " " + (data.content || data.message || "");

    line.appendChild(time);
    line.appendChild(document.createTextNode(" "));
    line.appendChild(text);
    return line;
  }

  function buildMessageLine(data) {
    if (data.is_system) return buildSystemLine(data);

    const line = document.createElement("p");
    line.dataset.id = data.id || "";
    line.dataset.kind = kind;
    line.dataset.created = data.created || "";

    const time = document.createElement("span");
    time.className = "chat-time";
    time.textContent = data.timestamp || "";
    if (data.full_timestamp) time.title = data.full_timestamp;

    const user = document.createElement("span");
    user.className = "chat-user";
    user.textContent = data.username || "";

    const msg = document.createElement("span");
    msg.className = "chat-message";
    msg.textContent = data.message || "";

    line.appendChild(time);
    line.appendChild(document.createTextNode(" "));
    line.appendChild(user);
    line.appendChild(document.createTextNode(" > "));
    line.appendChild(msg);

    if (data.edited) {
      const edited = document.createElement("span");
      edited.className = "chat-edited";
      edited.textContent = " (edited)";
      line.appendChild(edited);
    }

    line.appendChild(
      buildReactionsBlock(data.id, data.up || 0, data.down || 0, data.mine || 0)
    );

    applyColor(user, msg, data);
    attachActions(line);
    return line;
  }

  function openEditModal(line) {
    const msgEl = line.querySelector(".chat-message");
    if (!msgEl) return;
    if (!isRecent(line.dataset.created)) {
      appendError("This message is too old to edit.");
      return;
    }
    const original = msgEl.textContent;

    promptModal({
      title: "Edit message",
      message: "Change your message:",
      inputValue: original,
      confirmText: "SAVE",
      cancelText: "CANCEL",
      onResult: function (result) {
        if (typeof result !== "string") return;
        const trimmed = result.trim();
        if (!trimmed || trimmed === original) return;
        const msgId = line.dataset.id;

        fetch("/chat/msg/edit/", {
          method: "POST",
          headers: {
            "X-CSRFToken": getCSRF(),
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body:
            "id=" + encodeURIComponent(msgId) +
            "&kind=" + encodeURIComponent(kind) +
            "&content=" + encodeURIComponent(trimmed),
        })
          .then(function (r) { return r.json(); })
          .then(function (resp) {
            if (resp.ok) {
              msgEl.textContent = resp.content;
              if (!line.querySelector(".chat-edited")) {
                const edited = document.createElement("span");
                edited.className = "chat-edited";
                edited.textContent = " (edited)";
                const actions = line.querySelector(".chat-message-actions");
                if (actions) line.insertBefore(edited, actions);
                else line.appendChild(edited);
              }
            } else {
              appendError(resp.error || "Could not edit message");
            }
          })
          .catch(function () { appendError("Could not edit message"); });
      },
    });
  }

  function confirmDelete(line) {
    if (!isRecent(line.dataset.created)) {
      appendError("This message is too old to delete.");
      return;
    }
    confirmModal({
      title: "Delete message",
      message: "Delete this message permanently?",
      confirmText: "DELETE",
      cancelText: "CANCEL",
      danger: true,
      onResult: function (ok) {
        if (ok !== true) return;
        const msgId = line.dataset.id;
        fetch("/chat/msg/delete/", {
          method: "POST",
          headers: {
            "X-CSRFToken": getCSRF(),
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: "id=" + encodeURIComponent(msgId) + "&kind=" + encodeURIComponent(kind),
        })
          .then(function (r) { return r.json(); })
          .then(function (resp) {
            if (resp.ok) line.remove();
            else appendError(resp.error || "Could not delete message");
          })
          .catch(function () { appendError("Could not delete message"); });
      },
    });
  }

  function connect() {
    manuallyClosed = false;
    stopCountdown();
    setStatus("CONNECTING", "status-disconnected");
    socket = new WebSocket(url);

    socket.onopen = function () {
      reconnectDelay = 1000;
      stopCountdown();
      setStatus("CONNECTED", "status-connected");
      input.disabled = false;
      input.focus();
    };

    socket.onclose = function (event) {
      input.disabled = true;
      if (manuallyClosed) {
        stopCountdown();
        setStatus("DISCONNECTED", "status-disconnected");
        return;
      }
      if (event.code === 4001) {
        stopCountdown();
        setStatus("NOT AUTHENTICATED", "status-disconnected");
        return;
      }
      if (event.code === 4003) {
        stopCountdown();
        setStatus("ACCESS DENIED", "status-disconnected");
        return;
      }
      if (event.code === 4029) {
        stopCountdown();
        setStatus("TOO MANY CONNECTIONS", "status-disconnected");
        return;
      }
      const secs = Math.round(reconnectDelay / 1000);
      startCountdown(secs);
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, maxReconnectDelay);
    };

    socket.onerror = function () {
      if (socket) socket.close();
    };

    socket.onmessage = function (event) {
      let data;
      try { data = JSON.parse(event.data); } catch (e) { return; }
      if (data.error) { appendError(data.error); return; }

      if (data.type === "typing") {
        if (!typingIndicator) return;
        if (data.username === myUsername) return;
        typingIndicator.textContent = data.username + " is typing...";
        typingIndicator.hidden = false;
        if (typingClearTimer) clearTimeout(typingClearTimer);
        typingClearTimer = setTimeout(function () {
          typingIndicator.hidden = true;
        }, 3000);
        return;
      }

      if (data.type === "reaction") {
        updateReactionCounts(data.id, data.up, data.down);
        return;
      }

      if (data.type === "system_message") {
        log.appendChild(buildSystemLine({ content: data.text, username: "" }));
        log.scrollTop = log.scrollHeight;
        return;
      }

      if (data.type === "chat_event") {
        if (data.event_type === "edit") {
          var editedLine = log.querySelector('p[data-id="' + data.id + '"]');
          if (editedLine) {
            var msgEl = editedLine.querySelector(".chat-message");
            if (msgEl) msgEl.textContent = data.content;
            if (!editedLine.querySelector(".chat-edited")) {
              var badge = document.createElement("span");
              badge.className = "chat-edited";
              badge.textContent = " (edited)";
              var actions = editedLine.querySelector(".chat-message-actions");
              if (actions) editedLine.insertBefore(badge, actions);
              else editedLine.appendChild(badge);
            }
          }
        } else if (data.event_type === "delete") {
          var delLine = log.querySelector('p[data-id="' + data.id + '"]');
          if (delLine) delLine.remove();
        } else if (data.event_type === "clear_all") {
          log.innerHTML = "";
        } else if (data.event_type === "system") {
          log.appendChild(buildSystemLine(data));
          log.scrollTop = log.scrollHeight;
        } else if (data.event_type === "member_change") {
          if (typeof window.onMemberChange === "function") {
            window.onMemberChange();
          }
        }
        return;
      }

      log.appendChild(buildMessageLine(data));
      log.scrollTop = log.scrollHeight;
    };
  }

  log.querySelectorAll("p[data-id]").forEach(attachActions);

  input.disabled = true;
  connect();

  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      const message = input.value.trim();
      if (!message) return;
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      socket.send(JSON.stringify({ type: "message", message: message }));
      input.value = "";
      input.style.height = "auto";
    }
  });

  input.addEventListener("input", function () {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";

    if (!typingUrl) return;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    const now = Date.now();
    if (now - lastTypingSent < 2000) return;
    lastTypingSent = now;
    socket.send(JSON.stringify({ type: "typing" }));
  });

  log.addEventListener("click", function (event) {
    const btn = event.target.closest(".reaction-btn");
    if (!btn) return;
    const block = btn.closest(".chat-reactions");
    if (!block) return;
    const msgId = block.dataset.id;
    const value = parseInt(btn.dataset.value, 10);
    if (value !== 1 && value !== -1) return;
    toggleMyReaction(msgId, value);
    sendReaction(msgId, value);
  });

  if (olderUrl) {
    const btn = document.getElementById("load-older-btn");
    if (btn) {
      btn.addEventListener("click", function () {
        const first = log.querySelector("p[data-id]");
        const before = first ? first.dataset.id : "";
        btn.disabled = true;
        fetch(olderUrl + "?before=" + encodeURIComponent(before))
          .then(function (r) { return r.json(); })
          .then(function (resp) {
            const msgs = resp.messages || [];
            const frag = document.createDocumentFragment();
            msgs.forEach(function (m) {
              frag.appendChild(buildMessageLine(m));
            });
            const firstEl = log.firstChild;
            log.insertBefore(frag, firstEl);
            btn.disabled = false;
            if (!resp.has_more) btn.remove();
          })
          .catch(function () { btn.disabled = false; });
      });
    }
  }

  window.addEventListener("beforeunload", function () {
    manuallyClosed = true;
    if (socket) socket.close();
  });
})();
