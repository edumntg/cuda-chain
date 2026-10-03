// Live diagrams in the PlanetScale cluster-view style: compact HTML nodes with a header,
// a body and a monospaced footer; port dots; group boxes with stacked borders and a
// status pill; 1 px SVG wires measured from the DOM. Wires follow a trunk-and-bus scheme
// so no two colours share a segment: one trunk from the coordinator to a horizontal bus,
// one drop per group, corridors between groups for later rows. Marching ants mark the
// wires that carry data right now. Data comes from the JSON API and is reconciled in
// place every 3 s. Direction: DESIGN.md.
(function () {
  var SVG = "http://www.w3.org/2000/svg";

  function h(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function icon(name, cls) {
    var s = document.createElementNS(SVG, "svg");
    s.setAttribute("class", "ps-ico " + (cls || ""));
    s.setAttribute("width", "14"); s.setAttribute("height", "14"); s.setAttribute("aria-hidden", "true");
    var u = document.createElementNS(SVG, "use");
    u.setAttribute("href", "#i-" + name);
    s.appendChild(u);
    return s;
  }
  function setText(node, value) { var v = value == null ? "" : String(value); if (node.textContent !== v) node.textContent = v; }
  function pct(v) { return (v === undefined || v === null || v === "") ? "–" : Math.round(v) + "%"; }
  function fmt(v, d) { return (v === undefined || v === null) ? "–" : Number(v).toFixed(d); }
  function trunc(s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
  function osIcon(m) {
    var os = ((m.hardware || {}).os || "").toLowerCase();
    var gpu = (m.hardware || {}).gpu || {};
    if (gpu.kind === "cuda") return "gpu";
    if (os.indexOf("darwin") >= 0 || os.indexOf("mac") >= 0) return "apple";
    if (os.indexOf("windows") >= 0) return "windows";
    if (os.indexOf("linux") >= 0) return "linux";
    return "pc";
  }
  async function getJSON(url) {
    var r = await fetch(url, { headers: { accept: "application/json" }, credentials: "same-origin" });
    if (!r.ok) throw new Error(r.status + " " + url);
    return r.json();
  }

  // ----- node: one compact box, reconciled by id so nothing flickers ---------------------
  function nodeEl(parent, id, href) {
    var a = parent.querySelector(':scope > [data-id="' + CSS.escape(id) + '"]');
    if (a) return a;
    a = h("a", "ps-node"); a.dataset.id = id; a.href = href || "#";
    var body = h("div", "ps-body");
    var ic = h("div", "ps-icon"); ic.appendChild(icon("pc")); body.appendChild(ic);
    var txt = h("div", "ps-text"); txt.appendChild(h("span", "ps-title")); txt.appendChild(h("span", "ps-sub")); body.appendChild(txt);
    a.appendChild(body);
    var foot = h("div", "ps-foot mono");
    foot.appendChild(h("span", "ps-foot-l"));
    foot.appendChild(h("span", "ps-kvs"));
    a.appendChild(foot);
    parent.appendChild(a);
    return a;
  }
  function port(node, id, side) {
    var p = node.querySelector('[data-port="' + CSS.escape(id + ":" + side) + '"]');
    if (!p) { p = h("span", "ps-port ps-port-" + side); p.dataset.port = id + ":" + side; node.appendChild(p); }
    return p;
  }
  function setNode(a, o) {
    a.className = "ps-node status-" + (o.status || "none") + (o.extra ? " " + o.extra : "");
    if (o.href) a.href = o.href; else a.removeAttribute("href");
    a.title = o.tooltip || o.title || "";
    var use = a.querySelector(".ps-icon use");
    if (use.getAttribute("href") !== "#i-" + o.icon) use.setAttribute("href", "#i-" + o.icon);
    setText(a.querySelector(".ps-title"), trunc(o.title, 18));
    setText(a.querySelector(".ps-sub"), trunc(o.sub, 24));
    setText(a.querySelector(".ps-foot-l"), o.footLeft || "");
    var kvs = a.querySelector(".ps-kvs");
    var want = o.kv || [];
    while (kvs.children.length > want.length) kvs.lastChild.remove();
    want.forEach(function (pair, i) {
      var el = kvs.children[i];
      if (!el) { el = h("span", "ps-kv"); el.appendChild(h("span", "muted")); el.appendChild(h("b")); kvs.appendChild(el); }
      setText(el.firstChild, pair[0] + ":"); setText(el.lastChild, pair[1]);
    });
    (o.ports || []).forEach(function (side) { port(a, a.dataset.id, side); });
  }

  // ----- group: a bordered box with stacked shadows and a status pill ----------------------
  function groupEl(parent, id) {
    var g = parent.querySelector(':scope > [data-id="' + CSS.escape(id) + '"]');
    if (g) return g;
    g = h("div", "ps-group-wrap"); g.dataset.id = id;
    g.appendChild(h("div", "ps-stack ps-stack-2")); g.appendChild(h("div", "ps-stack ps-stack-1"));
    var box = h("div", "ps-group");
    var p = h("span", "ps-port ps-port-top ps-group-port"); p.dataset.port = id + ":top"; box.appendChild(p);
    box.appendChild(h("div", "ps-group-nodes"));
    var pill = h("a", "ps-pill"); pill.appendChild(h("span", "ps-pill-name")); pill.appendChild(h("span", "ps-pill-sep", "·")); pill.appendChild(h("span", "ps-pill-state")); box.appendChild(pill);
    g.appendChild(box);
    parent.appendChild(g);
    return g;
  }
  function setGroup(g, o) {
    g.className = "ps-group-wrap status-" + (o.status || "none");
    var pill = g.querySelector(".ps-pill");
    if (o.href) pill.href = o.href; else pill.removeAttribute("href");
    pill.title = o.tooltip || "";
    setText(pill.querySelector(".ps-pill-name"), trunc(o.name, 24));
    setText(pill.querySelector(".ps-pill-state"), o.state || "");
    g.querySelector(".ps-group-port").style.display = o.port === false ? "none" : "";
  }
  function prune(parent, keep) {
    Array.prototype.slice.call(parent.children).forEach(function (c) { var id = c.dataset && c.dataset.id; if (id && !keep[id]) c.remove(); });
  }

  // ----- wires -------------------------------------------------------------------------------
  // An orthogonal polyline with rounded bends. Consecutive equal points collapse.
  function poly(pts) {
    var p = [];
    pts.forEach(function (q) { if (!q) return; var l = p[p.length - 1]; if (!l || Math.abs(l.x - q.x) > 0.5 || Math.abs(l.y - q.y) > 0.5) p.push(q); });
    if (p.length < 2) return null;
    function f(n) { return Math.round(n * 2) / 2; }
    var d = "M" + f(p[0].x) + " " + f(p[0].y);
    for (var i = 1; i < p.length - 1; i++) {
      var a = p[i - 1], b = p[i], c = p[i + 1];
      var lab = Math.hypot(b.x - a.x, b.y - a.y), lbc = Math.hypot(c.x - b.x, c.y - b.y);
      var r = Math.min(4, lab / 2, lbc / 2);
      var p1 = { x: b.x - (b.x - a.x) / lab * r, y: b.y - (b.y - a.y) / lab * r };
      var p2 = { x: b.x + (c.x - b.x) / lbc * r, y: b.y + (c.y - b.y) / lbc * r };
      d += " L" + f(p1.x) + " " + f(p1.y) + " Q" + f(b.x) + " " + f(b.y) + " " + f(p2.x) + " " + f(p2.y);
    }
    var z = p[p.length - 1];
    return d + " L" + f(z.x) + " " + f(z.y);
  }
  // wires: [{ id, cls, d: function (P) -> path string or null }]. P(portId) gives a port's
  // centre relative to the container; P.rect(el) a box; P.width the container width.
  function drawWires(container, wires) {
    var svg = container.querySelector(":scope > .ps-wires");
    if (!svg) { svg = document.createElementNS(SVG, "svg"); svg.setAttribute("class", "ps-wires"); svg.setAttribute("aria-hidden", "true"); container.insertBefore(svg, container.firstChild); }
    var rect = container.getBoundingClientRect(), ox = rect.left + container.clientLeft, oy = rect.top + container.clientTop;
    svg.setAttribute("width", container.clientWidth); svg.setAttribute("height", container.clientHeight);
    svg.setAttribute("viewBox", "0 0 " + container.clientWidth + " " + container.clientHeight);
    function P(id) {
      var el = container.querySelector('[data-port="' + CSS.escape(id) + '"]');
      if (!el || el.offsetParent === null) return null;
      var r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2 - ox, y: r.top + r.height / 2 - oy };
    }
    P.rect = function (el) { var r = el.getBoundingClientRect(); return { left: r.left - ox, right: r.right - ox, top: r.top - oy, bottom: r.bottom - oy }; };
    P.width = container.clientWidth;
    var keep = {};
    wires.forEach(function (w) {
      var d = w.d(P);
      if (!d) return;
      var p = svg.querySelector('[data-id="' + CSS.escape(w.id) + '"]');
      if (!p) { p = document.createElementNS(SVG, "path"); p.dataset.id = w.id; p.setAttribute("fill", "none"); svg.appendChild(p); }
      if (p.getAttribute("d") !== d) p.setAttribute("d", d);
      var cls = "ps-wire " + (w.cls || "");
      if (p.getAttribute("class") !== cls) p.setAttribute("class", cls);
      keep[w.id] = true;
    });
    Array.prototype.slice.call(svg.children).forEach(function (c) { if (!keep[c.dataset.id]) c.remove(); });
  }
  function scheduleWires(root, wires) {
    root._wires = wires;
    requestAnimationFrame(function () { drawWires(root, wires); });
  }

  function ready(container) {
    container.classList.remove("is-loading");
    container.querySelectorAll(":scope > .skeleton, :scope > .skeleton-space").forEach(function (s) { s.remove(); });
    var e = container.querySelector(":scope > .diagram-error"); if (e) e.remove();
  }
  function failed(container, message) {
    var e = container.querySelector(":scope > .diagram-error");
    if (!e) { e = h("p", "diagram-error"); container.appendChild(e); }
    e.textContent = "Live view unavailable: " + message + ". Retrying.";
  }

  // ----- network ----------------------------------------------------------------------------
  function statusOfMachine(m) { return m.status === "idle" && m.current_job_id ? "training" : m.status; }
  function machineNode(parent, m, opts) {
    opts = opts || {};
    var met = m.metrics || {}, gpu = (m.hardware || {}).gpu || {}, hasGpu = gpu.kind && gpu.kind !== "none";
    var st = opts.status || statusOfMachine(m);
    var stepping = met.steps_total && met.step < met.steps_total;
    var sub = opts.sub || (st === "training" ? (stepping ? "round " + m.current_round + " · " + met.step + "/" + met.steps_total : (m.status_detail || "round " + m.current_round)) : (m.status_detail || (st === "idle" ? "waiting for a round" : st)));
    var n = nodeEl(parent, "m:" + m.node_id, "/machine/" + m.node_id);
    setNode(n, {
      status: st, icon: osIcon(m), title: m.name || m.node_id.slice(0, 8), sub: sub, href: "/machine/" + m.node_id,
      footLeft: hasGpu ? (gpu.kind === "mps" ? "mps" : "cuda") : "cpu",
      kv: hasGpu ? [["CPU", pct(met.cpu_pct)], ["GPU", pct(met.gpu_pct)]] : [["CPU", pct(met.cpu_pct)], ["Mem", pct(met.ram_pct)]],
      tooltip: opts.tooltip || ((m.name || "") + " · " + st + (hasGpu ? " · " + gpu.name : "") + (m.owner ? " · " + m.owner : "")), ports: ["top"],
    });
    return n;
  }
  function wireClass(st) {
    return st === "training" ? "ps-wire-active ps-ants" : st === "paused" ? "ps-wire-paused" : (st === "offline" || st === "error") ? "ps-wire-down" : "ps-wire-idle";
  }
  // Rows of boxes by top edge, for the corridor routing.
  function rowsOf(rects) {
    var rows = [];
    rects.forEach(function (r) {
      var row = null;
      rows.forEach(function (rw) { if (Math.abs(rw.top - r.top) < 6) row = rw; });
      if (!row) { row = { top: r.top, bottom: r.bottom, rects: [] }; rows.push(row); }
      row.rects.push(r); row.bottom = Math.max(row.bottom, r.bottom);
    });
    rows.sort(function (a, b) { return a.top - b.top; });
    return rows;
  }
  function rowOf(rows, y) { for (var i = 0; i < rows.length; i++) if (Math.abs(rows[i].top - y) < 6) return i; return 0; }
  // A free vertical corridor above row r, nearest to x: the outer margins or a gap between boxes.
  function corridor(rows, r, x, left, right, pad) {
    var spans = [];
    for (var i = 0; i < r; i++) rows[i].rects.forEach(function (q) { spans.push([q.left - pad, q.right + pad]); });
    spans.sort(function (a, b) { return a[0] - b[0]; });
    var merged = [];
    spans.forEach(function (s) { var l = merged[merged.length - 1]; if (l && s[0] <= l[1]) l[1] = Math.max(l[1], s[1]); else merged.push(s.slice()); });
    if (!merged.length) return x;
    // Hug the boxes above: just outside the first and the last one, or in a gap between two.
    var cands = [Math.max(left, merged[0][0]), Math.min(right, merged[merged.length - 1][1])];
    for (var k = 0; k + 1 < merged.length; k++) if (merged[k + 1][0] - merged[k][1] >= 2) cands.push((merged[k][1] + merged[k + 1][0]) / 2);
    var best = cands[0];
    cands.forEach(function (c) { if (Math.abs(c - x) < Math.abs(best - x)) best = c; });
    return best;
  }
  // Route from a bus at busY down to a port, through a corridor when the port is in a later row.
  function dropPath(rows, busY, pt, left, right, pad, rowGap) {
    var r = rowOf(rows, pt.y + 4);
    if (r === 0) return { x: pt.x, pts: [{ x: pt.x, y: busY }, pt] };
    var cx = corridor(rows, r, pt.x, left, right, pad), rowBus = rows[r].top - rowGap;
    return { x: cx, pts: [{ x: cx, y: busY }, { x: cx, y: rowBus }, { x: pt.x, y: rowBus }, pt] };
  }
  function renderNetwork(root, data) {
    var machines = data.fleet || [], jobs = data.jobs || [], summary = data.summary || {}, me = data.me || {};
    var tiers = root.querySelector(":scope > .ps-tiers");
    if (!tiers) { tiers = h("div", "ps-tiers"); root.appendChild(tiers); tiers.appendChild(h("div", "ps-tier ps-tier-top")); tiers.appendChild(h("div", "ps-tier ps-tier-groups")); }
    var top = tiers.children[0], groupsRow = tiers.children[1];

    // coordinator: a node with a header strip, like PlanetScale's router
    var c = top.querySelector('[data-id="coord"]');
    if (!c) {
      c = h("a", "ps-node ps-router"); c.dataset.id = "coord"; c.href = "/";
      var head = h("div", "ps-head"); var hl = h("span", "ps-head-l"); hl.appendChild(icon("server", "accent")); hl.appendChild(h("b", "", "Coordinator")); head.appendChild(hl);
      head.appendChild(h("span", "ps-head-r")); c.appendChild(head);
      var body = h("div", "ps-body ps-body-split");
      var left = h("div", "ps-text"); var tl = h("span", "ps-title-row"); tl.appendChild(h("b", "ps-title")); tl.appendChild(h("span", "ps-count")); left.appendChild(tl); left.appendChild(h("span", "ps-sub")); body.appendChild(left);
      body.appendChild(h("div", "ps-squares")); c.appendChild(body);
      var foot = h("div", "ps-foot mono"); foot.appendChild(h("span", "ps-foot-l")); foot.appendChild(h("span", "ps-kvs")); c.appendChild(foot);
      var cp = h("span", "ps-port ps-port-bottom"); cp.dataset.port = "coord:bottom"; c.appendChild(cp);
      top.appendChild(c);
    }
    var role = (me.user || {}).role || "member";
    var hrr = c.querySelector(".ps-head-r");
    var wantLinks = (role === "owner" || role === "admin" || role === "operator") ? [["graph", "/server", "Server status"], ["gear", "/settings", "Settings"]] : [];
    if (hrr.children.length !== wantLinks.length) {
      hrr.innerHTML = "";
      wantLinks.forEach(function (l) { var a = h("a", "ps-head-btn"); a.href = l[1]; a.title = l[2]; a.setAttribute("aria-label", l[2]); a.appendChild(icon(l[0])); hrr.appendChild(a); });
    }
    var scheduler = summary.scheduler_running === false ? "stopped" : "running";
    c.className = "ps-node ps-router status-" + (scheduler === "running" ? "training" : "error");
    setText(c.querySelector(".ps-title"), data.org || "plasmon");
    setText(c.querySelector(".ps-count"), String(summary.online || 0));
    setText(c.querySelector(".ps-sub"), (summary.machines || 0) + " machines · " + jobs.length + " job" + (jobs.length === 1 ? "" : "s"));
    setText(c.querySelector(".ps-foot-l"), "scheduler " + scheduler);
    var kvs = c.querySelector(".ps-kvs");
    if (!kvs.children.length) { var e1 = h("span", "ps-kv"); e1.appendChild(h("span", "muted", "rounds/h:")); e1.appendChild(h("b")); kvs.appendChild(e1); }
    setText(kvs.querySelector("b"), String(summary.rounds_last_hour || 0));
    var sq = c.querySelector(".ps-squares");
    var shown = machines.slice(0, 24);
    while (sq.children.length > shown.length) sq.lastChild.remove();
    shown.forEach(function (m, i) { var s = sq.children[i]; if (!s) { s = h("span", "ps-square"); sq.appendChild(s); } s.className = "ps-square status-" + statusOfMachine(m); s.title = (m.name || "") + ": " + statusOfMachine(m); });

    // groups: one per running job with the machines training it now or in its last two rounds,
    // then the available machines, then the offline or failed ones
    var keep = {}, groups = [], claimed = {}, fleetById = {}, membersOf = {};
    machines.forEach(function (m) { fleetById[m.node_id] = m; });
    jobs.forEach(function (j) { membersOf[j.id] = []; });
    machines.forEach(function (m) {
      if (m.current_job_id && membersOf[m.current_job_id]) { membersOf[m.current_job_id].push({ m: m, live: true }); claimed[m.node_id] = true; }
    });
    jobs.forEach(function (j) {
      (j.trainers || []).forEach(function (t) {
        if (claimed[t.node]) return;
        var inFlight = t.current && (t.status === "assigned" || t.status === "committed");
        var m = fleetById[t.node] || { node_id: t.node, name: t.name, status: inFlight ? "training" : "idle", hardware: {}, metrics: {}, status_detail: "" };
        membersOf[j.id].push({ m: m, live: inFlight, round: t.round });
        claimed[t.node] = true;
      });
    });
    jobs.forEach(function (j) {
      var id = "job:" + j.id, members = membersOf[j.id];
      var g = groupEl(groupsRow, id);
      var training = members.filter(function (x) { return x.live || (x.m.current_job_id === j.id && statusOfMachine(x.m) === "training"); }).map(function (x) { return x.m.node_id; });
      var active = training.length > 0;
      setGroup(g, { status: active ? "training" : "idle", name: j.name, state: "round " + j.round + "/" + j.total_rounds, href: "/jobs/" + j.id, tooltip: j.name + ": eval loss " + fmt(j.eval_loss, 3) });
      var nodes = g.querySelector(".ps-group-nodes"), keepM = {};
      if (!members.length) {
        var w = nodeEl(nodes, "wait:" + j.id, "/jobs/" + j.id);
        setNode(w, { status: "unavailable", icon: "clock", title: "waiting", sub: j.waiting_reason || "no trainer yet", tooltip: j.waiting_reason || "no trainer yet", href: "/jobs/" + j.id, kv: [["round", j.round + "/" + j.total_rounds]] });
        keepM["wait:" + j.id] = true;
      }
      members.forEach(function (x) {
        var isTraining = training.indexOf(x.m.node_id) >= 0;
        machineNode(nodes, x.m, isTraining ? {} : { status: "idle", sub: "between rounds", tooltip: (x.m.name || "") + " · between rounds" + (x.round != null ? " · round " + x.round + " done" : "") });
        keepM["m:" + x.m.node_id] = true;
      });
      prune(nodes, keepM);
      keep[id] = true;
      groups.push({ id: id, cls: active ? "ps-wire-active ps-ants" : "ps-wire-control", members: members.map(function (x) { return x.m; }), training: training });
    });
    var available = machines.filter(function (m) { return !claimed[m.node_id] && ["idle", "paused", "unavailable"].indexOf(m.status) >= 0; });
    var down = machines.filter(function (m) { return !claimed[m.node_id] && ["offline", "error"].indexOf(m.status) >= 0; });
    [["available", available, available.filter(function (m) { return m.status === "idle"; }).length + " idle", "idle", "ps-wire-idle"],
     ["offline", down, down.length + " down", "offline", "ps-wire-down"]].forEach(function (spec) {
      var id = spec[0], list = spec[1];
      if (!list.length) return;
      var g = groupEl(groupsRow, id);
      setGroup(g, { status: spec[3], name: id === "available" ? "available" : "offline or error", state: spec[2], href: "/fleet" });
      var nodes = g.querySelector(".ps-group-nodes"), keepM = {};
      list.forEach(function (m) { machineNode(nodes, m); keepM["m:" + m.node_id] = true; });
      prune(nodes, keepM);
      keep[id] = true;
      groups.push({ id: id, cls: spec[4], members: list });
    });
    if (!machines.length && !jobs.length) {
      var g0 = groupEl(groupsRow, "empty");
      setGroup(g0, { status: "unavailable", name: "no machines yet", state: "waiting", href: "/machine" });
      var n0 = nodeEl(g0.querySelector(".ps-group-nodes"), "empty:node", "/machine");
      setNode(n0, { status: "unavailable", icon: "pc", title: "plasmon trainer start", sub: "on a PC you lend", href: "/machine", kv: [] });
      keep.empty = true;
      groups.push({ id: "empty", cls: "ps-wire-idle", members: [] });
    }
    prune(groupsRow, keep);

    // wires: trunk, bus, one drop per group, one short drop per machine inside its group
    var anyTraining = groups.some(function (g) { return (g.training || []).length > 0; });
    var wires = [];
    function layout(P) {
      var c0 = P("coord:bottom");
      var rects = Array.prototype.map.call(groupsRow.querySelectorAll(":scope > .ps-group-wrap > .ps-group"), P.rect);
      var rows = rowsOf(rects);
      if (!c0 || !rows.length) return null;
      var busY = rows[0].top - 22, xs = [c0.x], drops = [];
      groups.forEach(function (g) {
        var pt = P(g.id + ":top"); if (!pt) return;
        var d = dropPath(rows, busY, pt, 6, P.width - 6, 11, 14);
        xs.push(d.x); drops.push({ g: g, pts: d.pts });
      });
      return { c0: c0, busY: busY, minX: Math.min.apply(null, xs), maxX: Math.max.apply(null, xs), drops: drops };
    }
    wires.push({ id: "trunk", cls: anyTraining ? "ps-wire-active ps-ants" : "ps-wire-bus", d: function (P) { var L = layout(P); return L && poly([L.c0, { x: L.c0.x, y: L.busY }]); } });
    wires.push({ id: "bus", cls: anyTraining ? "ps-wire-active" : "ps-wire-bus", d: function (P) { var L = layout(P); return L && L.minX < L.maxX - 0.5 ? poly([{ x: L.minX, y: L.busY }, { x: L.maxX, y: L.busY }]) : null; } });
    groups.forEach(function (g) {
      wires.push({ id: "drop:" + g.id, cls: g.cls, d: function (P) { var L = layout(P); if (!L) return null; var d = null; L.drops.forEach(function (x) { if (x.g === g) d = poly(x.pts); }); return d; } });
      // inside the group: a short bus under the top edge, one drop per machine, corridors for later rows
      var gEl = groupsRow.querySelector(':scope > [data-id="' + CSS.escape(g.id) + '"]');
      function inner(P) {
        var a = P(g.id + ":top"), box = gEl && gEl.querySelector(".ps-group"); if (!a || !box) return null;
        var b = P.rect(box), rows = rowsOf(Array.prototype.map.call(gEl.querySelectorAll(".ps-node"), P.rect));
        return { a: a, busY: a.y + 8, rows: rows, left: b.left + 6, right: b.right - 6 };
      }
      g.members.forEach(function (m) {
        wires.push({ id: "in:" + g.id + ":" + m.node_id, cls: (g.training || []).indexOf(m.node_id) >= 0 ? "ps-wire-active ps-ants" : wireClass(statusOfMachine(m)), d: function (P) {
          var L = inner(P), pt = P("m:" + m.node_id + ":top"); if (!L || !pt) return null;
          var d = dropPath(L.rows, L.busY, pt, L.left, L.right, 5, 5);
          return poly([L.a, { x: L.a.x, y: L.busY }].concat(d.pts));
        } });
      });
    });
    scheduleWires(root, wires);
  }

  function mountNetwork(root) {
    var org = root.getAttribute("data-org") || "plasmon";
    async function tick() {
      try {
        var r = await Promise.all([
          getJSON("/v1/fleet"),
          getJSON("/v1/jobs?all=true").catch(function () { return getJSON("/v1/jobs"); }),
          getJSON("/v1/fleet/summary"),
          getJSON("/v1/auth/me").catch(function () { return {}; }),
          getJSON("/v1/server/status").catch(function () { return null; }),
        ]);
        var summary = r[2]; if (r[4]) summary.scheduler_running = r[4].scheduler.running;
        ready(root);
        renderNetwork(root, { fleet: r[0], jobs: r[1].filter(function (j) { return j.status === "running"; }), summary: summary, me: r[3], org: org });
      } catch (e) { failed(root, e.message); }
    }
    tick(); setInterval(tick, 3000);
    new ResizeObserver(function () { if (root._wires) drawWires(root, root._wires); }).observe(root);
  }

  // ----- one job's round: data → trainers → aggregation → weights --------------------------
  function renderJob(root, job, updates, icons) {
    var row = root.querySelector(":scope > .ps-flow");
    if (!row) {
      row = h("div", "ps-flow"); root.appendChild(row);
      ["data", "trainers", "agg", "weights"].forEach(function (k) { var col = h("div", "ps-col ps-col-" + k); col.dataset.col = k; row.appendChild(col); });
    }
    var cols = {}; Array.prototype.forEach.call(row.children, function (c) { cols[c.dataset.col] = c; });
    var current = job.rounds.length ? job.rounds[job.rounds.length - 1] : null, ri = current ? current.index : 0;
    var open = !!(current && current.status === "open");
    var ups = updates.filter(function (u) { return u.round === ri; });
    // a round that just opened has no updates yet: keep showing who trained the previous one
    var stale = false;
    if (!ups.length && ri > 0) { ups = updates.filter(function (u) { return u.round === ri - 1; }); stale = ups.length > 0; }

    var d = nodeEl(cols.data, "data");
    setNode(d, { status: "none", icon: "db", title: job.spec.dataset.source.replace(/^.*[\/]/, "") || "data", sub: job.shards + " shards", footLeft: "shards", kv: [["size", String(job.spec.dataset.shard_size)]], extra: "ps-static", ports: ["right"] });

    var g = groupEl(cols.trainers, "round");
    var revealed = ups.filter(function (u) { return ["revealed", "accepted"].indexOf(u.status) >= 0; }).length;
    var pillState = stale ? "starting · " + ups.length + " from round " + (ri - 1) : open ? (ups.length ? revealed + "/" + ups.length + " updates in" : "waiting") : (current ? current.accepted + " accepted" : "–");
    setGroup(g, { status: stale ? "idle" : open ? (ups.length ? "training" : "unavailable") : "idle", name: "round " + ri, state: pillState, port: false });
    var tn = g.querySelector(".ps-group-nodes"), keepT = {}; tn.classList.add("ps-vertical");
    if (!ups.length) {
      var w = nodeEl(tn, "wait"); setNode(w, { status: "unavailable", icon: "clock", title: "no trainer yet", sub: job.waiting_reason || "joins at next heartbeat", tooltip: job.waiting_reason || "", kv: [] }); keepT.wait = true;
    }
    ups.forEach(function (u) {
      var st = stale ? "idle" : u.status === "assigned" ? "unavailable" : u.status === "committed" ? "paused" : (u.status === "revealed" || u.status === "accepted") ? "training" : "offline";
      var id = "u:" + u.node, href = u.node.length === 64 ? "/machine/" + u.node : null;
      var n = nodeEl(tn, id, href);
      setNode(n, { status: st, icon: icons[u.node] || "pc", title: u.machine, sub: stale ? "round " + u.round + " done · shard " + u.shard : u.status + " · shard " + u.shard, href: href, footLeft: "loss " + fmt(u.loss_end, 3), kv: [["score", fmt(u.score, 3)]], tooltip: u.reject_reason || u.status, ports: ["left", "right"] });
      keepT[id] = true;
    });
    prune(tn, keepT);

    var a = nodeEl(cols.agg, "agg");
    setNode(a, { status: open ? "training" : "idle", icon: "server", title: "aggregate", sub: open ? "waiting for updates" : (current ? current.accepted + " accepted" : ""), footLeft: "verify", kv: current && current.timings && current.timings.aggregate_s != null ? [["agg", current.timings.aggregate_s + "s"]] : [], extra: "ps-router-sm ps-static", ports: ["left", "right"] });

    var t = nodeEl(cols.weights, "theta", "/jobs/" + job.id + "/download");
    setNode(t, { status: job.status === "completed" ? "training" : "none", icon: "weights", title: "weights", sub: (job.param_count || 0).toLocaleString() + " params", href: "/jobs/" + job.id + "/download", footLeft: "eval", kv: [["loss", fmt(job.eval_loss, 3)], ["acc", job.eval_acc == null ? "–" : (job.eval_acc * 100).toFixed(1) + "%"]], tooltip: "Download the latest weights", ports: ["left"] });

    // wires: data → bus → each trainer; each trainer → bus → aggregate; aggregate → weights
    var wires = [];
    var inCls = function (u) { return !stale && u.status === "assigned" && open ? "ps-wire-active ps-ants" : "ps-wire-idle"; };
    var outCls = function (u) {
      if (stale) return "ps-wire-idle";
      return u.status === "committed" ? "ps-wire-paused ps-ants" : (u.status === "revealed" && open) ? "ps-wire-active ps-ants" : u.status === "accepted" ? "ps-wire-active" : (u.status === "rejected" || u.status === "expired") ? "ps-wire-down" : "ps-wire-idle";
    };
    var anyIn = !stale && open && ups.some(function (u) { return u.status === "assigned"; });
    var anyOut = !stale && open && ups.some(function (u) { return u.status === "committed" || u.status === "revealed"; });
    function busX(P, leftPort, rightPorts) {
      var l = P(leftPort); if (!l) return null;
      var rx = null; rightPorts.forEach(function (id) { var p = P(id); if (p && (rx === null || p.x < rx)) rx = p.x; });
      return rx === null ? null : { l: l, x: (l.x + rx) / 2 };
    }
    var leftPorts = ups.map(function (u) { return "u:" + u.node + ":left"; }), rightPorts = ups.map(function (u) { return "u:" + u.node + ":right"; });
    if (!ups.length) {
      wires.push({ id: "data-agg", cls: "ps-wire-idle", d: function (P) { var a0 = P("data:right"), b0 = P("agg:left"); return a0 && b0 && poly([a0, { x: (a0.x + b0.x) / 2, y: a0.y }, { x: (a0.x + b0.x) / 2, y: b0.y }, b0]); } });
    } else {
      wires.push({ id: "data-bus", cls: anyIn ? "ps-wire-active ps-ants" : "ps-wire-idle", d: function (P) {
        var B = busX(P, "data:right", leftPorts); if (!B) return null;
        var ys = [B.l.y]; leftPorts.forEach(function (id) { var p = P(id); if (p) ys.push(p.y); });
        return poly([B.l, { x: B.x, y: B.l.y }]) + " " + poly([{ x: B.x, y: Math.min.apply(null, ys) }, { x: B.x, y: Math.max.apply(null, ys) }]);
      } });
      ups.forEach(function (u) {
        wires.push({ id: "in:" + u.node, cls: inCls(u), d: function (P) { var B = busX(P, "data:right", leftPorts), p = P("u:" + u.node + ":left"); return B && p && poly([{ x: B.x, y: p.y }, p]); } });
        wires.push({ id: "out:" + u.node, cls: outCls(u), d: function (P) { var B = busX(P, "agg:left", rightPorts), p = P("u:" + u.node + ":right"); return B && p && poly([p, { x: B.x, y: p.y }]); } });
      });
      wires.push({ id: "bus-agg", cls: anyOut ? "ps-wire-active ps-ants" : "ps-wire-idle", d: function (P) {
        var B = busX(P, "agg:left", rightPorts); if (!B) return null;
        var ys = [B.l.y]; rightPorts.forEach(function (id) { var p = P(id); if (p) ys.push(p.y); });
        return poly([{ x: B.x, y: Math.min.apply(null, ys) }, { x: B.x, y: Math.max.apply(null, ys) }]) + " " + poly([{ x: B.x, y: B.l.y }, B.l]);
      } });
    }
    wires.push({ id: "agg-theta", cls: open ? "ps-wire-control" : "ps-wire-active", d: function (P) { var a0 = P("agg:right"), b0 = P("theta:left"); return a0 && b0 && poly([a0, b0]); } });
    scheduleWires(root, wires);
  }

  function mountJob(root) {
    var jobId = root.getAttribute("data-job"), stopped = false;
    async function tick() {
      try {
        var r = await Promise.all([getJSON("/v1/jobs/" + jobId), getJSON("/v1/jobs/" + jobId + "/updates"), getJSON("/v1/fleet").catch(function () { return []; })]);
        var icons = {}; r[2].forEach(function (m) { icons[m.node_id] = osIcon(m); });
        ready(root); renderJob(root, r[0], r[1], icons);
        if (r[0].status !== "running") stopped = true;
      } catch (e) { failed(root, e.message); }
    }
    tick();
    var timer = setInterval(function () { if (stopped) { clearInterval(timer); return; } tick(); }, 3000);
    new ResizeObserver(function () { if (root._wires) drawWires(root, root._wires); }).observe(root);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll('[data-diagram="network"]').forEach(mountNetwork);
    document.querySelectorAll('[data-diagram="job"]').forEach(mountJob);
    document.body.classList.add("is-loaded");
  });
})();
