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

  function svgUrl(svg) {
    var copy = svg.cloneNode(true);
    copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    copy.style.backgroundColor = getComputedStyle(document.body).backgroundColor;
    var text = new XMLSerializer().serializeToString(copy);
    return URL.createObjectURL(new Blob([text], {type: "image/svg+xml"}));
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
    var url = svgUrl(svg);
    var bar = document.createElement("p");
    bar.className = "diagram-links";
    bar.appendChild(link("Open as SVG", url, {target: "_blank", rel: "noopener"}));
    bar.appendChild(document.createTextNode(" · "));
    bar.appendChild(link("Download SVG", url, {download: fileName(index)}));
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
