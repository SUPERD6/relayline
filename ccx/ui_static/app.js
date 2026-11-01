/* ccx ui: draws what /api/data returns. A button whose ccx command the server allows (`run`) asks the server to
   prepare it, shows the exact command it answered and runs it only on a second click (K6); every other button,
   and every button in a snapshot, shows the command to copy. The page never sends a command, only which button.
   Every visible word comes from strings.json (one table, zh + en). Data (titles, summaries, file names) is
   always escaped: it may contain text written by others. No inline handlers: one delegated click listener. */
"use strict";
(function () {
  let STR = {zh: {}, en: {}};
  let LANG = "en", D = null, ALL = null, TOKEN = "", SNAP = false, OFFLINE = false, lastOk = 0, TESTS = false, HIDDEN = 0;
  let filt = "all", sel = null, expanded = {}, query = "", histOpen = {}, drawerSig = "", drawerStable = "", pending = null, chosen = null;
  let ACT = null, FLASH = null;     /* the one button being prepared / confirmed, and the last outcome line */
  let NEXT = null;                  /* after a verdict: the panel moved on to the next waiting piece ({sel, n}) */
  let LEADJUMP = "";                /* #/<project>/_lead: scroll to the project's lead panel once */
  let RUNLIST = null, RUNPAGE = null, RUNERR = "", RUNBUSY = false, RUNSTAMP = 0, RUNDIFF = null;
  let RUNFILTER = {project: "", status: "", date: "", until: ""};
  let RUNPAGE_NO = 0;
  let CHATDRAFT = "", CHATPROJECT = "", CHATPREP = null, CHATRESULT = null;
  let CHATGEN = 0;
  let CHATROLES = [], CHATROLEPROJECT = "";
  /* DeepSeek's own agent is shown with its command name (ccx handoff --to dsh, or deepseek); `deepseek` alone is
     the deepseek provider (Claude Code on DeepSeek's API) in run records, the DeepSeek session on the board */
  const KNOWN = {claude: "Claude", codex: "Codex", deepseek: "DeepSeek", dsh: "DeepSeek (dsh)", gemini: "Gemini"};
  const FIXED = {claude: "claude", codex: "codex", deepseek: "deepseek", dsh: "deepseek"};
  const SPARE = 4;
  const $ = (id) => document.getElementById(id);

  /* ---------- words ---------- */
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[c])); }
  function raw(h) { return {__html: h}; }
  /* t(key, params): params are data, so they are escaped unless wrapped with raw(); a missing key shows as [key] */
  function t(k, p) {
    if (p && p.n === 1 && (STR[LANG] || {})[k + "_1"] !== undefined) k += "_1";     // "1 piece", not "1 pieces"
    let s = (STR[LANG] || {})[k];
    if (s === undefined) s = (STR.en || {})[k];
    if (s === undefined) return "[" + esc(k) + "]";
    if (Array.isArray(s)) return s;
    if (p) for (const x in p) { const v = p[x]; s = s.split("{" + x + "}").join(v && v.__html !== undefined ? v.__html : esc(v)); }
    return s;
  }
  function chooseLang() {
    let saved = null;
    try { saved = localStorage.getItem("ccx-lang"); } catch (e) { /* private window */ }
    if (saved === "zh" || saved === "en") return saved;
    if (D && (D.lang === "zh" || D.lang === "en")) return D.lang;
    return (navigator.language || "en").toLowerCase().startsWith("zh") ? "zh" : "en";
  }

  /* ---------- numbers and times ---------- */
  function usd(x) { return x >= 0.995 ? "$" + x.toFixed(2) : x >= 0.0995 ? "$" + x.toFixed(3) : "$" + (x || 0).toFixed(4); }
  function tok(n) { return n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(n || 0); }
  function dur(s) {
    s = Math.max(0, Math.round(s || 0));
    if (s < 3600) return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
    return t("dur_h", {h: Math.floor(s / 3600), m: Math.floor((s % 3600) / 60)});
  }
  function clock(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000), now = new Date();
    const hm = String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
    if (d.toDateString() === now.toDateString()) return hm;
    const y = new Date(now); y.setDate(now.getDate() - 1);
    if (d.toDateString() === y.toDateString()) return t("yesterday", {h: hm});
    return t("date_hm", {m: d.getMonth() + 1, d: d.getDate(), h: hm});
  }
  /* seconds, minutes, hours up to two days, then days up to two weeks, then weeks ("9 days ago", not "216 h ago") */
  function ago(ts) {
    const s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 60) return t("ago_s", {n: Math.round(s)});
    if (s < 3600) return t("ago_m", {n: Math.round(s / 60)});
    if (s < 2 * 86400) return t("ago_h", {n: Math.round(s / 3600)});
    if (s < 14 * 86400) return t("ago_d", {n: Math.round(s / 86400)});
    return t("ago_w", {n: Math.round(s / 604800)});
  }

  /* ---------- agents: known colours fixed, any new one gets the next spare colour ---------- */
  function tone(agent) {
    if (FIXED[agent]) return FIXED[agent];
    const others = ((D && D.agents) || []).filter(a => !FIXED[a]);
    const i = others.indexOf(agent);
    return "x" + ((i < 0 ? others.length : i) % SPARE);
  }
  function agentName(a) { return KNOWN[a] || (a ? a.charAt(0).toUpperCase() + a.slice(1) : t("notyet")); }
  function who(agent, model) {
    if (!agent) return `<span class="who">${t("notyet")}</span>`;
    const c = tone(agent);
    return `<span class="who" style="background:var(--c-${c}-bg);color:var(--c-${c}-ink)">${esc(agentName(agent))}${model ? " · " + esc(model) : ""}</span>`;
  }

  /* ---------- walking the data ---------- */
  function walk(list, f, chain) { for (const p of list || []) { f(p, chain || []); if (p.children) walk(p.children, f, (chain || []).concat([p])); } }
  function acts(list) { const out = []; walk(list, (p, ch) => { if (p.act) out.push({p, chain: ch}); }); return out; }
  function below(p) { return acts(p.children || []).length; }
  /* evaluations, tests and dismissed leftovers (marked `test` by ccx ui) are left out unless asked for */
  function view(d) {
    HIDDEN = 0;
    if (!d || TESTS) return d;
    const prune = (list) => list.filter(p => { if (p.test) HIDDEN++; return !p.test; })
      .map(p => p.children ? Object.assign({}, p, {children: prune(p.children)}) : p);
    const projects = [];
    for (const pr of d.projects || []) {
      if (pr.test) { for (const tk of pr.tasks) walk(tk.pieces, () => HIDDEN++); continue; }
      const tasks = [];
      for (const tk of pr.tasks) {
        if (tk.test) { walk(tk.pieces, () => HIDDEN++); continue; }
        tasks.push(Object.assign({}, tk, {pieces: prune(tk.pieces)}));
      }
      if (tasks.length) projects.push(Object.assign({}, pr, {tasks}));
    }
    return Object.assign({}, d, {projects, leads: (d.leads || []).filter(l => !l.test),
                                 discussions: (d.discussions || []).filter(x => !x.test),
                                 conversations: (d.conversations || []).filter(x => !x.test)});
  }
  function findProject(id) { return ((D && D.projects) || []).find(x => x.id === id); }
  function findTask(pr, id) { return pr && pr.tasks.find(x => x.id === id); }
  function findPiece(list, id) { let hit = null; walk(list, (p, ch) => { if (p.id === id) hit = {p, chain: ch}; }); return hit; }
  function taskTitle(tk) { return tk.title || (tk.kind === "queue" ? t("queue_task") : t("untitled")); }
  function href(parts, s) { return "#/" + parts.map(encodeURIComponent).join("/") + (s ? "?sel=" + encodeURIComponent(s) : ""); }

  /* ---------- side bar ---------- */
  function quotaHTML() {
    const q = (D && D.quota) || [];
    if (!q.length) return `<div class="qnote">${t("q_none")}</div>`;
    return q.map(w => {
      const used = w.used == null ? null : Math.round(w.used * 100), pj = w.projected == null ? null : Math.round(w.projected * 100);
      const win = w.minutes === 300 || w.window === "five_hour" ? t("w_5h") : w.minutes === 10080 || w.window === "seven_day" ? t("w_7d") : w.minutes ? t("w_min", {n: Math.round(w.minutes / 60)}) : esc(w.window);
      let note = "";
      if (used == null) note = t("q_reset");
      else if (w.note) note = t("q_early");
      else note = `<span class="${pj > 100 ? "fail" : ""}">${t("q_proj", {p: pj})}</span>`;
      const reset = w.resets_at ? t("q_resets", {at: clock(w.resets_at)}) : "";
      return `<div class="qrow"><span>${esc(agentName(w.agent))} · ${win}</span><span>${used == null ? "—" : used + "%"}</span></div>
        <div class="qbar"><i style="width:${Math.min(100, used || 0)}%"></i>${pj != null && !w.note ? `<span class="pj" style="left:calc(${Math.min(100, pj)}% - 2px)"></span>` : ""}</div>
        <div class="qnote">${note}${reset ? " · " + reset : ""}</div>`;
    }).join("");
  }
  function renderSide(route) {
    const all = [];
    for (const pr of (D && D.projects) || []) for (const tk of pr.tasks) all.push(...acts(tk.pieces));
    all.push(...convTodos());
    let state = SNAP ? `<span class="dot snap"></span>${t("snapshot")}` : OFFLINE ? `<span class="dot off"></span>${t("offline")}` :
      `<span class="dot"></span>${D ? t("updated", {a: raw(ago(D.generated))}) : "…"}`;
    let h = `<div class="brand"><b>ccx</b><span style="color:var(--muted)">${t("now")}</span>${D && D.demo ? `<span class="demo-tag">${t("demo_tag")}</span>` : ""}<span class="live">${state}</span></div>
      <input class="search" id="search" placeholder="${esc(t("search"))}" value="${esc(query)}" aria-label="${esc(t("search"))}">
      <nav class="nav" id="nav"><a href="#/" class="${!route.length || route[0] === "map" ? "cur" : ""}">${t("map_nav")}</a><a href="#/all" class="${route[0] === "all" ? "cur" : ""}">${t("overview")}${all.length ? `<span class="badge">${all.length}</span>` : ""}</a>`;
    h += `<a href="#/tokens" class="${route[0] === "tokens" ? "cur" : ""}">${t("tok_nav")}</a>`;
    h += `<a href="/#/runs" class="${route[0] === "runs" ? "cur" : ""}">${t("runs_nav")}</a>`;
    const talks = (D && D.discussions) || [];
    if (talks.length) h += `<a href="#/discuss" class="${route[0] === "discuss" ? "cur" : ""}">${t("disc_nav")}<span class="mini-n">${talks.length}</span></a>`;
    for (const c of convs()) h += `<a href="${convHref(c.id)}" class="${route[0] === "conv" && route[1] === c.id ? "cur" : ""}">${t("conv_nav")} · ${esc(c.name)}${(c.todos || []).length ? `<span class="badge">${c.todos.length}</span>` : `<span class="mini-n">${c.threads}</span>`}</a>`;
    const q = query.toLowerCase();
    for (const pr of (D && D.projects) || []) {
      const need = pr.tasks.reduce((a, x) => a + acts(x.pieces).length, 0);
      const pmatch = !q || pr.name.toLowerCase().includes(q);
      let inner = "";
      for (const tk of pr.tasks) {
        const s = stats(tk.pieces), k = acts(tk.pieces).length, title = taskTitle(tk);
        const tmatch = !q || title.toLowerCase().includes(q) || pmatch;
        const hits = [];
        if (q) walk(tk.pieces, (p, ch) => { if ((p.title || "").toLowerCase().includes(q)) hits.push({p, ch}); });
        if (!tmatch && !hits.length) continue;
        inner += `<a class="task ${route[1] === tk.id && !route[2] ? "cur" : ""}" href="${href([pr.id, tk.id])}">${esc(title)}${k ? `<span class="badge">${k}</span>` : `<span class="mini"><i style="width:${s.n ? Math.round(100 * s.d / s.n) : 0}%"></i></span>`}</a>`;
        for (const {p, ch} of hits.slice(0, 8)) inner += `<a class="hit" href="${href([pr.id, tk.id].concat(ch.map(x => x.id)), p.id)}">↳ ${esc(p.title)}</a>`;
        if (route[0] === pr.id && route[1] === tk.id && !q) (function sub(list, depth) {
          for (const p of list) if (p.children) {
            const kk = below(p);
            inner += `<a class="sub ${route[route.length - 1] === p.id && route.length > 2 ? "cur" : ""}" style="padding-left:${22 + 16 * depth}px" href="${href(subPath(pr, tk, p))}">↳ ${esc(p.title)}${kk ? `<span class="badge">${kk}</span>` : ""}</a>`;
            sub(p.children, depth + 1);
          }
        })(tk.pieces, 1);
      }
      if (!pmatch && !inner) continue;
      h += `<a class="proj ${route[0] === pr.id && !route[1] ? "cur" : ""}" href="${href([pr.id])}" title="${esc(pr.path)}">▾ ${esc(pr.name)}${need ? `<span class="badge">${need}</span>` : ""}</a>` + inner;
    }
    h += `</nav><div class="foot"><div>${t("quota")}</div>${quotaHTML()}
      <div class="tools"><button data-do="lang">${t("lang_other")}</button><button data-do="theme">${t("theme")}</button>
      <button data-do="tests" aria-pressed="${TESTS}">${TESTS ? t("tests_hide") : t("tests_show", {n: HIDDEN})}</button></div></div>`;
    const side = $("side");
    const focused = document.activeElement && document.activeElement.id === "search";
    const pos = focused ? document.activeElement.selectionStart : null;
    side.innerHTML = h;
    if (focused) { const s = $("search"); s.focus(); try { s.setSelectionRange(pos, pos); } catch (e) { /* ok */ } }
  }
  function subPath(pr, tk, p) { const f = findPiece(tk.pieces, p.id); return [pr.id, tk.id].concat((f ? f.chain : []).map(x => x.id)).concat([p.id]); }
  function stats(list) { return {n: list.length, d: list.filter(p => p.status === "done").length}; }

  /* ---------- overview ---------- */
  function quotaWarn() {
    const bad = ((D && D.quota) || []).filter(w => w.used != null && !w.note && w.projected > 1).sort((a, b) => b.projected - a.projected)[0];
    return bad ? `<span class="warn">${t("ov_quota_bad", {a: agentName(bad.agent), p: Math.round(bad.projected * 100)})}</span>` : "";
  }
  /* an empty hub: what to do first, the same first command as README and `ccx setup`, then the demo if this ccx has it */
  function startHTML() {
    const s = (D && D.start) || {};
    if (!s.first) return "";
    const code = c => ({__html: `<code>${esc(c)}</code>`});
    return `<p class="start">${t("empty_first", {cmd: code(s.first)})}` +
      (s.demo ? `<br>${t("empty_demo", {cmd: code(s.demo)})}` : "") + `</p>`;
  }
  function renderOverview() {
    const todos = [];
    let running = 0, tasks = 0;
    for (const pr of D.projects) for (const tk of pr.tasks) {
      tasks++;
      walk(tk.pieces, (p, ch) => { if (p.status === "run") running++; if (p.act) todos.push({pr, tk, p, ch}); });
    }
    const ct = convTodos();
    let h = banner() + `<h1>${t("ov_title")}</h1>`;
    if (!tasks) {
      h += `<p class="lead">${t("empty")}</p>` + startHTML() + (ct.length ? `<h2>${t("todo_all")}</h2><div class="todo">${convTodoHTML(ct)}</div>` : "")
        + sugHTML() + leadsHTML() + discRecentHTML() + othersHTML() + weekHTML();
      return h;
    }
    const parts = [t("ov_running", {n: running})], nsug = (D && D.suggestions_total) || ((D && D.suggestions) || []).length;
    const nwait = todos.length + ct.length;
    parts.push(nwait ? `<span class="warn">${t("ov_waiting", {n: nwait})}</span>` : `<span class="good">${t("ov_nothing")}</span>`);
    if (nsug) parts.push(`<span class="warn">${t("ov_sug", {n: nsug})}</span>`);
    const qw = quotaWarn(); if (qw) parts.push(qw);
    if (D.inbox) parts.push(`<span class="warn">${t("ov_inbox", {n: D.inbox})}</span>`);
    h += `<p class="lead">${parts.join(" · ")}</p>`;
    if (nwait) {
      h += `<h2>${t("todo_all")}</h2><div class="todo">` + convTodoHTML(ct);
      todos.sort((a, b) => (a.p.act.kind === "review") - (b.p.act.kind === "review"));
      for (const x of todos) h += todoRow(x.p.act.kind === "review" ? "review" : "decide", href([x.pr.id, x.tk.id].concat(x.ch.map(c => c.id)), x.p.id),
        t(x.p.act.what), esc(x.p.title), esc(x.pr.name) + " › " + esc(cut(taskTitle(x.tk), 40)));
      h += `</div>`;
    }
    h += runningHTML() + sugHTML() + leadsHTML() + discRecentHTML();
    h += `<h2>${t("projects")}</h2><div class="grid">`;
    for (const pr of D.projects) {
      let n = 0, d = 0, need = 0; const ws = new Set();
      for (const tk of pr.tasks) { const s = stats(tk.pieces); n += s.n; d += s.d; need += acts(tk.pieces).length; walk(tk.pieces, p => { if (p.worker) ws.add(p.worker); }); }
      h += `<div class="pwrap"><a class="card pcard" href="${href([pr.id])}"><div class="top"><b>${esc(pr.name)}</b>${levelHTML(pr)}${need ? `<span class="badge">${t("needs_n", {n: need})}</span>` : ""}${(pr.rules || []).length ? `<span class="rulesb" title="${esc(t("rules_title"))}">${t("rules_n", {n: pr.rules.length})}</span>` : ""}</div>
        <div class="pbar"><i style="width:${n ? Math.round(100 * d / n) : 0}%"></i></div><div class="m">${t("tasks_pieces", {t: pr.tasks.length, d, n})}</div>
        <div class="whos">${[...ws].map(w => who(w)).join("")}</div></a>${leadLine(pr)}</div>`;
    }
    return h + `</div>` + othersHTML() + weekHTML();
  }
  /* one row of "Waiting for you": a chip for the kind (your call / check the result / a question for you, each its
     own colour), what the person has to do in bold, the agent's own words second (muted), then where. Every argument
     is HTML already: page strings from t(), data through esc() by the caller */
  const KCLS = {decide: "", review: "rv", answer: "ask"};
  function todoRow(kind, link, action, said, place) {
    return `<a class="${KCLS[kind]}" href="${link}"><span class="kchip k-${kind}">${t("k_" + kind)}</span><b>${action}</b>`
      + `<span class="said">${said}</span><span class="where">${place}</span></a>`;
  }
  function cut(s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
  /* U4: every run going on now, with its agent, time so far, tokens when known, and the piece's own stop button
     (the same prepare -> exact command -> second click as everywhere; a snapshot shows the command) */
  function runningHTML() {
    const rs = ((D && D.running) || []).filter(r => TESTS || !r.test);
    if (!rs.length) return "";
    let h = `<h2>${t("run_now")}</h2><div class="runs">`;
    for (const r of rs) {
      const key = r.project + "|" + r.task + "|" + r.piece;
      h += `<div class="runrow${r.stale ? " stale" : ""}"><div class="rt"><a href="${href([r.project, r.task], r.piece)}">${esc(r.title)}</a> ${who(r.worker, r.model)}</div>`
        + `<span class="rm"><span data-rsecs="${esc(r.piece)}">${t("run_for", {t: dur(r.secs)})}</span>${r.tokens ? " · " + t("run_tokens", {n: tok(r.tokens)}) : ""}${r.stale ? ` · <span class="warn">${t("run_stale")}</span>` : ""}</span>`;
      if (r.btn && !SNAP) h += `<button class="btn bad" data-rbtn="${esc(r.btn)}" data-key="${esc(key)}">${t("b_stop")}</button>`;
      else if (r.cmd) h += `<code class="mono">${esc(r.cmd)}</code>`;
      h += `<div class="cmd" data-actbox="${esc(key)}" hidden></div></div>`;
    }
    return h + `</div>`;
  }
  /* H5: notes ccx suggests keeping, each waiting for a yes or no (the page's one write; a snapshot shows the command) */
  const SUG_KINDS = {preference: "sug_preference", decision: "sug_decision", pitfall: "sug_pitfall"};
  function sugHTML() {
    const ss = (D && D.suggestions) || [];
    if (!ss.length) return "";
    let h = `<h2>${t("sug_title")}</h2><p class="stat">${t("sug_lead")}</p><div class="todo sug">`;
    for (const s of ss) {
      const id = esc(s.id), busy = sugBusy[s.id];
      h += `<div class="sugrow"><div><b>${esc(s.text)}</b><span class="where">${t(SUG_KINDS[s.kind] || "sug_other")} · ${esc(s.source || "")}</span></div>`;
      h += SNAP ? `<code>ccx mem accept ${id}</code>`
        : `<span class="acts"><button class="btn primary" data-sug="${id}" data-ok="1"${busy ? " disabled" : ""}>${t("sug_yes")}</button>`
          + `<button class="btn" data-sug="${id}" data-ok="0"${busy ? " disabled" : ""}>${t("sug_no")}</button></span>`;
      h += (busy === "err" ? `<span class="warn">${t("sug_failed")}</span>` : "") + `</div>`;
    }
    const more = ((D && D.suggestions_total) || 0) - ss.length;
    return h + `</div>` + (more > 0 ? `<p class="stat">${t("sug_more", {n: more})}</p>` : "");
  }
  const sugBusy = {};
  async function decideSug(id, ok) {
    sugBusy[id] = 1; render();
    try {
      await api("/api/suggestion", {method: "POST", headers: {"X-CCX-Token": TOKEN, "Content-Type": "application/json"},
                                    body: JSON.stringify({id: +id, accept: ok})});
      D.suggestions = (D.suggestions || []).filter(s => String(s.id) !== String(id));
      if (D.suggestions_total) D.suggestions_total--;
      delete sugBusy[id];
    } catch (e) { sugBusy[id] = "err"; }
    render();
  }
  function discRecentHTML() {
    const talks = (D && D.discussions) || [];
    return talks.length ? `<h2>${t("disc_recent")}</h2>` + discListHTML() : "";
  }
  function leadsHTML() {
    const ls = (D && D.leads) || [];
    if (!ls.length) return "";
    return `<h2>${t("leads_now")}</h2><div class="leads">` + ls.map(l => {
      const pr = projectAt(l.cwd), body = `${who(l.agent, l.model)} <span style="color:var(--muted);font-size:13px">${esc(shortPath(l.cwd))} · ${ago(l.last)}${l.helpers && l.helpers.length ? " · " + t("helpers_n", {n: l.helpers.length}) : ""}</span>`;
      return pr && pr.lead_switch ? `<a class="card" href="${leadHref(pr)}" title="${esc(t("ov_lead_switch"))}">${body}</a>` : `<div class="card">${body}</div>`;
    }).join("") + `</div>`;
  }
  /* U7 from the overview: who leads each project, a link to its switch-lead panel */
  function leadHref(pr) { return href([pr.id, "_lead"]); }
  function leadLine(pr) {
    const sw = pr.lead_switch; if (!sw) return "";
    const cur = sw.current ? t("ov_lead", {w: raw(who(sw.current))}) : t("ov_lead_none");
    return `<div class="leadline">${cur}${(sw.ctl || []).length ? ` · <a href="${leadHref(pr)}">${t("ov_lead_switch")}</a>` : ""}</div>`;
  }
  function normPath(p) { return String(p || "").replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase(); }
  function projectAt(cwd) {
    const c = normPath(cwd); if (!c) return null;
    return ((D && D.projects) || []).find(pr => { const r = normPath(pr.path); return r && (c === r || c.startsWith(r + "/")); }) || null;
  }
  function shortPath(p) { if (!p) return ""; const s = String(p).replace(/\\/g, "/").split("/").filter(Boolean); return s[s.length - 1] || p; }
  function weekHTML() {
    const w = (D && D.week) || {runs: 0};
    /* spend first (month, then week); a saving after it only once ccx trial measured one (P1-4) */
    let h = `<h2>${t("worth")}</h2>` + monthSpentHTML() + `<p class="stat">${t("week_spent", {u: usd(w.usd || 0), n: w.runs || 0})}${w.cash_usd ? " " + t("week_cash", {u: usd(w.cash_usd)}) : ""}</p>` + monthSavingHTML();
    return h + trackHTML();
  }
  /* H9: who is right the first time, per kind of work (judged pieces only) */
  function trackHTML() {
    const tr = (D && D.track) || {}, rows = [];
    for (const kind of Object.keys(tr).sort()) for (const a of Object.keys(tr[kind]).sort()) {
      const s = tr[kind][a];
      if (s.judged) rows.push(`<tr><td>${esc(t("kind_" + kind))}</td><td>${who(a)}</td><td>${s.judged}${s.enough ? "" : ` <span class="cost">${t("track_few")}</span>`}</td><td>${Math.round(100 * s.first_right)}%</td><td>${Math.round(100 * s.rework)}%</td></tr>`);
    }
    if (!rows.length) return `<h2>${t("track_title")}</h2><p class="stat">${t("track_none", {n: (D && D.track_min) || 5})}</p>`;
    return `<h2>${t("track_title")}</h2><table class="track"><thead><tr><th>${t("track_kind")}</th><th>${t("track_who")}</th><th>${t("track_judged")}</th><th>${t("track_first")}</th><th>${t("track_rework")}</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
  }
  function banner() {
    const demo = D && D.demo ? `<div class="banner demo">${t("demo_banner")}</div>` : "";    /* U6: always, on every page */
    if (SNAP) return demo + `<div class="banner snap">${t("snap_banner", {at: clock(D.generated)})}</div>`;
    if (OFFLINE) return demo + `<div class="banner">${t("offline_banner")}</div>`;
    if (FLASH && Date.now() - FLASH.at < 20000) return demo + `<div class="banner ${FLASH.ok ? "ok" : ""}" role="status">${FLASH.html}</div>`;
    return demo;
  }

  /* ---------- P2-10: the home page, one project on one map ----------
     top: this week's spend as the ledger has it, by the rung each run used (other ways only from the published
     table); middle: the agents and what they said to each other; left: shared memory -> the runs whose brief carried
     a note -> how they ended; right: the receipts; bottom: who is good at what, once enough work was judged. */
  function maps() { return ((D && D.maps) || []).filter(m => TESTS || findProject(m.id)); }
  function mapHref(id) { return "#/map/" + encodeURIComponent(id); }
  /* the piece (and its task) that shows run `rid`, as a link; "" when it is not on the page */
  function pieceHref(pid, rid) {
    const pr = findProject(pid); if (!pr || !rid) return "";
    for (const tk of pr.tasks) {
      let hit = null;
      walk(tk.pieces, (p, ch) => { if (!hit && p.run_id === rid) hit = {p, ch}; });
      if (hit) return href([pr.id, tk.id].concat(hit.ch.map(c => c.id)), hit.p.id);
    }
    return "";
  }
  function whoOrYou(w) { return vendorOf(w) === "user" ? `<span class="who you">${t("conv_you")}</span>` : who(vendorOf(w)); }
  let MAPPID = null;
  function renderMap(pid) {
    const ms = maps();
    if (!ms.length) return renderOverview();          /* nothing worked on yet: the overview's first steps */
    const m = ms.find(x => x.id === pid) || ms.find(x => x.id === MAPPID) || busiest(ms), pr = findProject(m.id);
    MAPPID = m.id;                                    /* the next poll keeps this project, it never jumps */
    let h = banner() + `<h1>${t("map_title", {p: m.name})}</h1><p class="lead">${t("map_intro")}</p>`;
    if (ms.length > 1) h += `<nav class="mapproj" aria-label="${esc(t("projects"))}">` + ms.map(x =>
      `<a class="chip${x.id === m.id ? " cur" : ""}" href="${mapHref(x.id)}"${x.id === m.id ? ` aria-current="page"` : ""}>${esc(x.name)}</a>`).join("") + `</nav>`;
    return h + mapWaitHTML() + `<div class="map"><section class="m-top">${mapSpendHTML(m)}</section>`
      + `<section class="m-mid">${mapTalkHTML(m, pr)}</section><section class="m-left">${mapMemHTML(m)}</section>`
      + `<section class="m-right">${mapRcptHTML(m)}</section><section class="m-bottom">${mapSkillHTML()}</section></div>`;
  }
  /* with no project named: the one where most waits for the person, then the most recent (the overview's order) */
  function busiest(ms) {
    const need = m => { const pr = findProject(m.id); let n = (m.todos || []).length; if (pr) for (const tk of pr.tasks) n += acts(tk.pieces).length; return n; };
    return ms.reduce((a, b) => need(b) > need(a) ? b : a, ms[0]);
  }
  /* what waits for the person anywhere, and what runs: the overview keeps the buttons */
  function mapWaitHTML() {
    let n = convTodos().length, running = 0;
    for (const pr of D.projects) for (const tk of pr.tasks) walk(tk.pieces, p => { if (p.act) n++; if (p.status === "run") running++; });
    return `<p class="stat">${n ? `<span class="warn">${t("map_wait", {n})}</span>` : `<span class="good">${t("ov_nothing")}</span>`} · ${t("map_running", {n: running})} · <a href="#/all">${t("map_all")}</a></p>`;
  }
  function mapSpendHTML(m) {
    const s = m.spend || {}, ref = D && D.measured_ref;
    const w = maps().reduce((a, x) => ({usd: a.usd + ((x.spend || {}).usd || 0), runs: a.runs + ((x.spend || {}).runs || 0)}), {usd: 0, runs: 0});
    let h = `<h2>${t("map_spend")}</h2><p class="stat"><b class="big">${usd(s.usd || 0)}</b> ${t("map_spend_runs", {n: s.runs || 0})}</p>`;
    if ((s.rungs || []).length) h += `<div class="rungs">` + s.rungs.map(r => `<span class="chip"><span class="mono">${r.review ? t("map_rung_review") + " · " : ""}${esc(r.rung)}</span>${r.tier ? ` <i>${esc(r.tier)}</i>` : ""} · ${usd(r.usd)}${r.runs ? " · " + t("map_runs_n", {n: r.runs}) : ""}</span>`).join("") + `</div>`;
    h += `<p class="cost">${t("map_spend_all", {u: usd(w.usd || 0), n: w.runs || 0})}</p>`;
    if (ref && (ref.rows || []).length) h += `<p class="cost">${t("map_ref", {t: inLang(ref.title) || ref.id || "",
      rows: raw(ref.rows.map(r => `${t("tok_arm_" + String(r.arm || "").replace(/[^a-z0-9]/g, ""))} $${esc(r.usd_per_success)}`).join(" · ")),
      link: raw(`<a href="#/tokens">${t("tok_nav")}</a>`)})}</p>`;
    return h;
  }
  /* a small picture of who worked with whom: one line per pair, its width by how much went between them */
  function mapGraph(m) {
    const names = m.agents || [], n = names.length;
    if (!n) return "";
    const W = 360, H = 190, cx = W / 2, cy = H / 2, R = n > 1 ? 66 : 0, pos = {};
    names.forEach((a, i) => { const ang = (n === 2 ? Math.PI : -Math.PI / 2) + 2 * Math.PI * i / n; pos[a] = [cx + 1.6 * R * Math.cos(ang), cy + R * Math.sin(ang)]; });
    const pairs = {};
    for (const e of m.edges || []) {
      if (!pos[e.from] || !pos[e.to] || e.from === e.to) continue;
      const k = [e.from, e.to].sort().join("|");
      pairs[k] = (pairs[k] || 0) + (e.sent || 0) + (e.said || 0);
    }
    let g = "";
    for (const k in pairs) {
      const [a, b] = k.split("|"), [x1, y1] = pos[a], [x2, y2] = pos[b];
      g += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="var(--muted)" stroke-opacity=".55" stroke-width="${Math.min(8, 1.5 + pairs[k])}"/>`
        + `<text x="${(x1 + x2) / 2}" y="${(y1 + y2) / 2 - 5}" text-anchor="middle" font-size="12" fill="var(--muted)">${pairs[k]}</text>`;
    }
    for (const a of names) {
      const [x, y] = pos[a], c = tone(a);
      g += `<g><rect x="${x - 44}" y="${y - 15}" width="88" height="30" rx="15" fill="var(--c-${c}-bg)" stroke="var(--line)"/>`
        + `<text x="${x}" y="${y + 5}" text-anchor="middle" font-size="13" font-weight="650" fill="var(--c-${c}-ink)">${esc(agentName(a))}</text></g>`;
    }
    return `<svg class="mgraph" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t("map_graph"))}">${g}</svg>`;
  }
  function mapTalkHTML(m, pr) {
    let h = `<h2>${t("map_talk")}</h2>` + mapGraph(m);
    const edges = (m.edges || []).filter(e => e.sent || e.said);
    if (edges.length) h += `<ul class="mlist edges">` + edges.map(e => `<li>${whoOrYou(e.from)} → ${e.to === "all" ? t("conv_all") : whoOrYou(e.to)} `
      + `<span class="cost">${[e.sent ? t("map_sent", {n: e.sent}) : "", e.said ? t("map_said", {n: e.said}) : ""].filter(Boolean).join(" · ")}</span></li>`).join("") + `</ul>`;
    const leads = pr ? pr.tasks.filter(tk => tk.kind === "lead" && tk.lead && tk.lead.agent).slice(0, 3) : [];
    if (leads.length) h += `<ul class="mlist">` + leads.map(tk => `<li>${t("map_lead", {w: raw(who(tk.lead.agent, tk.lead.model)),
      t: raw(`<a href="${href([pr.id, tk.id])}">${esc(taskTitle(tk))}</a>`)})}</li>`).join("") + `</ul>`;
    const todos = m.todos || [], ths = m.threads || [], talks = m.talks || [];
    if (todos.length) h += `<div class="todo">` + todos.map(x => todoRow("answer", convHref(m.id, x.key),
      x.kind === "stuck" ? t("conv_todo_stuck", {n: x.run}) : t("conv_todo_asks", {w: agentName(vendorOf(x.from))}),
      esc(x.text), esc(x.thread))).join("") + `</div>`;
    if (ths.length) h += `<h3 class="tok-h3">${t("map_threads", {n: m.threads_total || ths.length})}</h3><ul class="mlist">` + ths.map(th =>
      `<li><a href="${convHref(m.id, th.key)}">${esc(th.name)}</a> ${(th.who || []).map(whoOrYou).join("")} <span class="cost">${t("conv_msgs", {n: th.n})}${th.last ? " · " + ago(th.last) : ""}</span>`
      + `${th.wait ? ` <span class="kchip k-answer">${t(th.wait === "stuck" ? "map_stuck" : "conv_asks_badge")}</span>` : ""}<div class="said">${esc(th.text)}</div></li>`).join("") + `</ul>`;
    if (talks.length) h += `<h3 class="tok-h3">${t("disc_nav")}</h3><ul class="mlist">` + talks.map(x =>
      `<li><a href="#/discuss/${encodeURIComponent(x.id)}">${esc(x.question)}</a> <span class="cost">${t("disc_state_" + (x.state || "running"))} · ${x.turns} ${t("disc_turns")} · ${usd(x.usd || 0)}</span></li>`).join("") + `</ul>`;
    if (!ths.length && !talks.length) h += `<p class="cost">${t("map_talk_none")}</p>`;
    return h;
  }
  function receiptOf(m, rid) { return (m.receipts || []).find(r => r.run_id === rid); }
  function mapMemHTML(m) {
    const mm = m.memory || {};
    let h = `<h2>${t("map_mem")}</h2><p class="stat">${t("map_mem_counts", {n: mm.total || 0, h: mm.here || 0, c: mm.carried || 0})}</p>`;
    if (!(mm.notes || []).length) return h + `<p class="cost">${t("map_mem_none")}</p><p class="cost">${t("map_mem_how")}</p>`;
    h += `<ul class="mlist notes">` + mm.notes.map(n => {
      const rc = receiptOf(m, n.last_run), link = rc ? pieceHref(m.id, rc.piece) : "";
      const last = n.last_run ? " · " + t("map_note_last", {r: raw(link ? `<a href="${link}">${esc(n.last_run)}</a>` : `<span class="mono">${esc(n.last_run)}</span>`)}) : "";
      return `<li><b>#${esc(n.seq)}</b> ${n.gone ? `<i class="cost">${t("map_note_gone")}</i>` : esc(n.text)}`
        + `<div class="said">${n.by ? t("map_note_by", {w: toName(n.by)}) + " · " : ""}${t("map_note_used", {n: n.runs})}: `
        + `<span class="good">${t("map_right", {n: n.right})}</span> · <span class="${n.wrong ? "warn" : ""}">${t("map_wrong", {n: n.wrong})}</span> · ${t("map_open_n", {n: n.open})}${last}</div></li>`;
    }).join("") + `</ul>`;
    return h + `<p class="cost">${t("map_mem_how")}</p>`;
  }
  function checkLine(c) {
    if (!c) return t("map_chk_none");
    let s = t(c.passed ? "map_chk_ok" : "map_chk_bad", {c: raw(`<code>${esc(c.cmd)}</code>`)});
    if (c.unknown) s += " · " + t("map_cov_unknown");
    else if (c.n != null) s += " · " + t("map_cov", {n: c.n + (c.partial ? "+" : ""), f: (c.files || []).join(", ")}) + (c.filtered ? " · " + t("map_cov_part") : "");
    if ((c.basis_changed || []).length) s += ` · <span class="warn">${t("map_basis", {f: c.basis_changed.join(", ")})}</span>`;
    if (c.own_only) s += ` · <span class="warn">${t("map_own")}</span>`;
    return s;
  }
  function mapRcptHTML(m) {
    const rs = m.receipts || [];
    let h = `<h2>${t("map_rcpt")}</h2>`;
    if (!rs.length) return h + `<p class="cost">${t("map_rcpt_none")}</p>`;
    h += `<ul class="rcpts">` + rs.map(r => {
      const link = pieceHref(m.id, r.piece);
      const v = r.running ? "map_v_run" : r.verdict === true ? "map_v_ok" : r.verdict === false ? "map_v_bad" : r.outcome === "wrong" ? "map_v_wrong" : "map_v_open";
      const rv = r.review ? t("map_rv_" + r.review, {w: r.reviewer || "?"}) : t("map_rv_none");
      return `<li class="o-${esc(r.outcome)}"><div>${whoOrYou(r.from)} → ${who(r.to)} <b>${usd(r.usd || 0)}</b> `
        + `<span class="mono cost">${esc([r.tier, r.rung].filter(Boolean).join(" · "))}${r.rounds > 1 ? " · " + t("map_rounds", {n: r.rounds}) : ""}</span></div>`
        + `<div class="said">${checkLine(r.check)}</div><div class="said">${rv} · <span class="${v === "map_v_bad" || v === "map_v_wrong" ? "warn" : v === "map_v_ok" ? "good" : ""}">${t(v)}</span>`
        + `${link ? ` · <a href="${link}">${t("map_open")}</a>` : ""} · <a href="${runHref(r.run_id)}">${t("runs_open")}</a>${r.ts ? ` · ${ago(r.ts)}` : ""}</div></li>`;
    }).join("") + `</ul>`;
    return h + ((m.receipts_total || 0) > rs.length ? `<p class="cost">${t("map_rcpt_more", {n: m.receipts_total - rs.length})}</p>` : "");
  }
  /* who is right the first time per kind of work (H9's judged pieces): rates only where there is enough; until
     then it says so (P0-12 will feed a fuller table here) */
  function mapSkillHTML() {
    const tr = (D && D.track) || {}, rows = [];
    let most = 0;
    for (const kind of Object.keys(tr).sort()) for (const a of Object.keys(tr[kind]).sort()) {
      const s = tr[kind][a]; most = Math.max(most, s.judged || 0);
      if (s.enough) rows.push(`<tr><td>${esc(t("kind_" + kind))}</td><td>${who(a)}</td><td>${s.judged}</td><td>${Math.round(100 * s.first_right)}%</td><td>${Math.round(100 * s.rework)}%</td></tr>`);
    }
    const h = `<h2>${t("map_skill")}</h2>`, need = `<p class="cost">${t("map_skill_need", {n: (D && D.track_min) || 5, k: most})}</p>`;
    if (!rows.length) return h + `<p class="stat"><b>${t("map_skill_none")}</b></p>` + need;
    return h + `<div class="twrap"><table class="track"><thead><tr><th>${t("track_kind")}</th><th>${t("track_who")}</th><th>${t("track_judged")}</th><th>${t("track_first")}</th><th>${t("track_rework")}</th></tr></thead><tbody>${rows.join("")}</tbody></table></div>` + need;
  }

  /* ---------- K6: this month, the other projects, optional slots (autonomy level, inbox) ---------- */
  function monthSpentHTML() {
    const m = D && D.month;
    if (!m) return `<p class="stat">${t("month_wait")}</p>`;
    const since = new Date(m.since * 1000), day = t("date_md", {m: since.getMonth() + 1, d: since.getDate()});
    return `<p class="stat">${t("month_spent", {d: day, u: usd(m.sub_usd || 0), n: m.runs || 0})}</p>`;
  }
  /* secondary, never bold: only a saving `ccx trial` measured is shown as a number; until then spend only (P1-4) */
  function monthSavingHTML() {
    const m = D && D.month;
    if (!m) return "";
    const link = {__html: `<a href="${esc(t("measured_url"))}" target="_blank" rel="noopener">docs/measured.md</a>`};   /* the address lives in strings.json: no URL in the page code */
    if (m.kind !== "measured" || m.saving == null) return `<p class="stat cost">${t("month_unmeasured", {link})}</p>`;
    const ci = m.ci95 && m.ci95.length === 2 ? t("month_ci", {a: usd(Math.abs(m.ci95[0])) , b: usd(Math.abs(m.ci95[1])), neg: m.ci95[0] < 0 ? "−" : ""}) : "";
    const key = m.saving >= 0 ? "month_saving_m" : "month_extra_m";
    return `<p class="stat cost">${t(key, {u: usd(Math.abs(m.saving)), ci, n: m.n || 0})}</p>`
      + `<p class="stat cost">${t("month_measured")}</p>`;
  }
  function othersHTML() {
    const os = ((D && D.others) || []).filter(o => TESTS || !o.test);
    if (!os.length) return "";
    const more = ((D && D.others_total) || 0) - os.length;
    return `<h2>${t("others_title")}</h2><p class="stat">${t("others_lead")}</p><div class="others">`
      + os.map(o => `<span class="chip" title="${esc(o.summary || o.path)}">${esc(o.name)}${o.last ? ` <i>${ago(o.last)}</i>` : ""}</span>`).join("")
      + (more > 0 ? `<span class="chip more">${t("others_more", {n: more})}</span>` : "") + `</div>`;
  }
  function levelHTML(pr) { return pr.level ? `<span class="lvlb" title="${esc(t("level_title"))}">${esc(pr.level)}</span>` : ""; }
  function rulesHTML(pr) {
    if (!(pr.rules || []).length) return "";
    return `<h2>${t("rules_title")}</h2><p class="stat">${t("rules_lead")}</p><ul class="files">`
      + pr.rules.map(r => `<li><span class="mono">${esc(r.file)}:${esc(r.line)}</span> ${esc(r.text)}</li>`).join("") + `</ul>`;
  }

  /* ---------- K6: a button that runs its ccx command: prepare -> the exact command -> confirm -> run once ---------- */
  function where(key) { const [project, task, piece] = key.split("|"); return {project, task, piece: piece === "_" ? null : piece}; }
  function actBox(key, b) {
    if (!ACT || ACT.key !== key) return "";
    const cancel = `<button class="btn" data-do="act-cancel">${t("act_cancel")}</button>`;
    if (ACT.stage === "usd") return `<div class="k">${t(b ? b.label : "b_budget")} — ${t("act_usd")}</div><div class="acts"><input type="number" id="usdin" min="0.01" max="10000" step="0.5" value="${esc(ACT.usd)}" aria-label="${esc(t("act_usd"))}"><button class="btn primary" data-do="act-usd">${t("act_next")}</button>${cancel}</div>`;
    if (ACT.stage === "busy") return `<div class="k">${t("act_busy")}</div>`;
    if (ACT.stage === "demo") return `<div class="k">${t(ACT.label)} — ${t("act_demo")}</div><code class="mono" id="cmdtext">${esc(ACT.cmd)}</code><div class="acts">${cancel}<button data-do="copy">${t("copy")}</button></div>`;
    if (ACT.stage === "err") return `<div class="k"><span class="warn">${t("act_failed", {e: ACT.msg || ""})}</span></div><div class="acts">${cancel}</div>`;
    if (ACT.stage === "confirm") return `<div class="k">${t(ACT.label)} — ${t("act_will")}</div><code class="mono" id="cmdtext">${esc(ACT.cmd)}</code>`
      + `<p class="${ACT.spends || (b && b.note) ? "warn" : "cost"}" style="margin:6px 0">${t(b && b.note ? b.note : ACT.spends ? "act_spends" : "act_records")}</p>`
      + (ACT.blank ? `<p class="warn" style="margin:6px 0">${t("sw_blank_pre")}</p>` : "")
      + undoLists(ACT.undo)
      + `<div class="acts"><button class="btn ${ACT.spends ? "bad" : "primary"}" data-do="act-run">${t(ACT.spends ? "act_confirm_spend" : "act_confirm")}</button>${cancel}<button data-do="copy">${t("copy")}</button></div>`;
    return "";
  }
  /* the undo confirm box: the files `ccx undo`'s dry run would put back and move aside, checked by the server */
  function undoLists(u) {
    if (!u) return "";
    const li = xs => `<ul class="files">${xs.map(x => `<li class="mono">${esc(x)}</li>`).join("")}</ul>`;
    return (u.restore && u.restore.length ? `<div class="k">${t("undo_restore")}</div>${li(u.restore)}` : "")
      + (u.move_aside && u.move_aside.length ? `<div class="k">${t("undo_aside")}</div>${li(u.move_aside)}` : "")
      + (u.chain_from ? `<p class="warn" style="margin:6px 0">${t("undo_chain", {r: u.chain_from})}</p>` : "");
  }
  function paintAct() {
    const c = $("cmd");
    if (c && ACT) { c.hidden = true; chosen = null; }      /* one box at a time: the copy-only one goes */
    for (const el of document.querySelectorAll("[data-actbox]")) {
      const key = el.dataset.actbox, h = actBox(key, ACT && ACT.key === key ? ACT.b : null);
      el.innerHTML = h; el.hidden = !h;
    }
  }
  async function prepare(key, btn, b, fill) {
    ACT = {key, btn, b, label: b.label, stage: "busy"}; paintAct();
    try {
      const r = await post("/api/act/prepare", Object.assign(where(key), {btn, fill: fill || {}}));
      Object.assign(ACT, {stage: r.demo ? "demo" : "confirm", cmd: r.cmd, nonce: r.nonce, spends: r.spends, undo: r.undo || null,
        blank: "transcript" in r && !r.transcript});      /* U7: a handoff with no conversation file: a blank template */
    } catch (e) { Object.assign(ACT, {stage: "err", msg: e.message}); }
    paintAct();
  }
  async function runAct() {
    if (!ACT || ACT.stage !== "confirm") return;
    const a = ACT; a.stage = "busy"; paintAct();
    try {
      const r = await post("/api/act/run", {nonce: a.nonce});
      /* a background job that starts no agent (q accept): no run appears on the chart; its answer is in its log */
      const html = r.started && !a.spends ? t("act_started_bg", {c: raw(`<code class="mono">${esc(r.cmd)}</code>`), l: r.log || ""})
        : r.started ? t("act_started", {c: raw(`<code class="mono">${esc(r.cmd)}</code>`)})
        : r.ok ? t("act_done", {c: raw(`<code class="mono">${esc(r.cmd)}</code>`)})
        : t("act_exit", {c: raw(`<code class="mono">${esc(r.cmd)}</code>`), e: String(r.exit), m: (r.err || r.out || "").slice(-300)});
      if (r.handoff) HANDOFF[where(a.key).project] = r.handoff;      /* U7: kept on the panel, not only flashed */
      FLASH = {at: Date.now(), ok: !!r.ok, html: r.handoff ? t("sw_done", {f: r.handoff.file}) : html}; ACT = null;
      await refresh();
      if (r.ok && !a.spends) moveOn(where(a.key).piece);
      render();
    } catch (e) { Object.assign(a, {stage: "err", msg: e.message}); paintAct(); }
  }
  /* the pieces of the list on screen that wait for the person, in the order the page lists them */
  function waitingIn(list) { return (list || []).filter(p => p.act).sort((a, b) => (a.act.kind === "review") - (b.act.kind === "review")); }
  /* after a verdict on the piece in the panel: when it waits for nothing more (no new question, no Merge to press
     next), the panel moves to the next piece that waits, and says so */
  function moveOn(pid) {
    const cur = currentList(); if (!cur || !pid || sel !== pid) return;
    const f = findPiece(cur.list, pid);
    if (f && (f.p.act || (f.p.ctl || []).some(b => b.style === "primary"))) return;
    const w = waitingIn(cur.list);
    if (w.length) { sel = w[0].id; NEXT = {sel: sel, n: w.length}; }
  }
  function stepWaiting(dir) {
    const cur = currentList(); if (!cur) return;
    const w = waitingIn(cur.list); if (!w.length) return;
    const i = w.findIndex(p => p.id === sel);
    sel = w[i < 0 ? 0 : (i + dir + w.length) % w.length].id; NEXT = null; render();
  }
  async function post(path, body) {
    const r = await fetch(path, {method: "POST", cache: "no-store", credentials: "omit",
      headers: {"X-CCX-Token": TOKEN, "Content-Type": "application/json"}, body: JSON.stringify(body)});
    let j = {}; try { j = await r.json(); } catch (e) { /* empty */ }
    if (!r.ok) throw new Error(j.error || String(r.status));
    return j;
  }
  /* a button was pressed: runnable ones go through prepare; the rest (and every one in a snapshot) show the command */
  function pressBtn(key, holder, id) {
    const b = (id[0] === "a" ? (holder.act || {}).buttons : holder.ctl || [])[+id.slice(1)];
    if (!b) return;
    if (SNAP || !b.run) { if (id[0] === "a") showCmd(holder, +id.slice(1), false); else fillCmd(b.label, b.cmd, b.prose); return; }
    if (b.cmd.includes("{reason}") || b.cmd.includes("{note}")) { showCmd(holder, +id.slice(1), false); return; }
    if (b.cmd.includes("{usd}")) {
      const tk = findTask(findProject(where(key).project), where(key).task) || {};
      const base0 = holder === tk ? Math.max(tk.budget || 0, tk.spent || 0) : 0;
      ACT = {key, btn: id, b, label: b.label, stage: "usd", usd: (Math.ceil(base0) + 5).toFixed(2)}; paintAct(); return;
    }
    prepare(key, id, b, {});
  }

  /* ---------- discussions (ccx discuss): turns drawn as a conversation ---------- */
  function discListHTML(cur) {
    const talks = (D && D.discussions) || [];
    if (!talks.length) return `<p class="lead">${t("disc_none")}</p>`;
    return `<div class="todo talks">` + talks.map(x => `<a class="${x.id === cur ? "cur" : ""}" href="#/discuss/${encodeURIComponent(x.id)}"><b>${esc(x.question)}</b><span>${t("disc_state_" + (x.state || "running"))} · ${(x.turns || []).length} ${t("disc_turns")} · ${usd(x.usd || 0)}</span><span class="where">${clock(x.ts)}</span></a>`).join("") + `</div>`;
  }
  function discHTML(id) {
    const talks = (D && D.discussions) || [];
    const x = talks.find(d => d.id === id) || (!id ? talks[0] : null);
    let h = banner() + `<div class="crumbs"><a href="#/all">${t("overview")}</a> › ${t("disc_nav")}</div><h1>${t("disc_title")}</h1>`;
    if (!x) return h + discListHTML();
    const rl = x.roles || {};
    h += `<p class="lead"><b>${esc(x.question)}</b><br>${["proposer", "critic", "judge"].map(r => `${t("role_" + r)} ${who(rl[r])}`).join(" ")}${x.judge_independent === false ? " · " + t("disc_two") : ""}</p><div class="chat">`;
    let rnd = 0;
    for (const tn of x.turns || []) {
      if (tn.round !== rnd && tn.role !== "judge") { rnd = tn.round; h += `<div class="rnd">${t("disc_round", {n: rnd})}</div>`; }
      h += `<div class="msg ${esc(tn.role)}"><div class="hd">${who(tn.agent, tn.model)} <span>${t("role_" + tn.role)}</span><span class="cost">${usd(tn.usd || 0)}</span>${tn.unparsed ? ` <span class="warn">${t("disc_unparsed")}</span>` : ""}</div>
        <p>${esc(tn.summary)}</p>${(tn.points || []).length ? `<ul>${tn.points.map(pt => `<li>${esc(pt)}</li>`).join("")}</ul>` : ""}</div>`;
    }
    if (x.state === "running" || x.state === "starting") h += `<div class="rnd">${t("disc_state_" + x.state)}…</div>`;
    h += `</div>`;
    const r = x.result;
    if (r) {
      h += `<h2>${t("disc_outcome")}${x.agreed ? ` <span class="good">${t("disc_agreed")}</span>` : ""}</h2><div class="card outcome"><p><b>${t("disc_recommend")}</b> ${esc(r.recommendation)}</p>`;
      for (const [k, lab] of [["consensus", "disc_consensus"], ["disagreements", "disc_disagree"], ["reasons", "disc_reasons"]])
        if ((r[k] || []).length) h += `<div class="k">${t(lab)}</div><ul>${r[k].map(s => `<li>${esc(s)}</li>`).join("")}</ul>`;
      if (r.note) h += `<p class="cost">${esc(r.note)}</p>`;
      if (r.unparsed) h += `<p class="cost"><span class="warn">${esc(r.unparsed)}</span></p>`;
      h += `</div>`;
    }
    if (x.error) h += `<p class="lead"><span class="warn">${esc(x.error)}</span></p>`;
    h += `<p class="cost">${t("disc_total", {u: usd(x.usd || 0)})} · <code class="mono">ccx discuss --show ${esc(x.id)}</code></p>`;
    if (talks.length > 1) h += `<h2>${t("disc_others")}</h2>` + discListHTML(x.id);
    return h;
  }

  /* ---------- U2: the agents' conversation (each project's board: ccx say / ccx reply), I1: the person's reply ----------
     Every message is text written by agents (or remote copies of the board): esc() always, shown as plain text. The
     reply goes through the same two steps as a button: prepare (the server answers what it will write and a nonce),
     then a second click writes it once, as the person, via ui. It is a message on the board, never a command. */
  let CONV = null, CONVKEY = "", CONVSIG = "", CONVBUSY = false, CONVERR = "", SAY = null;
  const DRAFT = {};
  function convs() { return (D && D.conversations) || []; }
  function convTodos() { const out = []; for (const c of convs()) for (const x of c.todos || []) out.push({c, x}); return out; }
  function convHref(pid, th) { return "#/conv/" + encodeURIComponent(pid) + (th ? "/" + encodeURIComponent(th) : ""); }
  function vendorOf(w) { const v = String(w || "").split(":")[0].trim().toLowerCase(); return v === "dsh" || v === "deepseek-codex" ? "deepseek" : v === "human" || v === "person" ? "user" : v; }
  function toName(w) { const v = vendorOf(w); return v === "all" ? t("conv_all") : v === "user" ? t("conv_you") : agentName(v); }
  function msgWho(m) { return m.who === "user" ? `<span class="who you">${t("conv_you")}</span>` : who(m.who); }
  function convTodoHTML(list) {
    return list.map(({c, x}) => todoRow("answer", convHref(c.id, x.key),
      x.kind === "stuck" ? t("conv_todo_stuck", {n: x.run}) : t("conv_todo_asks", {w: agentName(vendorOf(x.from))}),
      esc(x.text), esc(c.name) + " › " + t("conv_nav") + " › " + esc(x.thread))).join("");
  }
  function convLinkHTML(pid) {
    const c = convs().find(x => x.id === pid);
    return c ? `<p class="stat"><a href="${convHref(pid)}">${t("conv_page_link", {n: c.threads})}</a>${(c.todos || []).length ? ` <span class="badge">${c.todos.length}</span>` : ""}</p>` : "";
  }
  /* one read of /api/conv/<project>; true when a thread changed */
  async function loadConv(pid) {
    const j = await api("/api/conv/" + encodeURIComponent(pid));
    const sig = JSON.stringify([j.threads, j.threads_total]), changed = CONVKEY !== pid || sig !== CONVSIG;
    CONV = j; CONVKEY = pid; CONVSIG = sig; CONVERR = "";
    return changed;
  }
  function wantConv(pid) {
    if (SNAP || CONVBUSY || (CONVKEY === pid && (CONV || CONVERR))) return;
    CONVBUSY = true;
    loadConv(pid).catch(e => { CONV = null; CONVKEY = pid; CONVERR = (e && e.message) || "?"; })
      .then(() => { CONVBUSY = false; if (route().r[0] === "conv") render(); });
  }
  function msgHTML(m) {
    const via = m.via && m.via !== m.from ? " · " + t("conv_via", {v: m.via}) : "";
    return `<div class="msg bmsg${m.who === "user" ? " you" : ""}${m.asks ? " asks" : ""}"><div class="hd">${msgWho(m)}<span>→ ${esc(toName(m.to))}</span><span class="mono">#${esc(m.id)}${m.reply_to ? " re #" + esc(m.reply_to) : ""}</span><span class="cost">${clock(m.ts)}${via}</span></div>`
      + `<p class="btext">${esc(m.text)}</p>${m.kind === "run" && /^[A-Za-z0-9_-]{1,64}$/.test(m.run_id || "") ? `<a href="/runs/${encodeURIComponent(m.run_id)}">${t("runs_open")}</a>` : ""}${m.cut ? `<p class="cost">${t("conv_cut", {n: m.chars})}</p>` : ""}${m.asks ? `<p class="warn">${t("conv_asks_you")}</p>` : ""}</div>`;
  }
  function threadHead(pid, x, open) {
    const flags = (x.stuck ? ` <span class="warn">${t("conv_stuck", {n: x.run})}</span>` : "") + ((x.asks || []).length ? ` <span class="warn">${t("conv_asks_badge")}</span>` : "");
    return `<h2>${open ? esc(x.thread) : `<a href="${convHref(pid, x.key)}">${esc(x.thread)}</a>`} <span class="cost">${t("conv_msgs", {n: x.n})} · ${clock(x.last)}</span>${flags}</h2>`;
  }
  function sayBox(key) {
    if (!SAY || SAY.key !== key) return "";
    const cancel = `<button class="btn" data-do="say-cancel">${t("act_cancel")}</button>`;
    if (SAY.stage === "busy") return `<div class="k">${t("act_busy")}</div>`;
    if (SAY.stage === "err") return `<div class="k"><span class="warn">${t("act_failed", {e: SAY.msg || ""})}</span></div><div class="acts">${cancel}</div>`;
    return `<div class="k">${t("conv_will", {to: toName(SAY.to), thread: SAY.thread, id: SAY.id})}</div><pre class="says btext mono">${esc(SAY.text)}</pre>`
      + `<p class="cost">${t("conv_not_run")} <code class="mono">${esc(SAY.cmd || "")}</code></p>`
      + `<div class="acts"><button class="btn primary" data-do="say-run">${t("conv_send")}</button>${cancel}</div>`;
  }
  function replyHTML(pid, x) {
    const key = pid + "|" + x.key, d = DRAFT[key] || "", max = (CONV && CONV.say_max) || 4000, box = sayBox(key);
    return `<div class="card reply"><label class="k" for="saytext">${t("conv_reply_to", {to: toName(x.reply.to), id: x.reply.id})}</label>`
      + `<textarea id="saytext" data-saykey="${esc(key)}" maxlength="${max}" rows="4">${esc(d)}</textarea>`
      + `<div class="acts"><span class="cost" id="saycount">${t("conv_chars", {n: d.length, m: max})}</span><button class="btn primary" data-do="say-prep">${t("conv_reply")}</button></div>`
      + `<p class="cost">${t("conv_reply_rule", {m: max})}</p><div class="cmd" id="saybox"${box ? "" : " hidden"}>${box}</div></div>`;
  }
  function renderConv(pid, th) {
    const c = convs().find(x => x.id === pid), name = c ? c.name : CONV && CONVKEY === pid ? CONV.project.name : "";
    let h = banner() + `<div class="crumbs"><a href="#/all">${t("overview")}</a> › ${name ? esc(name) + " › " : ""}${th ? `<a href="${convHref(pid)}">${t("conv_title")}</a> › ${esc(th)}` : t("conv_title")}</div>`;
    h += `<h1>${t("conv_title")}${name ? " · " + esc(name) : ""}</h1><p class="lead">${t("conv_lead", {n: (CONV && CONV.max_machine) || 6})}</p>`;
    if (SNAP) {
      if (c && (c.todos || []).length) h += `<div class="todo">${convTodoHTML(convTodos().filter(z => z.c.id === pid))}</div>`;
      return h + `<p class="lead">${t("conv_snap")}</p>`;
    }
    if (CONVKEY !== pid || (!CONV && !CONVERR)) { wantConv(pid); return h + `<p class="lead">${t("conv_loading")}</p>`; }
    if (CONVERR || !CONV) return h + `<p class="lead">${t("conv_gone")}</p>`;
    h += `<div class="run-notices">${(CONV.run_messages || []).map(m => `<p class="card">${clock(m.ts)} · ${esc(m.text)} <a href="${runHref(m.run_id)}">${t("runs_open")}</a></p>`).join("")}</div>`;
    if (!CONV.threads.length) return h + `<p class="lead">${t("conv_none")}</p>`;
    if (th) {
      const x = CONV.threads.find(z => z.key === th);
      if (!x) return h + `<p class="lead">${t("conv_gone")}</p>`;
      h += threadHead(pid, x, true);
      if (x.more) h += `<p class="cost">${t("conv_more", {n: x.more, t: x.thread})}</p>`;
      h += `<div class="chat">${x.messages.map(msgHTML).join("")}</div>`;
      if (x.clipped) h += `<p class="cost">${t("conv_clipped", {t: x.thread})}</p>`;
      return h + replyHTML(pid, x);
    }
    for (const x of CONV.threads) {
      h += threadHead(pid, x, false) + `<div class="chat">${x.messages.slice(-3).map(msgHTML).join("")}</div>`;
      h += `<p class="stat"><a href="${convHref(pid, x.key)}">${t("conv_open")}</a></p>`;
    }
    if (CONV.threads_total > CONV.threads.length) h += `<p class="cost">${t("conv_more_threads", {n: CONV.threads_total - CONV.threads.length})}</p>`;
    return h;
  }
  /* a redraw keeps what the person is typing: the draft, the focus and the caret */
  function drawConv(pid, th) {
    const ta = $("saytext"), focused = ta && document.activeElement === ta, a = focused ? ta.selectionStart : 0, b = focused ? ta.selectionEnd : 0;
    const keep = window.scrollY;
    $("main").innerHTML = renderConv(pid, th) + chatPanel();
    const nt = $("saytext");
    if (focused && nt) { nt.focus(); try { nt.setSelectionRange(a, b); } catch (e) { /* ok */ } }
    window.scrollTo(0, keep);
  }
  function paintSay() {
    const box = $("saybox"), ta = $("saytext"); if (!box || !ta) return;
    const h = sayBox(ta.dataset.saykey); box.innerHTML = h; box.hidden = !h;
  }
  async function prepSay() {
    const ta = $("saytext"); if (!ta || !CONV || SNAP) return;
    const key = ta.dataset.saykey, cut = key.indexOf("|"), pid = key.slice(0, cut), thread = key.slice(cut + 1);
    const x = CONV.threads.find(z => z.key === thread), text = ta.value;
    SAY = {key, stage: "busy", text}; paintSay();
    try {
      const r = await post("/api/say/prepare", {project: pid, thread, reply_to: x ? x.reply.id : null, text});
      if (SAY && SAY.key === key && SAY.text === text) Object.assign(SAY, {stage: "confirm", nonce: r.nonce, to: r.to, id: r.reply_to, thread: r.thread, cmd: r.cmd});
    } catch (e) { if (SAY && SAY.key === key) Object.assign(SAY, {stage: "err", msg: e.message}); }
    paintSay();
  }
  async function runSay() {
    if (!SAY || SAY.stage !== "confirm") return;
    const s = SAY; s.stage = "busy"; paintSay();
    try {
      const r = await post("/api/say/run", {nonce: s.nonce});
      FLASH = {at: Date.now(), ok: true, html: t("conv_sent", {id: r.posted.id, thread: r.posted.thread})};
      delete DRAFT[s.key]; SAY = null;
      const ta = $("saytext"); if (ta) ta.value = "";
      try { await refresh(); } catch (e) { /* the next poll */ }
      const rt = route().r; if (rt[0] === "conv") { try { await loadConv(rt[1]); } catch (e) { /* the next poll */ } }
      render();
    } catch (e) { Object.assign(s, {stage: "err", msg: e.message}); paintSay(); }
  }

  /* ---------- B1: measured results and where tokens go (/api/tokens, /api/leadcost: read only, capped) ----------
     Task titles, labels, run ids, model names and anything read from a conversation are data: esc() always. The
     page asks /api/tokens when it is opened or a filter changes (not on every poll), and parses a lead conversation
     only when its row is opened. */
  let TOK = null, TOKKEY = "", TOKBUSY = false, TOKERR = "", TOKPERIOD = "7d", TOKPROJ = "";
  const TOKOPEN = {}, LEADOPEN = {}, LEADC = {}, LEADBUSY = {};
  function tokKey() { return TOKPERIOD + "|" + TOKPROJ + "|" + (TESTS ? 1 : 0); }
  function wantTok(force) {
    if (SNAP || TOKBUSY || (!force && TOKKEY === tokKey() && (TOK || TOKERR))) return;
    TOKBUSY = true;
    const key = tokKey();
    const qs = "?period=" + encodeURIComponent(TOKPERIOD) + (TOKPROJ ? "&project=" + encodeURIComponent(TOKPROJ) : "") + (TESTS ? "&tests=1" : "");
    api("/api/tokens" + qs).then(j => { TOK = j; TOKERR = ""; }).catch(e => { TOK = null; TOKERR = (e && e.message) || "?"; })
      .then(() => { TOKKEY = key; TOKBUSY = false; if (route().r[0] === "tokens") drawTokens(); });
  }
  function pct(x) { return x == null ? "–" : Math.round(x * 100) + "%"; }
  function inLang(o) { return o ? (o[LANG] || o.en || "") : ""; }
  function measuredHTML(m) {
    let h = `<h2>${t("tok_m_title")}</h2>`;
    if (!m || !(m.tables || []).length) return h + `<p class="cost">${t("tok_m_src", {path: raw("<code>docs/measured.md</code>")})}</p>`;
    const head = `<div class="twrap"><table class="ttab"><thead><tr><th>${t("tok_col_arm")}</th><th>${t("tok_col_right")}</th><th>${t("tok_col_usd")}</th><th>${t("tok_col_wall")}</th></tr></thead><tbody>`;
    const rowsOf = rs => (rs || []).map(r => `<tr><td>${t("tok_arm_" + String(r.arm || "").replace(/[^a-z0-9]/g, ""))}${r.run ? ` <span class="cost">${esc(r.run)}</span>` : ""}</td>`
      + `<td>${esc(r.right)}${r.note ? `<br><span class="cost">${esc(inLang(r.note))}</span>` : ""}</td><td>${r.usd_per_success ? "$" + esc(r.usd_per_success) : "–"}</td><td>${r.wall_median_s ? t("tok_secs", {s: r.wall_median_s}) : "–"}</td></tr>`).join("");
    for (const tb of m.tables) {
      h += `<h3 class="tok-h3">${esc(inLang(tb.title) || tb.id)} <span class="cost">${esc(tb.date || "")}</span></h3>` + head + rowsOf(tb.rows) + `</tbody></table></div>`;
      if (tb.ext && (tb.ext.rows || []).length) h += `<h3 class="tok-h3">${esc(inLang(tb.ext.title))}</h3>` + head + rowsOf(tb.ext.rows) + `</tbody></table></div>`;
      h += `<p class="cost">${t("tok_limit", {t: inLang(tb.limit)})}</p>`;
    }
    if (m.tests) h += `<p class="cost">${t("tok_tests", {d: m.tests.date || "", t: inLang(m.tests)})}</p>`;
    return h + `<p class="cost">${t("tok_m_src", {path: raw("<code>docs/measured.md</code>")})}</p>`;
  }
  function mineRow(name, b) {
    return `<tr><td>${name}</td><td>${+b.runs || 0}</td><td>${+b.ok || 0}</td><td>${pct(b.ok_rate)}</td><td>${b.usd_per_ok == null ? "–" : usd(+b.usd_per_ok)}</td></tr>`;
  }
  function mineHTML(x) {
    let h = `<h2>${t("tok_mine_title")}</h2><p class="cost">${t("tok_mine_note")}</p>`;
    if (!x || !x.runs) return h + `<p class="lead">${t("tok_mine_none")}</p>`;
    h += `<div class="twrap"><table class="ttab"><thead><tr><th></th><th>${t("tok_col_runs")}</th><th>${t("tok_col_ok")}</th><th>${t("tok_col_okr")}</th><th>${t("tok_col_perok")}</th></tr></thead><tbody>`;
    h += mineRow(`<b>${t("tok_all")}</b>`, x);
    for (const [m, b] of Object.entries(x.by_mode || {})) h += mineRow(t("tok_mode", {m}), b);
    for (const [a, b] of Object.entries(x.by_agent || {})) h += mineRow(esc(agentName(a)), b);
    return h + `</tbody></table></div>`;
  }
  function tokCells(k) { k = k || {}; return `<td>${tok(k.fresh)}</td><td>${tok(k.cached)}</td><td>${tok(k.cache_write)}</td><td>${tok(k.output)}</td>`; }
  function tokHead(first) {
    return `<thead><tr><th>${first}</th><th>${t("tok_fresh")}</th><th>${t("tok_cached")}</th><th>${t("tok_cw")}</th><th>${t("tok_out")}</th><th>${t("tok_usd")}</th></tr></thead>`;
  }
  function money(x) { return x == null ? "–" : usd(+x); }
  function runRows(r) {
    const tag = r.review ? ` <span class="cost">${t("tok_review")}</span>` : "";
    let h = `<tr><td><span class="mono">${esc(r.run_id)}</span>${tag}<br>${who(r.agent, r.model)} <span class="cost">${esc(r.status)}${r.ts ? " · " + clock(r.ts) : ""}${r.requests ? " · " + t("tok_req", {n: r.requests}) + (r.first_input ? " · " + t("tok_req_first", {f: tok(r.first_input)}) : "") + (r.prefix_tokens ? " · " + t("tok_req_each", {k: tok(r.prefix_tokens)}) : "") : ""}</span>`
      + (r.children_share != null ? `<br><span class="cost">${t("tok_kids", {n: (r.children || []).length + (r.children_more || 0), s: pct(r.children_share)})}</span>` : "")
      + (r.children_share > 1 ? `<br><span class="warn">${t("tok_kids_over")}</span>` : "")
      + `</td>${tokCells(r.tokens)}<td>${money(r.usd)}</td></tr>`;
    for (const c of r.children || []) h += `<tr class="kid"><td>↳ <span class="mono">${esc(c.id)}</span> · ${esc(agentName(c.vendor))}</td>${tokCells(c.tokens)}<td>${money(c.usd)}</td></tr>`;
    if (r.children_more) h += `<tr class="kid"><td colspan="6">${t("tok_kids_more", {n: r.children_more})}</td></tr>`;
    return h;
  }
  function flowHTML(d) {
    let h = `<h2>${t("tok_flow_title")}</h2><p class="lead">${t("tok_flow_lead")}</p>`;
    const T = d.totals || {};
    if (!T.runs) return h + `<p class="lead">${t("tok_empty", {cmd: raw("<code>ccx demo</code>")})}</p>`;
    h += `<p class="stat">${t("tok_total", {n: T.runs, t: tok((T.tokens || {}).total), u: usd(T.usd || 0)})}</p>`;
    h += `<div class="twrap"><table class="ttab">${tokHead(t("tok_col_agent"))}<tbody>`;
    for (const [a, b] of Object.entries(T.by_agent || {})) h += `<tr><td>${who(a)} <span class="cost">${t("tok_task_runs", {n: +b.runs || 0})}${b.requests_per_run ? " · " + t("tok_req_avg", {n: b.requests_per_run, m: b.measured_runs}) + (b.first_input_median ? " · " + t("tok_req_first_med", {f: tok(b.first_input_median)}) : "") + (b.prefix_median ? " · " + t("tok_req_each_med", {k: tok(b.prefix_median)}) : "") : ""}</span></td>${tokCells(b.tokens)}<td>${money(b.usd)}</td></tr>`;
    h += `</tbody></table></div><p class="cost">${t("tok_by_agent_note")}</p>`;
    const kt = (d.children_shown || {}).total || 0;
    h += `<p class="cost">${t("tok_kids_shown", {t: tok(kt)})} ${t("tok_kids_codex_note")}</p>`;
    (d.tasks || []).forEach((g, i) => {
      const open = TOKOPEN[g.key] !== undefined ? TOKOPEN[g.key] : i < 3;
      h += `<details class="tflow" data-tok="${esc(g.key)}"${open ? " open" : ""}><summary><b>${esc(g.title)}</b>${g.kind === "task" && g.name !== g.title ? ` <span class="cost mono">${esc(g.name)}</span>` : ""}<span class="cost">${t("tok_task_runs", {n: +g.runs_total || 0})} · ${tok((g.tokens || {}).total)} · ${money(g.usd)} · ${ago(g.last)}</span></summary>`
        + `<div class="twrap"><table class="ttab">${tokHead(t("tok_col_run"))}<tbody>${(g.runs || []).map(runRows).join("")}</tbody></table></div>`
        + (g.runs_cut ? `<p class="cost">${t("tok_runs_cut", {n: g.runs_cut})}</p>` : "") + `</details>`;
    });
    const c = d.cut || {};
    if (c.tasks) h += `<p class="cost">${t("tok_cut", {n: (d.tasks || []).length, t: c.tasks, r: c.runs, k: tok(c.tokens || 0), u: usd(+c.usd || 0)})}</p>`;
    return h;
  }
  function wantLead(key) {
    if (SNAP || LEADC[key] || LEADBUSY[key]) return;
    LEADBUSY[key] = 1;
    const i = key.indexOf("|"), agent = key.slice(0, i), session = key.slice(i + 1);
    api("/api/leadcost?agent=" + encodeURIComponent(agent) + "&session=" + encodeURIComponent(session))
      .then(j => { LEADC[key] = {ok: j}; }).catch(e => { LEADC[key] = {err: (e && e.message) || "?"}; })
      .then(() => { delete LEADBUSY[key]; if (route().r[0] === "tokens") drawTokens(); });
  }
  function leadBody(key) {
    const c = LEADC[key];
    if (!c) { wantLead(key); return `<p class="cost">${t("tok_lead_loading")}</p>`; }
    if (c.err) return `<p class="cost"><span class="warn">${t("tok_err", {e: c.err})}</span></p>`;
    const j = c.ok;
    if (!j.found) return `<p class="cost">${t("tok_lead_gone")}</p>`;
    let h = `<p class="stat">${t("tok_lead_first", {t: tok(j.first_turn_tokens || 0), m: j.model || "?"})}</p>`;
    h += `<div class="twrap"><table class="ttab"><thead><tr><th>${t("tok_col_part")}</th><th>${t("tok_col_tokens")}</th><th>${t("tok_col_share")}</th><th>${t("tok_col_per100")}</th></tr></thead><tbody>`
      + (j.parts || []).map(x => `<tr><td>${esc(x.part)}</td><td>${tok(x.tokens)}</td><td>${pct(x.share)}</td><td>${money(x.usd_per_100_turns)}</td></tr>`).join("") + `</tbody></table></div>`;
    if (j.parts_cut) h += `<p class="cost">${t("tok_parts_cut", {n: j.parts_cut})}</p>`;
    if ((j.advice || []).length) h += `<p class="cost">${t("tok_lead_advice")}</p><ul>${j.advice.map(a => `<li>${esc(a)}</li>`).join("")}</ul>`;
    if (!j.breaks_total) return h + `<p class="cost">${t("tok_breaks_none")}</p>`;
    h += `<p class="stat">${t("tok_breaks", {n: j.breaks_total, u: money(j.extra_usd)})}</p>`
      + `<div class="twrap"><table class="ttab"><thead><tr><th>${t("tok_col_why")}</th><th>${t("tok_col_when")}</th><th>${t("tok_col_rewritten")}</th><th>${t("tok_usd")}</th></tr></thead><tbody>`
      + (j.breaks || []).map(b => `<tr><td>${esc((b.why || []).join("; "))}</td><td>${esc(b.ts)}</td><td>${tok(b.rewritten_tokens)}</td><td>${money(b.extra_usd)}</td></tr>`).join("") + `</tbody></table></div>`;
    if (j.note) h += `<p class="cost">${esc(j.note)}</p>`;
    return h;
  }
  function leadsCostHTML(d) {
    let h = `<h2>${t("tok_leads_title")}</h2><p class="cost">${t("tok_leads_lead")}</p>`;
    const list = d.leads || [];
    if (!list.length) return h + `<p class="lead">${t("tok_leads_none")}</p>`;
    for (const g of list) {
      const key = g.agent + "|" + g.session;
      h += `<details class="tflow" data-lead="${esc(key)}"${LEADOPEN[key] ? " open" : ""}><summary>${who(g.agent)} <span class="mono">${esc(cut(g.session, 18))}</span>`
        + `<span class="cost">${t("tok_task_runs", {n: +g.runs || 0})} · ${money(g.usd)} · ${ago(g.last)}</span></summary>${LEADOPEN[key] ? leadBody(key) : ""}</details>`;
    }
    return h;
  }
  function renderTokens() {
    let h = banner() + `<div class="crumbs"><a href="#/all">${t("overview")}</a> › ${t("tok_nav")}</div><h1>${t("tok_title")}</h1><p class="lead">${t("tok_lead")}</p>`;
    if (SNAP) return h + `<p class="lead">${t("tok_snap")}</p>`;
    h += `<div class="filters tfilters">` + ["today", "7d", "all"].map(x => `<button data-tperiod="${x}" class="${TOKPERIOD === x ? "on" : ""}" aria-pressed="${TOKPERIOD === x}">${t("tok_p_" + x)}</button>`).join("");
    const ps = (TOK && TOK.projects) || [];
    // TOKPROJ "" sends no project (the server then shows the ui's own --project, if any); "all" asks for every
    // project; what is selected follows what the server says it showed (TOK.project)
    const shownProj = TOK ? (TOK.project || "all") : (TOKPROJ || "all");
    if (ps.length > 1 || TOKPROJ || (TOK && TOK.project)) h += `<select id="tokproj" aria-label="${esc(t("tok_project"))}"><option value="all"${shownProj === "all" ? " selected" : ""}>${t("tok_project_all")}</option>${ps.map(p => `<option value="${esc(p.id)}"${p.id === shownProj ? " selected" : ""}>${esc(p.name)}</option>`).join("")}</select>`;
    h += `<button data-do="tok-refresh">${t("tok_refresh")}</button></div>`;
    if (TOKKEY !== tokKey() || (!TOK && !TOKERR)) { wantTok(); if (!TOK) return h + `<p class="lead">${t("tok_loading")}</p>`; }
    if (TOKERR) return h + `<p class="lead"><span class="warn">${t("tok_err", {e: TOKERR})}</span></p>`;
    return h + measuredHTML(TOK.measured) + mineHTML(TOK.mine) + flowHTML(TOK) + leadsCostHTML(TOK);
  }
  function drawTokens() {
    const keep = window.scrollY;
    $("main").innerHTML = renderTokens();
    window.scrollTo(0, keep);
  }

  /* ---------- U7: who leads this project, when the lead changed, and handing it to another lead ----------
     The buttons run `ccx handoff` through the same prepare -> exact command -> second click; the answer (the handoff
     file and the one line to give the other tool) stays on the panel. Names and paths are data: esc() always. */
  const HANDOFF = {};
  function leadPanelHTML(pr) {
    const sw = pr.lead_switch; if (!sw) return "";
    let h = `<h2 id="leadpanel">${t("sw_title")}</h2><p class="stat">${sw.current ? t("sw_current", {w: raw(who(sw.current))}) : t("sw_unknown")}</p>`;
    const ps = sw.periods || [];
    if (ps.length > 1) h += `<ul class="tl leadtl">${ps.map(p => `<li><time>${p.since ? clock(p.since) : t("sw_start")}</time>${who(p.agent)} <span class="cost">${p.until ? t("sw_until", {at: clock(p.until)}) : t("sw_now")}</span></li>`).join("")}</ul>`;
    const key = pr.id + "|_lead|_", ctl = sw.ctl || [];
    if (ctl.length) {
      h += `<p class="cost">${t("sw_lead")}</p>`;
      h += SNAP ? ctl.map(b => `<div><code class="mono">${esc(b.cmd)}</code></div>`).join("")
        : `<div class="acts">${ctl.map((b, i) => `<button class="btn ${esc(b.style || "")}" data-lbtn="c${i}" data-key="${esc(key)}">${t(b.label)}</button>`).join("")}</div><div class="cmd" data-actbox="${esc(key)}" hidden></div>`;
    }
    const r = HANDOFF[pr.id];
    if (r) h += `<div class="card handoff" role="status"><div class="k">${t("sw_done", {f: r.file})}</div>`
      + (r.blank ? `<div class="k warn">${t("sw_blank", {f: r.file})}</div>` : "")
      + `<div class="k">${t(r.shown_at_start === false ? "sw_paste_read" : "sw_paste", {w: agentName(r.to), d: r.root})}</div>`
      + `<code class="mono" id="hopaste">${esc(r.paste)}</code> <button data-do="copy-paste">${t("copy")}</button></div>`;
    return h;
  }

  /* ---------- a project page ---------- */
  function renderProject(pr) {
    let h = banner() + `<div class="crumbs"><a href="#/all">${t("overview")}</a> › ${esc(pr.name)}</div><h1>${esc(pr.name)}${levelHTML(pr)}</h1><p class="lead mono" style="font-size:13px">${esc(pr.path)}</p>${convLinkHTML(pr.id)}${rulesHTML(pr)}${leadPanelHTML(pr)}<h2>${t("tasks")}</h2><div class="grid">`;
    for (const tk of pr.tasks) {
      const s = stats(tk.pieces), k = acts(tk.pieces).length, ws = new Set();
      walk(tk.pieces, p => { if (p.worker) ws.add(p.worker); });
      h += `<a class="card pcard" href="${href([pr.id, tk.id])}"><div class="top"><b>${esc(taskTitle(tk))}</b>${k ? `<span class="badge">${t("needs_n", {n: k})}</span>` : ""}</div>
        <div class="pbar"><i style="width:${s.n ? Math.round(100 * s.d / s.n) : 0}%"></i></div><div class="m">${t("pieces", {d: s.d, n: s.n})} · ${clock(tk.asked)}</div><div class="whos">${[...ws].map(w => who(w)).join("")}</div></a>`;
    }
    return h + "</div>";
  }

  /* ---------- a task page (or a split piece's own page): the org chart, the to-dos on it, the side panel ---------- */
  const SHOW = 4, NEEDS_SHOWN = 6;
  function statusHTML(p) {
    const steps = t("step");
    if (p.status === "done") return `<span class="st pass">${t(p.verdict && p.verdict.soft ? "st_done_soft" : "st_done")}</span>`;
    if (p.status === "run") return `<span class="st" style="color:var(--teal)">${t("st_run", {s: steps[p.step] || "", t: dur(p.secs)})}${p.tokens ? " · " + tok(p.tokens) : ""}</span>`;
    if (p.status === "review") return `<span class="st" style="color:var(--amber)">${t("st_review")}</span>`;
    if (p.status === "decide") return `<span class="st fail">${t("st_decide")}</span>`;
    if (p.status === "fail") return `<span class="st fail">${t("st_fail")}</span>`;
    if (p.status === "split") return `<span class="st" style="color:var(--teal)">${t("st_split")}</span>`;
    return `<span class="st" style="color:var(--muted)">${t("st_queued")}</span>`;
  }
  function pieceHTML(p, base) {
    const cls = p.act ? p.act.kind : p.status === "run" ? "run" : "";
    const flag = p.act ? `<span class="flag">${p.act.kind === "review" ? t("flag_review") : "!"}</span>` : "";
    const dots = p.status === "run" || p.act ? `<span class="dots">${t("step").map((_, i) => `<i class="${(p.skip || []).includes(i) ? "x" : i < p.step ? "d" : i === p.step ? "n" : ""}"></i>`).join("")}</span>` : "";
    let drill = "";
    if (p.children) {
      const c = p.children, n = c.length, d = c.filter(x => x.status === "done").length, r = c.filter(x => x.status === "run").length, k = below(p);
      const pc = x => (100 * x / n).toFixed(1) + "%";
      const link = href(base.concat([p.id]));
      drill = `<div class="pr">${t("in_split", {n, d, r, k})}</div><span class="inbar"><i class="ok" style="width:${pc(d)}"></i><i class="rn" style="width:${pc(r)}"></i><i class="nd" style="width:${pc(c.filter(x => x.act).length)}"></i></span>`
        + (k ? `<a class="inner" href="${link}">${t("inner_needs", {n: k})}</a> ` : "") + `<a class="drill" href="${link}">${t("open_level")}</a>`;
    }
    if (p.native && p.native.length) drill += ` <span class="native">${t("native", {n: p.native.length})}</span>`;
    const from = p._from ? `<div class="pr">${t("from", {w: agentName(p._from.worker), t: p._from.title})}</div>` : "";
    const dim = (filt === "mine" && !p.act) || (filt === "run" && p.status !== "run") ? " dim" : "";
    const rev = p.reviewer ? `<div class="pr">${t("rev", {w: p.reviewer})}</div>` : "";
    return `<div class="piece ${cls}${dim}${sel === p.id ? " on" : ""}" role="button" tabindex="0" data-sel="${esc(p.id)}">${flag}${from}<div class="pt">${esc(p.title)}</div>${rev}${statusHTML(p)}${dots}${drill}</div>`;
  }
  function columns(list) {
    const groups = new Map();
    for (const p of list) { const k = p.worker || "_wait"; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(p); }
    const known = Object.keys(FIXED);
    const rank = k => k === "_wait" ? 99 : known.includes(k) ? known.indexOf(k) : 10;
    return [...groups.keys()].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b)).map(k => [k, groups.get(k)]);
  }
  function renderTask(pr, tk, chainIds) {
    let node = null, chain = [];
    if (chainIds.length) {
      const f = findPiece(tk.pieces, chainIds[chainIds.length - 1]);
      if (f && f.p.children) { node = f.p; chain = f.chain.concat([f.p]); }
    }
    const list = node ? node.children : tk.pieces;
    const base = [pr.id, tk.id].concat(chain.map(x => x.id));
    for (const p of list) if (p.children) p.children.forEach(ch => { if (ch.worker && ch.worker !== p.worker) ch._from = p; });
    const cols = columns(list);
    const s = stats(list);
    const sep = LANG === "zh" ? "、" : ", ";
    const parts = cols.map(([w, ps]) => t("sum_part", {who: w === "_wait" ? t("notyet") : agentName(w), n: ps.length})).join(sep);
    let h = banner() + `<div class="crumbs"><a href="#/all">${t("overview")}</a> › <a href="${href([pr.id])}">${esc(pr.name)}</a> › `
      + (node ? `<a href="${href([pr.id, tk.id])}">${esc(taskTitle(tk))}</a> › ` + chain.map((x, i) => i === chain.length - 1 ? esc(x.title) : `<a href="${href([pr.id, tk.id].concat(chain.slice(0, i + 1).map(c => c.id)))}">${esc(x.title)}</a>`).join(" › ") : esc(taskTitle(tk))) + `</div>`;
    h += `<h1>${esc(node ? node.title : taskTitle(tk))}${node ? `<span class="lvl">${t("level", {l: chain.length + 1})}</span>` : ""}</h1>`;
    h += `<p class="lead">${node ? t("sub_sum", {parent: agentName(node.worker), n: list.length, parts}) : t("sum", {n: list.length, parts})} ${t("pieces", {d: s.d, n: s.n})}.</p>`;
    const needs = list.filter(p => p.act).sort((a, b) => (a.act.kind === "review") - (b.act.kind === "review"));
    if (needs.length) {
      const first = needs.slice(0, NEEDS_SHOWN);
      h += `<div class="needs"><span style="color:var(--muted);font-size:13.5px;align-self:center">${t("needs_here")}</span>${first.map(p => `<button type="button" data-sel="${esc(p.id)}" class="chip-todo ${p.act.kind === "review" ? "rv" : ""}${sel === p.id ? " sel" : ""}" aria-pressed="${sel === p.id}" title="${esc(p.title)}">${esc(p.title)} · ${t(p.act.what)}</button>`).join("")}`
        + (needs.length > first.length ? `<button type="button" data-filt="mine" class="chip-todo rv">${t("needs_more", {n: needs.length - first.length})}</button>` : "") + `</div>`;
    }
    h += `<div class="filters">${[["all", "f_all"], ["mine", "f_mine"], ["run", "f_run"]].map(([k, l]) => `<button class="${filt === k ? "on" : ""}" data-filt="${k}">${t(l)}</button>`).join("")}</div>`;
    h += `<div class="layout"><div class="card"><div class="orgwrap"><div class="org">`;
    if (!node) {
      const top = tk.kind === "queue" ? (tk.budget ? t("queue_box_b", {n: list.length, b: usd(tk.budget)}) : t("queue_box", {n: list.length}))
        : t("you_asked", {t: taskTitle(tk)});
      h += `<div class="box you"><div class="t">${top}</div><div class="m">${t("asked_at", {h: clock(tk.asked)})}</div></div><div class="vline"></div>`;
      const sent = list.filter(p => p.worker).length;
      const lead = tk.lead && tk.lead.agent ? who(tk.lead.agent, null).replace(/>[^<]*<\/span>$/, ">" + t("boss", {m: agentName(tk.lead.agent) + (tk.lead.model ? " · " + tk.lead.model : "")}) + "</span>") : `<span class="who">${t("boss_unknown")}</span>`;
      h += `<div class="box boss"><div>${lead}</div><div class="t">${t("boss_sum", {n: list.length, s: sent})}</div>`;
      if (tk.spent || tk.budget) h += `<div class="cost">${tk.budget ? t("spent_budget", {u: usd(tk.spent || 0), b: usd(tk.budget)}) : t("spent", {u: usd(tk.spent)})}</div>`;
      const tkey = pr.id + "|" + tk.id + "|_";
      if ((tk.ctl || []).length) h += `<div class="acts tctl">${tk.ctl.map((b, i) => `<button class="btn" data-tbtn="c${i}" data-key="${esc(tkey)}">${t(b.label)}</button>`).join("")}</div><div class="cmd" data-actbox="${esc(tkey)}" hidden></div>`;
      if (tk.helpers && tk.helpers.length) h += `<div class="helper">${t("helper", {n: tk.helpers.length})}</div>`;
      h += `</div>`;
    } else {
      h += `<div class="box boss"><div>${who(node.worker, node.model)}</div><div class="t">${esc(node.title)}</div><div class="m">${t("split_n", {n: list.length})}</div></div>`;
    }
    h += `<div class="cols" style="--half:${(50 / Math.max(1, cols.length)).toFixed(2)}">`;
    for (const [w, ps] of cols) {
      const c = w === "_wait" ? null : tone(w);
      const head = w === "_wait" ? `<span class="who">${t("notyet")}</span>` : who(w, ps.find(p => p.model) ? ps.find(p => p.model).model : "");
      const urgent = ps.filter(p => p.act || p.status === "run" || p.id === sel), rest = ps.filter(p => !(p.act || p.status === "run" || p.id === sel));
      const key = (node ? node.id : tk.id) + ":" + w;
      const shown = expanded[key] ? rest : rest.slice(0, Math.max(0, SHOW - urgent.length)), folded = rest.length - shown.length;
      const spent = ps.reduce((a, p) => a + (p.usd || 0), 0);
      h += `<div class="col ${w === "_wait" ? "wait" : ""}" style="border-top-color:${c ? `var(--c-${c})` : "var(--muted)"}"><div class="head">${head}<span class="cnt">${t("count", {n: ps.length})}</span></div>${spent ? `<div class="spent">${t("col_spent", {u: usd(spent)})}</div>` : ""}
        ${urgent.concat(shown).map(p => pieceHTML(p, base)).join("")}${folded ? `<button class="more" data-more="${esc(key)}">${t("more_done", {n: folded})}</button>` : ""}</div>`;
    }
    h += `</div></div></div><div class="legend">${t("legend")}</div>`;
    const hist = node ? [] : (tk.hist || []);
    if (hist.length) {
      const hk = pr.id + "/" + tk.id;
      h += `<details class="hist" data-hist="${esc(hk)}"${histOpen[hk] ? " open" : ""}><summary>${t("hist")}</summary><ul class="tl">${hist.map(x => `<li class="${esc(x.tone || "")}"><time>${clock(x.ts)}</time>${histText(x)}</li>`).join("")}</ul></details>`;
    }
    if (!node && pr.lead_switch) h += `<p class="stat"><a href="${leadHref(pr)}">${t("sw_title")} ›</a></p>`;
    h += `</div><aside class="drawer card" id="drawer"></aside></div>`;
    if (!sel || !findPiece(list, sel)) sel = needs.length ? needs[0].id : null;
    const old = $("drawer");
    const busy = old && (old.contains(document.activeElement) || !!(old.querySelector("#reasons") || {}).innerHTML);
    $("main").innerHTML = h;
    renderDrawer(list, base, old, busy);
    paintAct();
  }
  /* the fields that change every poll while a run goes on: a panel someone is using keeps its old copy of them */
  function stableOf(p) { const c = Object.assign({}, p); for (const k of ["secs", "tokens", "beat", "ts", "_from"]) delete c[k]; return c; }
  function histText(x) {
    const p = Object.assign({}, x.p || {});
    if (p.w) p.w = agentName(p.w);
    if (p.w2) p.w2 = agentName(p.w2);
    p.soft = p.soft ? "(" + t("soft") + ")" : "";
    return t(x.k, p);
  }

  /* ---------- the side panel: details, and for a red/amber block the reason, evidence and buttons ---------- */
  function renderDrawer(list, base, old, busy) {
    const d = $("drawer"); if (!d) return;
    const f = sel ? findPiece(list, sel) : null;
    const jd = f && JUDGE[judgeKey(f.p)] ? 1 : 0;
    const sig = JSON.stringify([LANG, sel, f && f.p, jd]), stable = JSON.stringify([LANG, sel, f && stableOf(f.p), jd]);
    if (old && (sig === drawerSig || (busy && stable === drawerStable))) { d.replaceWith(old); return; }
    drawerSig = sig; drawerStable = stable;
    if (!f) { d.innerHTML = `<p class="empty">${t("pick")}</p>`; return; }
    const p = f.p, a = p.act;
    let h = "";
    const others = waitingIn(list).filter(x => x.id !== p.id);
    if (NEXT && NEXT.sel === p.id) h += `<p class="nextnote" role="status">${t("next_note", {n: NEXT.n})}</p>`;
    if (others.length) h += `<div class="acts nextrow"><button class="btn" data-do="next-wait" title="${esc(t("next_keys"))}">${t("next_wait", {n: others.length})}</button></div>`;
    if (a) h += `<span class="tag ${a.kind}">${t(a.kind === "review" ? "t_review" : "t_decide")}</span>`;
    h += `<div class="what">${esc(p.title)}${a ? (LANG === "zh" ? "：" : ": ") + t(a.what) : ""}</div>`;
    if (a && a.why) h += `<p class="why">${whyText(a.why)}</p>`;
    h += `<dl class="dl"><dt>${t("d_who")}</dt><dd>${p.worker ? who(p.worker, p.model) : esc(t("notyet"))}${p.effort ? ` <span style="color:var(--muted)">${esc(p.effort)}</span>` : ""}</dd>`;
    h += `<dt>${t("d_state")}</dt><dd>${statusHTML(p)}</dd>`;
    if (p.secs) h += `<dt>${t("d_time")}</dt><dd>${dur(p.secs)}${p.rounds > 1 ? " · " + t("rounds", {n: p.rounds}) : ""}</dd>`;
    if (p.usd || p.tokens) h += `<dt>${t("d_cost")}</dt><dd>${usd(p.usd || 0)}${p.tokens ? " · " + tok(p.tokens) + " tokens" : ""}${p.live ? " · " + t("live") : ""}</dd>`;
    if (p.check) h += `<dt>${t("ev_check")}</dt><dd><span class="${p.check.passed ? "pass" : "fail"}">${t(p.check.passed ? "passed" : "failed")}</span> <span class="mono" style="font-size:12px">${esc(p.check.cmd || "")}</span></dd>`;
    if (p.review && p.review.verdict && p.review.verdict !== "not-run") h += `<dt>${t("ev_review")}</dt><dd><span class="${p.review.verdict === "pass" ? "pass" : "fail"}">${t("rv_" + p.review.verdict)}</span>${p.reviewer ? " · " + esc(p.reviewer) : ""}</dd>`;
    if (p.verdict) h += `<dt>${t("d_verdict")}</dt><dd>${t(p.verdict.ok ? "vd_ok" : "vd_bad")}${p.verdict.soft ? " (" + t("soft") + ")" : ""}</dd>`;
    if (p.children) h += `<dt>${t("d_inside")}</dt><dd>${t("in_split", {n: p.children.length, d: p.children.filter(x => x.status === "done").length, r: p.children.filter(x => x.status === "run").length, k: below(p)})}<br><a href="${href(base.concat([p.id]))}">${t("open_level")}</a></dd>`;
    if (p.run_id) h += `<dt>${t("d_run")}</dt><dd class="mono" style="font-size:12px">${esc(p.run_id)}</dd>`;
    h += `</dl>`;
    const ctl = p.ctl || [], key = base[0] + "|" + base[1] + "|" + p.id;
    h += judgeHTML(p, key);
    if (p.review && p.review.issues && p.review.issues.length) h += `<h3>${t("issues")}</h3><ul class="files">${p.review.issues.map(x => `<li>${esc(x)}</li>`).join("")}</ul>`;
    if (p.native && p.native.length) h += `<h3>${t("d_native", {w: agentName(p.worker)})}</h3><ul class="nlist">${p.native.map(x => `<li><span class="mono">${esc(x.id)}</span><div class="m">${tok(x.tokens)} tokens</div></li>`).join("")}</ul>`;
    if (a || ctl.length) {
      const one = (b, id) => `<button class="btn ${esc(b.style || "")}" data-btn="${id}" data-key="${esc(key)}">${t(b.label)}${b.run && !SNAP ? (b.spends ? " ▸" : "") : ""}</button>`;
      /* undo sits beside the change (judgeHTML), the rest here */
      h += `<div class="acts">${(a ? a.buttons : []).map((b, i) => one(b, "a" + i)).join("")}${ctl.map((b, i) => b.label === "b_undo" ? "" : one(b, "c" + i)).join("")}</div>`;
      if (a && a.then) h += `<p class="cost">${t("q_then_merge", {c: raw(`<code class="mono">${esc(a.then)}</code>`)})}</p>`;
      if (!a && p.status === "run") h += `<p class="cost">${t("ctl_running")}</p>`;
      h += `<div id="reasons"></div><div class="cmd" data-actbox="${esc(key)}" hidden></div><div class="cmd" id="cmd" hidden></div>`;
    }
    d.innerHTML = h;
    wantJudge(p);
    paintAct();
    if (ACT && ACT.key === key) return;
    if (a && chosen && chosen.sel === p.id) fillCmd(chosen.label, chosen.cmd, chosen.prose);
    else if (a && (SNAP || !a.buttons[0].run)) showCmd(p, 0, true);
  }
  /* ---------- U1: is it right? what the agent says beside what ccx ran, and the change from ccx's own snapshots ----------
     Every name, output and diff line is data written by others (a file may be called <img onerror=...>): esc() always. */
  const JUDGE = {}, JBUSY = {}, JFILES = 40;
  function judgeKey(p) { return p && p.run_id ? p.run_id + ":" + p.status + ":" + (p.attempts || 0) + ":" + (p.rounds || 0) : ""; }
  function wantJudge(p) {
    const k = judgeKey(p);
    if (SNAP || !k || p.live || JUDGE[k] || JBUSY[k]) return;
    JBUSY[k] = 1;
    api("/api/judge/" + encodeURIComponent(p.run_id))
      .then(j => { JUDGE[k] = j; }, e => { JUDGE[k] = {error: (e && e.message) || "?"}; })
      .then(() => {
        delete JBUSY[k];
        const cur = currentList(), d = $("drawer");
        if (cur && sel === p.id && d && !d.contains(document.activeElement)) { drawerSig = ""; renderDrawer(cur.list, cur.base, null, false); }
      });
  }
  function diffLines(s) {
    return String(s).split("\n").map(l => {
      const c = l.startsWith("+++") || l.startsWith("---") ? "" : l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : l.startsWith("@@") ? "hunk" : "";
      return c ? `<span class="${c}">${esc(l)}</span>` : esc(l);
    }).join("\n");
  }
  function fileList(list) {
    const more = list.length - JFILES;
    return `<ul class="files mono">${list.slice(0, JFILES).map(x => `<li>${esc(x)}</li>`).join("")}</ul>` + (more > 0 ? `<p class="cost">${t("j_more", {n: more})}</p>` : "");
  }
  function judgeHTML(p, key) {
    const j = JUDGE[judgeKey(p)] || null, c = p.check;
    let h = "";
    const ui = (p.ctl || []).findIndex(b => b.label === "b_undo");
    const undo = ui < 0 ? "" : `<div class="acts undo"><button class="btn bad" data-btn="c${ui}" data-key="${esc(key || "")}">${t("b_undo")}</button><span class="cost">${t("undo_hint")}</span></div>`;
    /* the two columns only for a piece that has run: a queued to-do or a live run has said nothing and ccx has run
       nothing yet, and "no check was given" would be wrong there */
    if (!p.live && (p.run_id || p.summary || p.verification || c)) {
    h += `<div class="judge"><div class="jcol"><h3>${t("j_says")}</h3>`;
    if (p.summary) h += `<p class="says">${esc(p.summary)}</p>`;
    h += p.verification ? `<div class="k">${t("j_verified")}</div><p class="says">${esc(p.verification)}</p>` : `<p class="cost">${t("j_no_verif")}</p>`;
    h += `</div><div class="jcol"><h3>${t("j_ran")}</h3>`;
    if (c) {
      const cls = c.passed ? "pass" : c.passed === false ? "fail" : "cost", word = c.passed ? "passed" : c.passed === false ? "failed" : "j_not_judged";
      h += `<p class="says"><span class="${cls}">${t(word)}</span>${c.exit != null ? " · " + t("j_exit", {e: c.exit}) : ""}</p><code class="mono jcmd">${esc(c.cmd || "")}</code>`;
      if (c.broken) h += `<p class="warn">${esc(c.broken)}</p>`;
      if (c.unchanged_tree) h += `<p class="warn">${t("j_unchanged")}</p>`;
      if (c.weak) h += `<p class="warn">${esc(c.weak)}</p>`;
      h += c.tail ? `<div class="k">${t("j_tail")}</div><pre class="tail mono">${esc(c.tail)}</pre>` : `<p class="cost">${t("j_no_tail")}</p>`;
    } else h += `<p class="cost">${t("j_no_check")}</p>`;
    h += `</div></div>`;
    }
    if (j && j.changed) {
      const mm = j.mismatch;
      if (mm) {
        h += `<div class="mismatch"><b>${t("j_mismatch")}</b>`;
        if ((mm.said_not_changed || []).length) h += `<div class="k">${t("j_said_not")}</div>` + fileList(mm.said_not_changed);
        if ((mm.changed_not_said || []).length) h += `<div class="k">${t("j_changed_not")}</div>` + fileList(mm.changed_not_said);
        if ((mm.changed_not_said || []).length && c && c.cmd) h += `<p class="cost">${t("j_check_files")}</p>`;
        h += `</div>`;
      } else if (j.changed.length) h += `<p class="good-note">${t("j_match")}</p>`;
      h += `<h3>${t("j_changed", {n: j.changed.length})}</h3>` + fileList(j.changed.map(x => x.status + "  " + x.path));
      if (j.chain_from) h += `<p class="cost">${t("j_chain", {r: j.chain_from})}</p>`;
      if ((j.untracked_before || []).length) h += `<p class="cost">${t("j_untracked_before", {n: j.untracked_before.length})}</p>`;
      if (j.diff != null) h += `<details class="diffbox"><summary>${t("j_diff")}</summary><pre class="diff mono">${diffLines(j.diff)}</pre>${j.truncated ? `<p class="warn">${t("j_truncated")}</p>` : ""}</details>`;
      if (j.truncated) h += `<p class="warn">${t("j_truncated")}</p>`;
      h += undo;
    } else {
      if (p.files && p.files.length) h += `<h3>${t("ev_changed")}</h3>` + fileList(p.files);
      h += undo;
    }
    if (p.undone) h += `<p class="good-note">${t("j_undone", {at: clock(p.undone)})}</p>`;
    if (j && j.note) h += `<p class="cost">${t(j.note)}</p>`;
    if (j && j.error) h += `<p class="cost">${t("j_failed", {e: j.error})}</p>`;
    if (!j && p.run_id && !p.live) h += `<p class="cost">${t(SNAP ? "j_snap" : "j_loading")}</p>`;
    return h;
  }
  function whyText(why) {
    const [k, p] = why; const q = Object.assign({}, p || {});
    if (q.at) q.at = clock(q.at); else if ("at" in q) q.at = t("unknown");
    if (q.agent) q.agent = agentName(q.agent);
    return t(k, q);
  }
  function quoteArg(s) { s = String(s).replace(/"/g, "'"); return `"${s}"`; }
  function showCmd(p, i, quiet) {
    const a = p.act, c = $("cmd"), r = $("reasons"); if (!a || !c) return;
    const b = a.buttons[i];
    if (r) r.innerHTML = "";
    if (!quiet && ACT) { ACT = null; paintAct(); }
    if (a.reasons && b.style === "bad" && !quiet) {
      r.innerHTML = `<div class="reasons"><div style="font-size:13px;color:var(--muted);margin-bottom:4px">${t("why_bad")}</div>`
        + [["unfinished", "r1"], ["wrong", "r2"], ["overreach", "r3"]].map(([v, l]) => `<label><input type="radio" name="r" value="${v}"> ${t(l)}</label>`).join("")
        + `<label><input type="radio" name="r" value="other" checked> ${t("r4")}<input type="text" id="rnote" maxlength="200"></label><button class="btn bad" style="margin-top:6px;min-height:32px" data-reason="${i}">${t(b.run && !SNAP ? "act_next" : "r_ok")}</button></div>`;
      c.hidden = true; return;
    }
    if (b.cmd.includes("{reason}") || b.cmd.includes("{note}")) { if (quiet) { c.hidden = true; return; } }
    fillCmd(b.label, b.cmd, b.prose);
  }
  /* prose: a message for the person to give the lead, not a command (labelled so) */
  function fillCmd(label, cmd, prose) {
    const c = $("cmd"); if (!c) return;
    chosen = {sel, label, cmd, prose};
    c.hidden = !cmd;
    c.innerHTML = cmd ? `<div class="k">${t(label)} — ${t(prose ? "paste_lead" : "will_run")}</div><code class="mono" id="cmdtext">${esc(cmd)}</code><button data-do="copy">${t("copy")}</button>` : "";
  }
  function copy(text, btn) {
    const done = () => { btn.textContent = t("copied"); };
    if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text) && done()); return; }
    if (fallbackCopy(text)) done();
  }
  function fallbackCopy(text) {
    const ta = document.createElement("textarea"); ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select(); let ok = false; try { ok = document.execCommand("copy"); } catch (e) { ok = false; } ta.remove(); return ok;
  }

  /* ---------- complete run pages and the confirmed command composer ---------- */
  const runHref = rid => "/runs/" + encodeURIComponent(rid);
  function runText(x) { return `<pre class="run-text">${esc(x && x.text || "")}</pre>${x && x.cut ? `<p>${t("runs_cut")}</p>` : ""}`; }
  function runValue(v) { return v == null ? t("runs_unknown") : typeof v === "object" ? JSON.stringify(v, null, 2) : String(v); }
  async function loadRuns(rid, force) {
    if (SNAP || RUNBUSY || (!force && Date.now() - RUNSTAMP < 5000)) return false;
    RUNBUSY = true;
    try {
      if (rid) {
        const old = RUNPAGE && RUNPAGE.run_id === rid ? RUNPAGE : null;
        const qs = old ? "?after=" + old.activity.cursor + "&source=" + encodeURIComponent(old.activity.source) : "";
        const data = await api("/api/runs/" + encodeURIComponent(rid) + qs);
        if (old && !data.activity.reset) data.activity.events = old.activity.events.concat(data.activity.events);
        RUNPAGE = data;
      } else {
        const qs = new URLSearchParams(RUNFILTER);
        qs.set("page", RUNPAGE_NO);
        RUNLIST = await api("/api/runs?" + qs);
        RUNPAGE_NO = RUNLIST.page;
      }
      RUNERR = ""; RUNSTAMP = Date.now(); return true;
    } catch (e) { RUNERR = e.message; return true; }
    finally { RUNBUSY = false; }
  }
  function runListHTML() {
    if (!RUNLIST && !RUNBUSY && !RUNERR && !SNAP) loadRuns(null, true).then(render);
    const projects = RUNLIST && RUNLIST.projects || [];
    const statuses = ["running", "ok", "ok_self_checked", "review_failed", "review_issues", "blocked", "over_budget", "quota", "env", "failed", "user_stopped", "timeout"];
    return banner() + `<h1>${t("runs_nav")}</h1><p>${t("runs_lead")}</p><div class="run-filters">`
      + `<label>${t("runs_project")}<select data-runfilter="project"><option value="">${t("runs_all")}</option>${projects.map(p => `<option value="${esc(p.id)}"${RUNFILTER.project === p.id ? " selected" : ""}>${esc(p.name)}</option>`).join("")}</select></label>`
      + `<label>${t("runs_status")}<select data-runfilter="status"><option value="">${t("runs_all")}</option>${statuses.map(s => `<option${RUNFILTER.status === s ? " selected" : ""}>${esc(s)}</option>`).join("")}</select></label>`
      + ["date", "until"].map(k => `<label>${t(k === "date" ? "runs_from" : "runs_until")}<input type="date" data-runfilter="${k}" value="${esc(RUNFILTER[k])}"></label>`).join("") + `</div>`
      + (RUNERR ? `<p role="alert">${esc(RUNERR)}</p>` : "")
      + `<div class="run-table"><table><thead><tr>${["runs_time", "runs_who", "runs_task", "runs_status", "runs_cost", "runs_wall", "runs_receipt"].map(k => `<th>${t(k)}</th>`).join("")}</tr></thead><tbody>`
      + ((RUNLIST && RUNLIST.runs) || []).map(r => `<tr><td>${clock(r.ts)}</td><td>${esc(r.from)} → ${esc(r.rung || r.to)}</td><td><a href="${runHref(r.run_id)}">${esc(r.task || r.run_id)}</a><small>${esc(r.project_name)}</small></td><td>${esc(r.status)}</td><td>${usd(r.usd)}</td><td>${dur(r.seconds)}</td><td>${esc(r.summary)}</td></tr>`).join("") + `</tbody></table></div>`
      + (RUNLIST ? `<nav class="acts" aria-label="${esc(t("runs_pages"))}"><button class="btn" data-run-page="${RUNLIST.page - 1}"${RUNLIST.has_previous ? "" : " disabled"}>${t("runs_previous")}</button><span>${t("runs_page", {n: RUNLIST.page + 1, total: RUNLIST.total})}</span><button class="btn" data-run-page="${RUNLIST.page + 1}"${RUNLIST.has_next ? "" : " disabled"}>${t("runs_next")}</button></nav>` : "");
  }
  function runPageHTML(rid) {
    if ((!RUNPAGE || RUNPAGE.run_id !== rid) && !RUNBUSY && !RUNERR && !SNAP) loadRuns(rid, true).then(render);
    if (SNAP) return `<h1>${t("runs_nav")}</h1><p>${t("conv_snap")}</p>`;
    if (RUNERR) return `<p role="alert">${esc(RUNERR)}</p>`;
    const r = RUNPAGE && RUNPAGE.run_id === rid ? RUNPAGE : null;
    if (!r) return `<p>${t("conv_loading")}</p>`;
    const c = r.checks || {}, rv = r.review || {}, receipt = r.receipt || {};
    let h = banner() + `<p><a href="/runs">${t("runs_nav")}</a> › ${esc(rid)}</p><h1>${esc(r.task || rid)}</h1><p>${esc(r.from)} → ${esc(r.rung || r.to)} · ${esc(r.status)}</p>`;
    h += `<section class="card run-section" id="run-dispatch"><h2>${t("runs_dispatch")}</h2>${runText(r.dispatch.brief)}<h3>${t("runs_context")}</h3>${runText(r.dispatch.context)}<details><summary>${t("runs_prompt")}</summary>${runText(r.dispatch.prompt)}</details></section>`;
    h += `<section class="card run-section" id="run-activity"><h2>${t("runs_activity")}</h2><p class="cost">${t("runs_event_note")}</p><ol class="run-events">${r.activity.events.map(e => `<li><span class="cost">${esc(e.ts || t("runs_unknown"))} · ${esc(e.kind)} · ${esc(e.phase || "")}</span><pre>${esc(e.text)}</pre>${e.kind === "command" ? `<small>${t("runs_exit")}: ${esc(runValue(e.exit_code))}</small>` : ""}${e.output ? `<details><summary>${t("runs_output")}</summary><pre>${esc(e.output)}</pre></details>` : ""}</li>`).join("")}</ol></section>`;
    h += `<section class="card run-section" id="run-checks"><h2>${t("runs_checks")}</h2><pre>${esc(c.cmd || t("runs_unknown"))}</pre><p>${t("runs_exit")}: ${esc(runValue(c.exit))}</p><h3>${t("runs_covers")}</h3><pre>${esc(runValue(c.covers))}</pre><p>basis_changed: ${esc(runValue(c.basis_changed))} · added_to: ${esc(runValue(c.added_to))}</p><pre>${esc(c.tail || "")}</pre></section>`;
    h += `<section class="card run-section" id="run-review"><h2>${t("runs_review")}</h2><p>${esc(rv.by || t("runs_unknown"))} · ${esc(rv.verdict || t("runs_unknown"))}</p><pre>${esc(rv.summary || "")}</pre>${rv.issues.map(i => `<pre>${esc(runValue(i))}</pre>`).join("")}${(rv.notes || []).map(n => `<pre>${esc(runValue(n))}</pre>`).join("")}<h3>${t("runs_fixes")}</h3><p>${t("runs_round")}: ${esc(runValue(rv.round))}</p>${rv.fixes.map(f => `<p>${f.run_id ? `<a href="${runHref(f.run_id)}">${esc(f.run_id)}</a>` : t("runs_round") + " " + esc(runValue(f.round))} · ${esc(f.kind)}<br>${esc(f.summary)}</p>`).join("")}</section>`;
    h += `<section class="card run-section" id="run-receipt"><h2>${t("runs_receipt")}</h2><p>${t("runs_cost")}: ${usd(receipt.usd)} · ${t("runs_wall")}: ${dur(receipt.seconds)}</p><pre>${esc(JSON.stringify(receipt, null, 2))}</pre><button class="btn" data-run-diff="${esc(rid)}">${t("runs_diff")}</button> <a href="${judgeHref(rid)}">${t("runs_decide")}</a>${RUNDIFF && RUNDIFF.run_id === rid ? `<pre>${esc(RUNDIFF.diff || t(RUNDIFF.note || "runs_unknown"))}</pre>` : ""}</section>`;
    return h;
  }
  function judgeHref(rid) {
    for (const p of D.projects || []) for (const tk of p.tasks || []) {
      let link = ""; walk(tk.pieces, (x, chain) => { if (x.run_id === rid) link = href([p.id, tk.id].concat(chain.map(c => c.id)), x.id); });
      if (link) return link;
    }
    return "/#/all";
  }
  function selectChatProject(pid) {
    if (pid !== CHATPROJECT) { CHATPROJECT = pid; CHATGEN++; CHATPREP = null; CHATRESULT = null; CHATROLES = []; CHATROLEPROJECT = ""; }
    if (pid && pid !== CHATROLEPROJECT && !SNAP) {
      CHATROLEPROJECT = pid;
      api("/api/roles?project=" + encodeURIComponent(pid)).then(r => {
        if (CHATPROJECT === pid) { CHATROLES = r.roles || []; repaintChat(); }
      }).catch(() => { if (CHATPROJECT === pid) { CHATROLES = []; repaintChat(); } });
    }
  }
  function chatOutcome() {
    if (!CHATRESULT) return "";
    const body = CHATRESULT.delegated === false ? `${t("chat_not_delegated")} · ${esc(CHATRESULT.decision)}<pre>${esc(CHATRESULT.reason)}</pre>`
      : esc(CHATRESULT.error || (CHATRESULT.demo ? t("act_demo") : t("chat_sent")));
    return `<div role="status">${body} ${CHATRESULT.href ? `<a href="${esc(CHATRESULT.href)}">${t("runs_open")}</a>` : ""}</div>`;
  }
  async function refreshChatResult() {
    if (!CHATRESULT || !CHATRESULT.pending || !CHATRESULT.result_url || SNAP) return false;
    const old = CHATRESULT, generation = CHATGEN;
    const result = await api(old.result_url);
    if (CHATGEN !== generation || CHATRESULT !== old) return false;
    CHATRESULT = Object.assign({}, old, result); return true;
  }
  function chatPanel() {
    if (SNAP) return "";
    const projects = D.projects || [];
    if (!CHATPROJECT && projects.length) selectChatProject(projects[0].id);
    const roleButtons = CHATROLES.length ? `<div class="chat-roles" role="group" aria-label="${t("chat_roles")}"><span>${t("chat_roles")}</span> ${CHATROLES.map(r => `<button class="btn" data-chat-role="${esc(r.name)}" title="${esc(r.spec)}">${esc(r.name)}</button>`).join(" ")}</div>` : "";
    return `<section class="card ui-chat"><h2>${t("chat_title")}</h2><p>${t("chat_rule")}</p><label for="chat-project">${t("runs_project")}</label><select id="chat-project">${projects.map(p => `<option value="${esc(p.id)}"${p.id === CHATPROJECT ? " selected" : ""}>${esc(p.name)}</option>`).join("")}</select>${roleButtons}<label for="chat-input">${t("chat_input")}</label><textarea id="chat-input" maxlength="4000" rows="4">${esc(CHATDRAFT)}</textarea><button class="btn" data-chat="preview">${t("chat_preview")}</button>`
      + (CHATPREP ? `<div class="cmd"><p>${t("chat_will")}</p><pre>${esc(CHATPREP.cmd)}</pre>${CHATPREP.role ? `<p>${esc(CHATPREP.role.spec)}</p><pre>${esc(JSON.stringify(CHATPREP.role.effective_defaults))}</pre>${CHATPREP.role.check_notice ? `<p role="note">${esc(CHATPREP.role.check_notice)}</p>` : ""}<pre>${esc(CHATPREP.brief)}</pre>` : ""}<p>${t("chat_estimate")}: ${CHATPREP.estimate === "unknown" ? t("runs_unknown") : usd(CHATPREP.estimate)} · ${t("chat_ttl")}</p><button class="btn primary" data-chat="confirm">${t("chat_confirm")}</button></div>` : "")
      + chatOutcome() + `</section>`;
  }
  function repaintChat() {
    const el = document.querySelector(".ui-chat"); if (el) el.outerHTML = chatPanel();
  }
  document.addEventListener("input", e => { if (e.target.id === "chat-input") { CHATDRAFT = e.target.value; CHATPREP = null; const cmd = document.querySelector(".ui-chat .cmd"); if (cmd) cmd.remove(); } });
  document.addEventListener("change", e => {
    if (e.target.id === "chat-project") { selectChatProject(e.target.value); repaintChat(); }
    if (e.target.dataset.runfilter) { RUNFILTER[e.target.dataset.runfilter] = e.target.value; RUNPAGE_NO = 0; RUNLIST = null; RUNERR = ""; loadRuns(null, true).then(render); }
  });
  document.addEventListener("click", async e => {
    const roleButton = e.target.closest("[data-chat-role]");
    if (roleButton) {
      let task = CHATDRAFT;
      const previous = /^ccx run --role [A-Za-z][A-Za-z0-9_-]* -- ([\s\S]*)$/.exec(task);
      if (previous) { try { task = JSON.parse(previous[1]); } catch (_) { task = previous[1]; } }
      CHATDRAFT = `ccx run --role ${roleButton.dataset.chatRole} -- ${JSON.stringify(task)}`;
      CHATGEN++; CHATPREP = null; CHATRESULT = null; repaintChat();
      const input = $("chat-input"); if (input) input.focus();
      return;
    }
    const page = e.target.closest("[data-run-page]");
    if (page) { if (!page.disabled && !RUNBUSY) { RUNPAGE_NO = Math.max(0, Number(page.dataset.runPage)); loadRuns(null, true).then(render); } return; }
    const diff = e.target.closest("[data-run-diff]");
    if (diff) { try { RUNDIFF = await api("/api/judge/" + encodeURIComponent(diff.dataset.runDiff)); render(); } catch (err) { RUNERR = err.message; render(); } return; }
    const btn = e.target.closest("[data-chat]"); if (!btn || btn.disabled) return;
    btn.disabled = true;
    try {
      if (btn.dataset.chat === "preview") { CHATRESULT = null; const project = CHATPROJECT, text = CHATDRAFT, generation = CHATGEN; const prep = await post("/api/chat/prepare", {project, text}); CHATPREP = generation === CHATGEN && project === CHATPROJECT && text === CHATDRAFT ? prep : null; }
      else if (CHATPREP) { const nonce = CHATPREP.nonce, generation = CHATGEN; CHATPREP = null; const result = await post("/api/chat/run", {nonce}); if (generation === CHATGEN) CHATRESULT = result; }
    } catch (err) { CHATRESULT = {error: err.message}; CHATPREP = null; }
    repaintChat();
  });

  /* ---------- routing: existing pages plus /runs and /runs/<id> ---------- */
  function route() {
    const [path, qs] = (location.hash.replace(/^#\/?/, "") || "").split("?");
    const real = /^\/runs(?:\/|$)/.test(location.pathname) ? location.pathname : "";
    const r = (path || real) ? (path || real).split("/").map(decodeURIComponent).filter(Boolean) : [];
    const s = new URLSearchParams(qs || "").get("sel");
    return {r, s};
  }
  let lastRoute = "";
  function render() {
    if (!D) return;
    LANG = chooseLang();
    document.documentElement.lang = LANG === "zh" ? "zh-CN" : "en";
    const {r, s} = route();
    const key = r.join("/");
    const sameRoute = key === lastRoute;
    if (key !== lastRoute) { if (r[0] === "conv" && r[1]) selectChatProject(r[1]); lastRoute = key; filt = "all"; sel = s || null; RUNERR = ""; RUNSTAMP = 0; }
    else if (s && pending !== s) { sel = s; }
    pending = s;
    renderSide(r);
    if (sameRoute && document.activeElement && document.activeElement.id === "chat-input" && document.querySelector(".ui-chat")) return;
    const main = $("main");
    if (r[0] === "runs") { main.innerHTML = r[1] ? runPageHTML(r[1]) : runListHTML(); return; }
    if (r[0] === "discuss") { main.innerHTML = discHTML(r[1]); return; }
    if (r[0] === "conv") { drawConv(r[1], r[2]); return; }
    if (r[0] === "tokens") { drawTokens(); return; }
    const pr = r.length ? findProject(r[0]) : null;
    const tk = pr && r[1] ? findTask(pr, r[1]) : null;
    if (r[0] === "all") { main.innerHTML = renderOverview(); paintAct(); return; }
    if (!pr) { main.innerHTML = renderMap(r[0] === "map" ? r[1] : null) + chatPanel(); paintAct(); return; }   /* P2-10: #/ and #/map/<project> */
    if (!tk) {
      main.innerHTML = renderProject(pr); paintAct();
      if (r[1] === "_lead" && LEADJUMP !== key) { LEADJUMP = key; const lp = $("leadpanel"); if (lp) lp.scrollIntoView({block: "start"}); }
      if (r[1] !== "_lead") LEADJUMP = "";
      return;
    }
    const keep = window.scrollY;
    renderTask(pr, tk, r.slice(2));
    window.scrollTo(0, keep);
  }
  function currentList() {
    const {r} = route(); const pr = findProject(r[0]); const tk = pr && findTask(pr, r[1]); if (!tk) return null;
    if (r.length > 2) { const f = findPiece(tk.pieces, r[r.length - 1]); if (f && f.p.children) return {list: f.p.children, base: [pr.id, tk.id].concat(f.chain.map(x => x.id)).concat([f.p.id])}; }
    return {list: tk.pieces, base: [pr.id, tk.id]};
  }

  /* ---------- events (one listener; no inline handlers, the page's CSP forbids them) ---------- */
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-sel],[data-filt],[data-more],[data-btn],[data-tbtn],[data-rbtn],[data-lbtn],[data-reason],[data-do],[data-sug],[data-tperiod]");
    if (!el) return;
    if (el.dataset.tperiod) { TOKPERIOD = el.dataset.tperiod; drawTokens(); return; }
    if (el.dataset.do === "tok-refresh") { for (const k in LEADC) delete LEADC[k]; wantTok(true); return; }
    if (el.dataset.do === "say-prep") { prepSay(); return; }
    if (el.dataset.do === "say-run") { runSay(); return; }
    if (el.dataset.do === "say-cancel") { SAY = null; paintSay(); return; }
    if (el.dataset.sug !== undefined) { if (!SNAP && !el.disabled) decideSug(el.dataset.sug, el.dataset.ok === "1"); return; }
    if (el.dataset.do === "act-cancel") { ACT = null; paintAct(); return; }
    if (el.dataset.do === "next-wait") { stepWaiting(1); return; }
    if (el.dataset.do === "act-run") { runAct(); return; }
    if (el.dataset.do === "act-usd") {
      const v = ($("usdin") || {}).value;
      if (ACT) { ACT.usd = v; prepare(ACT.key, ACT.btn, ACT.b, {usd: v}); }
      return;
    }
    if (el.dataset.tbtn !== undefined) {           /* a task's own control (the queue's budget) */
      const w = where(el.dataset.key), tk = findTask(findProject(w.project), w.task);
      if (tk) pressBtn(el.dataset.key, tk, el.dataset.tbtn);
      return;
    }
    if (el.dataset.lbtn !== undefined) {           /* U7: the project's switch-lead panel */
      const pr = findProject(where(el.dataset.key).project);
      if (pr && pr.lead_switch) pressBtn(el.dataset.key, pr.lead_switch, el.dataset.lbtn);
      return;
    }
    if (el.dataset.do === "copy-paste") { const c = $("hopaste"); if (c) copy(c.textContent, el); return; }
    if (el.dataset.rbtn !== undefined) {           /* the "running now" strip's stop: that piece's own button */
      const w = where(el.dataset.key), tk = findTask(findProject(w.project), w.task), f = tk && findPiece(tk.pieces, w.piece);
      if (f) pressBtn(el.dataset.key, f.p, el.dataset.rbtn);
      return;
    }
    if (el.dataset.do === "lang") { LANG = LANG === "zh" ? "en" : "zh"; try { localStorage.setItem("ccx-lang", LANG); } catch (x) { /* ok */ } render(); return; }
    if (el.dataset.do === "theme") {
      const root = document.documentElement, dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark"; try { localStorage.setItem("ccx-theme", root.dataset.theme); } catch (x) { /* ok */ } return;
    }
    if (el.dataset.do === "tests") { TESTS = !TESTS; try { localStorage.setItem("ccx-tests", TESTS ? "1" : ""); } catch (x) { /* ok */ } D = view(ALL); render(); return; }
    if (el.dataset.do === "copy") { const c = $("cmdtext"); if (c) copy(c.textContent, el); return; }
    if (el.dataset.filt) { filt = el.dataset.filt; render(); return; }
    if (el.dataset.more) { expanded[el.dataset.more] = 1; render(); return; }
    const cur = currentList();
    if (el.dataset.sel !== undefined && !e.target.closest("a[href]")) {
      sel = el.dataset.sel; NEXT = null; render();
      if (innerWidth < 1100) { const d = $("drawer"); if (d) d.scrollIntoView({behavior: "smooth", block: "start"}); }
      return;
    }
    if (!cur) return;
    const f = sel ? findPiece(cur.list, sel) : null; if (!f || !(f.p.act || (f.p.ctl || []).length)) return;
    if (el.dataset.btn !== undefined) { pressBtn(el.dataset.key, f.p, el.dataset.btn); return; }
    if (el.dataset.reason !== undefined && f.p.act) {
      const i = +el.dataset.reason, b = f.p.act.buttons[i];
      const pick = document.querySelector("#reasons input[name=r]:checked"), note = ($("rnote") || {}).value || "";
      const reason = pick ? pick.value : "other";
      const text = note || t("r_" + reason + "_note");
      $("reasons").innerHTML = "";
      if (b.run && !SNAP) { prepare(cur.base[0] + "|" + cur.base[1] + "|" + f.p.id, "a" + i, b, {reason, note: text}); return; }
      const cmd = b.cmd.split("{reason}").join(reason).split("{note}").join(quoteArg(b.cmd.includes("{reason}") ? text : reason + ": " + text));
      fillCmd(b.label, cmd);
    }
  });
  document.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches(".piece[data-sel]")) { e.preventDefault(); e.target.click(); }
    /* j / k: the next / previous piece that waits for you (not while typing) */
    if ((e.key === "j" || e.key === "k") && !e.ctrlKey && !e.metaKey && !e.altKey && !(e.target.closest && e.target.closest("input,textarea,select,[contenteditable]"))) {
      if (currentList()) { e.preventDefault(); stepWaiting(e.key === "j" ? 1 : -1); }
    }
  });
  document.addEventListener("input", (e) => {
    if (e.target.id === "search") { query = e.target.value; const {r} = route(); renderSide(r); }
    if (e.target.id === "usdin" && ACT) ACT.usd = e.target.value;
    if (e.target.id === "saytext") {
      const key = e.target.dataset.saykey, max = (CONV && CONV.say_max) || 4000;
      DRAFT[key] = e.target.value;
      const n = $("saycount"); if (n) n.textContent = t("conv_chars", {n: e.target.value.length, m: max});
      if (SAY && SAY.key === key && SAY.stage !== "busy" && SAY.text !== e.target.value) { SAY = null; paintSay(); }
    }
  });
  document.addEventListener("toggle", (e) => {
    const ds = e.target.dataset || {};
    if (ds.hist) histOpen[ds.hist] = e.target.open;
    if (ds.tok !== undefined) TOKOPEN[ds.tok] = e.target.open;
    if (ds.lead !== undefined && !!LEADOPEN[ds.lead] !== e.target.open) { LEADOPEN[ds.lead] = e.target.open; if (e.target.open) drawTokens(); }
  }, true);
  document.addEventListener("change", (e) => { if (e.target.id === "tokproj") { TOKPROJ = e.target.value; drawTokens(); } });
  addEventListener("hashchange", render);

  /* ---------- talking to ccx ui ---------- */
  async function api(path, opts) {
    const r = await fetch(path, Object.assign({headers: {"X-CCX-Token": TOKEN}, cache: "no-store", credentials: "omit"}, opts || {}));
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }
  /* Only a real change redraws the page; while a run goes on, its time and tokens are patched in place, so clicks,
     focus and scroll are left alone. */
  const VOLATILE = new Set(["secs", "tokens", "beat", "generated", "last", "reading_age_min", "hours_left"]);
  function stableSig(d) { return d ? JSON.stringify(d, (k, v) => VOLATILE.has(k) ? undefined : v) : ""; }
  function patchLive() {
    const live = $("side") && $("side").querySelector(".brand .live");
    if (live && D) live.innerHTML = `<span class="dot"></span>${t("updated", {a: raw(ago(D.generated))})}`;
    for (const r of (D && D.running) || []) for (const el of document.querySelectorAll("[data-rsecs]")) if (el.dataset.rsecs === r.piece) el.innerHTML = t("run_for", {t: dur(r.secs)});
    const cur = currentList(); if (!cur) return;
    walk(cur.list, p => {
      if (p.status !== "run") return;
      for (const el of document.querySelectorAll(".piece[data-sel]")) if (el.dataset.sel === p.id) {
        const st = el.querySelector(".st"); if (st) st.outerHTML = statusHTML(p);
      }
    });
    const f = sel ? findPiece(cur.list, sel) : null, d = $("drawer");
    if (f && f.p.status === "run" && d && !d.contains(document.activeElement)) { drawerSig = ""; renderDrawer(cur.list, cur.base, null, false); }
  }
  /* one read of /api/data; true when something besides the ticking numbers changed */
  async function refresh() {
    const got = await api("/api/data");
    const changed = stableSig(got) !== stableSig(ALL) || OFFLINE;
    ALL = got; D = view(got); OFFLINE = false; lastOk = Date.now();
    return changed;
  }
  /* U5: new to-dos are read out by screen readers through the one live region outside the redrawn page */
  let SEEN = null;
  function announce() {
    const now = new Set(), fresh = [];
    for (const pr of (D && D.projects) || []) for (const tk of pr.tasks) walk(tk.pieces, p => {
      if (!p.act) return;
      const k = pr.id + "|" + tk.id + "|" + p.id + "|" + p.act.what;
      now.add(k);
      if (SEEN && !SEEN.has(k)) fresh.push(p.title + " — " + t(p.act.what));
    });
    for (const {c, x} of convTodos()) {
      const k = c.id + "|" + x.key + "|" + x.kind + "|" + x.id;
      now.add(k);
      if (SEEN && !SEEN.has(k)) fresh.push(x.text + " — " + t(x.kind === "stuck" ? "conv_todo_stuck" : "conv_todo_asks", {n: x.run, w: agentName(vendorOf(x.from))}));
    }
    SEEN = now;
    const el = $("announce");
    if (el && fresh.length) el.textContent = t("todo_new", {n: fresh.length}) + " " + fresh.slice(0, 3).join("; ");
  }
  async function poll() {
    try {
      let changed = await refresh();
      changed = (await refreshChatResult()) || changed;
      const rt = route().r;
      if (rt[0] === "runs") changed = (await loadRuns(rt[1], true)) || changed;
      if (rt[0] === "conv" && rt[1] && !SNAP) { try { changed = (await loadConv(rt[1])) || changed; } catch (e) { /* shown on the page */ } }
      if (changed) { render(); announce(); } else patchLive();
    } catch (e) {
      if (!OFFLINE && Date.now() - lastOk > 8000) { OFFLINE = true; render(); }
    }
    setTimeout(poll, route().r[0] === "runs" ? 5000 : ((D && D.poll_s) || 3) * 1000);
  }
  /* "still open"; hidden=1 from a background tab, whose timers the browser wakes about once a minute: the server then
     waits several minutes instead of one before it decides the page is gone */
  function alive() { if (!SNAP && TOKEN) api("/api/alive" + (document.hidden ? "?hidden=1" : ""), {method: "POST"}).catch(() => {}); }
  function beat() {
    if (!OFFLINE || Date.now() - lastOk < 60000) alive();
    setTimeout(beat, ((D && D.beat_s) || 10) * 1000);
  }
  /* shown again: say so at once, not in 10 s. Going hidden sends nothing: closing a tab also turns it hidden, and that
     last word must not keep the server up for minutes; a tab that stays open says "hidden" on its next timer beat */
  document.addEventListener("visibilitychange", () => { if (!document.hidden) alive(); });
  addEventListener("focus", alive);

  async function start() {
    try { const th = localStorage.getItem("ccx-theme"); if (th === "dark" || th === "light") document.documentElement.dataset.theme = th; } catch (e) { /* ok */ }
    try { TESTS = localStorage.getItem("ccx-tests") === "1"; } catch (e) { /* ok */ }
    const inlineStr = document.getElementById("ccx-strings"), snap = document.getElementById("ccx-snapshot");
    if (snap) {
      SNAP = true; STR = JSON.parse(inlineStr.textContent); ALL = JSON.parse(snap.textContent); D = view(ALL);
      if (!location.hash) location.hash = "#/";
      render(); return;
    }
    const m = location.hash.match(/^#k=([A-Za-z0-9_-]+)(?:&(\/.*))?$/);      // #k=TOKEN or #k=TOKEN&/project/task
    if (m) {
      TOKEN = m[1];
      try { sessionStorage.setItem("ccx-token", TOKEN); } catch (e) { /* ok */ }
      history.replaceState(null, "", location.pathname + "#" + (m[2] || "/"));
    } else {
      try { TOKEN = sessionStorage.getItem("ccx-token") || ""; } catch (e) { TOKEN = ""; }
    }
    if (/^\/runs(?:\/|$)/.test(location.pathname)) history.replaceState(null, "", "/#" + location.pathname);
    try { STR = await (await fetch("/strings.json", {cache: "no-store"})).json(); } catch (e) { /* keys show */ }
    LANG = chooseLang();
    if (!TOKEN) { $("main").innerHTML = `<h1>ccx ui</h1><p class="lead">${t("no_token")}</p>`; return; }
    alive();
    await poll();
    setTimeout(beat, ((D && D.beat_s) || 10) * 1000);
  }
  start();
})();
