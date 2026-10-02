// Theme toggle and the per-round chart. Everything else is server-rendered and refreshed by htmx.
(function () {
  var root = document.documentElement;
  function current() {
    var set = root.getAttribute("data-theme");
    if (set) return set;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function bindToggle() {
    var btn = document.getElementById("theme-toggle");
    if (!btn) return;
    btn.setAttribute("aria-pressed", current() === "dark" ? "true" : "false");
    btn.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      localStorage.setItem("plasmon-theme", next);
      btn.setAttribute("aria-pressed", next === "dark" ? "true" : "false");
      drawChart();
    });
  }
  function colors() {
    var s = getComputedStyle(root);
    return { accent: s.getPropertyValue("--accent").trim(), ink2: s.getPropertyValue("--ink-2").trim(), line: s.getPropertyValue("--line").trim() };
  }
  var chart = null;
  function drawChart() {
    var el = document.getElementById("loss-chart");
    if (!el || typeof uPlot === "undefined") return;
    var series;
    try { series = JSON.parse(el.getAttribute("data-series")); } catch (e) { return; }
    if (!series.rounds || series.rounds.length < 1) return;
    el.querySelectorAll(".empty").forEach(function (n) { n.remove(); });
    var c = colors();
    var opts = {
      width: Math.max(320, el.clientWidth), height: 220,
      scales: { x: { time: false }, loss: { auto: true }, acc: { range: [0, 1] } },
      axes: [
        { label: "round", stroke: c.ink2, grid: { stroke: c.line }, ticks: { stroke: c.line } },
        { scale: "loss", label: "eval loss", stroke: c.ink2, grid: { stroke: c.line }, ticks: { stroke: c.line } },
        { scale: "acc", side: 1, label: "eval accuracy", stroke: c.ink2, grid: { show: false }, values: function (u, v) { return v.map(function (x) { return Math.round(x * 100) + " %"; }); } }
      ],
      series: [
        { label: "round" },
        { label: "eval loss", scale: "loss", stroke: c.accent, width: 2 },
        { label: "eval accuracy", scale: "acc", stroke: c.ink2, width: 1.5, dash: [4, 4] }
      ],
      legend: { show: true }
    };
    var data = [series.rounds, series.loss, series.acc];
    if (chart) { chart.destroy(); }
    el.innerHTML = "";
    chart = new uPlot(opts, data, el);
  }
  document.addEventListener("DOMContentLoaded", function () { bindToggle(); drawChart(); });
  document.addEventListener("htmx:afterSwap", function () { chart = null; drawChart(); });
  window.addEventListener("resize", function () { if (chart) { var el = document.getElementById("loss-chart"); chart.setSize({ width: Math.max(320, el.clientWidth), height: 220 }); } });
})();
