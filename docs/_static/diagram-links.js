// Every diagram opens on its own as SVG, and saves as one.
//
// Mermaid draws the diagrams in the browser, so the site has no image file
// to link to. Once a diagram is drawn, its SVG is copied into a file of its
// own, with the page's background so the text stays readable in a new tab.
(function () {
  "use strict";

  function fileName(index) {
    var page = location.pathname.split("/").pop().replace(/\.html?$/, "");
    return (page || "diagram") + "-" + (index + 1) + ".svg";
  }

  function svgText(svg) {
    var copy = svg.cloneNode(true);
    copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    copy.style.backgroundColor = getComputedStyle(document.body).backgroundColor;
    return new XMLSerializer().serializeToString(copy);
  }

  // The site is served with Cross-Origin-Opener-Policy: same-origin, so a
  // blob: URL opened in a new tab lands in another browsing context group
  // and shows nothing. An empty tab stays with its opener, and the SVG is
  // written into it.
  function openSvg(text, title) {
    var tab = window.open("", "_blank");
    if (!tab) return;
    var background = getComputedStyle(document.body).backgroundColor;
    tab.document.open();
    tab.document.write("<!doctype html><meta charset=\"utf-8\"><title></title>"
      + "<body style=\"margin:0;background:" + background + "\">"
      + text + "</body>");
    tab.document.close();
    tab.document.title = title;
  }

  function link(label, url, extra) {
    var a = document.createElement("a");
    a.textContent = label;
    a.href = url;
    for (var key in extra) a.setAttribute(key, extra[key]);
    return a;
  }

  function addLinks(box, index) {
    var svg = box.querySelector("svg");
    if (!svg || box.dataset.diagramLinks) return;
    box.dataset.diagramLinks = "1";
    var text = svgText(svg);
    var name = fileName(index);
    var url = URL.createObjectURL(new Blob([text], {type: "image/svg+xml"}));
    var bar = document.createElement("p");
    bar.className = "diagram-links";
    var open = link("Open as SVG", url, {});
    open.addEventListener("click", function (event) {
      event.preventDefault();
      openSvg(text, name);
    });
    bar.appendChild(open);
    bar.appendChild(document.createTextNode(" · "));
    bar.appendChild(link("Download SVG", url, {download: name}));
    box.insertAdjacentElement("afterend", bar);
  }

  function watch() {
    var boxes = document.querySelectorAll(".mermaid");
    boxes.forEach(function (box, index) {
      addLinks(box, index);
      new MutationObserver(function () { addLinks(box, index); })
        .observe(box, {childList: true, subtree: true});
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watch);
  } else {
    watch();
  }
})();
