(function () {
  var root = window.__ROOT__ || "";
  var toggle = document.querySelector("[data-search-toggle]");
  var panel = document.querySelector("[data-search-panel]");
  var input = document.querySelector("[data-search-input]");
  var results = document.querySelector("[data-search-results]");
  if (!toggle || !panel || !input || !results) return;

  var index = null;

  function load() {
    if (index) return Promise.resolve(index);
    return fetch(root + "search.json").then(function (r) { return r.json(); }).then(function (data) {
      index = data;
      return index;
    });
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function search(q) {
    q = q.trim().toLowerCase();
    results.innerHTML = "";
    if (q.length < 2) return;
    load().then(function (data) {
      var terms = q.split(/\s+/);
      var hits = data.filter(function (d) {
        var hay = (d.title + " " + d.orig + " " + d.summary + " " + d.tags.join(" ") + " " + d.source + " " + d.topic).toLowerCase();
        return terms.every(function (t) { return hay.indexOf(t) !== -1; });
      }).slice(0, 40);
      if (!hits.length) {
        results.innerHTML = '<div class="hit"><small>검색 결과가 없습니다.</small></div>';
        return;
      }
      results.innerHTML = hits.map(function (d) {
        return '<div class="hit"><a href="' + esc(d.url) + '" target="_blank" rel="noopener">' + esc(d.title) + "</a>" +
          "<small>" + esc(d.date) + " · " + esc(d.source) + " · " + esc(d.topic) +
          ' · <a href="' + root + "archive/" + esc(d.date) + '.html">브리핑</a></small></div>';
      }).join("");
    });
  }

  toggle.addEventListener("click", function () {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) { input.focus(); load(); }
  });
  var timer;
  input.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(function () { search(input.value); }, 120);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "/" && document.activeElement !== input) {
      e.preventDefault(); panel.hidden = false; input.focus(); load();
    }
    if (e.key === "Escape" && !panel.hidden) { panel.hidden = true; }
  });
})();
