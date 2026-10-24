/* ==========================================================================
   Pike website — front-end behaviour
   Theme toggle, mobile nav, scroll effects, copy buttons and docs TOC.
   ========================================================================== */
(function () {
  "use strict";

  var doc = document;
  var root = doc.documentElement;

  /* ---------------------------------------------------------------- Theme */
  var THEME_KEY = "pike.site.theme";

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme === "light" ? "light" : "dark");
    root.style.colorScheme = theme;
  }

  var themeToggle = doc.getElementById("theme-toggle");
  if (themeToggle) {
    themeToggle.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
      applyTheme(next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* ignore */ }
    });
  }

  /* ----------------------------------------------------------- Mobile nav */
  var navToggle = doc.getElementById("nav-toggle");
  var primaryNav = doc.getElementById("primary-nav");

  function closeNav() {
    if (!primaryNav) return;
    primaryNav.classList.remove("is-open");
    if (navToggle) navToggle.setAttribute("aria-expanded", "false");
  }

  if (navToggle && primaryNav) {
    navToggle.addEventListener("click", function () {
      var open = primaryNav.classList.toggle("is-open");
      navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    });

    primaryNav.addEventListener("click", function (event) {
      if (event.target.closest("a")) closeNav();
    });

    doc.addEventListener("click", function (event) {
      if (!primaryNav.classList.contains("is-open")) return;
      if (primaryNav.contains(event.target) || navToggle.contains(event.target)) return;
      closeNav();
    });

    doc.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeNav();
    });
  }

  /* -------------------------------------------------- Header scroll state */
  var header = doc.getElementById("site-header");
  if (header) {
    var onScroll = function () {
      header.classList.toggle("is-scrolled", window.scrollY > 8);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  /* --------------------------------------------------- Reveal on scroll */
  var revealTargets = doc.querySelectorAll(
    ".feature-card, .step, .download-card, .detail-item, .spec, .contact-card, .release, .provider-chip, .privacy-band, .cta-panel"
  );

  if (revealTargets.length && "IntersectionObserver" in window) {
    var revealObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        revealObserver.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });

    revealTargets.forEach(function (el, index) {
      el.classList.add("reveal");
      el.style.transitionDelay = Math.min(index % 6, 5) * 45 + "ms";
      revealObserver.observe(el);
    });
  }

  /* ----------------------------------------------------------- Copy code */
  doc.addEventListener("click", function (event) {
    var button = event.target.closest(".copy-btn");
    if (!button) return;

    var targetId = button.getAttribute("data-copy-target");
    var source = targetId ? doc.getElementById(targetId) : button.closest(".code-panel").querySelector("pre");
    if (!source) return;

    var text = source.innerText.replace(/\s+$/, "");

    var done = function () {
      var original = button.innerHTML;
      button.classList.add("is-copied");
      button.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#i-check"/></svg> Copied';
      window.setTimeout(function () {
        button.classList.remove("is-copied");
        button.innerHTML = original;
      }, 1800);
    };

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done).catch(function () { fallbackCopy(text, done); });
    } else {
      fallbackCopy(text, done);
    }
  });

  function fallbackCopy(text, done) {
    var area = doc.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    doc.body.appendChild(area);
    area.select();
    try { doc.execCommand("copy"); done(); } catch (e) { /* ignore */ }
    doc.body.removeChild(area);
  }

  /* ------------------------------------------------------- Docs TOC spy */
  var tocLinks = Array.prototype.slice.call(doc.querySelectorAll(".docs-toc a[href^='#']"));
  if (tocLinks.length && "IntersectionObserver" in window) {
    var sections = tocLinks
      .map(function (link) { return doc.getElementById(link.getAttribute("href").slice(1)); })
      .filter(Boolean);

    var setActive = function (id) {
      tocLinks.forEach(function (link) {
        link.classList.toggle("is-active", link.getAttribute("href") === "#" + id);
      });
    };

    var spy = new IntersectionObserver(function (entries) {
      var visible = entries
        .filter(function (e) { return e.isIntersecting; })
        .sort(function (a, b) { return a.boundingClientRect.top - b.boundingClientRect.top; });
      if (visible.length) setActive(visible[0].target.id);
    }, { rootMargin: "-25% 0px -65% 0px", threshold: 0 });

    sections.forEach(function (section) { spy.observe(section); });

    tocLinks.forEach(function (link) {
      link.addEventListener("click", function () {
        setActive(link.getAttribute("href").slice(1));
      });
    });
  }

  /* ------------------------------------------------------ Console greeting */
  var style = "background:linear-gradient(90deg,#7aa2f7,#8b5cf6);color:#fff;padding:4px 10px;border-radius:6px;font-weight:700;";
  // eslint-disable-next-line no-console
  console.log("%cPike", style, "— thanks for poking around. Source: https://github.com/DavidMkindi/pike-desktop");
})();