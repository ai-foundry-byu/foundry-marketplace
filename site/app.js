/* AI Foundry Marketplace: a static, hash-routed single page over catalog.json.
   No build step, no tracking. Markdown via marked, sanitized with DOMPurify. */
(function () {
  "use strict";

  var SITE = "https://ai-foundry-byu.github.io/foundry-marketplace/";
  var CATALOG_URL = SITE + "catalog.json";
  var TYPE_ORDER = { skill: 0, agent: 1, hook: 2, template: 3, plugin: 4 };
  var TYPE_LABEL = { skill: "Skill", agent: "Agent", hook: "Hook", template: "Template", plugin: "Plugin" };
  var MAT_LABEL = { proven: "Proven", "new": "New", unlabeled: "Unlabeled", external: "External", mixed: "Mixed" };
  var MAT_EXPLAIN = {
    proven: "Runs in production in our own harness today, generalized for this marketplace.",
    "new": "Written for this marketplace, not yet battle-tested. Please report what breaks.",
    unlabeled: "The plugin README does not say how mature this is yet.",
    external: "Maintained in its own repository. Read its README for status."
  };

  var app = document.getElementById("app");
  var live = document.getElementById("live");
  var DATA = null;
  var byId = {};
  var pluginByName = {};

  // ------------------------------------------------------------ helpers
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function inlineCode(s) {
    // escape, then turn `x` into <code>x</code> (for README table text)
    return esc(s).replace(/`([^`]+)`/g, "<code>$1</code>");
  }
  function enc(s) { return encodeURIComponent(s); }
  function itemHref(it) { return "#/item/" + enc(it.plugin) + "/" + enc(it.slug); }
  function pluginHref(name) { return "#/plugin/" + enc(name); }
  function stageName(id) {
    var st = DATA.stages[id];
    return st ? st.name : "";
  }
  function stageText(it) {
    if (it.all_stages) return "Every stage";
    if (!it.stages || !it.stages.length) return it.external ? "" : "No stage";
    if (it.stages.length === 1) return "Stage " + it.stages[0] + " " + stageName(it.stages[0]);
    return "Stages " + it.stages.join(", ");
  }
  function announce(msg) {
    live.textContent = "";
    setTimeout(function () { live.textContent = msg; }, 30);
  }
  function setTitle(t) { document.title = t ? t + " | AI Foundry Marketplace" : "AI Foundry Marketplace"; }
  function typeBadge(t) { return '<span class="badge badge-type t-' + esc(t) + '">' + esc(TYPE_LABEL[t] || t) + "</span>"; }
  function matBadge(m) {
    return '<span class="badge m-' + esc(m) + '" title="' + esc(MAT_EXPLAIN[m] || "") + '">' + esc(MAT_LABEL[m] || m) + "</span>";
  }
  function sortItems(list) {
    var order = {};
    DATA.plugins.forEach(function (p, i) { order[p.name] = i; });
    return list.slice().sort(function (a, b) {
      return (order[a.plugin] - order[b.plugin]) ||
        (TYPE_ORDER[a.type] - TYPE_ORDER[b.type]) ||
        a.name.localeCompare(b.name);
    });
  }

  // A command block: label, copy button, and the exact text in <code>.
  function cmdBlock(text, label) {
    var wrap = String(text).indexOf("\n") < 0 ? " wrap" : "";
    return '<div class="cmd' + wrap + '"><div class="cmd-bar"><span class="label">' + esc(label || "Run") +
      '</span><button type="button" class="copy" aria-label="Copy ' + esc(label || "command") + '">Copy</button></div>' +
      "<pre><code>" + esc(text) + "</code></pre></div>";
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).catch(function () { return fallbackCopy(text); });
    }
    return fallbackCopy(text);
  }
  function fallbackCopy(text) {
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "-1000px";
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      if (ok) resolve(); else reject(new Error("copy failed"));
    });
  }
  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest ? ev.target.closest(".copy") : null;
    if (!btn) return;
    var code = btn.closest(".cmd").querySelector("code");
    var text = code ? code.textContent : "";
    copyText(text).then(function () {
      btn.textContent = "Copied";
      btn.classList.add("done");
      announce("Copied to the clipboard");
      setTimeout(function () { btn.textContent = "Copy"; btn.classList.remove("done"); }, 1800);
    }, function () {
      btn.textContent = "Select";
      var r = document.createRange();
      r.selectNodeContents(code);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(r);
      announce("Copy is blocked here. The text is selected; press Control or Command plus C.");
    });
  });

  // Markdown: marked + DOMPurify, links made absolute against the file's folder on GitHub.
  function renderMarkdown(md, baseBlob, baseRaw) {
    if (!md) return "";
    var html;
    if (window.marked && window.DOMPurify) {
      setupMarked();
      html = window.DOMPurify.sanitize(window.marked.parse(md, { gfm: true, breaks: false }));
    } else {
      return "<pre>" + esc(md) + "</pre>";
    }
    var box = document.createElement("div");
    box.innerHTML = html;
    box.querySelectorAll("a[href]").forEach(function (a) {
      var h = a.getAttribute("href");
      if (/^#/.test(h)) { a.removeAttribute("href"); return; }
      if (!/^[a-z][a-z0-9+.-]*:/i.test(h) && baseBlob) {
        try { a.setAttribute("href", new URL(h, baseBlob).href); } catch (e) { a.removeAttribute("href"); }
      }
      if (/^https?:/i.test(a.getAttribute("href") || "")) a.setAttribute("rel", "noopener");
    });
    box.querySelectorAll("img[src]").forEach(function (img) {
      var s = img.getAttribute("src");
      if (!/^[a-z][a-z0-9+.-]*:/i.test(s) && baseRaw) {
        try { img.setAttribute("src", new URL(s, baseRaw).href); } catch (e) { img.remove(); }
      }
      img.setAttribute("loading", "lazy");
    });
    // demote h1 inside bodies so the page keeps one h1
    box.querySelectorAll("h1").forEach(function (h) {
      var h2 = document.createElement("h2");
      h2.innerHTML = h.innerHTML;
      h.replaceWith(h2);
    });
    return box.innerHTML;
  }
  // Raw HTML in a SKILL.md is shown as text: bodies mention placeholders like <path>.
  var markedReady = false;
  function setupMarked() {
    if (markedReady || !window.marked) return;
    window.marked.use({ renderer: { html: function (t) { return esc(typeof t === "string" ? t : (t && (t.raw || t.text)) || ""); } } });
    markedReady = true;
  }
  function dirOf(url) { return url ? url.replace(/[^/]*$/, "") : ""; }

  // ------------------------------------------------------------ install commands
  function pluginCmds(pluginName) {
    var mp = DATA.marketplace;
    return ["/plugin marketplace add " + mp.repo, "/plugin install " + pluginName + "@" + mp.name];
  }
  function skillDir(it, scope) { return (scope === "project" ? ".claude/skills/" : "~/.claude/skills/") + it.name; }
  function agentDir(scope) { return scope === "project" ? ".claude/agents" : "~/.claude/agents"; }

  function fileLoop(dest, base, files) {
    var list = files.map(function (f) { return "  " + f + " \\"; });
    list[list.length - 1] = list[list.length - 1].replace(/ \\$/, "");
    return [
      "d=" + dest,
      "base=" + base,
      "for f in \\",
      list.join("\n"),
      "do",
      '  mkdir -p "$d/$(dirname "$f")" && curl -fsSL "$base/$f" -o "$d/$f"',
      "done"
    ].join("\n");
  }
  function skillCmd(it, scope) {
    var dir = skillDir(it, scope);
    var files = it.files || [];
    if (files.length <= 1) {
      return "mkdir -p " + dir + " && curl -fsSL " + it.raw_url + " -o " + dir + "/SKILL.md";
    }
    var base = it.raw_url.replace(/\/SKILL\.md$/, "");
    return fileLoop(dir, base, files.map(function (f) { return f.path; }));
  }
  function agentCmd(it, scope) {
    var dir = agentDir(scope);
    return "mkdir -p " + dir + " && curl -fsSL " + it.raw_url + " -o " + dir + "/" + it.name + ".md";
  }
  function templateCmd(it) {
    var files = it.files || [];
    if (files.length === 1 && it.raw_url) {
      var fname = files[0].path.split("/").pop();
      return "curl -fsSL " + it.raw_url + " -o " + fname;
    }
    var first = files[0];
    var base = first.raw_url.slice(0, first.raw_url.length - first.path.length).replace(/\/$/, "");
    return fileLoop(".", base, files.map(function (f) { return f.path; }));
  }
  function agentPrompt(it, scope) {
    var where = scope === "project" ? "this project only" : "all my projects";
    var id = it.id;
    if (it.type === "skill") {
      return "Read " + CATALOG_URL + " and find the item with id \"" + id + "\". Install that skill for " + where +
        ": download every file in its \"files\" list from its raw_url into " + skillDir(it, scope) +
        "/ keeping the folder layout. Then read the SKILL.md and tell me in two sentences when you will use it." +
        (it.needs_plugin ? " It calls scripts from the " + it.plugin + " plugin, so if they are missing, tell me to install the plugin instead." : "");
    }
    if (it.type === "agent") {
      return "Read " + CATALOG_URL + " and find the item with id \"" + id + "\". Install that subagent for " + where +
        ": download its raw_url to " + agentDir(scope) + "/" + it.name + ".md. Then tell me in two sentences what it does and when you will hand work to it.";
    }
    if (it.type === "template") {
      return "Read " + CATALOG_URL + " and find the item with id \"" + id + "\". Copy that template's files into this project where they belong, " +
        "fill in the placeholders from what you know about this project, and show me what you changed.";
    }
    return "Install the " + it.plugin + " plugin from the AI Foundry marketplace: run /plugin marketplace add " + DATA.marketplace.repo +
      " and then /plugin install " + it.plugin + "@" + DATA.marketplace.name + ". Read its README at " +
      (pluginByName[it.plugin] && pluginByName[it.plugin].readme_url || DATA.marketplace.repo_url) +
      " and tell me what it now does on its own" + (it.type === "hook" ? ", including how to turn the " + it.name + " hook off" : "") + ".";
  }
  function sitePrompt() {
    return "Read " + CATALOG_URL + ". It lists skills, agents, hooks and templates for Claude Code, each with an SDLC stage (0 Scaffold to 8 Feedback) and a maturity label. " +
      "Work out which stage this project is in from its files, pick the items that fit that stage, and tell me which ones you picked and why. " +
      "Then install them: prefer whole plugins (/plugin marketplace add " + DATA.marketplace.repo + ", then /plugin install <plugin>@" + DATA.marketplace.name +
      "), and for a single skill or agent copy its files from their raw_url into .claude/skills/<name>/ or .claude/agents/.";
  }

  // ------------------------------------------------------------ cards
  function itemCard(it) {
    var meta = [];
    meta.push("<span>" + esc(it.plugin) + "</span>");
    var st = stageText(it);
    if (st) meta.push("<span>" + esc(st) + "</span>");
    return '<a class="card" href="' + itemHref(it) + '">' +
      '<div class="badges">' + typeBadge(it.type) + matBadge(it.maturity) + "</div>" +
      "<h3>" + esc(it.name) + "</h3>" +
      '<p class="desc">' + inlineCode(it.description || "No description yet.") + "</p>" +
      '<div class="meta">' + meta.join("") + "</div></a>";
  }
  function countsText(p) {
    var c = p.counts || {};
    var parts = [];
    ["skill", "agent", "hook", "template"].forEach(function (t) {
      if (c[t]) parts.push(c[t] + " " + TYPE_LABEL[t].toLowerCase() + (c[t] > 1 ? "s" : ""));
    });
    return parts.join(", ");
  }
  function pluginCard(p, withInstall) {
    var badges = (p.starter ? '<span class="badge badge-starter">Starter</span>' : "") +
      (p.external ? matBadge("external") : "");
    return '<div class="card card-plugin">' +
      (badges ? '<div class="badges">' + badges + "</div>" : "") +
      '<h3><a href="' + pluginHref(p.name) + '">' + esc(p.name) + "</a></h3>" +
      '<p class="desc">' + inlineCode(p.description) + "</p>" +
      (p.external ? '<p class="counts">External plugin, maintained in its own repository</p>' : '<p class="counts">' + esc(countsText(p)) + "</p>") +
      (withInstall ? '<div class="install-mini">' + cmdBlock(pluginCmds(p.name)[1], "Install") + "</div>" : "") +
      "</div>";
  }

  // ------------------------------------------------------------ pages
  function pageHome() {
    setTitle("");
    var items = DATA.items.filter(function (i) { return !i.external; });
    var proven = items.filter(function (i) { return i.maturity === "proven"; }).length;
    var starters = DATA.plugins.filter(function (p) { return p.starter; });
    var others = DATA.plugins.filter(function (p) { return !p.starter; });
    var mp = DATA.marketplace;
    app.innerHTML =
      '<section class="hero"><div class="wrap">' +
      "<h1 tabindex=\"-1\">Build your own Claude Code harness, one tested piece at a time.</h1>" +
      "<p>The AI Foundry Marketplace is a free, open set of skills, agents, hooks and templates for Claude Code, organized around the eight-stage SDLC we use to ship software with agents. " +
      "Every item says whether it runs in our own harness today or was written for this marketplace and is not yet battle-tested.</p>" +
      '<div class="actions"><a class="btn btn-primary" href="#/browse">Browse everything</a><a class="btn btn-ghost" href="#/sdlc">See the SDLC</a></div>' +
      '<div class="stats"><span><strong>' + items.length + "</strong>items</span><span><strong>" + DATA.plugins.length +
      "</strong>plugins</span><span><strong>" + proven + "</strong>proven in production</span><span><strong>9</strong>SDLC stages</span></div>" +
      "</div></section>" +

      '<div class="wrap">' +
      '<section class="section" aria-labelledby="start-h"><div class="section-head"><h2 id="start-h">Start here: the starter set</h2>' +
      '<a href="#/browse">All items</a></div>' +
      '<p class="lede">Three plugins cover the workflow, the safety rails and the QA. Add the marketplace once, then install each one inside Claude Code.</p>' +
      cmdBlock(pluginCmds("x")[0], "Add the marketplace once") +
      '<div class="grid" style="margin-top:14px">' + starters.map(function (p) { return pluginCard(p, true); }).join("") + "</div></section>" +

      '<section class="section" aria-labelledby="agent-h"><div class="callout">' +
      '<h2 id="agent-h">Or have your agent do it</h2>' +
      "<p>Paste this into Claude Code in your project. It reads the catalog, works out your stage, and installs what fits.</p>" +
      cmdBlock(sitePrompt(), "Prompt") + "</div></section>" +

      '<section class="section" aria-labelledby="layers-h"><div class="section-head"><h2 id="layers-h">Build your own harness: the four layers</h2></div>' +
      '<p class="lede">A harness is everything around the model that makes it work your way. Claude Code gives you four places to put that, and each one is good at a different job.</p>' +
      '<div class="layers">' +
      layer("CLAUDE.md", "", "A file loaded into every session in the project. Project facts and standing rules: how to run the tests, what done means, what never to touch.", "Use it for what must always be true. Keep it short, because every line costs context in every session.") +
      layer("Skills", "t-skill", "A folder with a SKILL.md. Claude reads only the name and description until a task matches, then loads the full procedure.", "Use it for a repeatable procedure: writing a PRD, running a done gate, adding auth.") +
      layer("Agents", "t-agent", "A subagent with its own fresh context, its own instructions and a limited tool list. It returns a result, not its whole transcript.", "Use it when you want independent judgment, such as a critic who did not write the PRD, or to keep noisy work out of your main session.") +
      layer("Hooks", "t-hook", "A script Claude Code runs on an event, like before a tool call or when the agent tries to stop. It can block the action.", "Use it when advice is not enough. A hook is the only layer that enforces a rule every time.") +
      "</div>" +
      '<p class="muted small" style="margin-top:12px">A plugin bundles skills, agents and hooks so they install, update and switch off together. Templates are files you copy into your project.</p></section>' +

      '<section class="section" aria-labelledby="more-h"><div class="section-head"><h2 id="more-h">More plugins</h2></div>' +
      '<div class="grid">' + others.map(function (p) { return pluginCard(p, false); }).join("") + "</div></section>" +
      "</div>";
    function layer(title, t, body, when) {
      return '<div class="layer"><h3><span class="dot" style="--tc:var(--' + (t || "t-plugin") + ')"></span>' + esc(title) + "</h3><p>" + esc(body) + '</p><p class="when">' + esc(when) + "</p></div>";
    }
  }

  // ----- browse
  var FILTERS = ["type", "maturity", "stage", "plugin"];
  function parseQuery(qs) {
    var st = { q: "", type: [], plugin: [], stage: [], maturity: [] };
    if (!qs) return st;
    qs.split("&").forEach(function (kv) {
      var i = kv.indexOf("=");
      var k = decodeURIComponent(i < 0 ? kv : kv.slice(0, i));
      var v = i < 0 ? "" : decodeURIComponent(kv.slice(i + 1).replace(/\+/g, " "));
      if (k === "q") st.q = v;
      else if (FILTERS.indexOf(k) >= 0 && v) st[k] = v.split(",");
    });
    return st;
  }
  function buildQuery(st) {
    var parts = [];
    if (st.q) parts.push("q=" + enc(st.q));
    FILTERS.forEach(function (k) { if (st[k].length) parts.push(k + "=" + st[k].map(enc).join(",")); });
    return parts.join("&");
  }
  function itemStages(it) {
    var s = (it.stages || []).map(String);
    if (it.all_stages) s.push("all");
    return s;
  }
  function matches(it, st, skip) {
    if (st.q) {
      var hay = (it.name + " " + it.description + " " + it.plugin + " " + it.type + " " + (it.tags || []).join(" ")).toLowerCase();
      var terms = st.q.toLowerCase().split(/\s+/).filter(Boolean);
      for (var i = 0; i < terms.length; i++) if (hay.indexOf(terms[i]) < 0) return false;
    }
    if (skip !== "type" && st.type.length && st.type.indexOf(it.type) < 0) return false;
    if (skip !== "plugin" && st.plugin.length && st.plugin.indexOf(it.plugin) < 0) return false;
    if (skip !== "maturity" && st.maturity.length && st.maturity.indexOf(it.maturity) < 0) return false;
    if (skip !== "stage" && st.stage.length) {
      var s = itemStages(it);
      if (!st.stage.some(function (x) { return s.indexOf(x) >= 0; })) return false;
    }
    return true;
  }
  function filterOptions() {
    var types = ["skill", "agent", "hook", "template", "plugin"].filter(function (t) {
      return DATA.items.some(function (i) { return i.type === t; });
    });
    var mats = ["proven", "new", "unlabeled", "external"].filter(function (m) {
      return DATA.items.some(function (i) { return i.maturity === m; });
    });
    return {
      type: types.map(function (t) { return [t, TYPE_LABEL[t]]; }),
      plugin: DATA.plugins.map(function (p) { return [p.name, p.name]; }),
      stage: [["all", "Every stage"]].concat(DATA.stages.map(function (s) { return [String(s.id), s.id + " " + s.name]; })),
      maturity: mats.map(function (m) { return [m, MAT_LABEL[m]]; })
    };
  }
  var LEGEND = { type: "Type", plugin: "Plugin", stage: "SDLC stage", maturity: "Maturity" };

  function pageBrowse(qs) {
    setTitle("Browse");
    var st = parseQuery(qs);
    var opts = filterOptions();
    var active = FILTERS.reduce(function (n, k) { return n + st[k].length; }, 0);
    var wide = window.matchMedia("(min-width: 900px)").matches;
    app.innerHTML = '<div class="wrap"><div class="crumbs"><a href="#/">Home</a> / Browse</div>' +
      '<h1 tabindex="-1">Browse the marketplace</h1>' +
      '<p class="lede">Search by name or what it does, then narrow by type, plugin, stage or maturity.</p>' +
      '<div class="browse">' +
      '<aside aria-label="Filters"><details class="filters" id="filters"' + (wide || active ? " open" : "") + '>' +
      '<summary>Filters<span class="muted small" id="fcount">' + (active ? " (" + active + " on)" : "") + "</span></summary>" +
      '<div class="filter-body" id="filter-body"></div></details></aside>' +
      '<section aria-label="Results"><div class="search"><label class="sr-only" for="q">Search the marketplace</label>' +
      '<input id="q" type="search" autocomplete="off" placeholder="Search skills, agents, hooks, templates" value="' + esc(st.q) + '"></div>' +
      '<div class="results-head"><p id="rcount" aria-live="polite"></p><button type="button" class="link-btn" id="clear">Clear all</button></div>' +
      '<div class="grid" id="results"></div></section></div></div>';

    var body = document.getElementById("filter-body");
    function renderFilters() {
      body.innerHTML = FILTERS.map(function (k) {
        return "<fieldset><legend>" + LEGEND[k] + "</legend>" + opts[k].map(function (o) {
          var val = o[0];
          var n = DATA.items.filter(function (it) {
            if (!matches(it, st, k)) return false;
            if (k === "stage") return itemStages(it).indexOf(val) >= 0;
            return String(it[k]) === val;
          }).length;
          var id = "f-" + k + "-" + val.replace(/[^a-z0-9-]/gi, "_");
          return '<label class="check" for="' + id + '"><input type="checkbox" id="' + id + '" data-k="' + k + '" value="' + esc(val) + '"' +
            (st[k].indexOf(val) >= 0 ? " checked" : "") + "><span>" + esc(o[1]) + '</span><span class="n">' + n + "</span></label>";
        }).join("") + "</fieldset>";
      }).join("");
    }
    function renderResults() {
      var list = sortItems(DATA.items.filter(function (it) { return matches(it, st); }));
      var el = document.getElementById("results");
      el.innerHTML = list.length ? list.map(itemCard).join("") :
        '<div class="empty" style="grid-column:1/-1">Nothing matches. Try fewer filters or a shorter search.</div>';
      document.getElementById("rcount").textContent = list.length + (list.length === 1 ? " item" : " items");
      var a = FILTERS.reduce(function (n, k) { return n + st[k].length; }, 0);
      document.getElementById("fcount").textContent = a ? " (" + a + " on)" : "";
      document.getElementById("clear").hidden = !(a || st.q);
    }
    function sync() {
      var q = buildQuery(st);
      history.replaceState(null, "", "#/browse" + (q ? "?" + q : ""));
      renderFilters();
      renderResults();
    }
    renderFilters();
    renderResults();
    body.addEventListener("change", function (ev) {
      var cb = ev.target;
      if (!cb.dataset || !cb.dataset.k) return;
      var k = cb.dataset.k;
      var idx = st[k].indexOf(cb.value);
      if (cb.checked && idx < 0) st[k].push(cb.value);
      if (!cb.checked && idx >= 0) st[k].splice(idx, 1);
      var focusId = cb.id;
      sync();
      var again = document.getElementById(focusId);
      if (again) again.focus();
    });
    var timer = null;
    document.getElementById("q").addEventListener("input", function (ev) {
      clearTimeout(timer);
      var v = ev.target.value;
      timer = setTimeout(function () { st.q = v.trim(); sync(); }, 120);
    });
    document.getElementById("clear").addEventListener("click", function () {
      st = parseQuery("");
      document.getElementById("q").value = "";
      sync();
      document.getElementById("q").focus();
    });
  }

  // ----- item detail
  function tabsHtml(tabs) {
    var bar = '<div class="tabs" role="tablist" aria-label="Install options">' + tabs.map(function (t, i) {
      return '<button type="button" role="tab" class="tab" id="tab-' + t.id + '" aria-controls="panel-' + t.id + '" aria-selected="' + (i === 0) + '" tabindex="' + (i === 0 ? 0 : -1) + '">' + esc(t.label) + "</button>";
    }).join("") + "</div>";
    var panels = tabs.map(function (t, i) {
      return '<div class="tabpanel" role="tabpanel" id="panel-' + t.id + '" aria-labelledby="tab-' + t.id + '" tabindex="0"' + (i === 0 ? "" : " hidden") + ">" + t.html + "</div>";
    }).join("");
    return bar + panels;
  }
  function wireTabs(root) {
    var tabs = Array.prototype.slice.call(root.querySelectorAll('[role="tab"]'));
    function select(tab, focus) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute("aria-selected", on);
        t.tabIndex = on ? 0 : -1;
        document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
      });
      if (focus) tab.focus();
    }
    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () { select(t, false); });
      t.addEventListener("keydown", function (ev) {
        var j = null;
        if (ev.key === "ArrowRight") j = (i + 1) % tabs.length;
        else if (ev.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
        else if (ev.key === "Home") j = 0;
        else if (ev.key === "End") j = tabs.length - 1;
        if (j !== null) { ev.preventDefault(); select(tabs[j], true); }
      });
    });
  }
  function scopeToggle(name) {
    return '<fieldset class="scope"><legend class="small muted">Install for</legend>' +
      '<label><input type="radio" name="' + name + '" value="user" checked> All my projects</label>' +
      '<label><input type="radio" name="' + name + '" value="project"> This project only</label></fieldset>';
  }

  function installTabs(it) {
    var pc = pluginCmds(it.plugin);
    var pluginTab = {
      id: "plugin", label: it.type === "plugin" ? "Install" : "Whole plugin",
      html: "<p>Inside Claude Code. This installs <strong>" + esc(it.plugin) + "</strong> with all of its items, and keeps them updated together.</p>" +
        cmdBlock(pc[0], "Step 1: add the marketplace (once)") + cmdBlock(pc[1], "Step 2: install the plugin")
    };
    var tabs = [];
    if (it.type === "skill") {
      tabs.push({
        id: "single", label: "Just this skill",
        html: "<p>No plugin system needed. This copies the skill's files from GitHub" +
          ((it.files || []).length > 1 ? " (" + it.files.length + " files)" : "") + ".</p>" + scopeToggle("scope-skill") +
          '<div data-cmd="skill"></div>' +
          (it.needs_plugin ? '<div class="notice notice-info"><p>This skill runs scripts that ship with the <strong>' + esc(it.plugin) +
            "</strong> plugin (it refers to <code>${CLAUDE_PLUGIN_ROOT}</code>). A copy of the skill gives you the instructions, not the scripts. Install the whole plugin for the full thing.</p></div>" : "")
      });
      tabs.push(pluginTab);
    } else if (it.type === "agent") {
      tabs.push({
        id: "single", label: "Just this agent",
        html: "<p>No plugin system needed. A subagent is one Markdown file.</p>" + scopeToggle("scope-agent") + '<div data-cmd="agent"></div>' +
          (it.needs_plugin ? '<div class="notice notice-info"><p>This agent calls scripts from the <strong>' + esc(it.plugin) + "</strong> plugin. Install the whole plugin for the full thing.</p></div>" : "")
      });
      tabs.push(pluginTab);
    } else if (it.type === "hook") {
      pluginTab.label = "Install";
      pluginTab.html += '<div class="notice notice-info"><p><strong>Why plugin only.</strong> A hook is an entry in <code>hooks.json</code> plus the script it runs, found through <code>${CLAUDE_PLUGIN_ROOT}</code>. ' +
        "A copy of one file would leave the entry pointing at nothing, so hooks install with their plugin. Turn the whole plugin off with <code>/plugin</code>.</p></div>" +
        (it.disable ? "<p><strong>Turn just this hook off.</strong> Set its switch in the <code>env</code> block of <code>.claude/settings.json</code>, or export it before you start Claude Code:</p>" +
          cmdBlock("export " + it.disable, "Disable " + it.name) : "");
      tabs.push(pluginTab);
    } else if (it.type === "template") {
      tabs.push({
        id: "single", label: "Download",
        html: "<p>Run this in your project folder to copy the template" + ((it.files || []).length > 1 ? " (" + it.files.length + " files)" : "") + ".</p>" +
          cmdBlock(templateCmd(it), "Shell")
      });
      tabs.push(pluginTab);
    } else {
      tabs.push(pluginTab);
      if (it.source_url) {
        tabs.push({ id: "source", label: "Source", html: '<p>This plugin lives in its own repository. Read its README before you install it.</p><p><a href="' + esc(it.source_url) + '" rel="noopener">' + esc(it.external_repo || it.source_url) + "</a></p>" });
      }
    }
    var needsScope = it.type === "skill" || it.type === "agent";
    tabs.push({
      id: "agent", label: "Ask your agent",
      html: "<p>Paste this into Claude Code and let it do the install.</p>" + (needsScope ? scopeToggle("scope-prompt") : "") +
        '<div data-cmd="prompt">' + (needsScope ? "" : cmdBlock(agentPrompt(it, "user"), "Prompt")) + "</div>"
    });
    return tabs;
  }
  function wireScopes(it) {
    function paint(kind, scope) {
      var holder = app.querySelector('[data-cmd="' + kind + '"]');
      if (!holder) return;
      if (kind === "skill") holder.innerHTML = cmdBlock(skillCmd(it, scope), "Shell");
      else if (kind === "agent") holder.innerHTML = cmdBlock(agentCmd(it, scope), "Shell");
      else if (kind === "prompt") holder.innerHTML = cmdBlock(agentPrompt(it, scope), "Prompt");
    }
    paint("skill", "user"); paint("agent", "user");
    if (it.type === "skill" || it.type === "agent") paint("prompt", "user");
    var root = app.querySelector(".detail");
    root.addEventListener("change", function (ev) {
      var r = ev.target;
      if (r.type !== "radio") return;
      if (r.name === "scope-skill") paint("skill", r.value);
      if (r.name === "scope-agent") paint("agent", r.value);
      if (r.name === "scope-prompt") paint("prompt", r.value);
    });
  }

  function pageItem(plugin, slug) {
    var it = byId[plugin + "/" + slug];
    if (!it) return pageNotFound("That item is not in the catalog. It may have been renamed.");
    setTitle(it.name);
    var p = pluginByName[it.plugin] || {};
    var facts = [];
    facts.push(["Plugin", '<a href="' + pluginHref(it.plugin) + '">' + esc(it.plugin) + "</a>"]);
    facts.push(["Type", esc(TYPE_LABEL[it.type])]);
    if (stageText(it)) {
      var stLinks = (it.stages || []).map(function (s) { return '<a href="#/browse?stage=' + s + '">' + s + " " + esc(stageName(s)) + "</a>"; });
      if (it.all_stages) stLinks.unshift('<a href="#/browse?stage=all">Every stage</a>');
      facts.push(["SDLC stage", stLinks.join(", ") || esc(stageText(it))]);
    }
    facts.push(["Maturity", esc(MAT_LABEL[it.maturity]) + (it.maturity_note && it.maturity_note.toLowerCase() !== it.maturity ? ' <span class="muted">(' + inlineCode(it.maturity_note.replace(/\*\*/g, "")) + ")</span>" : "")]);
    if (it.tools && it.tools.length) facts.push(["Tools", it.tools.map(function (t) { return "<code>" + esc(t) + "</code>"; }).join(" ")]);
    if (it.model) facts.push(["Model", "<code>" + esc(it.model) + "</code>"]);
    if (it.triggers && it.triggers.length) {
      facts.push(["Runs on", it.triggers.map(function (t) { return "<code>" + esc(t.event) + "</code>" + (t.matcher ? " for <code>" + esc(t.matcher) + "</code>" : ""); }).join("<br>")]);
    }
    if (it.disable) facts.push(["Turn off", "<code>" + esc(it.disable) + "</code>"]);
    if (p.owner || DATA.marketplace.owner) facts.push(["Owner", esc((DATA.marketplace.owner || {}).name || "")]);
    if (p.license) facts.push(["License", esc(p.license)]);

    var related = sortItems(DATA.items.filter(function (o) {
      if (o.id === it.id) return false;
      return (it.stages || []).some(function (s) { return (o.stages || []).indexOf(s) >= 0; });
    })).slice(0, 6);

    var notice = it.maturity === "new" ? '<div class="notice notice-new"><p><strong>New.</strong> Written for this marketplace, not yet battle-tested. Try it on something low stakes first, and please report what breaks.</p></div>' :
      it.maturity === "unlabeled" ? '<div class="notice notice-info"><p><strong>Unlabeled.</strong> The plugin README does not say whether this is proven or new yet.</p></div>' : "";

    var bodyHtml = renderMarkdown(it.body, dirOf(it.source_url), dirOf(it.raw_url || (it.files && it.files[0] && it.files[0].raw_url)));
    var files = (it.files || []);

    app.innerHTML = '<div class="wrap">' +
      '<div class="crumbs"><a href="#/browse">Browse</a> / <a href="' + pluginHref(it.plugin) + '">' + esc(it.plugin) + "</a> / " + esc(it.name) + "</div>" +
      '<div class="detail-head"><div class="badges">' + typeBadge(it.type) + matBadge(it.maturity) + "</div>" +
      '<h1 tabindex="-1">' + esc(it.name) + "</h1>" +
      '<p class="desc">' + inlineCode(it.description || "") + "</p></div>" +
      '<div class="detail"><div>' + notice +
      '<section class="panel" aria-labelledby="install-h"><h2 id="install-h">Install</h2><div id="tabs">' + tabsHtml(installTabs(it)) + "</div></section>" +
      (bodyHtml ? '<section class="panel" aria-labelledby="how-h"><h2 id="how-h">How to use</h2><p class="muted small">The full ' +
        (it.type === "skill" ? "SKILL.md" : it.type === "agent" ? "agent definition" : it.type === "hook" ? "README section and script header" : "file") +
        ", straight from the repository.</p><div class=\"md\">" + bodyHtml + "</div></section>" : "") +
      "</div>" +
      "<aside>" +
      '<section class="panel" aria-labelledby="facts-h"><h2 id="facts-h">Details</h2><dl class="facts">' +
      facts.map(function (f) { return "<dt>" + f[0] + "</dt><dd>" + f[1] + "</dd>"; }).join("") + "</dl></section>" +
      '<section class="panel" aria-labelledby="src-h"><h2 id="src-h">Source</h2>' +
      (it.source_url ? '<p><a href="' + esc(it.source_url) + '" rel="noopener">View on GitHub</a>' + (it.raw_url ? ' <span aria-hidden="true">·</span> <a href="' + esc(it.raw_url) + '" rel="noopener">Raw file</a>' : "") + "</p>" : "") +
      (files.length ? '<ul class="file-list">' + files.map(function (f) { return '<li><a href="' + esc(f.raw_url) + '" rel="noopener">' + esc(f.path) + "</a></li>"; }).join("") + "</ul>" : "") +
      "</section>" +
      (related.length ? '<section class="panel" aria-labelledby="rel-h"><h2 id="rel-h">Also in ' + esc(it.stages.length === 1 ? "stage " + it.stages[0] : "these stages") + '</h2><div class="related">' + related.map(itemCard).join("") + "</div></section>" : "") +
      "</aside></div></div>";
    wireTabs(document.getElementById("tabs"));
    wireScopes(it);
  }

  // ----- plugin page
  function pagePlugin(name) {
    var p = pluginByName[name];
    if (!p) return pageNotFound("That plugin is not in the catalog.");
    setTitle(p.name);
    var items = sortItems(DATA.items.filter(function (i) { return i.plugin === name && i.type !== "plugin"; }));
    var ext = DATA.items.filter(function (i) { return i.plugin === name && i.type === "plugin"; })[0];
    var pc = pluginCmds(name);
    var readmeHtml = renderMarkdown(p.readme, p.readme_url ? dirOf(p.readme_url) : "", p.readme_url ? dirOf(p.readme_url.replace("/blob/", "/raw/")) : "");
    app.innerHTML = '<div class="wrap"><div class="crumbs"><a href="#/browse">Browse</a> / ' + esc(p.name) + "</div>" +
      '<div class="detail-head"><div class="badges">' + typeBadge("plugin") + (p.starter ? '<span class="badge badge-starter">Starter</span>' : "") +
      (p.external ? matBadge("external") : (p.maturity ? matBadge(p.maturity) : "")) + "</div>" +
      '<h1 tabindex="-1">' + esc(p.name) + "</h1><p class=\"desc\">" + inlineCode(p.description) + "</p></div>" +
      '<div class="detail"><div>' +
      '<section class="panel" aria-labelledby="pi-h"><h2 id="pi-h">Install</h2><p>Inside Claude Code:</p>' + cmdBlock(pc[0], "Step 1: add the marketplace (once)") + cmdBlock(pc[1], "Step 2: install the plugin") +
      (p.external ? '<p>Maintained at <a href="' + esc(p.url) + '" rel="noopener">' + esc(p.source_repo || p.url) + "</a>.</p>" : "") + "</section>" +
      (items.length ? '<section class="section" aria-labelledby="pitems-h" style="margin-top:0"><div class="section-head"><h2 id="pitems-h">What is inside</h2><span class="muted">' + esc(countsText(p)) + '</span></div><div class="grid">' + items.map(itemCard).join("") + "</div></section>" : "") +
      (readmeHtml ? '<section class="panel" style="margin-top:24px" aria-labelledby="readme-h"><h2 id="readme-h">README</h2><div class="md">' + readmeHtml + "</div></section>" : "") +
      "</div><aside>" +
      '<section class="panel"><h2>Details</h2><dl class="facts">' +
      (p.version ? "<dt>Version</dt><dd>" + esc(p.version) + "</dd>" : "") +
      (p.category ? "<dt>Category</dt><dd>" + esc(p.category) + "</dd>" : "") +
      (p.license ? "<dt>License</dt><dd>" + esc(p.license) + "</dd>" : "") +
      ((p.tags || []).length ? "<dt>Tags</dt><dd>" + p.tags.map(esc).join(", ") + "</dd>" : "") +
      "</dl>" + (p.url ? '<p style="margin-top:12px"><a href="' + esc(p.url) + '" rel="noopener">View on GitHub</a></p>' : "") + "</section>" +
      (ext ? "" : '<section class="panel"><h2>Ask your agent</h2>' + cmdBlock(agentPrompt({ plugin: name, type: "plugin", name: name, id: name }, "user"), "Prompt") + "</section>") +
      "</aside></div></div>";
  }

  // ----- SDLC
  function chip(it) {
    return '<li><a class="chip t-' + esc(it.type) + '" href="' + itemHref(it) + '" title="' + esc(TYPE_LABEL[it.type] + ", " + MAT_LABEL[it.maturity]) + '">' + esc(it.name) +
      (it.maturity === "new" ? '<span class="chip-new">new</span>' : "") + "</a></li>";
  }
  function pageSdlc() {
    setTitle("SDLC");
    var always = sortItems(DATA.items.filter(function (i) { return i.all_stages; }));
    app.innerHTML = '<div class="wrap"><div class="crumbs"><a href="#/">Home</a> / SDLC</div>' +
      '<h1 tabindex="-1">The Foundry SDLC</h1>' +
      '<p class="lede">How we take software from an idea to something people use, with agents doing most of the building. Each stage produces one file and ends at a gate. Never skip a gate.</p>' +
      '<p><a href="' + esc(DATA.marketplace.sdlc_url) + '" rel="noopener">Read the full SDLC.md</a> <span aria-hidden="true">·</span> <a href="' + itemHrefSafe("foundry-sdlc", "sdlc") + '">The sdlc router skill</a></p>' +
      '<div class="legend" aria-label="Legend"><span><i style="background:var(--t-skill)"></i>Skill</span><span><i style="background:var(--t-agent)"></i>Agent</span><span><i style="background:var(--t-hook)"></i>Hook</span><span><i style="background:var(--t-template)"></i>Template</span><span><span class="chip-new" style="color:var(--new-text);font-weight:700;font-size:.72rem;text-transform:uppercase">new</span> not yet battle-tested</span></div>' +
      (always.length ? '<section class="panel" style="margin-top:22px" aria-labelledby="always-h"><h2 id="always-h">Runs at every stage</h2><p class="muted small">The router and the guardrail hooks. Once installed, the hooks check every tool call and every stop.</p><ul class="chips">' + always.map(chip).join("") + "</ul></section>" : "") +
      '<ol class="stages">' + DATA.stages.map(function (s) {
        var its = sortItems(DATA.items.filter(function (i) { return (i.stages || []).indexOf(s.id) >= 0; }));
        return '<li class="stage" id="stage-' + s.id + '"><div class="stage-num" aria-hidden="true">' + s.id + "</div><div>" +
          "<h2>Stage " + s.id + ": " + esc(s.name) + "</h2>" +
          (s.goal ? '<p class="goal">' + inlineCode(cap(s.goal)) + "</p>" : "") +
          (s.gate ? '<p class="gate"><strong>Gate:</strong> ' + inlineCode(s.gate) + "</p>" : "") +
          (its.length ? '<ul class="chips">' + its.map(chip).join("") + "</ul>" : '<p class="muted small">Nothing in the catalog for this stage yet.</p>') +
          (its.length ? '<p class="small" style="margin:10px 0 0"><a href="#/browse?stage=' + s.id + '">Browse stage ' + s.id + " (" + its.length + ")</a></p>" : "") +
          "</div></li>";
      }).join("") + "</ol></div>";
  }
  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
  function itemHrefSafe(p, slug) { return byId[p + "/" + slug] ? "#/item/" + enc(p) + "/" + enc(slug) : "#/browse"; }

  // ----- contribute
  function pageContribute() {
    setTitle("Contribute");
    var mp = DATA.marketplace;
    app.innerHTML = '<div class="wrap prose"><div class="crumbs"><a href="#/">Home</a> / Contribute</div>' +
      '<h1 tabindex="-1">Contribute</h1>' +
      '<p class="lede">Built something that helped you ship with agents? Add it so the next cohort starts where you finished. A skill, an agent, a hook, a template, or a fix to one of ours all count.</p>' +
      '<p><a class="btn btn-plain" href="' + esc(mp.contributing_url) + '" rel="noopener">Read CONTRIBUTING.md</a></p>' +
      '<h2 style="margin-top:28px">How it works</h2>' +
      '<ol class="steps">' +
      "<li>Fork <a href=\"" + esc(mp.repo_url) + "\" rel=\"noopener\">" + esc(mp.repo) + "</a> and add your plugin under <code>plugins/&lt;your-plugin&gt;/</code>, or add an item to an existing plugin.</li>" +
      "<li>Give every skill and agent frontmatter with a <code>name</code> and a <code>description</code> that says when to use it. That description is what Claude reads to decide, and it is what this site shows on the card.</li>" +
      "<li>In your plugin README, add a table with a <code>Maturity</code> column (and an <code>SDLC stage</code> column if you like). Say <code>proven</code> only if it runs in a real harness today; otherwise say <code>new</code>.</li>" +
      "<li>List the plugin in <code>.claude-plugin/marketplace.json</code>, then run <code>python3 scripts/build_catalog.py</code> and open <code>site/index.html</code> through a local server to see your cards.</li>" +
      "<li>Open a pull request. When it merges, this site rebuilds itself from the files.</li>" +
      "</ol>" +
      '<h2 style="margin-top:28px">How this site reads your files</h2>' +
      "<p>The site has no database. A small script reads the repository and writes <a href=\"catalog.json\">catalog.json</a>, and these pages render that file. It reads:</p>" +
      "<ul><li><strong>Skills</strong> from <code>skills/*/SKILL.md</code>, with every sibling file listed for the single-skill install.</li>" +
      "<li><strong>Agents</strong> from <code>agents/*.md</code>, including the <code>tools</code> line.</li>" +
      "<li><strong>Hooks</strong> from <code>hooks/hooks.json</code> and the header comment of each script. A <code>FOO=0</code> switch in your README or script header shows up as the way to turn it off.</li>" +
      "<li><strong>Templates</strong> from <code>templates/</code>, one card per file or folder.</li>" +
      "<li><strong>Stage</strong> from a <code>stage:</code> frontmatter line, then SDLC.md, then your README's stage column.</li>" +
      "<li><strong>Maturity</strong> from a <code>Maturity:</code> line in the body, then your README table. If neither exists, the card says Unlabeled.</li></ul>" +
      "<p>Found a problem with an item? <a href=\"" + esc(mp.repo_url) + "/issues/new\" rel=\"noopener\">Open an issue</a> and name the item.</p>" +
      "</div>";
  }

  function pageNotFound(msg) {
    setTitle("Not found");
    app.innerHTML = '<div class="wrap"><div class="error-box"><h1 tabindex="-1">Not found</h1><p>' + esc(msg || "There is no page at this address.") + '</p><p><a href="#/browse">Browse everything</a></p></div></div>';
  }

  // ------------------------------------------------------------ router
  function route() {
    var h = location.hash.replace(/^#/, "");
    if (h === "app") return; // skip link target
    var path = h, qs = "";
    var qi = h.indexOf("?");
    if (qi >= 0) { path = h.slice(0, qi); qs = h.slice(qi + 1); }
    var parts = path.split("/").filter(Boolean).map(function (x) {
      try { return decodeURIComponent(x); } catch (e) { return x; }
    });
    var section = parts[0] || "";
    document.querySelectorAll("[data-nav]").forEach(function (a) {
      if (a.getAttribute("data-nav") === section || (section === "item" && a.getAttribute("data-nav") === "browse") || (section === "plugin" && a.getAttribute("data-nav") === "browse")) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    if (!section) pageHome();
    else if (section === "browse") pageBrowse(qs);
    else if (section === "item" && parts.length >= 3) pageItem(parts[1], parts.slice(2).join("/"));
    else if (section === "plugin" && parts[1]) pagePlugin(parts[1]);
    else if (section === "sdlc") pageSdlc();
    else if (section === "contribute") pageContribute();
    else pageNotFound();
    window.scrollTo(0, 0);
    var h1 = app.querySelector("h1");
    if (route.started && h1) h1.focus({ preventScroll: true });
    route.started = true;
  }

  document.querySelector(".skip").addEventListener("click", function (ev) {
    ev.preventDefault();
    var h1 = app.querySelector("h1");
    (h1 || app).focus();
  });

  function boot() {
    fetch("catalog.json", { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (data) {
      DATA = data;
      data.items.forEach(function (i) { byId[i.plugin + "/" + i.slug] = i; });
      data.plugins.forEach(function (p) { pluginByName[p.name] = p; });
      window.addEventListener("hashchange", route);
      route();
    }).catch(function (e) {
      app.innerHTML = '<div class="wrap"><div class="error-box" role="alert"><h1>Could not load the catalog</h1><p>' + esc(e.message) +
        '. If you opened this file straight from disk, serve the folder instead: <code>python3 -m http.server</code> inside <code>site/</code>.</p></div></div>';
    });
  }
  boot();
})();
