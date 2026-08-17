/* Landing-page motion.
 *
 * Three constraints this file is built around, in order of importance:
 *
 * 1. **The page must render without it.** The pre-reveal state is gated on a
 *    `.motion` class that is added at runtime, never baked into the stylesheet,
 *    and a failsafe in the page head strips it again if this file never runs.
 *    A blocked script therefore leaves a fully readable page — which is exactly
 *    the failure mode every scroll-reveal library ships by putting `opacity:0`
 *    in CSS and hoping the JS arrives.
 *
 * 2. **Only transform and opacity are animated.** Both are composited, so the
 *    work happens off the main thread. Height, top and box-shadow are not, and
 *    animating those is what turns a reveal into visible stutter on a phone.
 *
 * 3. **No scroll listener anywhere.** IntersectionObserver does the watching and
 *    each one disconnects the instant it fires, so scrolling back through the
 *    page a second time costs nothing at all.
 *
 * Interactive affordances (the paste box noticing a link) are set up whether or
 * not motion is allowed — they are behaviour, not decoration, and a visitor who
 * asked for reduced motion still wants the feedback, just without the travel.
 */
(function (global) {
  "use strict";

  var doc = global.document;
  var root = doc.documentElement;

  // Fires slightly before the element is fully on screen, so the motion is
  // finishing as it arrives rather than starting once it is already there.
  var REVEAL_MARGIN = "0px 0px -12% 0px";

  // Cascades, revealed together when their container comes into view. The step
  // differs per group because the content does: the three how-it-works cards
  // are a sequence the reader follows, so they earn a slower cascade than six
  // feature cards, which are a set and only need to not arrive as one slab.
  var SEQUENCES = [
    { container: ".platform-list", items: ".platform-chip", step: 40 },
    { container: ".steps-grid", items: "li", step: 95 },
    { container: ".feature-grid", items: "article", step: 55 },
    { container: ".plan-grid", items: ".plan-card", step: 75 },
    { container: ".faq-list", items: "details", step: 30 },
  ];

  // Revealed on their own, no cascade to belong to.
  var SINGLES = ".band .section-heading, .plan-foot";

  // The hero is already on screen at load, so it plays on a timer rather than
  // on scroll, top to bottom, ending on the thing we want looked at.
  var HERO = [
    ".brand-tagline", ".hero-inner h1", ".hero-sub",
    ".paste-box", ".paste-meta", ".trust-row",
  ];

  function each(list, fn) {
    Array.prototype.forEach.call(list, fn);
  }

  function prime(el, delayMs) {
    el.classList.add("reveal");
    if (delayMs) el.style.transitionDelay = delayMs + "ms";
  }

  function reveal(el) {
    el.classList.add("is-in");
    // The delay has done its job; leaving it on would also delay any later
    // transition the element picks up, such as a hover lift.
    el.addEventListener("transitionend", function once() {
      el.style.transitionDelay = "";
      el.removeEventListener("transitionend", once);
    });
  }

  function watchOnce(el, onEnter) {
    var io = new IntersectionObserver(function (entries) {
      if (!entries[0].isIntersecting) return;
      io.disconnect();
      onEnter();
    }, { rootMargin: REVEAL_MARGIN, threshold: 0.05 });
    io.observe(el);
  }

  // ---------------------------------------------------------------------
  // behaviour — runs regardless of motion preference
  // ---------------------------------------------------------------------

  function enhance() {
    // The paste box is the whole product. When what you pasted actually looks
    // like a link, the box says so — the point is to catch the paste that went
    // wrong (a page title, a truncated share sheet) before you press anything.
    var box = doc.querySelector(".paste-box");
    var field = doc.querySelector("#url");
    if (box && field) {
      var LINK = /https?:\/\/[^\s]+/i;
      var sync = function () {
        box.classList.toggle("has-link", LINK.test(field.value));
      };
      field.addEventListener("input", sync);
      // Paste lands before the value updates, hence the deferred read.
      field.addEventListener("paste", function () { setTimeout(sync, 0); });
      sync();
    }

    // Header gains its edge once the page has moved. A one-pixel sentinel at
    // the top of the document instead of a scroll handler: the browser reports
    // the crossing itself, and nothing runs on the frames in between.
    var header = doc.querySelector(".site-header");
    if (header && "IntersectionObserver" in global) {
      var sentinel = doc.createElement("div");
      sentinel.className = "scroll-sentinel";
      sentinel.setAttribute("aria-hidden", "true");
      doc.body.insertBefore(sentinel, doc.body.firstChild);
      new IntersectionObserver(function (entries) {
        header.classList.toggle("is-stuck", !entries[0].isIntersecting);
      }).observe(sentinel);
    }
  }

  // ---------------------------------------------------------------------
  // reveals — skipped entirely when motion is not wanted
  // ---------------------------------------------------------------------

  function animate() {
    root.classList.add("motion-ready");

    var hero = [];
    HERO.forEach(function (selector, i) {
      var el = doc.querySelector(selector);
      if (!el) return;
      prime(el, 70 + i * 75);
      hero.push(el);
    });

    // Two frames, not one: the first lets the browser paint the primed state,
    // the second changes it. Collapse them and there is no start value to
    // animate from, so the element just appears.
    global.requestAnimationFrame(function () {
      global.requestAnimationFrame(function () {
        hero.forEach(reveal);
      });
    });

    SEQUENCES.forEach(function (group) {
      var container = doc.querySelector(group.container);
      if (!container) return;
      var items = container.querySelectorAll(group.items);
      if (!items.length) return;
      each(items, function (el, i) { prime(el, i * group.step); });
      watchOnce(container, function () { each(items, reveal); });
    });

    each(doc.querySelectorAll(SINGLES), function (el) {
      prime(el, 0);
      watchOnce(el, function () { reveal(el); });
    });
  }

  function start() {
    enhance();

    var reduced = global.matchMedia
      && global.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced || !("IntersectionObserver" in global)) {
      // Take the pre-reveal state back off in case the head script guessed
      // otherwise, and leave the page in its final form.
      root.classList.remove("motion");
      return;
    }
    animate();
  }

  if (doc.readyState === "loading") {
    doc.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})(window);
