/*
 * pdfjs_overlay.js — coordinate highlight overlay for the bundled pdf.js viewer.
 *
 * The inference app deep-links to viewer.html with a custom hash param
 *   #page=N&mhl=<base64url of [[x0,y0,x1,y1], …]>
 * where the rects are the matched source segment's bbox in PDF points, top-left
 * origin (fitz/PyMuPDF convention — the same the pipeline stores in
 * Segments.bbox). This script draws those rects as highlight boxes on page N,
 * giving a resolution-independent, exact source marker instead of a text search.
 *
 * Transform (rotation 0, the case for these portrait documents): pdf.js renders
 * the page at `viewport.scale` CSS px per PDF point with the canvas top-left at
 * the page's top-left — the same origin as fitz — so a fitz point (fx, fy) maps
 * to (fx*scale, fy*scale) with NO y-flip. (Derivation: pdf.js
 * convertToViewportPoint of the PDF-user-space point (fx, H-fy) is
 * (fx*scale, fy*scale).) Rotated pages would need viewport.convertToViewport-
 * Rectangle; they are rare here, and the app still carries a `&search=` phrase
 * fallback for any page where the overlay is absent.
 *
 * Install: copy this file into the pdf.js bundle's web/ dir and add
 *   <script src="pdfjs_overlay.js"></script>
 * at the end of viewer.html's <body>. Self-contained, no dependencies; a no-op
 * unless the hash carries `mhl`.
 */
(function () {
  "use strict";

  function parseHash() {
    var out = {};
    (location.hash || "").replace(/^#/, "").split("&").forEach(function (kv) {
      var i = kv.indexOf("=");
      if (i > 0) out[kv.slice(0, i)] = kv.slice(i + 1);
    });
    return out;
  }

  function decodeRects(token) {
    try {
      var b64 = token.replace(/-/g, "+").replace(/_/g, "/");
      while (b64.length % 4) b64 += "=";
      var rects = JSON.parse(atob(b64));   // rects are pure ASCII numbers
      if (Array.isArray(rects)) {
        return rects.filter(function (r) {
          return Array.isArray(r) && r.length === 4 && r.every(function (v) {
            return typeof v === "number" && isFinite(v);
          });
        });
      }
    } catch (e) { /* malformed → no overlay */ }
    return null;
  }

  function draw(pageView, rects) {
    if (!pageView || !pageView.div || !pageView.viewport) return;
    var div = pageView.div;
    div.querySelectorAll(".mheat-hl").forEach(function (n) { n.remove(); });
    var scale = pageView.viewport.scale;
    rects.forEach(function (r) {
      var el = document.createElement("div");
      el.className = "mheat-hl";
      el.style.cssText =
        "position:absolute;pointer-events:none;z-index:1;border-radius:2px;" +
        "background:rgba(255,214,0,0.30);outline:2px solid rgba(255,168,0,0.9);" +
        "left:" + (Math.min(r[0], r[2]) * scale) + "px;" +
        "top:" + (Math.min(r[1], r[3]) * scale) + "px;" +
        "width:" + (Math.abs(r[2] - r[0]) * scale) + "px;" +
        "height:" + (Math.abs(r[3] - r[1]) * scale) + "px;";
      div.appendChild(el);
    });
  }

  function init(app, page, rects) {
    var scrolled = false;
    function centreOnFirst(div) {
      if (scrolled) return;
      var first = div.querySelector(".mheat-hl");
      if (first) { first.scrollIntoView({ block: "center" }); scrolled = true; }
    }
    app.eventBus.on("pagerendered", function (ev) {
      if (ev.pageNumber !== page) return;
      var pv = app.pdfViewer.getPageView(page - 1);
      draw(pv, rects);
      if (pv) centreOnFirst(pv.div);
    });
    // Draw immediately if the target page is already rendered (listener race).
    var pv = app.pdfViewer.getPageView(page - 1);
    if (pv && pv.div && pv.div.querySelector("canvas")) {
      draw(pv, rects);
      centreOnFirst(pv.div);
    }
  }

  function boot() {
    var p = parseHash();
    if (!p.mhl) return;                       // nothing to draw → no-op
    var page = parseInt(p.page, 10) || 1;
    var rects = decodeRects(p.mhl);
    if (!rects || !rects.length) return;
    var app = window.PDFViewerApplication;
    if (!app) return;
    var run = function () { try { init(app, page, rects); } catch (e) {} };
    if (app.initializedPromise && app.initializedPromise.then) {
      app.initializedPromise.then(run);
    } else {
      run();
    }
  }

  if (window.PDFViewerApplication) {
    boot();
  } else {
    document.addEventListener("webviewerloaded", boot);
  }
})();
