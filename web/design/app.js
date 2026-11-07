/* Buildless local design browser. Membership edges never imply signal flow. */
(() => {
  "use strict";
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const el = (tag, attrs = {}, text) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v;
      else n.setAttribute(k, v);
    }
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const PHASE = {planning:"问题与规划", model:"模型规划", circuit:"参数 / 电路", validation:"仿真验证", conclusion:"迭代结论"};
  const DOMAIN = {serdes:["#5e83ce", "#edf3ff", "S"], tx:["#c18a64", "#fbf1e9", "TX"], bias:["#62a18b", "#eef8f3", "B"], rx:["#5e92b0", "#edf6fa", "RX"], pll:["#9b80bf", "#f4effa", "P"], channel:["#8c9dab", "#f1f5f8", "C"]};
  let catalog = window.DESIGN_CATALOG;
  let nodes = new Map();
  let selected = "serdes", focus = "serdes", tab = "overview";
  let expanded = new Set(["serdes"]);
  let transform = {x:0, y:0, scale:1}, worldSize = {w:856, h:580};
  let drag = null, moved = false, graphDrawn = false;
  let layoutMobile = window.innerWidth <= 760;
  let toastTimer;
  const fileMode = location.protocol === "file:";
  let workspaceMode = false;

  const children = id => catalog.nodes.filter(n => n.parent === id);
  const domain = id => DOMAIN[id.split(".")[0]] || DOMAIN.serdes;
  function rebuild() { nodes = new Map(catalog.nodes.map(n => [n.id, n])); }
  function parents(id) {
    const list = [];
    let n = nodes.get(id);
    while (n) { list.unshift(n); n = nodes.get(n.parent); }
    return list;
  }
  function toast(text) {
    clearTimeout(toastTimer);
    $("#toast").textContent = text;
    $("#toast").hidden = false;
    toastTimer = setTimeout(() => { $("#toast").hidden = true; }, 3400);
  }
  function setTab(next) {
    tab = next;
    $$("[data-tab]").forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    renderInspector();
  }
  function select(id, navigate = false) {
    if (!nodes.has(id)) return;
    selected = id;
    parents(id).forEach(n => expanded.add(n.id));
    if (navigate) {
      focus = children(id).length ? id : (nodes.get(id).parent || id);
      renderGraph(true);
    } else {
      $$(".graph-node").forEach(n => n.classList.toggle("selected", n.dataset.id === id));
    }
    history.replaceState(null, "", "#" + encodeURIComponent(id));
    renderTree();
    renderBreadcrumbs();
    renderInspector();
  }
  function drill(id) {
    if (!children(id).length) {
      select(id);
      return;
    }
    focus = id;
    select(id);
    renderGraph(true);
  }
  function renderTree() {
    const root = $("#module-tree"); root.replaceChildren();
    function row(node, depth) {
      const kids = children(node.id), d = domain(node.id);
      const b = el("button", {class:`tree-row depth-${depth}${depth === 0 ? " root" : ""}${selected === node.id ? " selected" : ""}`, "data-id":node.id, title:node.name, style:`padding-left:${9 + depth * 10}px;--domain-color:${d[0]}`, "aria-current": selected === node.id ? "true" : "false"});
      const toggle = el("span", {class:"tree-toggle", "aria-hidden":"true"}, kids.length ? (expanded.has(node.id) ? "⌄" : "›") : "");
      b.append(toggle, el("span", {class:"tree-dot"}), el("span", {class:"tree-name"}, node.name));
      if (node.key) b.append(el("span", {class:"tree-key"}, node.key));
      else if (kids.length) b.append(el("span", {class:"tree-count"}, String(kids.length)));
      b.addEventListener("click", e => {
        if (e.target === toggle && kids.length) {
          expanded.has(node.id) ? expanded.delete(node.id) : expanded.add(node.id);
          renderTree(); return;
        }
        select(node.id, true);
      });
      root.append(b);
      if (expanded.has(node.id)) kids.forEach(k => row(k, depth + 1));
    }
    row(nodes.get("serdes"), 0);
    $("#module-count").textContent = String(catalog.nodes.length);
  }
  function renderBreadcrumbs() {
    const bar = $("#breadcrumbs"); bar.replaceChildren();
    parents(selected).forEach((n, i) => {
      if (i) bar.append(el("span", {}, "/"));
      const b = el("button", {}, n.name);
      b.addEventListener("click", () => select(n.id, true));
      bar.append(b);
    });
  }
  function renderGraph(fit = false) {
    const parent = nodes.get(focus), kids = children(focus);
    const mobile = window.innerWidth <= 760;
    layoutMobile = mobile;
    $("#graph-title").textContent = parent.name;
    $("#graph-subtitle").textContent = parent.subtitle + (kids.length ? ` · ${kids.length} 个直属模块` : "");
    $("#graph-up").disabled = parent.parent === null;
    const cardWidth = mobile ? 160 : 216, gap = mobile ? 18 : 32, margin = mobile ? 18 : 72;
    const startY = mobile ? 215 : 239, rowStep = mobile ? 174 : 176;
    const cols = Math.min(mobile ? 2 : 3, Math.max(1, kids.length));
    worldSize = {w: margin * 2 + cols * cardWidth + (cols - 1) * gap, h: kids.length ? startY + Math.ceil(kids.length / cols) * rowStep : 250};
    $(".graph-panel").style.height = mobile ? worldSize.h + 260 + "px" : "";
    const positions = [{n:parent, x:(worldSize.w - cardWidth) / 2, y:39, parent:true}];
    kids.forEach((n, i) => positions.push({n, x:margin + (i % cols) * (cardWidth + gap), y:startY + Math.floor(i / cols) * rowStep}));
    const world = $("#graph-world"); world.style.width = worldSize.w + "px"; world.style.height = worldSize.h + "px";
    const svg = $("#graph-lines"); svg.replaceChildren(); svg.setAttribute("width", worldSize.w); svg.setAttribute("height", worldSize.h);
    function path(d) {
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", d); p.setAttribute("class", "graph-line"); svg.append(p);
    }
    if (kids.length) {
      const center = worldSize.w / 2;
      const trunk = mobile ? 7 : 38, junction = mobile ? 189 : 191;
      path(`M ${center} ${mobile ? 173 : 163} V ${junction} H ${trunk} V ${startY + Math.floor((kids.length - 1) / cols) * rowStep - 26}`);
      positions.slice(1).forEach(p => path(`M ${trunk} ${p.y - 26} H ${p.x + cardWidth / 2} V ${p.y}`));
    }
    const container = $("#graph-nodes"); container.replaceChildren();
    positions.forEach(({n, x, y, parent: isParent}) => {
      const d = domain(n.id), kids = children(n.id);
      const card = el("div", {class:`graph-node${isParent ? " root-card" : ""}${n.id === selected ? " selected" : ""}`, style:`left:${x}px;top:${y}px;width:${cardWidth}px;${mobile ? `height:${isParent ? 134 : 144}px;` : ""}--domain-color:${d[0]};--domain-light:${d[1]}`, role:"button", tabindex:"0", "data-id":n.id, "aria-label": `${n.name}，${n.state}${kids.length ? `，${kids.length}个子模块` : ""}`});
      const top = el("div", {class:"node-top"});
      top.append(el("span", {class:"node-label"}, n.key || (n.id === "serdes" ? "PROJECT" : n.id.toUpperCase())), el("span", {class:"node-mark"}, d[2]));
      const bottom = el("div", {class:"node-bottom"});
      bottom.append(el("span", {class:"node-state"}, n.state));
      if (kids.length && !isParent) {
        const b = el("button", {class:"node-enter", "aria-label":`展开${n.name}的子模块`}, `${kids.length} 模块 ↗`);
        b.addEventListener("click", e => {e.stopPropagation(); drill(n.id);});
        bottom.append(b);
      } else if (kids.length) bottom.append(el("span", {class:"node-enter"}, `${kids.length} 子模块`));
      else if (n.iterations?.length) bottom.append(el("span", {class:"node-enter"}, `${n.iterations.length} 迭代`));
      card.append(top, el("div", {class:"node-name"}, n.name), el("div", {class:"node-subtitle"}, n.subtitle), bottom);
      card.addEventListener("click", () => { if (!moved) select(n.id); });
      card.addEventListener("dblclick", () => drill(n.id));
      card.addEventListener("keydown", e => {
        if (e.target !== card) return;
        if (e.key === "Enter") {e.preventDefault(); drill(n.id);}
        if (e.key === " ") {e.preventDefault(); select(n.id);}
      });
      container.append(card);
    });
    graphDrawn = true;
    if (fit) requestAnimationFrame(fitGraph);
    else applyTransform();
  }
  function fitGraph() {
    const v = $("#graph-viewport");
    transform.scale = Math.min(1, Math.max(.55, Math.min((v.clientWidth - 42) / worldSize.w, (v.clientHeight - 43) / worldSize.h)));
    transform.x = (v.clientWidth - worldSize.w * transform.scale) / 2;
    transform.y = Math.max(15, (v.clientHeight - worldSize.h * transform.scale) / 2 - 8);
    applyTransform();
  }
  function applyTransform() {
    $("#graph-world").style.transform = `translate(${transform.x}px,${transform.y}px) scale(${transform.scale})`;
    $("#zoom-level").textContent = Math.round(transform.scale * 100) + "%";
  }
  function zoom(factor, x, y) {
    const v = $("#graph-viewport");
    x ??= v.clientWidth / 2; y ??= v.clientHeight / 2;
    const old = transform.scale, next = Math.max(.35, Math.min(1.8, old * factor));
    transform.x = x - (x - transform.x) * next / old;
    transform.y = y - (y - transform.y) * next / old;
    transform.scale = next; applyTransform();
  }

  function label(text) { return el("h3", {class:"section-label"}, text); }
  function empty(title, copy) {
    const n = el("div", {class:"empty-state"}); n.append(el("strong", {}, title), el("p", {}, copy)); return n;
  }
  function reference(ref) {
    const b = el("button", {class:"reference-card"});
    const suffix = ref.path.split("#")[0].split(".").pop().toUpperCase();
    const info = el("span", {class:"reference-info"}); info.append(el("strong", {}, ref.title), el("small", {}, ref.path));
    b.append(el("span", {class:"reference-icon"}, suffix.slice(0, 4)), info, el("span", {}, "↗"));
    b.addEventListener("click", () => openArtifact(ref.path, ref.title));
    return b;
  }
  function renderInspector() {
    const n = nodes.get(selected), d = domain(n.id), h = $("#inspector-heading"), body = $("#inspector-body");
    h.replaceChildren();
    const id = el("div", {class:"module-id", style:`--domain-color:${d[0]}`}); id.append(el("i"), document.createTextNode(n.key ? `${n.id.toUpperCase()} / ${n.key}` : n.id.toUpperCase()));
    h.append(id, el("h2", {}, n.name), el("span", {class:"state-chip"}, n.state));
    $("#iteration-count").textContent = n.iterations?.length || "0";
    $("#focus-selected").disabled = !children(selected).length || selected === focus;
    body.replaceChildren();
    if (tab === "overview") {
      body.append(el("p", {class:"body-summary"}, n.summary), label("模块现状"));
      const grid = el("div", {class:"fact-grid"});
      Object.entries(n.facts || {}).forEach(([k, v]) => { const f = el("div", {class:"fact"}); f.append(el("span", {}, k), el("p", {}, v)); grid.append(f); });
      body.append(grid);
      if (n.id === "pll") body.append(el("p", {class:"integration-note"}, "PLL 顶层集成已有。近期 VCO、分频和环路参数的改进，分别保留模型规划与局部验证记录。"));
      const kids = children(n.id);
      if (kids.length) {
        body.append(label("下一级模块"));
        const list = el("div", {class:"child-list"});
        kids.forEach(c => {
          const b = el("button", {class:"child-link"}); b.append(el("span", {}, c.name), el("small", {}, `${c.key || c.state}  ›`)); b.addEventListener("click", () => select(c.id, true)); list.append(b);
        }); body.append(list);
      }
      if (n.references?.length) { body.append(label("设计入口"), reference(n.references[0])); }
    } else if (tab === "boundary") {
      [["输入边界", "inputs"], ["输出边界", "outputs"], ["适用范围与假设", "assumptions"]].forEach(([title, key]) => {
        body.append(label(title)); const ul = el("ul", {class:`boundary-list${key === "assumptions" ? " assumptions" : ""}`});
        (n.boundary?.[key] || []).forEach(s => ul.append(el("li", {}, s))); body.append(ul);
      });
      body.append(el("p", {class:"subtle-copy"}, "边界描述激励、负载、接口与测量范围。更换边界时，在迭代记录里注明依据与结果。"));
    } else if (tab === "model") {
      const plan = n.planning;
      if (!plan) { body.append(empty("规划挂在所属模块", "可在这一级添加模型推导或参数选择记录，也可以查看父级的设计规划。")); }
      else {
        const flow = el("div", {class:"model-path"}); ["约束", "粗模型", "参数求解", "仿真校准"].forEach(s => flow.append(el("span", {}, s))); body.append(flow);
        [["设计问题", "question"], ["行为 / 理论模型", "model"], ["设计参数与修改依据", "parameters"], ["验证方法", "verification"]].forEach(([title, key]) => {
          const item = el("section", {class:"model-item"}); item.append(el("h4", {}, title), el("p", {}, plan[key] || "")); body.append(item);
        });
      }
      const refs = (n.references || []).filter(r => /模型|规划|方法|工作区/.test(r.title) || /theory|sizing|workmap/.test(r.path));
      if (refs.length) { body.append(label("模型与推导入口")); refs.forEach(r => body.append(reference(r))); }
    } else if (tab === "iterations") {
      body.append(el("p", {class:"subtle-copy"}, "每次改进都归属模块：保留问题、模型规划、参数变化、验证边界和结论。"), label("模块迭代记录"));
      const records = [...(n.iterations || [])].sort((a, b) => (b.timestamp || b.date || "").localeCompare(a.timestamp || a.date || ""));
      if (!records.length) body.append(empty("这里承载下一次改进", "用下方「添加迭代」，把规划、仿真或结论挂到这个模块。既有设计依据仍可从证据页查看。"));
      records.forEach(r => {
        const card = el("article", {class:"iteration-card"});
        const meta = el("div", {class:"iteration-meta"}); meta.append(el("span", {class:"phase-chip"}, PHASE[r.phase] || "记录"), el("span", {}, r.date || ""));
        card.append(meta, el("h3", {}, r.title));
        [["问题", "problem"], ["模型与规划", "model"], ["参数 / 电路变化", "changes"], ["验证与边界", "validation"], ["结论", "conclusion"]].forEach(([title, key]) => {
          if (!r[key]) return; const f = el("div", {class:"iteration-field"}); f.append(el("span", {}, title), el("p", {}, r[key])); card.append(f);
        });
        const refs = el("div", {class:"iteration-attachments"});
        (r.attachments || []).forEach(a => {const b = el("button", {}, a.title + " ↗"); b.addEventListener("click", () => openArtifact(a.path, a.title)); refs.append(b);});
        if (refs.childNodes.length) card.append(refs);
        body.append(card);
      });
    } else if (tab === "evidence") {
      const refs = new Map();
      (n.references || []).forEach(r => refs.set(r.path, r));
      (n.iterations || []).forEach(r => (r.attachments || []).forEach(a => refs.set(a.path, a)));
      body.append(label("设计资料与验证依据"));
      refs.forEach(r => body.append(reference(r)));
      body.append(el("p", {class:"subtle-copy"}, "来源保留在仓库文档、模型脚本、工作电路与图中；数值判据以对应记录的边界为准。"));
    }
  }

  function search(query) {
    const box = $("#search-results"); box.replaceChildren();
    query = query.trim().toLowerCase();
    if (!query) {box.hidden = true; return;}
    const hits = [];
    catalog.nodes.forEach(n => {
      const base = [n.id, n.key, n.name, n.subtitle, n.summary, ...Object.values(n.facts || {})].join(" ").toLowerCase();
      const iteration = (n.iterations || []).find(i => [i.title, i.problem, i.model, i.changes].join(" ").toLowerCase().includes(query));
      if (base.includes(query) || iteration) hits.push({n, iteration: !base.includes(query) ? iteration : null, score:n.name.toLowerCase().includes(query) ? 0 : 1});
    });
    hits.sort((a, b) => a.score - b.score).slice(0, 16).forEach(({n, iteration}) => {
      const b = el("button", {class:"search-result"}); b.append(el("strong", {}, iteration ? iteration.title : n.name), el("small", {}, parents(n.id).map(x => x.name).join(" / ")));
      b.addEventListener("click", () => {select(n.id, true); if (iteration) setTab("iterations"); box.hidden = true; $("#search").value = "";}); box.append(b);
    });
    if (!hits.length) box.append(el("div", {class:"search-empty"}, "没有匹配的模块或迭代"));
    box.hidden = false;
  }

  function repoPath(target, base = "README.md") {
    const resolved = new URL(target, "https://repository.invalid/" + base);
    if (resolved.origin !== "https://repository.invalid") return null;
    return decodeURIComponent(resolved.pathname).replace(/^\//, "") + resolved.hash;
  }
  function repoURL(path) {
    if (fileMode) return new URL("../../" + path, location.href).href;
    const [file, hash] = path.split("#");
    return "/repo/" + file.split("/").map(encodeURIComponent).join("/") + (hash ? "#" + hash : "");
  }
  function inline(parent, text, base) {
    const pattern = /(!?\[([^\]]*)\]\(([^\s)]+)\)|`([^`]+)`|\*\*([^*]+)\*\*)/g;
    let last = 0;
    for (const m of text.matchAll(pattern)) {
      parent.append(document.createTextNode(text.slice(last, m.index)));
      if (m[4]) parent.append(el("code", {}, m[4]));
      else if (m[5]) parent.append(el("strong", {}, m[5]));
      else {
        const target = m[3], local = repoPath(target, base);
        if (m[1].startsWith("!")) {
          if (local) parent.append(el("img", {src:repoURL(local), alt:m[2], loading:"lazy"}));
          else parent.append(document.createTextNode(m[2]));
        } else {
          const a = el("a", {}, m[2]);
          if (local) {a.href = repoURL(local); a.addEventListener("click", e => {e.preventDefault(); openArtifact(local, m[2]);});}
          else if (/^https?:\/\//.test(target)) {a.href = target; a.target = "_blank"; a.rel = "noopener";}
          parent.append(a);
        }
      }
      last = m.index + m[0].length;
    }
    parent.append(document.createTextNode(text.slice(last)));
  }
  function renderMarkdown(text, base) {
    const fragment = document.createDocumentFragment(), lines = text.split("\n");
    let list = null;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (/^```/.test(line)) {
        const code = []; while (++i < lines.length && !/^```/.test(lines[i])) code.push(lines[i]);
        fragment.append(el("pre", {}, code.join("\n"))); list = null; continue;
      }
      const heading = line.match(/^(#{1,6})\s+(.+)/);
      if (heading) {
        const h = el("h" + heading[1].length);
        h.id = heading[2].toLowerCase().replace(/\s+/g, "-").replace(/[^\p{L}\p{N}_-]/gu, "");
        inline(h, heading[2], base); fragment.append(h); list = null; continue;
      }
      if (/^\s*\|/.test(line) && /^\s*\|?\s*:?-+/.test(lines[i + 1] || "")) {
        const table = el("table");
        function row(value, tag) {const tr = el("tr"); value.trim().replace(/^\||\|$/g, "").split("|").forEach(x => {const td = el(tag); inline(td, x.trim(), base); tr.append(td);}); table.append(tr);}
        row(line, "th"); i++;
        while (i + 1 < lines.length && /^\s*\|/.test(lines[i + 1])) row(lines[++i], "td");
        fragment.append(table); list = null; continue;
      }
      const bullet = line.match(/^\s*[-*]\s+(.*)/);
      if (bullet) {if (!list) {list = el("ul"); fragment.append(list);} const li = el("li"); inline(li, bullet[1], base); list.append(li); continue;}
      list = null;
      if (!line.trim()) continue;
      const block = el(/^>/.test(line) ? "blockquote" : "p"); inline(block, line.replace(/^>\s?/, ""), base); fragment.append(block);
    }
    return fragment;
  }
  let artifactRequest = 0;
  async function openArtifact(path, title) {
    if (fileMode) {window.open(repoURL(path), "_blank", "noopener"); return;}
    const request = ++artifactRequest;
    const dialog = $("#artifact-dialog"), content = $("#artifact-content"), [file, anchor] = path.split("#");
    $("#artifact-title").textContent = title || file.split("/").pop(); $("#artifact-path").textContent = file;
    $("#artifact-external").href = repoURL(path); content.replaceChildren(el("p", {class:"subtle-copy"}, "正在读取设计资料…"));
    if (!dialog.open) dialog.showModal();
    try {
      if (/\.(png|svg|pdf)$/i.test(file)) {
        const n = /\.pdf$/i.test(file) ? el("iframe", {src:repoURL(path), title:title || file}) : el("img", {src:repoURL(path), alt:title || file});
        content.replaceChildren(n); return;
      }
      const response = await fetch(repoURL(file)); if (!response.ok) throw new Error("无法读取资料，请检查仓库路径");
      const text = await response.text(); if (request !== artifactRequest) return;
      content.replaceChildren(/\.md$/i.test(file) ? renderMarkdown(text, file) : el("pre", {}, text));
      content.scrollTop = 0;
      if (anchor) requestAnimationFrame(() => content.querySelector("#" + CSS.escape(decodeURIComponent(anchor)))?.scrollIntoView({block:"start"}));
    } catch (err) {if (request === artifactRequest) content.replaceChildren(el("p", {class:"form-error"}, err.message));}
  }

  function newIteration() {
    $("#iteration-form").reset(); $("#form-error").textContent = "";
    $("#iteration-module-label").textContent = parents(selected).map(n => n.name).join(" / ");
    $("#save-hint").textContent = workspaceMode ? "保存为模块下的独立记录，保留已有迭代。" : "静态浏览模式：导出 JSON；本地服务支持保存到仓库。";
    $("#iteration-form button[type=submit]").textContent = workspaceMode ? "保存迭代记录" : "导出迭代 JSON";
    $("#iteration-dialog").dataset.module = selected;
    $("#iteration-dialog").showModal();
  }
  async function saveIteration(e) {
    e.preventDefault(); const form = e.target, module = $("#iteration-dialog").dataset.module, values = new FormData(form);
    const payload = {module}; ["title", "phase", "problem", "model", "changes", "validation", "conclusion"].forEach(k => payload[k] = String(values.get(k) || "").trim());
    payload.attachments = String(values.get("attachments") || "").split("\n").map(x => x.trim()).filter(Boolean).map(path => ({path, title:path.split("/").pop()}));
    const button = $("button[type=submit]", form); button.disabled = true;
    try {
      if (!workspaceMode) {
        const record = {...payload, id:"export_" + Date.now(), date:new Date().toISOString().slice(0, 10)};
        const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2) + "\n"], {type:"application/json"}));
        const a = el("a", {href:url, download:module + "_iteration.json"}); a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
        $("#iteration-dialog").close(); toast("已导出迭代 JSON；尚未写入仓库。按说明保存后即可归入模块。");
      } else {
        const response = await fetch("/api/iterations", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
        const result = await response.json(); if (!response.ok) throw new Error(result.error || "保存失败");
        nodes.get(module).iterations ||= []; nodes.get(module).iterations.push(result);
        $("#iteration-dialog").close(); select(module); setTab("iterations"); renderGraph(false);
        toast("迭代已保存到「" + nodes.get(module).name + "」");
      }
    } catch (err) {$("#form-error").textContent = err.message;}
    finally {button.disabled = false;}
  }
  function bind() {
    $$("[data-tab]").forEach(b => {
      b.addEventListener("click", () => setTab(b.dataset.tab));
      b.addEventListener("keydown", e => {
        if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
        const tabs = $$("[data-tab]"), i = tabs.indexOf(b), next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
        e.preventDefault(); next.focus(); next.click();
      });
    });
    $$("[data-close]").forEach(b => b.addEventListener("click", () => $("#" + b.dataset.close).close()));
    $("#add-iteration").addEventListener("click", newIteration);
    $("#iteration-form").addEventListener("submit", saveIteration);
    $("#open-source").addEventListener("click", () => {const ref = nodes.get(selected).references?.[0]; if (ref) openArtifact(ref.path, ref.title);});
    $("#method-link").addEventListener("click", () => openArtifact("docs/verification/sizing.md", "尺寸设计方法"));
    $("#focus-selected").addEventListener("click", () => drill(selected));
    $("#reset-view").addEventListener("click", () => {focus = "serdes"; select("serdes"); renderGraph(true);});
    $("#graph-up").addEventListener("click", () => {const p = nodes.get(focus).parent; if (p) {focus = p; select(p); renderGraph(true);}});
    $("#zoom-in").addEventListener("click", () => zoom(1.15));
    $("#zoom-out").addEventListener("click", () => zoom(1 / 1.15));
    $("#zoom-fit").addEventListener("click", fitGraph);
    $$("[data-method]").forEach(b => b.addEventListener("click", () => setTab(b.dataset.method === "boundary" ? "boundary" : ["validation", "conclusion"].includes(b.dataset.method) ? "iterations" : "model")));
    $("#search").addEventListener("input", e => search(e.target.value));
    document.addEventListener("click", e => {if (!e.target.closest(".search-wrap")) $("#search-results").hidden = true;});
    document.addEventListener("keydown", e => {
      if (e.key === "/" && !e.target.matches("input,textarea,select")) {e.preventDefault(); $("#search").focus();}
      if (e.key === "Escape") $("#search-results").hidden = true;
    });
    const viewport = $("#graph-viewport");
    viewport.addEventListener("pointerdown", e => {
      if (window.innerWidth <= 760 && e.pointerType === "touch") return;
      if (e.target.closest(".graph-node,.zoom-tools")) return;
      drag = {x:e.clientX, y:e.clientY, ox:transform.x, oy:transform.y}; moved = false;
      viewport.setPointerCapture(e.pointerId); viewport.classList.add("dragging");
    });
    viewport.addEventListener("pointermove", e => {
      if (!drag) return; moved = Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 4;
      transform.x = drag.ox + e.clientX - drag.x; transform.y = drag.oy + e.clientY - drag.y; applyTransform();
    });
    const endDrag = () => {drag = null; viewport.classList.remove("dragging"); setTimeout(() => {moved = false;}, 0);};
    viewport.addEventListener("pointerup", endDrag); viewport.addEventListener("pointercancel", endDrag);
    viewport.addEventListener("wheel", e => {
      e.preventDefault(); const r = viewport.getBoundingClientRect();
      if (e.ctrlKey || e.metaKey) zoom(Math.exp(-e.deltaY * .003), e.clientX - r.left, e.clientY - r.top);
      else {transform.x -= e.deltaX; transform.y -= e.deltaY; applyTransform();}
    }, {passive:false});
    let resize;
    new ResizeObserver(() => {clearTimeout(resize); resize = setTimeout(() => {if (graphDrawn) {
      if (layoutMobile !== (window.innerWidth <= 760)) renderGraph(true);
      else fitGraph();
    }}, 80);}).observe(viewport);
    window.addEventListener("hashchange", () => {const id = decodeURIComponent(location.hash.slice(1)); if (nodes.has(id)) select(id, true);});
  }
  async function init() {
    if (!catalog) {document.body.append(el("p", {class:"form-error"}, "缺少模块数据，请先运行 uv run python -m serdes_flow.design_viewer --export")); return;}
    if (!fileMode) {
      try {const response = await fetch("/api/catalog"); if (response.ok) {catalog = await response.json(); workspaceMode = catalog.mode === "workspace";}} catch (_) { /* standalone data remain available */ }
    }
    rebuild();
    const id = decodeURIComponent(location.hash.slice(1));
    if (nodes.has(id)) {selected = id; focus = children(id).length ? id : nodes.get(id).parent || id;}
    parents(selected).forEach(n => expanded.add(n.id));
    $("#connection").lastChild.textContent = workspaceMode ? "工作区已连接" : "静态浏览";
    bind(); renderTree(); renderBreadcrumbs(); renderGraph(true); renderInspector();
  }
  init();
})();
