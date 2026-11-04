(function () {
  "use strict";

  if (!window.location.pathname.match(/^\/(chat|account)\b/)) return;

  var wsProto = window.location.protocol === "https:" ? "wss://" : "ws://";
  var url = wsProto + window.location.host + "/ws/events/";
  var socket = null;
  var reconnectDelay = 2000;
  var maxReconnectDelay = 30000;
  var manuallyClosed = false;

  function connect() {
    manuallyClosed = false;
    try {
      socket = new WebSocket(url);
    } catch (e) {
      return;
    }

    socket.onopen = function () {
      reconnectDelay = 2000;
    };

    socket.onclose = function () {
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
        if (typeof window.refreshChatIndex === "function") {
          window.refreshChatIndex();
        }
      }
    };
  }

  connect();

  window.addEventListener("beforeunload", function () {
    manuallyClosed = true;
    if (socket) socket.close();
  });
})();
