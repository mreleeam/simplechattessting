(function() {
  "use strict";

  if (!document.body || document.body.dataset.authenticated === "false") {
    var body = document.body;
    if (body) body.dataset.authenticated = "true";
  }

  var wsProto = window.location.protocol === "https:" ? "wss://" : "ws://";
  var url = wsProto + window.location.host + "/ws/presence/";
  var socket = null;
  var reconnectDelay = 2000;
  var maxReconnectDelay = 30000;
  var manuallyClosed = false;

  function apply(username, online) {
    document.querySelectorAll('[data-username="' + username + '"]').forEach(function(el) {
      var dot = el.querySelector(".presence");
      if (!dot) return;
      dot.classList.toggle("online", online);
    });
  }

  function connect() {
    manuallyClosed = false;
    try {
      socket = new WebSocket(url);
    } catch (e) {
      return;
    }

    socket.onopen = function() {
      reconnectDelay = 2000;
    };

    socket.onclose = function() {
      if (manuallyClosed) return;
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, maxReconnectDelay);
    };

    socket.onerror = function() {
      if (socket) socket.close();
    };

    socket.onmessage = function(event) {
      var data;
      try { data = JSON.parse(event.data); } catch (e) { return; }
      if (data.type === "presence") {
        apply(data.username, data.online);
      }
    };
  }

  connect();

  window.addEventListener("beforeunload", function() {
    manuallyClosed = true;
    if (socket) socket.close();
  });
})();
