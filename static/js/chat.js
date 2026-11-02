(function () {
  "use strict";

  const log = document.getElementById("chat-log");
  const input = document.getElementById("chat-message-input");
  const statusEl = document.getElementById("connection-status");
  if (!log || !input) return;

  const wsPrefix = log.dataset.wsPrefix;
  const roomName = log.dataset.room;
  const chatId = log.dataset.chatId;

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

  log.scrollTop = log.scrollHeight;

  function setStatus(text, cls) {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.className = cls;
  }

  function appendError(msg) {
    const line = document.createElement("p");
    line.className = "chat-error";
    line.textContent = "! " + msg;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }

  function appendMessage(data) {
    const line = document.createElement("p");
    const time = document.createElement("span");
    time.className = "chat-time";
    time.textContent = data.timestamp || "";
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
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }

  function connect() {
    manuallyClosed = false;
    setStatus("CONNECTING", "status-disconnected");
    socket = new WebSocket(url);

    socket.onopen = function () {
      reconnectDelay = 1000;
      setStatus("CONNECTED", "status-connected");
      input.disabled = false;
      input.focus();
    };

    socket.onclose = function (event) {
      input.disabled = true;
      if (manuallyClosed) {
        setStatus("DISCONNECTED", "status-disconnected");
        return;
      }
      if (event.code === 4001) {
        setStatus("NOT AUTHENTICATED", "status-disconnected");
        return;
      }
      if (event.code === 4003) {
        setStatus("ACCESS DENIED", "status-disconnected");
        return;
      }
      if (event.code === 4029) {
        setStatus("TOO MANY CONNECTIONS", "status-disconnected");
        return;
      }
      const secs = Math.round(reconnectDelay / 1000);
      setStatus("RECONNECTING (" + secs + "s)", "status-disconnected");
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, maxReconnectDelay);
    };

    socket.onerror = function () {
      if (socket) socket.close();
    };

    socket.onmessage = function (event) {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (e) {
        return;
      }
      if (data.error) {
        appendError(data.error);
        return;
      }
      appendMessage(data);
    };
  }

  input.disabled = true;
  connect();

  input.addEventListener("keydown", function (event) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ message: message }));
    input.value = "";
  });

  window.addEventListener("beforeunload", function () {
    manuallyClosed = true;
    if (socket) socket.close();
  });
})();
