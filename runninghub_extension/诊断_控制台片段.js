/* ============================================================
 * RunningHub 批量助手 · 一次性体检脚本 (diag-2026090801)
 *
 * 用途：插件失效时，一次性查清「到底是哪个假设被 RunningHub 改掉了」。
 *      合并并加强了 导出DOM_控制台片段.js + 导出节点_控制台片段.js，
 *      额外覆盖：上传接口连通性、api 事件总线、ComfyUI 前端版本。
 *
 * 用法：登录后打开工作流页，等画布完全加载出来（能看到节点），
 *      F12 → Console（执行环境保持在 top，不要切 iframe），
 *      整段粘贴回车。结果打印 + 自动复制到剪贴板，直接粘给作者。
 *
 * 副作用：会往 ComfyUI 的 input 目录上传一张 1x1 像素测试图
 *        （名字 __rh_probe.png，overwrite=true，不会污染你的素材）。
 *        不想传就把下面 PROBE_UPLOAD 改成 false。
 * ============================================================ */
(async () => {
  const PROBE_UPLOAD = true;

  const vis = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
  };
  const dis = (el) => {
    if (!el) return true;
    if (el.disabled) return true;
    if (el.getAttribute && el.getAttribute("aria-disabled") === "true") return true;
    return /ant-btn-loading|disabled/.test((el.className || "").toString());
  };

  const out = {
    build: "diag-2026090801",
    url: location.href,
    userAgent: navigator.userAgent.slice(0, 160),
    time: new Date().toISOString(),
  };

  // ---------- 假设 0：插件本体有没有注入进来 ----------
  out.extension = {
    contentScriptLoaded: !!window.__rhBatchLoaded, // MAIN world 注入成功的标志
    panelInDom: !!document.getElementById("rh-batch-panel"),
  };

  // ---------- 假设 1：同源 iframe 里的 ComfyUI app ----------
  const frames = [...document.querySelectorAll("iframe")];
  out.iframes = frames.map((f, i) => {
    const row = { index: i, src: (f.src || "").slice(0, 200), visible: vis(f) };
    try {
      const w = f.contentWindow;
      if (!w) {
        row.access = "contentWindow 为 null";
        return row;
      }
      row.access = "同源可读";
      row.href = ((w.location && w.location.href) || "").slice(0, 200);
      row.hasApp = !!w.app;
      row.hasGraph = !!(w.app && w.app.graph);
      row.nodeCount = w.app && w.app.graph && (w.app.graph._nodes || []).length;
    } catch (e) {
      // ↓ 若是这行，假设 1 已破，插件必须换实现（不能再靠读 iframe 里的 app）
      row.access = "跨域被拦: " + ((e && e.message) || e);
    }
    return row;
  });
  if (window.app && window.app.graph) {
    out.appOnTopWindow = { nodeCount: (window.app.graph._nodes || []).length };
  }

  // 按插件同样的逻辑取 app
  let app = null,
    win = null,
    from = "";
  const ordered = frames
    .slice()
    .sort((a, b) => (/comfy/i.test(b.src) ? 1 : 0) - (/comfy/i.test(a.src) ? 1 : 0));
  for (const f of ordered) {
    try {
      const w = f.contentWindow;
      if (w && w.app && w.app.graph) {
        app = w.app;
        win = w;
        from = f.src || "(无 src)";
        break;
      }
    } catch (_) {}
  }
  if (!app && window.app && window.app.graph) {
    app = window.app;
    win = window;
    from = "top window";
  }
  out.comfyFoundIn = from || null;

  // ---------- 假设 2：节点与 widget ----------
  if (app) {
    const nodes = app.graph._nodes || [];
    out.graph = {
      nodeCount: nodes.length,
      typeHistogram: nodes.reduce((m, n) => ((m[n.type] = (m[n.type] || 0) + 1), m), {}),
      loadImageNodes: nodes.filter((n) => n.type === "LoadImage").map((n) => n.id),
      vhsLoadVideoNodes: nodes.filter((n) => n.type === "VHS_LoadVideo").map((n) => n.id),
      // 插件的宽松兜底：任何带 image / video widget 的节点
      nodesWithImageWidget: nodes
        .filter((n) => (n.widgets || []).some((w) => w.name === "image"))
        .map((n) => ({ id: n.id, type: n.type })),
      nodesWithVideoWidget: nodes
        .filter((n) => (n.widgets || []).some((w) => w.name === "video"))
        .map((n) => ({ id: n.id, type: n.type })),
      outputNodes: nodes
        .filter((n) =>
          ["SaveImage", "VHS_VideoCombine", "PreviewImage", "ZML_PreviewImage"].includes(n.type)
        )
        .map((n) => ({ id: n.id, type: n.type })),
    };
    out.nodes = nodes.map((n) => ({
      id: n.id,
      type: n.type,
      title: n.title || "",
      widgets: (n.widgets || []).map((w) => ({
        name: w.name,
        type: w.type,
        value: typeof w.value === "string" ? w.value.slice(0, 80) : w.value,
      })),
    }));

    // ---------- 假设 5：api 事件总线 ----------
    out.api = {
      hasApi: !!app.api,
      hasAddEventListener: !!(app.api && app.api.addEventListener),
      hasFetchApi: !!(app.api && typeof app.api.fetchApi === "function"),
      apiBase:
        (app.api && (app.api.api_base ?? (app.api.apiURL && app.api.apiURL("")))) || null,
      frontendVersion: win.__COMFYUI_FRONTEND_VERSION__ || app.frontendVersion || null,
      hasExtensionManager: !!app.extensionManager,
    };

    // ---------- 假设 3：上传接口 ----------
    if (PROBE_UPLOAD) {
      const b64 =
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==";
      const png = Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
      const file = new win.File([png], "__rh_probe.png", { type: "image/png" });
      const fd = new win.FormData();
      fd.append("image", file, "__rh_probe.png");
      fd.append("type", "input");
      fd.append("overwrite", "true");
      const probe = { via: null, status: null, ok: null, body: null, error: null };
      try {
        let r;
        if (app.api && typeof app.api.fetchApi === "function") {
          probe.via = "app.api.fetchApi('/upload/image')";
          r = await app.api.fetchApi("/upload/image", { method: "POST", body: fd });
        } else {
          probe.via = win.location.origin + "/upload/image";
          r = await win.fetch(probe.via, { method: "POST", body: fd, credentials: "include" });
        }
        probe.status = r.status;
        probe.ok = r.ok;
        probe.finalUrl = (r.url || "").slice(0, 200);
        probe.body = (await r.text()).slice(0, 300); // 期望 {"name":"__rh_probe.png",...}
      } catch (e) {
        probe.error = (e && e.message) || String(e); // Failed to fetch / 401 / 被网关拦
      }
      out.uploadProbe = probe;
    }
  }

  // ---------- 假设 4：运行按钮 ----------
  const MODE_RE = /Lite|Standard|Plus|Pro/i;
  const cands = [...document.querySelectorAll('button, [role="button"], .ant-btn, a, div, span')]
    .filter((b) => {
      const t = (b.innerText || b.textContent || "").trim();
      return t && t.length <= 20 && /运行|开始|生成|Run|Start|Generate|Queue/i.test(t);
    })
    .map((b) => ({
      text: (b.innerText || b.textContent || "").trim().replace(/\s+/g, " ").slice(0, 30),
      tag: b.tagName.toLowerCase(),
      className: (b.className || "").toString().slice(0, 140),
      visible: vis(b),
      disabled: dis(b),
      hasModeWord: MODE_RE.test((b.innerText || "").trim()),
      target: b.getAttribute && b.getAttribute("target"),
    }));
  const seen = new Set();
  out.runButtonCandidates = cands.filter((b) => {
    const k = b.text + "|" + b.className;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  // 旧逻辑（1.0.1）会挑中哪个（null = 假设 4 已破）
  const usable = [...document.querySelectorAll('button, [role="button"], .ant-btn')].filter(
    (b) => vis(b) && !dis(b)
  );
  const picked =
    usable.find((b) => /^运行$/.test((b.innerText || "").trim())) ||
    usable.find(
      (b) => /^运行/.test((b.innerText || "").trim()) && !MODE_RE.test((b.innerText || "").trim())
    ) ||
    usable.find((b) => /run-btn/.test((b.className || "").toString()));
  const brief = (b) =>
    b
      ? {
          text: (b.innerText || "").trim().replace(/\s+/g, " ").slice(0, 30),
          className: (b.className || "").toString().slice(0, 140),
          bevel: ((b.className || "").toString().match(/beveled-btn-\w+/) || [null])[0],
        }
      : null;
  out.runButtonPluginWouldPick = brief(picked);

  // 新版三档运行按钮（2026-09 改版）：档位识别 + 1.0.2 新逻辑会挑中哪个
  const TIERS = [
    { key: "ultra", re: /ultra/i },
    { key: "plus", re: /plus/i },
    { key: "standard", re: /standard/i },
  ];
  const tierTextOf = (btn) => {
    const pick = (el) => (el ? (el.innerText || el.textContent || "").trim() : "");
    const inner = btn.querySelector(".plus-tags");
    if (inner) return pick(inner);
    const p = btn.parentElement;
    let sib = p ? p.querySelector(":scope > .plus-tags") : null;
    if (!sib && p && p.parentElement) sib = p.parentElement.querySelector(":scope > .plus-tags");
    return pick(sib);
  };
  const tierBtns = [...document.querySelectorAll(".run-btn")]
    .filter((b) => b.tagName === "BUTTON" || b.getAttribute("role") === "button")
    .map((btn) => {
      const label = tierTextOf(btn) || (btn.innerText || "").trim();
      const t = TIERS.find((x) => x.re.test(label));
      return t ? { key: t.key, label, visible: vis(btn), disabled: dis(btn), btn } : null;
    })
    .filter(Boolean);
  out.runTiers = tierBtns.map((t) => ({
    key: t.key,
    label: t.label,
    visible: t.visible,
    disabled: t.disabled,
    bevel: ((t.btn.className || "").toString().match(/beveled-btn-\w+/) || [null])[0],
  }));
  // 把 WANT 改成你在面板里选的档位，看新逻辑挑得对不对
  const WANT = "standard";
  const pool = tierBtns.filter((t) => t.visible && !t.disabled);
  const newPick = WANT ? pool.find((t) => t.key === WANT) : pool[0];
  out.runButtonNewLogicWouldPick = newPick ? { want: WANT, ...brief(newPick.btn) } : { want: WANT, picked: null };

  // ---------- 顶层 file input（万一改成走原生上传控件） ----------
  out.topFileInputs = [...document.querySelectorAll('input[type="file"]')].map((i) => ({
    accept: i.accept || "",
    name: i.name || "",
    multiple: i.multiple,
    visible: vis(i),
    parentClass: ((i.parentElement && i.parentElement.className) || "").toString().slice(0, 100),
  }));

  // ---------- 一句话结论 ----------
  const verdict = [];
  if (!out.extension.contentScriptLoaded)
    verdict.push("❌ 插件没注入（manifest matches / 扩展被停用 / MAIN world 失败）");
  if (!app) verdict.push("❌ 假设1破：读不到 ComfyUI 的 app（看 iframes[].access 是不是跨域被拦）");
  if (app && !out.graph.loadImageNodes.length && !out.graph.nodesWithImageWidget.length)
    verdict.push("❌ 假设2破：图里没有 LoadImage / image widget");
  if (out.uploadProbe && !out.uploadProbe.ok)
    verdict.push(
      "❌ 假设3破：/upload/image 不通 → " +
        (out.uploadProbe.error || out.uploadProbe.status + " " + out.uploadProbe.body)
    );
  if (!out.runButtonPluginWouldPick) verdict.push("❌ 假设4破：找不到可点的「运行」按钮");
  if (out.runTiers.length > 1) {
    const old = out.runButtonPluginWouldPick;
    const oldTier = old && out.runTiers.find((t) => t.bevel && t.bevel === old.bevel);
    if (oldTier && oldTier.key !== "standard")
      verdict.push(`⚠️ 新版三档运行按钮：旧版插件(1.0.1)会误点「${oldTier.label}」，请升级到 1.0.2 并在面板选档位`);
    if (!out.runButtonNewLogicWouldPick.text)
      verdict.push(`❌ 新逻辑也挑不到档位「${out.runButtonNewLogicWouldPick.want}」（页面上没有这一档或当前不可点）`);
  }
  if (app && !out.api.hasAddEventListener)
    verdict.push("❌ 假设5破：app.api 没有 addEventListener，等不到任务结束事件");
  if (!verdict.length) verdict.push("✅ 五个假设都还在 —— 问题在别处（把面板日志一起发来）");
  out.verdict = verdict;

  const json = JSON.stringify(out, null, 2);
  console.log(json);
  console.log("%c" + verdict.join("\n"), "font-weight:bold;font-size:13px");
  try {
    copy(json);
    console.log("%c✅ 已复制到剪贴板，直接粘给作者", "color:#22c55e;font-weight:bold");
  } catch (e) {
    console.log("自动复制失败，手动选中上面的 JSON 复制");
  }
  return out;
})();
