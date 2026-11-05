(function () {
  "use strict";

  if (!window.location.pathname.match(/^\/(chat|account)\b/)) return;

  var wsProto = window.location.protocol === "https:" ? "wss://" : "ws://";
  var url = wsProto + window.location.host + "/ws/events/";
  var socket = null;
  var reconnectDelay = 2000;
  var maxReconnectDelay = 30000;
  var manuallyClosed = false;
  var heartbeat = null;

  function startHeartbeat() {
    stopHeartbeat();
    heartbeat = setInterval(function () {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "ping" }));
      }
    }, 25000);
  }

  function stopHeartbeat() {
    if (heartbeat) {
      clearInterval(heartbeat);
      heartbeat = null;
    }
  }

  function connect() {
    manuallyClosed = false;
    try {
      socket = new WebSocket(url);
    } catch (e) {
      return;
    }

    socket.onopen = function () {
      reconnectDelay = 2000;
      startHeartbeat();
    };

    socket.onclose = function () {
      stopHeartbeat();
      if (manuallyClosed) return;
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, maxReconnectDelay);
    };

    socket.onerror = function () {
      if (socket) socket.close();
    };

    socket.onmessage = function (event) {
      var data;
      try { data = JSON.parse(event.data); } catch (e) { return; }
      if (data.type === "refresh_index") {
        if (window.location.pathname === "/chat/" || window.location.pathname === "/chat") {
          setTimeout(function () { window.location.reload(); }, 100);
        }
      }
    };
  }

  connect();

  window.addEventListener("beforeunload", function () {
    manuallyClosed = true;
    stopHeartbeat();
    if (socket) socket.close();
  });
})();
