/* ==========================================================================
   Pike website — account pages (sign in / register / device approval)
   ========================================================================== */
(function () {
  "use strict";

  var doc = document;

  /* --------------------------------------------------- password reveal */
  doc.addEventListener("click", function (event) {
    var button = event.target.closest("[data-toggle-password]");
    if (!button) return;
    var input = doc.getElementById(button.getAttribute("data-toggle-password"));
    if (!input) return;
    var show = input.type === "password";
    input.type = show ? "text" : "password";
    button.setAttribute("title", show ? "Hide password" : "Show password");
  });

  function showError(message) {
    var box = doc.getElementById("formError");
    if (!box) return;
    box.textContent = message;
    box.hidden = !message;
  }

  function busy(button, on, label) {
    if (!button) return;
    button.disabled = on;
    var span = button.querySelector(".btn-label");
    if (span && label) span.textContent = label;
  }

  async function postJson(url, body) {
    var response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
    var data = {};
    try { data = await response.json(); } catch (e) { /* ignore */ }
    if (!response.ok || data.ok === false) {
      throw new Error((data && data.error) || "Something went wrong. Please try again.");
    }
    return data;
  }

  function go(next, fallback) {
    window.location.href = next || fallback;
  }

  /* ------------------------------------------------------------- login */
  var loginForm = doc.getElementById("loginForm");
  if (loginForm) {
    loginForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      showError("");
      var button = doc.getElementById("submitBtn");
      var email = doc.getElementById("email").value.trim();
      var password = doc.getElementById("password").value;
      if (!email || !password) {
        showError("Enter your email and password.");
        return;
      }
      busy(button, true, "Signing in…");
      try {
        await postJson("/api/account/login", { email: email, password: password });
        go(doc.getElementById("next").value, "/dashboard");
      } catch (error) {
        showError(error.message);
        busy(button, false, "Sign in");
      }
    });
  }

  /* ---------------------------------------------------------- register */
  var registerForm = doc.getElementById("registerForm");
  if (registerForm) {
    registerForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      showError("");
      var button = doc.getElementById("submitBtn");
      var name = doc.getElementById("name").value.trim();
      var email = doc.getElementById("email").value.trim();
      var password = doc.getElementById("password").value;
      if (!email || !password) {
        showError("Enter your email and a password.");
        return;
      }
      if (password.length < 8) {
        showError("Password must be at least 8 characters.");
        return;
      }
      busy(button, true, "Creating account…");
      try {
        await postJson("/api/account/register", { name: name, email: email, password: password });
        go(doc.getElementById("next").value, "/dashboard");
      } catch (error) {
        showError(error.message);
        busy(button, false, "Create account");
      }
    });
  }

  /* --------------------------------------------------- device approval */
  var approveBtn = doc.getElementById("approveBtn");
  if (approveBtn) {
    approveBtn.addEventListener("click", async function () {
      var code = approveBtn.getAttribute("data-code");
      busy(approveBtn, true, "Approving…");
      try {
        await postJson("/api/account/device/approve", { user_code: code });
        window.location.reload();
      } catch (error) {
        showError(error.message);
        busy(approveBtn, false, "Approve device");
      }
    });
  }

  var denyBtn = doc.getElementById("denyBtn");
  if (denyBtn) {
    denyBtn.addEventListener("click", async function () {
      try {
        await postJson("/api/account/device/deny", { user_code: denyBtn.getAttribute("data-code") });
      } catch (error) { /* ignore */ }
      window.location.reload();
    });
  }

  /* ------------------------------------------------------- code lookup */
  var codeForm = doc.getElementById("codeForm");
  if (codeForm) {
    codeForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var value = doc.getElementById("userCode").value.trim().replace(/\s+/g, "");
      if (!value) {
        showError("Enter the code shown in your app.");
        return;
      }
      window.location.href = "/device?code=" + encodeURIComponent(value.toUpperCase());
    });
  }
})();