/* ==========================================================================
   Pike website — dashboard behaviour
   Live refresh of devices / activity + device revocation + profile updates.
   ========================================================================== */
(function () {
  "use strict";

  var doc = document;

  /* ------------------------------------------------ sidebar (mobile) */
  (function () {
    var sidebar = doc.getElementById("appSidebar");
    var toggle = doc.getElementById("sidebarToggle");
    var close = doc.getElementById("sidebarClose");
    var scrim = doc.getElementById("sidebarScrim");
    if (!sidebar || !toggle) return;

    function setOpen(open) {
      sidebar.classList.toggle("is-open", open);
      if (scrim) scrim.classList.toggle("is-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    }

    toggle.addEventListener("click", function () {
      setOpen(!sidebar.classList.contains("is-open"));
    });
    if (close) close.addEventListener("click", function () { setOpen(false); });
    if (scrim) scrim.addEventListener("click", function () { setOpen(false); });
    doc.addEventListener("keydown", function (event) {
      if (event.key === "Escape") setOpen(false);
    });
    sidebar.addEventListener("click", function (event) {
      if (event.target.closest("a") && window.matchMedia("(max-width: 1024px)").matches) {
        setOpen(false);
      }
    });
  })();

  function toast(message, ok) {
    var stack = doc.getElementById("toastStack");
    if (!stack) {
      stack = doc.createElement("div");
      stack.id = "toastStack";
      stack.className = "toast-stack";
      doc.body.appendChild(stack);
    }
    var el = doc.createElement("div");
    el.className = "toast " + (ok ? "is-ok" : "is-error");
    el.textContent = message;
    stack.appendChild(el);
    window.setTimeout(function () { el.classList.add("is-in"); }, 10);
    window.setTimeout(function () {
      el.classList.remove("is-in");
      window.setTimeout(function () { el.remove(); }, 250);
    }, 3600);
  }

  async function api(url, options) {
    var response = await fetch(url, Object.assign({ credentials: "same-origin" }, options || {}));
    var data = {};
    try { data = await response.json(); } catch (e) { /* ignore */ }
    if (!response.ok || data.ok === false) {
      throw new Error((data && data.error) || "Request failed.");
    }
    return data;
  }

  /* ---------------------------------------------------- revoke device */
  doc.addEventListener("click", async function (event) {
    var button = event.target.closest(".revoke-btn");
    if (!button) return;
    var name = button.getAttribute("data-name") || "this device";
    if (!window.confirm("Revoke “" + name + "”? It will be signed out immediately.")) return;
    var id = button.getAttribute("data-device");
    button.disabled = true;
    try {
      await api("/api/account/devices/" + id, { method: "DELETE" });
      var row = doc.querySelector('.device-row[data-device="' + id + '"]');
      if (row) row.remove();
      toast("Device revoked.", true);
    } catch (error) {
      toast(error.message, false);
      button.disabled = false;
    }
  });

  /* --------------------------------------------------- profile update */
  var profileForm = doc.getElementById("profileForm");
  if (profileForm) {
    profileForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      var name = doc.getElementById("profileName").value.trim();
      var password = doc.getElementById("profilePassword").value;
      var body = { name: name };
      if (password) body.password = password;
      try {
        await api("/api/account/profile", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        doc.getElementById("profilePassword").value = "";
        toast("Profile saved.", true);
      } catch (error) {
        toast(error.message, false);
      }
    });
  }

  /* ------------------------------------------ periodic live refresh */
  var deviceList = doc.getElementById("deviceList");
  var activityList = doc.getElementById("activityList");
  if (!deviceList && !activityList) return;

  function timeAgo(value) {
    if (!value) return "never";
    var diff = (Date.now() - new Date(value).getTime()) / 1000;
    if (diff < 60) return "just now";
    if (diff < 3600) return Math.floor(diff / 60) + " min ago";
    if (diff < 86400) return Math.floor(diff / 3600) + " hour" + (Math.floor(diff / 3600) === 1 ? "" : "s") + " ago";
    return Math.floor(diff / 86400) + " day" + (Math.floor(diff / 86400) === 1 ? "" : "s") + " ago";
  }

  async function refresh() {
    if (doc.hidden) return;
    try {
      var data = await api("/api/account/overview");
      var dash = data.dashboard || {};

      if (activityList && dash.activity) {
        activityList.innerHTML = dash.activity.map(function (item) {
          return (
            '<li class="activity-row"><span class="activity-dot" data-source="' + item.source + '"></span>' +
            '<div><span class="activity-detail">' + escapeHtml(item.detail || item.kind) + "</span>" +
            '<span class="activity-meta">' + escapeHtml(item.source) + " · " + timeAgo(item.created_at) + "</span></div></li>"
          );
        }).join("");
      }

      if (deviceList && dash.devices) {
        var seen = {};
        dash.devices.forEach(function (device) {
          seen[device.id] = true;
          var row = doc.querySelector('.device-row[data-device="' + device.id + '"]');
          if (row) {
            var span = row.querySelector(".device-seen");
            if (span) span.textContent = "Last active " + timeAgo(device.last_seen);
          }
        });
      }
    } catch (error) { /* silent */ }
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  window.setInterval(refresh, 15000);
})();