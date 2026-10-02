// Live SVG diagrams drawn from the JSON API and updated in place, so paths keep moving
// across refreshes. Two kinds: the network (coordinator, running jobs, machines) and a
// job's round (shards, trainers, aggregation, weights). Direction: DESIGN.md.
(function () {
  var NS = "http://www.w3.org/2000/svg";
  var W = 168, H = 72, GAPX = 18, GAPY = 84, PER_ROW = 6, PAD = 12;

  function el(tag, attrs, parent) {
    var node = document.createElementNS(NS, tag);
    for (var k in attrs) { if (attrs[k] !== undefined && attrs[k] !== null) node.setAttribute(k, attrs[k]); }
    if (parent) parent.appendChild(node);
    return node;
  }
  function text(node, value) { var v = value == null ? "" : String(value); if (node.textContent !== v) node.textContent = v; }
  function trunc(s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
  function pct(v) { return (v === undefined || v === null || v === "") ? "–" : Math.round(v) + " %"; }
  function fmt(v, digits) { return (v === undefined || v === null) ? "–" : Number(v).toFixed(digits); }

  async function getJSON(url) {
    var r = await fetch(url, { headers: { accept: "application/json" }, credentials: "same-origin" });
    if (!r.ok) throw new Error(r.status + " " + url);
    return r.json();
  }

  // Orthogonal path with rounded elbows, from the bottom port of one node to the top port of another.
  function elbow(x1, y1, x2, y2) {
    if (Math.abs(x1 - x2) < 1) return "M" + x1 + " " + y1 + " L" + x2 + " " + y2;
    var ym = (y1 + y2) / 2, r = 8, dir = x2 > x1 ? 1 : -1;
    return "M" + x1 + " " + y1 + " L" + x1 + " " + (ym - r) + " Q" + x1 + " " + ym + " " + (x1 + dir * r) + " " + ym +
      " L" + (x2 - dir * r) + " " + ym + " Q" + x2 + " " + ym + " " + x2 + " " + (ym + r) + " L" + x2 + " " + y2;
  }

  // A node is <a><g class="node ..."> with a fixed set of children; render() only updates attributes and text.
  function ensureNode(layer, id, href) {
    var a = layer.querySelector('[data-id="' + CSS.escape(id) + '"]');
    if (a) return a;
    a = el("a", { "data-id": id, href: href || "#", class: "node-link" }, layer);
    var g = el("g", { class: "node" }, a);
    el("rect", { class: "node-bg", width: W, height: H, rx: 8 }, g);
    el("rect", { class: "node-head", width: W, height: 22, rx: 8 }, g);
    el("rect", { class: "node-head-fill", width: W, height: 14, y: 8 }, g);
    el("text", { class: "node-kind", x: 10, y: 15 }, g);
    el("text", { class: "node-state", x: W - 10, y: 15, "text-anchor": "end" }, g);
    el("text", { class: "node-title", x: 10, y: 40 }, g);
    el("text", { class: "node-sub", x: 10, y: 56 }, g);
    el("rect", { class: "node-bar-bg", x: 10, y: 62, width: W - 20, height: 3, rx: 1.5 }, g);
    el("rect", { class: "node-bar", x: 10, y: 62, width: 0, height: 3, rx: 1.5 }, g);
    el("circle", { class: "port-pulse", cx: W / 2, cy: H, r: 4 }, g);
    el("circle", { class: "port", cx: W / 2, cy: H, r: 3.5 }, g);
    var title = el("title", {}, g);
    title.textContent = id;
    return a;
  }
  function setNode(a, opts) {
    var g = a.firstChild;
    g.setAttribute("class", "node " + (opts.cls || ""));
    g.setAttribute("transform", "translate(" + opts.x + " " + opts.y + ")");
    a.setAttribute("href", opts.href || "#");
    text(g.querySelector(".node-kind"), opts.kind);
    text(g.querySelector(".node-state"), opts.state);
    text(g.querySelector(".node-title"), trunc(opts.title, 22));
    text(g.querySelector(".node-sub"), trunc(opts.sub, 26));
    g.querySelector(".node-bar").setAttribute("width", Math.max(0, Math.min(1, opts.progress || 0)) * (W - 20));
    g.querySelector(".node-bar-bg").style.display = opts.progress === undefined ? "none" : "";
    g.querySelector(".node-bar").style.display = opts.progress === undefined ? "none" : "";
    g.querySelector("title").textContent = opts.tooltip || opts.title;
  }
  function ensurePath(layer, id) {
    var p = layer.querySelector('[data-id="' + CSS.escape(id) + '"]');
    if (!p) p = el("path", { "data-id": id, class: "flow", fill: "none" }, layer);
    return p;
  }
  function prune(layer, keep) {
    Array.prototype.slice.call(layer.children).forEach(function (c) {
      var id = c.getAttribute("data-id");
      if (id && !keep[id]) c.remove();
    });
  }
  function ready(container) {
    if (container.classList.contains("is-loading")) {
      container.classList.remove("is-loading");
      container.querySelectorAll(".skeleton").forEach(function (s) { s.remove(); });
    }
    var err = container.querySelector(".diagram-error");
    if (err) err.remove();
  }
  function failed(container, message) {
    var err = container.querySelector(".diagram-error");
    if (!err) { err = document.createElement("p"); err.className = "diagram-error"; container.appendChild(err); }
    err.textContent = "Live view unavailable: " + message + ". Retrying.";
  }

  // ----- network -----------------------------------------------------------------------
  function renderNetwork(svg, data) {
    var machines = data.fleet || [], jobs = data.jobs || [], summary = data.summary || {};
    var paths = svg.querySelector(".paths"), nodes = svg.querySelector(".nodes");
    var rows = Math.max(1, Math.ceil(machines.length / PER_ROW));
    var cols = Math.min(PER_ROW, Math.max(machines.length, jobs.length, 1));
    var width = PAD * 2 + cols * W + (cols - 1) * GAPX;
    var tiers = 2 + (jobs.length ? 1 : 0);
    var height = PAD * 2 + tiers * H + (tiers - 1) * GAPY + (rows - 1) * (H + 26);
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    var keepN = {}, keepP = {};

    var cx = width / 2 - W / 2, cy = PAD;
    var coord = ensureNode(nodes, "coordinator", "/server");
    var sched = summary.scheduler_running === false ? "stopped" : "live";
    setNode(coord, {
      x: cx, y: cy, cls: "node-coordinator", kind: "coordinator", state: sched, title: data.org || "plasmon",
      sub: (summary.online || 0) + " of " + (summary.machines || 0) + " online · " + (summary.rounds_last_hour || 0) + " rounds/h",
      tooltip: "The coordinator: rounds, aggregation, ledger",
    });
    keepN.coordinator = true;

    var jobPos = {};
    var jobsY = cy + H + GAPY;
    jobs.forEach(function (j, i) {
      var total = jobs.length, x = width / 2 - (total * W + (total - 1) * GAPX) / 2 + i * (W + GAPX);
      jobPos[j.id] = { x: x, y: jobsY };
      var trainers = machines.filter(function (m) { return m.current_job_id === j.id; }).length;
      var n = ensureNode(nodes, "job:" + j.id, "/jobs/" + j.id);
      setNode(n, {
        x: x, y: jobsY, cls: "node-job status-training", kind: "job", state: "round " + j.round + "/" + j.total_rounds, title: j.name,
        sub: trainers + " training · loss " + fmt(j.eval_loss, 3) + " · " + (j.eval_acc == null ? "–" : (j.eval_acc * 100).toFixed(1) + " %"),
        progress: j.total_rounds ? j.round / j.total_rounds : 0, tooltip: j.name + ": round " + j.round + " of " + j.total_rounds,
      });
      keepN["job:" + j.id] = true;
      var p = ensurePath(paths, "pj:" + j.id);
      p.setAttribute("d", elbow(x + W / 2, jobsY, cx + W / 2, cy + H));
      p.setAttribute("class", "flow flow-control");
      keepP["pj:" + j.id] = true;
    });

    var firstRowY = jobsY + (jobs.length ? H + GAPY : 0);
    machines.forEach(function (m, i) {
      var row = Math.floor(i / PER_ROW), col = i % PER_ROW;
      var inRow = Math.min(PER_ROW, machines.length - row * PER_ROW);
      var x = width / 2 - (inRow * W + (inRow - 1) * GAPX) / 2 + col * (W + GAPX);
      var y = firstRowY + row * (H + 26);
      var met = m.metrics || {}, gpu = (m.hardware || {}).gpu || {};
      var hasGpu = gpu.kind && gpu.kind !== "none";
      var sub = m.status === "training" && m.current_job_id
        ? "round " + m.current_round + (met.steps_total ? " · step " + met.step + "/" + met.steps_total : "")
        : (m.status_detail || (m.status === "idle" ? "waiting for a round" : m.status));
      var foot = "cpu " + pct(met.cpu_pct) + (hasGpu ? " · gpu " + pct(met.gpu_pct) : " · ram " + pct(met.ram_pct));
      var n = ensureNode(nodes, "m:" + m.node_id, "/machine/" + m.node_id);
      setNode(n, {
        x: x, y: y, cls: "node-machine status-" + m.status, kind: hasGpu ? trunc(gpu.name, 14) : "cpu", state: m.status, title: m.name || m.node_id.slice(0, 8),
        sub: sub + " · " + foot, progress: m.status === "training" && met.steps_total ? (met.step || 0) / met.steps_total : undefined,
        tooltip: (m.name || "") + " · " + m.status + (m.owner ? " · " + m.owner : ""),
      });
      keepN["m:" + m.node_id] = true;
      var target = (m.current_job_id && jobPos[m.current_job_id]) ? jobPos[m.current_job_id] : { x: cx, y: cy };
      var p = ensurePath(paths, "pm:" + m.node_id);
      // paths run upward: from this node's top port to the target's bottom port
      p.setAttribute("d", elbow(x + W / 2, y, target.x + W / 2, target.y + H));
      p.setAttribute("class", "flow flow-" + m.status);
      keepP["pm:" + m.node_id] = true;
    });
    prune(nodes, keepN);
    prune(paths, keepP);
  }

  function mountNetwork(container) {
    var svg = el("svg", { class: "diagram-svg", role: "img", "aria-label": "Network: coordinator, running jobs and machines", preserveAspectRatio: "xMidYMin meet" }, container);
    el("g", { class: "paths" }, svg);
    el("g", { class: "nodes" }, svg);
    var org = container.getAttribute("data-org") || "plasmon";
    async function tick() {
      try {
        var results = await Promise.all([
          getJSON("/v1/fleet"),
          getJSON("/v1/jobs?all=true").catch(function () { return getJSON("/v1/jobs"); }),
          getJSON("/v1/fleet/summary"),
          getJSON("/v1/server/status").catch(function () { return null; }),
        ]);
        var summary = results[2];
        if (results[3]) summary.scheduler_running = results[3].scheduler.running;
        renderNetwork(svg, { fleet: results[0], jobs: results[1].filter(function (j) { return j.status === "running"; }), summary: summary, org: org });
        ready(container);
      } catch (e) { failed(container, e.message); }
    }
    tick();
    setInterval(tick, 3000);
  }

  // ----- one job's round -----------------------------------------------------------------
  function renderJob(svg, job, updates) {
    var paths = svg.querySelector(".paths"), nodes = svg.querySelector(".nodes");
    var current = job.rounds.length ? job.rounds[job.rounds.length - 1] : null;
    var roundIndex = current ? current.index : 0;
    var ups = updates.filter(function (u) { return u.round === roundIndex; });
    var n = Math.max(ups.length, 1);
    var colX = [PAD, PAD + W + 60, PAD + 2 * (W + 60), PAD + 3 * (W + 60)];
    var height = PAD * 2 + Math.max(n * (H + 14) - 14, H);
    svg.setAttribute("viewBox", "0 0 " + (colX[3] + W + PAD) + " " + height);
    var mid = height / 2 - H / 2;
    var keepN = {}, keepP = {};

    var shards = ensureNode(nodes, "shards", "#");
    setNode(shards, { x: colX[0], y: mid, cls: "node-data", kind: "data", state: job.shards + " shards", title: job.spec.dataset.source.replace(/^.*\//, ""), sub: job.spec.dataset.shard_size + " samples each", tooltip: "Data shards on the server" });
    keepN.shards = true;

    var agg = ensureNode(nodes, "agg", "#");
    var open = current && current.status === "open";
    setNode(agg, { x: colX[2], y: mid, cls: "node-coordinator" + (open ? "" : " node-done"), kind: "coordinator", state: current ? current.status : "–", title: "round " + roundIndex + " of " + job.total_rounds, sub: open ? ups.filter(function (u) { return u.status === "revealed"; }).length + " of " + ups.length + " updates in" : (current ? current.accepted + " accepted" : ""), tooltip: "Verification and aggregation" });
    keepN.agg = true;

    var theta = ensureNode(nodes, "theta", "/jobs/" + job.id + "/download");
    setNode(theta, { x: colX[3], y: mid, cls: "node-data" + (job.status === "completed" ? " status-training" : ""), kind: "weights", state: job.status, title: job.param_count ? job.param_count.toLocaleString() + " parameters" : "weights", sub: "loss " + fmt(job.eval_loss, 3) + " · acc " + (job.eval_acc == null ? "–" : (job.eval_acc * 100).toFixed(1) + " %"), tooltip: "Download the latest weights" });
    keepN.theta = true;
    var pt = ensurePath(paths, "p:agg-theta");
    pt.setAttribute("d", "M" + (colX[2] + W) + " " + (mid + H / 2) + " L" + colX[3] + " " + (mid + H / 2));
    pt.setAttribute("class", "flow " + (open ? "flow-control" : "flow-training-static"));
    keepP["p:agg-theta"] = true;

    if (!ups.length) {
      var waiting = ensureNode(nodes, "waiting", "#");
      setNode(waiting, { x: colX[1], y: mid, cls: "node-machine status-unavailable", kind: "trainers", state: "waiting", title: "no trainer yet", sub: "machines join at the next heartbeat" });
      keepN.waiting = true;
    }
    ups.forEach(function (u, i) {
      var y = PAD + i * (H + 14);
      var st = u.status === "assigned" ? "unavailable" : u.status === "committed" ? "paused" : (u.status === "revealed" || u.status === "accepted") ? "training" : "offline";
      var id = "u:" + u.node;
      var nd = ensureNode(nodes, id, u.node.length === 64 ? "/machine/" + u.node : "#");
      setNode(nd, { x: colX[1], y: y, cls: "node-machine status-" + st, kind: "trainer", state: u.status, title: u.machine, sub: "shard " + u.shard + (u.loss_end != null ? " · loss " + fmt(u.loss_end, 3) : "") + (u.score != null ? " · score " + fmt(u.score, 3) : ""), tooltip: u.reject_reason || u.status });
      keepN[id] = true;
      var pin = ensurePath(paths, "pi:" + u.node);
      pin.setAttribute("d", "M" + (colX[0] + W) + " " + (mid + H / 2) + " C" + (colX[0] + W + 30) + " " + (mid + H / 2) + " " + (colX[1] - 30) + " " + (y + H / 2) + " " + colX[1] + " " + (y + H / 2));
      pin.setAttribute("class", "flow " + (u.status === "assigned" && open ? "flow-training" : "flow-unavailable"));
      keepP["pi:" + u.node] = true;
      var pout = ensurePath(paths, "po:" + u.node);
      pout.setAttribute("d", "M" + (colX[1] + W) + " " + (y + H / 2) + " C" + (colX[1] + W + 30) + " " + (y + H / 2) + " " + (colX[2] - 30) + " " + (mid + H / 2) + " " + colX[2] + " " + (mid + H / 2));
      var cls = u.status === "committed" ? "flow-paused" : (u.status === "revealed" && open) ? "flow-training" : u.status === "accepted" ? "flow-training-static" : u.status === "rejected" || u.status === "expired" ? "flow-offline" : "flow-unavailable";
      pout.setAttribute("class", "flow " + cls);
      keepP["po:" + u.node] = true;
    });
    prune(nodes, keepN);
    prune(paths, keepP);
  }

  function mountJob(container) {
    var jobId = container.getAttribute("data-job");
    var svg = el("svg", { class: "diagram-svg", role: "img", "aria-label": "This job's round: shards, trainers, aggregation, weights", preserveAspectRatio: "xMidYMin meet" }, container);
    el("g", { class: "paths" }, svg);
    el("g", { class: "nodes" }, svg);
    var stopped = false;
    async function tick() {
      try {
        var results = await Promise.all([getJSON("/v1/jobs/" + jobId), getJSON("/v1/jobs/" + jobId + "/updates")]);
        renderJob(svg, results[0], results[1]);
        ready(container);
        if (results[0].status !== "running") stopped = true;
      } catch (e) { failed(container, e.message); }
    }
    tick();
    var timer = setInterval(function () { if (stopped) { clearInterval(timer); return; } tick(); }, 3000);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll('[data-diagram="network"]').forEach(mountNetwork);
    document.querySelectorAll('[data-diagram="job"]').forEach(mountJob);
    document.body.classList.add("is-loaded");
  });
})();
