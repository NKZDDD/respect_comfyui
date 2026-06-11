// RunningHub 批量任务助手 — Chrome/Edge 扩展 content script（MAIN world）
// 自动适配两类工作流：
//   A) 有 VHS_LoadVideo 节点 = 视频换装：图片+视频按视频为主 1 配 1（有限批量）
//   B) 无视频节点 = 纯图片：上传图片 → 运行 → 出图，可“无限循环”（顺序/随机）
// 通用能力：选目录(可刷新续跑)、从第几个开始、运行模式、卡住 N 分钟自动刷新续跑、
//          回收成品（SaveImage 图片 / VHS_VideoCombine 视频，成功失败都下载）。
//
// 必须以 world:"MAIN" 注入（见 manifest.json），否则拿不到 iframe 里的 ComfyUI `app`。

(function () {
  "use strict";

  if (window.__rhBatchLoaded) return;
  window.__rhBatchLoaded = true;

  // ============================================================
  // 配置区（不灵就改这里）
  // ============================================================
  const CONFIG = {
    // 节点定位：默认 null＝按类型自动识别（适配多个工作流）；也可填 id 精确匹配
    imageNodeId: null, // LoadImage（换装=332 / Z-Image=55，自动识别）
    imageWidget: "image",
    videoNodeId: null, // VHS_LoadVideo（没有视频节点的工作流＝纯图片模式）
    videoWidget: "video",
    imageNodeType: "LoadImage",
    videoNodeType: "VHS_LoadVideo",

    // 输出/保存节点类型（回收成品用）：图片 SaveImage、视频 VHS_VideoCombine 等
    outputNodeTypes: ["SaveImage", "VHS_VideoCombine", "PreviewImage", "ZML_PreviewImage"],

    uploadType: "input", // ComfyUI 上传目标目录
    uploadOverwrite: true,

    // 运行按钮（顶层页面）
    runButtonText: /^运行/, // 文字以“运行”开头
    runButtonClass: /run-btn/, // 兜底：class 含 run-btn
    confirmButtonText: /确认|确定|继续|同意|Confirm|OK/i, // 消耗确认弹窗

    // 回收成品（任务跑完——无论成功/失败——把输出节点的成品下载到本地）
    downloadOutput: true,
    videopreviewWidget: "videopreview", // VHS 视频节点承载成品信息的 widget
    outputWaitMs: 1200000, // 等成品出现的最长时间（默认 20 分钟）

    // 运行模式（顶层那个“运行 Lite/Standard”下拉）。
    // 默认留空＝不自动切换（你在页面手动选一次 Lite/Plus 即可，会一直生效，零风险）。
    // 想让扩展自动切就填 "Lite/Plus"——但因运行/模式按钮结构相近，自动点可能误触，建议先测 1 条确认不会重复运行。
    runMode: "",

    // 计时（毫秒）
    appReadyTimeoutMs: 60000, // 等 ComfyUI app 就绪
    uploadTimeoutMs: 180000, // 单个文件上传超时（视频较大）
    afterRunDelayMs: 3000, // 点运行后先等一下让 UI 反应
    waitButtonReenableMs: 600000, // 等运行按钮重新可用（串行排队，最长 10 分钟）
    runButtonWaitMs: 180000, // 点运行前，等“运行”按钮恢复可点的最长时间（任务间它会短暂禁用/变文字）
    balanceModalText: /RH币余额为\s*0|余额为\s*0|余额不足/, // “RH币余额为0”弹窗文字
    balanceReloadDelayMs: 30000, // 检测到余额为0后，等多久再刷新页面（避免狂刷，给余额刷新留时间）
    uploadRetries: 3, // 上传失败重试次数（网络抖动/Failed to fetch）
    retryDelayMs: 4000, // 重试间隔（会按次数递增）
    taskRetries: 2, // 单条任务整体失败的自动重试次数；无限图片模式重试后仍失败则跳过继续
    perTaskGapMs: 3000, // 两个任务之间额外间隔

    imageExts: [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"],
    videoExts: [".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi", ".flv", ".wmv"],
  };

  // ============================================================
  // 基础工具
  // ============================================================
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const log = (msg, type = "info") => {
    const t = new Date().toLocaleTimeString();
    const line = `[${t}] ${msg}`;
    console.log("[RH批量]", line);
    appendLog(line, type);
  };

  const naturalCompare = (a, b) =>
    a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });

  const extOf = (name) => {
    const i = name.lastIndexOf(".");
    return i >= 0 ? name.slice(i).toLowerCase() : "";
  };
  const isImage = (n) => CONFIG.imageExts.includes(extOf(n));
  const isVideo = (n) => CONFIG.videoExts.includes(extOf(n));

  const isVisible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
  };
  const isDisabled = (el) => {
    if (!el) return true;
    if (el.disabled) return true;
    if (el.getAttribute && el.getAttribute("aria-disabled") === "true") return true;
    const c = (el.className || "").toString();
    if (/ant-btn-loading|disabled/.test(c)) return true;
    return false;
  };

  async function waitFor(predicate, timeout, interval = 400) {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      try {
        const v = predicate();
        if (v) return v;
      } catch (_) {}
      await sleep(interval);
    }
    return null;
  }

  // ============================================================
  // ComfyUI app 接入（同源 iframe）
  // ============================================================
  function getComfy() {
    // 1) 找 comfyUI.html 的 iframe
    const ifrs = [...document.querySelectorAll("iframe")];
    const ordered = ifrs.sort((a, b) =>
      (/comfy/i.test(b.src) ? 1 : 0) - (/comfy/i.test(a.src) ? 1 : 0)
    );
    for (const f of ordered) {
      try {
        const w = f.contentWindow;
        if (w && w.app && w.app.graph) return { app: w.app, win: w };
      } catch (_) {
        /* 跨域，跳过 */
      }
    }
    // 2) 也许当前页本身就是 ComfyUI
    if (window.app && window.app.graph) return { app: window.app, win: window };
    return null;
  }

  function findNode(app, idCfg, typeCfg, widgetName) {
    const nodes = app.graph._nodes || [];
    if (idCfg != null) {
      const byId = nodes.find((n) => String(n.id) === String(idCfg));
      if (byId) return byId;
    }
    // 按类型 + 是否含目标 widget 识别
    const candidates = nodes.filter(
      (n) =>
        n.type === typeCfg &&
        (n.widgets || []).some((w) => w.name === widgetName)
    );
    if (candidates.length) return candidates[0];
    // 再宽松：只要有该 widget
    return nodes.find((n) => (n.widgets || []).some((w) => w.name === widgetName)) || null;
  }

  function getWidget(node, name) {
    return (node.widgets || []).find((w) => w.name === name) || null;
  }

  // 上传文件到 ComfyUI 输入目录，返回服务器文件名
  async function uploadOnce(win, file) {
    const app = win.app;
    const fd = new win.FormData();
    fd.append("image", file, file.name);
    fd.append("type", CONFIG.uploadType);
    fd.append("overwrite", CONFIG.uploadOverwrite ? "true" : "false");

    let resp;
    if (app && app.api && typeof app.api.fetchApi === "function") {
      resp = await app.api.fetchApi("/upload/image", { method: "POST", body: fd });
    } else {
      resp = await win.fetch(win.location.origin + "/upload/image", {
        method: "POST",
        body: fd,
        credentials: "include",
      });
    }
    if (!resp || !resp.ok) throw new Error("上传失败 HTTP " + (resp ? resp.status : "?"));
    const data = await resp.json();
    if (!data || !data.name) throw new Error("上传返回缺少文件名: " + JSON.stringify(data));
    let name = data.name;
    if (data.subfolder) name = data.subfolder + "/" + name;
    return name;
  }

  // 带重试的上传（网络抖动 / Failed to fetch / 5xx 会自动重试，每次重新拿最新 iframe）
  async function uploadToComfy(_win, file) {
    const tries = Math.max(1, CONFIG.uploadRetries || 3);
    let lastErr;
    for (let t = 1; t <= tries; t++) {
      const comfy = getComfy();
      const win = comfy ? comfy.win : _win;
      if (!win) {
        lastErr = new Error("ComfyUI 窗口不可用");
      } else {
        try {
          return await uploadOnce(win, file);
        } catch (e) {
          lastErr = e;
        }
      }
      if (t < tries) {
        log(`上传失败(${(lastErr && lastErr.message) || lastErr})，第 ${t}/${tries} 次重试…`, "err");
        await sleep((CONFIG.retryDelayMs || 4000) * t);
      }
    }
    throw lastErr || new Error("上传失败");
  }

  function setNodeFile(app, node, widgetName, name) {
    const w = getWidget(node, widgetName);
    if (!w) throw new Error(`节点 ${node.id} 上没找到 widget "${widgetName}"`);
    if (w.options && Array.isArray(w.options.values) && !w.options.values.includes(name)) {
      w.options.values.push(name);
    }
    w.value = name;
    try {
      if (typeof w.callback === "function") w.callback(name, app.canvas, node);
    } catch (e) {
      console.warn("[RH批量] widget.callback 异常（不影响赋值）:", e);
    }
    try {
      app.graph.setDirtyCanvas(true, true);
    } catch (_) {}
  }

  // 点顶层运行按钮
  const MODE_RE = /Lite|Standard|Plus|Pro/i;

  function findRunButton() {
    const btns = [...document.querySelectorAll('button, [role="button"], .ant-btn')];
    const usable = btns.filter((b) => isVisible(b) && !isDisabled(b) && !opensNewTab(b));
    // 1) 纯“运行”按钮（不含模式词，避免点到模式下拉）
    let btn = usable.find((b) => /^运行$/.test((b.innerText || "").trim()));
    if (btn) return btn;
    // 2) 文字以“运行”开头且不含模式词
    btn = usable.find((b) => {
      const t = (b.innerText || "").trim();
      return CONFIG.runButtonText.test(t) && !MODE_RE.test(t);
    });
    if (btn) return btn;
    // 3) 兜底 class
    btn = usable.find((b) => CONFIG.runButtonClass.test((b.className || "").toString()));
    return btn || null;
  }

  // 等“运行”按钮恢复可点（任务之间它会短暂禁用 / 文字变成运行中-排队中等）
  async function waitRunButton(timeoutMs) {
    return await waitFor(() => findRunButton(), timeoutMs || CONFIG.runButtonWaitMs, 500);
  }

  // 找页面上的“取消/停止/中断”按钮（排除本扩展面板自己的按钮）
  function findCancelButton() {
    // RunningHub 任务列表里运行中的任务，取消按钮是 <div class="rh-cancel-btn">取消</div>
    const rh = [...document.querySelectorAll(".rh-cancel-btn")].find((el) => isVisible(el));
    if (rh) return rh;
    // 兜底：任意可见元素，文字恰好是“取消/停止/中断”等（不点“删除”）
    const all = [...document.querySelectorAll('button, [role="button"], .ant-btn, div, span, a')];
    return (
      all.find((b) => {
        if (panel && panel.contains(b)) return false;
        if (!isVisible(b) || opensNewTab(b)) return false;
        const t = (b.innerText || b.textContent || "").trim();
        return /^(取消|停止|中断|结束运行|Cancel|Stop|Interrupt)$/.test(t);
      }) || null
    );
  }

  // 检测“RH币余额为0”弹窗
  function balanceModalPresent() {
    const re = CONFIG.balanceModalText;
    const scopes = [...document.querySelectorAll('.ant-modal, .ant-modal-confirm, [role="dialog"]')].filter(isVisible);
    if (scopes.some((m) => re.test(m.innerText || ""))) return true;
    // 兜底：任意可见短文本元素命中
    const els = [...document.querySelectorAll("div, span, p")];
    return els.some((el) => {
      if (!isVisible(el)) return false;
      const t = (el.innerText || el.textContent || "").trim();
      return t.length <= 40 && re.test(t);
    });
  }

  // 余额为0时：保存断点 → 延迟后刷新页面（刷新后断点续跑）
  async function handleBalanceModalIfAny() {
    if (!state.running || state._reloading) return false;
    if (!balanceModalPresent()) return false;
    state._reloading = true;
    const sec = Math.round((CONFIG.balanceReloadDelayMs || 30000) / 1000);
    log(`检测到「RH币余额为0」弹窗，${sec}秒后保存断点并刷新页面续跑…`, "err");
    saveProgress({ active: true, index: state.index });
    await sleep(CONFIG.balanceReloadDelayMs || 30000);
    if (balanceModalPresent()) {
      location.reload();
    } else {
      state._reloading = false; // 余额恢复了，弹窗没了，不刷
      log("余额弹窗已消失，继续运行", "ok");
    }
    return true;
  }

  // 取消当前/最新任务，让“运行”按钮恢复可用（卡住时刷新没用，必须取消任务）
  async function cancelCurrentTask(reason, reloadAfter) {
    let did = false;
    const comfy = getComfy();
    if (comfy && comfy.win && comfy.win.app && comfy.win.app.api) {
      const api = comfy.win.app.api;
      try {
        if (typeof api.interrupt === "function") {
          await api.interrupt();
          did = true;
        } else {
          await api.fetchApi("/interrupt", { method: "POST" });
          did = true;
        }
      } catch (_) {}
      // 清掉队列里还没跑的
      try {
        await api.fetchApi("/queue", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ clear: true }),
        });
      } catch (_) {}
    }
    // 再点一下页面上的“取消/停止”按钮（RunningHub 的）
    const btn = findCancelButton();
    if (btn) {
      btn.click();
      did = true;
    }
    log(`已尝试取消当前任务${reason ? "（" + reason + "）" : ""}：${did ? "已发送中断/取消" : "没找到可取消的入口"}`, did ? "ok" : "err");

    // 取消后刷新页面续跑（卡住时仅取消往往还不够，需整页刷新）
    if (reloadAfter) {
      state._reloading = true;
      saveProgress({ active: true, index: state.index });
      log("取消后刷新页面续跑…", "err");
      await sleep(1500);
      try {
        location.reload();
      } catch (_) {
        location.href = location.href;
      }
      // reload 偶发不生效时再试一次
      setTimeout(() => {
        try {
          location.reload();
        } catch (_) {
          location.href = location.href;
        }
      }, 4000);
    }
    return did;
  }

  // 找不到可点运行按钮时，列出页面上相关按钮的状态，帮助定位原因
  function diagnoseRunButtons() {
    const all = [...document.querySelectorAll('button, [role="button"], .ant-btn, a')];
    const cand = all.filter((b) => {
      const t = (b.innerText || "").trim();
      return (
        /运行|生成|提交|Run|排队|运行中|生成中|充值|余额|积分|确认|继续/.test(t) ||
        /run-btn/.test((b.className || "").toString())
      );
    });
    const items = cand.slice(0, 10).map((b) => {
      const t = (b.innerText || "").trim().replace(/\s+/g, " ").slice(0, 24);
      return `「${t || b.tagName}」${isVisible(b) ? "" : "[隐藏]"}${isDisabled(b) ? "[禁用]" : "[可点]"}`;
    });
    return items.length ? items.join(" ; ") : "(页面上没有任何含“运行/生成/充值”的按钮)";
  }

  // 在“运行 Lite/Standard”下拉里选好运行模式（best-effort）
  async function selectRunMode(modeStr) {
    if (!modeStr) return;
    const strip = (s) => (s || "").replace(/\s+/g, "");
    const want = strip(modeStr);

    const btns = [...document.querySelectorAll('button, [role="button"], .ant-btn, .ant-dropdown-trigger')];
    const trigger = btns.find((b) => isVisible(b) && MODE_RE.test(b.innerText || ""));
    if (!trigger) {
      log("没找到运行模式下拉，跳过设置模式（用页面当前模式）", "info");
      return;
    }
    if (strip(trigger.innerText).includes(want)) {
      log("运行模式已是：" + modeStr, "ok");
      return;
    }
    trigger.click();
    const item = await waitFor(
      () => {
        const items = [
          ...document.querySelectorAll(
            '.ant-dropdown-menu-item, [role="menuitem"], .ant-dropdown li, .ant-select-item-option'
          ),
        ].filter(isVisible);
        return (
          items.find((it) => strip(it.innerText).includes(want)) ||
          items.find((it) => want.split("/").some((p) => p && strip(it.innerText).includes(strip(p)))) ||
          null
        );
      },
      3000,
      200
    );
    if (item) {
      item.click();
      await sleep(400);
      log("已选择运行模式：" + (item.innerText || modeStr).trim(), "ok");
    } else {
      const opts = [...document.querySelectorAll('.ant-dropdown-menu-item, [role="menuitem"]')]
        .filter(isVisible)
        .map((i) => (i.innerText || "").trim())
        .filter(Boolean);
      log(`没找到模式“${modeStr}”。可选项：${opts.join(" | ") || "(空)"}。请按实际改面板里的运行模式`, "err");
      document.body.click(); // 关闭下拉
    }
  }

  // 会打开新标签/新窗口的元素（要避免误点）
  function opensNewTab(el) {
    if (!el) return false;
    if (el.tagName === "A") {
      const tgt = (el.getAttribute("target") || "").toLowerCase();
      if (tgt === "_blank" || tgt === "_new") return true;
      const href = el.getAttribute("href") || "";
      if (/^https?:\/\//i.test(href)) return true; // 跳到外部/新页
    }
    return false;
  }

  // 只在「可见的弹窗内」找确认按钮（绝不点页面上的其它按钮，避免开新窗口）
  async function clickConfirmIfAny() {
    const btn = await waitFor(
      () => {
        const dialogs = [
          ...document.querySelectorAll('.ant-modal-wrap, .ant-modal, .ant-modal-confirm, [role="dialog"]'),
        ].filter((d) => isVisible(d));
        for (const dlg of dialogs) {
          const cands = [...dlg.querySelectorAll('button, [role="button"], .ant-btn')];
          const hit = cands.find((el) => {
            if (!isVisible(el) || isDisabled(el) || opensNewTab(el)) return false;
            const txt = (el.innerText || el.textContent || "").trim();
            return txt && txt.length <= 12 && CONFIG.confirmButtonText.test(txt);
          });
          if (hit) return hit;
        }
        return null;
      },
      2500,
      250
    );
    if (btn) {
      log("检测到确认弹窗，点击：" + (btn.innerText || "").trim(), "ok");
      btn.click();
      await sleep(800);
      return true;
    }
    return false;
  }

  // ============================================================
  // 批量主流程
  // ============================================================
  const state = {
    pairs: [],
    index: 0,
    running: false,
    paused: false,
    stop: false,
    saveDirHandle: null, // 保存目录句柄
    selectedSaveNodeIds: new Set(), // 勾选要回收的视频节点 id
    imageDirHandle: null, // 图片目录句柄（可持久化、刷新后恢复）
    videoDirHandle: null, // 视频目录句柄
    imageItems: [], // 图片文件句柄（已排序）
    videoItems: [], // 视频文件句柄（已排序）
    imageMode: "loop", // 配对/取图方式：loop 顺序循环 / random 随机
    videoStart: 1, // 从第几个开始（1-based）：视频模式=第几个视频；图片模式=第几张图
    randomSeed: 1, // 随机种子（持久化，刷新后可复现）
    runMode: "", // 运行模式（来自 CONFIG.runMode，可在面板改）
    infinite: false, // 图片模式：无限循环
    modeOverride: "auto", // 工作流模式：auto 自动 / pair 视频换装 / image 纯图片
    watchdogMin: 20, // 看门狗分钟数（卡住多久刷新）
    currentWfId: null, // 当前工作流 id（检测 SPA 切换）
    _reloading: false, // 正在因余额为0刷新（防重复）
    lastActivity: 0, // 最近一次 ComfyUI 活动时间（看门狗用）
    lastExecEndTs: 0, // 最近一次任务结束时间（串行节流用）
    captured: {}, // nodeId -> {items:[{filename,subfolder,type,format,cos_url}], ts}（executed 事件捕获）
    _watchdog: null,
  };

  // ============================================================
  // 持久化（IndexedDB 存目录句柄 / localStorage 存进度设置）—— 用于刷新后续跑
  // ============================================================
  const IDB_NAME = "rhBatch";
  const IDB_STORE = "kv";

  // 按工作流 id 分开存（两个工作流互不干扰）
  function wfId() {
    const m = location.pathname.match(/workflow\/([^/?#]+)/);
    return m ? m[1] : "default";
  }
  function lsKey() {
    return "rhBatchState:" + wfId();
  }
  function dirKey(name) {
    return name + ":" + wfId();
  }

  function idbOpen() {
    return new Promise((res, rej) => {
      const r = indexedDB.open(IDB_NAME, 1);
      r.onupgradeneeded = () => r.result.createObjectStore(IDB_STORE);
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
  }
  async function idbSet(k, v) {
    const db = await idbOpen();
    return new Promise((res, rej) => {
      const tx = db.transaction(IDB_STORE, "readwrite");
      tx.objectStore(IDB_STORE).put(v, k);
      tx.oncomplete = () => res();
      tx.onerror = () => rej(tx.error);
    });
  }
  async function idbGet(k) {
    const db = await idbOpen();
    return new Promise((res, rej) => {
      const tx = db.transaction(IDB_STORE, "readonly");
      const rq = tx.objectStore(IDB_STORE).get(k);
      rq.onsuccess = () => res(rq.result);
      rq.onerror = () => rej(rq.error);
    });
  }

  function saveProgress(extra) {
    const data = Object.assign(
      {
        active: state.running,
        index: state.index,
        videoStart: state.videoStart,
        imageMode: state.imageMode,
        randomSeed: state.randomSeed,
        runMode: state.runMode,
        infinite: state.infinite,
        modeOverride: state.modeOverride,
        watchdogMin: state.watchdogMin,
        selected: [...state.selectedSaveNodeIds],
      },
      extra || {}
    );
    try {
      localStorage.setItem(lsKey(), JSON.stringify(data));
    } catch (_) {}
  }
  function loadProgress() {
    try {
      return JSON.parse(localStorage.getItem(lsKey()) || "null");
    } catch (_) {
      return null;
    }
  }
  function clearProgress() {
    // 清进度但保留选项（active/index 置空，设置保留）→ 刷新后不丢选项
    try {
      const data = loadProgress() || {};
      data.active = false;
      data.index = 0;
      localStorage.setItem(lsKey(), JSON.stringify(data));
    } catch (_) {}
  }

  // 仅保存选项（不动 active/index）；用户改选项时调用，刷新后能还原
  function saveSettings() {
    try {
      const data = loadProgress() || {};
      data.videoStart = state.videoStart;
      data.imageMode = state.imageMode;
      data.infinite = state.infinite;
      data.modeOverride = state.modeOverride;
      data.watchdogMin = state.watchdogMin;
      data.runMode = state.runMode;
      data.randomSeed = state.randomSeed;
      data.selected = [...state.selectedSaveNodeIds];
      localStorage.setItem(lsKey(), JSON.stringify(data));
    } catch (_) {}
  }

  // 加载选项到 state（不还原运行进度，那个由 tryResume 负责）
  function restoreSettings() {
    const data = loadProgress();
    if (!data) return false;
    if (data.videoStart != null) state.videoStart = data.videoStart;
    if (data.imageMode) state.imageMode = data.imageMode;
    if (typeof data.infinite === "boolean") state.infinite = data.infinite;
    if (data.modeOverride) state.modeOverride = data.modeOverride;
    if (data.watchdogMin) state.watchdogMin = data.watchdogMin;
    if (data.runMode != null) state.runMode = data.runMode;
    if (data.randomSeed) state.randomSeed = data.randomSeed;
    return true;
  }

  const bumpActivity = () => {
    state.lastActivity = Date.now();
  };

  // ============================================================
  // 回收成品视频
  // ============================================================
  function nodeSaveOutput(node) {
    const w = (node.widgets || []).find((x) => x.name === "save_output");
    return w ? !!w.value : false;
  }

  // 所有可作为“成品输出”的节点（图片 SaveImage / 视频 VHS_VideoCombine / 各种预览）
  function getOutputNodes(app) {
    return (app.graph._nodes || []).filter((n) => CONFIG.outputNodeTypes.includes(n.type));
  }

  // 默认勾选哪些输出节点：真正保存的（SaveImage 总是；VHS_VideoCombine 看 save_output）
  function isDefaultChecked(node) {
    if (node.type === "SaveImage") return true;
    if (node.type === "VHS_VideoCombine") return nodeSaveOutput(node);
    return false;
  }

  // 当前工作流模式：手动指定优先；否则自动（有视频输入节点=pair，否则=image）
  function currentMode() {
    if (state.modeOverride === "pair" || state.modeOverride === "image") return state.modeOverride;
    const comfy = getComfy();
    if (!comfy) return "unknown";
    const v = findNode(comfy.app, CONFIG.videoNodeId, CONFIG.videoNodeType, CONFIG.videoWidget);
    return v ? "pair" : "image";
  }

  function getNodeVideoParams(app, id) {
    const n = (app.graph._nodes || []).find((x) => String(x.id) === String(id));
    if (!n) return null;
    const w = (n.widgets || []).find(
      (x) => x.name === CONFIG.videopreviewWidget || x.type === "preview"
    );
    const p = w && w.value && w.value.params;
    return p && p.filename ? p : null;
  }

  function viewRoute(item) {
    const q = new URLSearchParams({
      filename: item.filename,
      type: item.type || "output",
      subfolder: item.subfolder || "",
    });
    if (item.format) q.set("format", item.format);
    return "/view?" + q.toString();
  }

  async function fetchOutputBlob(win, item) {
    const app = win.app;
    const route = viewRoute(item);
    const errs = [];

    // 1) ComfyUI 内部 fetchApi（与上传同一通道，最可靠）
    if (app && app.api && typeof app.api.fetchApi === "function") {
      try {
        const r = await app.api.fetchApi(route);
        if (r.ok) return await r.blob();
        errs.push("fetchApi " + r.status);
      } catch (e) {
        errs.push("fetchApi " + (e.message || e));
      }
    }
    // 2) apiURL + fetch
    if (app && app.api && typeof app.api.apiURL === "function") {
      try {
        const r = await win.fetch(app.api.apiURL(route), { credentials: "include" });
        if (r.ok) return await r.blob();
        errs.push("apiURL " + r.status);
      } catch (e) {
        errs.push("apiURL " + (e.message || e));
      }
    }
    // 3) 同源根路径 /view
    try {
      const r = await win.fetch(win.location.origin + route, { credentials: "include" });
      if (r.ok) return await r.blob();
      errs.push("origin " + r.status);
    } catch (e) {
      errs.push("origin " + (e.message || e));
    }
    // 4) cos_url CDN 直链（可能被 CORS 拦）
    if (item.cos_url) {
      try {
        const r = await win.fetch(item.cos_url);
        if (r.ok) return await r.blob();
        errs.push("cos " + r.status);
      } catch (e) {
        errs.push("cos " + (e.message || e));
      }
    }
    throw new Error("下载失败 [" + errs.join(" | ") + "]");
  }

  async function ensureDirPerm(handle) {
    if (!handle) return false;
    const opts = { mode: "readwrite" };
    try {
      if ((await handle.queryPermission(opts)) === "granted") return true;
      return (await handle.requestPermission(opts)) === "granted";
    } catch (_) {
      return false;
    }
  }

  async function saveBlob(win, blob, name) {
    if (state.saveDirHandle && (await ensureDirPerm(state.saveDirHandle))) {
      const fh = await state.saveDirHandle.getFileHandle(name, { create: true });
      const ws = await fh.createWritable();
      await ws.write(blob);
      await ws.close();
      return "目录:" + state.saveDirHandle.name;
    }
    // 兜底：浏览器默认下载文件夹
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 15000);
    return "默认下载文件夹";
  }

  // 收集某节点“新”的输出项（事件捕获优先，回退到视频预览 widget）
  function collectNodeNewItems(app, id, baseline) {
    const out = [];
    const params = getNodeVideoParams(app, id); // 视频节点的 widget 预览（含 cos_url）
    const cap = state.captured[id];
    if (cap && cap.ts > baseline.ts) {
      for (const it of cap.items) {
        if (it && it.filename) {
          const item = {
            filename: it.filename,
            subfolder: it.subfolder || "",
            type: it.type || "output",
            format: it.format,
          };
          // 事件项没有 cos_url：若与 widget 预览同名，借用其 cos_url 作兜底
          if (params && params.filename === it.filename && params.cos_url) {
            item.cos_url = params.cos_url;
          }
          out.push(item);
        }
      }
    }
    if (!out.length && params && params.filename && params.filename !== (baseline.before[id] || null)) {
      out.push({
        filename: params.filename,
        subfolder: params.subfolder || "",
        type: params.type || "output",
        format: params.format,
        cos_url: params.cos_url,
      });
    }
    return out;
  }

  // 跑完后回收：等被勾选输出节点出现“新成品”（图片或视频），下载到本地
  async function collectOutputs(comfy, baseline) {
    if (!CONFIG.downloadOutput) return 0;
    if (!state.selectedSaveNodeIds.size) {
      log("未勾选任何输出节点，跳过回收", "info");
      return 0;
    }
    const { app, win } = comfy;

    const found = await waitFor(
      () => {
        for (const id of state.selectedSaveNodeIds) {
          if (collectNodeNewItems(app, id, baseline).length) return "output";
        }
        // 任务已结束（成功/失败/被取消）也别再干等
        if (state.lastExecEndTs > baseline.ts) return "ended";
        return false;
      },
      CONFIG.outputWaitMs,
      800
    );
    if (!found) {
      log("没等到新成品（可能在出图/出视频前就失败了）", "err");
      return 0;
    }
    if (found === "ended") {
      // 给“执行完成”事件后置的 UI 更新留点时间，再看看有没有成品
      await sleep(1200);
    }
    await sleep(1200); // 让其它被勾选节点也出结果

    const seen = new Set();
    let n = 0;
    for (const id of state.selectedSaveNodeIds) {
      for (const item of collectNodeNewItems(app, id, baseline)) {
        const name = String(item.filename).split("/").pop();
        if (seen.has(name)) continue;
        seen.add(name);
        try {
          const blob = await fetchOutputBlob(win, item);
          const where = await saveBlob(win, blob, name);
          log(`已回收 节点${id} → ${name}（${where}）`, "ok");
          n++;
        } catch (e) {
          log(`回收 节点${id} ${name} 失败：${e.message}`, "err");
        }
      }
    }
    return n;
  }

  // 记录回收基线（事件时间戳 + 各节点当前文件名）
  function outputBaseline(app) {
    const before = {};
    for (const id of state.selectedSaveNodeIds) {
      const p = getNodeVideoParams(app, id);
      before[id] = p ? p.filename : null;
    }
    return { ts: Date.now(), before };
  }

  // 给第 vIdx 个视频选一张图片：loop=顺序循环；random=按种子确定性随机（刷新后可复现）
  function pickImageIndex(vIdx) {
    const m = state.imageItems.length;
    if (m <= 0) return 0;
    if (state.imageMode === "random") {
      let x = ((vIdx + 1) * 2654435761) ^ (state.randomSeed | 0);
      x = (x ^ (x >>> 15)) >>> 0;
      return x % m;
    }
    return vIdx % m; // loop
  }

  // 重新计算（区分 pair / image 模式）。keepIndex=true 时不重置进度（续跑用）
  function recomputePairs(keepIndex) {
    const imgs = state.imageItems;
    const vids = state.videoItems;
    const start = Math.max(1, parseInt(state.videoStart, 10) || 1);
    const modeTxt = state.imageMode === "random" ? "随机" : "顺序循环";
    const wfMode = currentMode();

    if (wfMode === "image") {
      // 纯图片模式：无 pairs，按图片序列跑
      state.pairs = [];
      if (!keepIndex) state.index = start - 1;
      if (statEl) {
        const cntTxt = state.infinite ? "无限循环" : `单遍 ${Math.max(0, imgs.length - (start - 1))} 张`;
        statEl.textContent = `图片 ${imgs.length} · 第${start}张起 · ${modeTxt} · ${cntTxt}`;
      }
    } else {
      // 视频换装模式：视频为主 1 配 1
      const pairs = [];
      if (imgs.length && vids.length) {
        for (let v = start - 1; v < vids.length; v++) {
          pairs.push({ video: vids[v], image: imgs[pickImageIndex(v)], vIdx: v });
        }
      }
      state.pairs = pairs;
      if (!keepIndex) state.index = 0;
      if (statEl) {
        statEl.textContent = `图片 ${imgs.length} · 视频 ${vids.length} · 第${start}个起 · ${modeTxt} → ${pairs.length} 个任务`;
      }
    }
    updateProgress();
    setButtons();
  }

  // 等待 ComfyUI + 关键节点就绪（iframe 可能在任务间被 RunningHub 重载/重同步）
  async function waitComfyNodes(needVideo) {
    const got = await waitFor(
      () => {
        const c = getComfy();
        if (!c) return null;
        const img = findNode(c.app, CONFIG.imageNodeId, CONFIG.imageNodeType, CONFIG.imageWidget);
        if (!img) return null;
        if (needVideo) {
          const vid = findNode(c.app, CONFIG.videoNodeId, CONFIG.videoNodeType, CONFIG.videoWidget);
          if (!vid) return null;
          return { comfy: c, imgNode: img, vidNode: vid };
        }
        return { comfy: c, imgNode: img };
      },
      CONFIG.appReadyTimeoutMs,
      500
    );
    return got;
  }

  async function processOne(pair, i) {
    const ready = await waitComfyNodes(true);
    if (!ready) throw new Error("等待超时：ComfyUI 或 图片/视频节点未就绪（iframe 可能正在重载）");
    const { comfy, imgNode, vidNode } = ready;
    const { app, win } = comfy;

    bumpActivity();
    // 从目录句柄读取真实 File（支持刷新后恢复）
    const imgFile = typeof pair.image.getFile === "function" ? await pair.image.getFile() : pair.image;
    const vidFile = typeof pair.video.getFile === "function" ? await pair.video.getFile() : pair.video;

    log(`#${i + 1}/${state.pairs.length}（视频#${(pair.vIdx ?? i) + 1}）上传图片：${pair.image.name}`);
    const imgName = await Promise.race([
      uploadToComfy(win, imgFile),
      sleep(CONFIG.uploadTimeoutMs).then(() => Promise.reject(new Error("图片上传超时"))),
    ]);
    setNodeFile(app, imgNode, CONFIG.imageWidget, imgName);
    bumpActivity();
    log(`  图片已设到节点 ${imgNode.id} → ${imgName}`, "ok");

    log(`#${i + 1} 上传视频：${pair.video.name}（较大请耐心）`);
    const vidName = await Promise.race([
      uploadToComfy(win, vidFile),
      sleep(CONFIG.uploadTimeoutMs).then(() => Promise.reject(new Error("视频上传超时"))),
    ]);
    setNodeFile(app, vidNode, CONFIG.videoWidget, vidName);
    bumpActivity();
    log(`  视频已设到节点 ${vidNode.id} → ${vidName}`, "ok");

    const baseline = outputBaseline(app);

    const runBtn = await waitRunButton();
    if (!runBtn) throw new Error("等待超时：运行按钮一直不可点。候选按钮：" + diagnoseRunButtons());
    log("点击运行：「" + (runBtn.innerText || "").trim().replace(/\s+/g, " ") + "」", "ok");
    runBtn.click();
    bumpActivity();

    await clickConfirmIfAny();
    await sleep(CONFIG.afterRunDelayMs);
    if (await handleBalanceModalIfAny()) return; // 余额为0：刷新续跑

    // 回收成品（无论成功/失败，等输出节点出新结果就下载）
    if (CONFIG.downloadOutput && state.selectedSaveNodeIds.size) {
      log(`#${i + 1} 等待成品…`);
      await collectOutputs(comfy, baseline);
    } else {
      await waitTaskDone(baseline.ts, `#${i + 1}`);
    }

    // 等运行按钮重新可用（表示这条已结束，可提交下一条）
    await waitFor(() => {
      const b = findRunButton();
      return b && !isDisabled(b);
    }, CONFIG.waitButtonReenableMs, 800);

    log(`#${i + 1} 完成`, "ok");
  }

  // 图片模式：上传一张图 → 写 LoadImage → 运行 → 回收成品
  async function processImageOne(comfy, imgNode, handle, label) {
    const { app, win } = comfy;
    bumpActivity();
    const imgFile = typeof handle.getFile === "function" ? await handle.getFile() : handle;

    log(`${label} 上传图片：${handle.name}`);
    const imgName = await Promise.race([
      uploadToComfy(win, imgFile),
      sleep(CONFIG.uploadTimeoutMs).then(() => Promise.reject(new Error("图片上传超时"))),
    ]);
    setNodeFile(app, imgNode, CONFIG.imageWidget, imgName);
    bumpActivity();
    log(`  已设到节点 ${imgNode.id} → ${imgName}`, "ok");

    const baseline = outputBaseline(app);

    const runBtn = await waitRunButton();
    if (!runBtn) throw new Error("等待超时：运行按钮一直不可点。候选按钮：" + diagnoseRunButtons());
    runBtn.click();
    bumpActivity();
    log("点击运行：「" + (runBtn.innerText || "").trim().replace(/\s+/g, " ") + "」", "ok");

    await clickConfirmIfAny();
    await sleep(CONFIG.afterRunDelayMs);
    if (await handleBalanceModalIfAny()) return; // 余额为0：刷新续跑

    if (CONFIG.downloadOutput && state.selectedSaveNodeIds.size) {
      log(`${label} 等待成品图…`);
      await collectOutputs(comfy, baseline);
    } else {
      // 没勾输出节点：也要等任务真正结束，避免狂刷并发开很多任务
      await waitTaskDone(baseline.ts, label);
    }

    await waitFor(() => {
      const b = findRunButton();
      return b && !isDisabled(b);
    }, CONFIG.waitButtonReenableMs, 800);
  }

  // 等当前任务结束（成功/失败/队列清空）。baseTs=点运行前的时间
  async function waitTaskDone(baseTs, label) {
    const ok = await waitFor(() => state.lastExecEndTs > baseTs, CONFIG.outputWaitMs, 800);
    if (!ok) log(`${label || ""} 没等到任务结束信号（超时），继续下一条`, "err");
    return ok;
  }

  async function runBatch() {
    if (state.running) return;
    const comfy = getComfy();
    if (!comfy) {
      log("还没检测到 ComfyUI（iframe 未加载完？）。等画布加载完再点开始。", "err");
      return;
    }
    const mode = currentMode();
    if (mode === "image") {
      if (!state.imageItems.length) {
        log("没有图片，请先选择图片文件夹", "err");
        return;
      }
    } else {
      if (!state.pairs.length) {
        log("没有可处理的配对，请先选择图片/视频文件夹", "err");
        return;
      }
    }

    state.running = true;
    state.stop = false;
    bumpActivity();
    state.lastExecEndTs = 0;
    ensureActivityListeners(comfy.win);
    startWatchdog();
    setButtons();
    saveProgress({ active: true });

    if (CONFIG.downloadOutput && state.selectedSaveNodeIds.size && !state.saveDirHandle) {
      log("提醒：没选保存目录，成品会走浏览器默认下载；若浏览器设了“每次询问保存位置”会频繁弹窗，建议先点“📥 选择保存目录”。", "err");
    }

    // 先设置运行模式（只设一次）
    try {
      await selectRunMode(state.runMode);
    } catch (e) {
      log("设置运行模式异常：" + e.message, "err");
    }

    if (mode === "image") {
      await runImageLoop();
    } else {
      await runPairs(comfy);
    }

    state.running = false;
    stopWatchdog();
    updateProgress();
    setButtons();
    if (!state.stop) log("✅ 全部完成", "ok");
    clearProgress();
  }

  // 视频换装模式：按 pairs 顺序跑（有限）
  async function runPairs(comfy) {
    for (; state.index < state.pairs.length; state.index++) {
      if (state.stop) {
        log("已停止", "err");
        break;
      }
      while (state.paused && !state.stop) await sleep(300);
      if (state.stop) break;

      updateProgress();
      saveProgress({ active: true });

      let ok = false;
      const maxTry = Math.max(1, (CONFIG.taskRetries || 2) + 1);
      for (let t = 1; t <= maxTry && !state.stop; t++) {
        try {
          await processOne(state.pairs[state.index], state.index);
          ok = true;
          break;
        } catch (e) {
          log(`#${state.index + 1} 失败(${t}/${maxTry})：${e.message}`, "err");
          if (t < maxTry) await sleep((CONFIG.retryDelayMs || 4000) * t);
        }
      }
      if (state.stop) break;
      if (!ok) {
        log("多次重试仍失败，已暂停。检查页面后点“继续”重试当前条，或点“停止”。", "err");
        state.paused = true;
        setButtons();
        while (state.paused && !state.stop) await sleep(300);
        if (state.stop) break;
        state.index--;
        continue;
      }
      if (state.index < state.pairs.length - 1) await sleep(CONFIG.perTaskGapMs);
    }
  }

  // 纯图片模式：从第 videoStart 张开始，顺序循环或随机，可无限
  async function runImageLoop() {
    const m = state.imageItems.length;
    const start = Math.max(1, parseInt(state.videoStart, 10) || 1) - 1;
    if (!state.index || state.index < start) state.index = start; // 续跑时 index 已恢复
    let k = state.index;

    while (!state.stop) {
      while (state.paused && !state.stop) await sleep(300);
      if (state.stop) break;

      // 非无限：顺序模式跑完一遍就停
      if (!state.infinite && state.imageMode !== "random" && k >= m) break;
      if (!state.infinite && state.imageMode === "random" && k - start >= m) break;

      const idx = state.imageMode === "random" ? Math.floor(Math.random() * m) : k % m;
      const handle = state.imageItems[idx];
      const label = `#${k + 1}${state.infinite ? "（无限）" : "/" + (state.infinite ? "∞" : m)} 图[${idx}]`;

      state.index = k;
      updateProgress();
      saveProgress({ active: true, index: k });

      let ok = false;
      const maxTry = Math.max(1, (CONFIG.taskRetries || 2) + 1);
      for (let t = 1; t <= maxTry && !state.stop; t++) {
        try {
          const ready = await waitComfyNodes(false);
          if (!ready) throw new Error("等待超时：ComfyUI 或图片节点未就绪");
          await processImageOne(ready.comfy, ready.imgNode, handle, label);
          ok = true;
          break;
        } catch (e) {
          log(`${label} 失败(${t}/${maxTry})：${e.message}`, "err");
          if (t < maxTry) await sleep((CONFIG.retryDelayMs || 4000) * t);
        }
      }
      if (state.stop) break;
      if (!ok) {
        // 无限模式：自动跳过当前张，继续不停；非无限：暂停等人工
        if (state.infinite) {
          log(`${label} 多次失败，跳过，继续下一张`, "err");
        } else {
          log("已暂停。检查页面后点“继续”重试当前张，或“停止”。", "err");
          state.paused = true;
          setButtons();
          while (state.paused && !state.stop) await sleep(300);
          if (state.stop) break;
          continue; // 重试当前 k
        }
      }
      k++;
      state.index = k;
      await sleep(CONFIG.perTaskGapMs);
    }
  }

  // ============================================================
  // 看门狗 + 活动监听 + 刷新续跑
  // ============================================================
  function ensureActivityListeners(win) {
    if (!win || win.__rhActivity) return;
    const api = win.app && win.app.api;
    if (!api || !api.addEventListener) return;
    [
      "progress",
      "executing",
      "executed",
      "status",
      "execution_success",
      "execution_error",
      "execution_cached",
      "b_preview",
    ].forEach((ev) => {
      try {
        api.addEventListener(ev, bumpActivity);
      } catch (_) {}
    });
    // 捕获节点输出（图片 images / 视频 gifs），供回收成品用
    try {
      api.addEventListener("executed", (e) => {
        const d = (e && e.detail) || {};
        const o = d.output || {};
        const items = o.images || o.gifs || o.video || o.videos || null;
        if (items && items.length && d.node != null) {
          state.captured[String(d.node)] = { items: items.slice(), ts: Date.now() };
        }
      });
    } catch (_) {}
    // 任务结束信号（用于串行节流，避免狂刷并发）
    const markEnd = () => {
      state.lastExecEndTs = Date.now();
    };
    try {
      api.addEventListener("execution_success", markEnd);
      api.addEventListener("execution_error", markEnd);
      api.addEventListener("execution_interrupted", markEnd);
      // 旧版：executing 且 node 为 null 表示队列跑完
      api.addEventListener("executing", (e) => {
        const d = (e && e.detail) || {};
        const node = d && (d.node !== undefined ? d.node : d);
        if (node == null) markEnd();
      });
      // 队列清空
      api.addEventListener("status", (e) => {
        const d = (e && e.detail) || {};
        const remaining =
          d && d.exec_info && typeof d.exec_info.queue_remaining === "number"
            ? d.exec_info.queue_remaining
            : null;
        if (remaining === 0) markEnd();
      });
    } catch (_) {}
    win.__rhActivity = true;
  }

  function startWatchdog() {
    if (state._watchdog) return;
    state._watchdog = setInterval(() => {
      if (!state.running || state.paused || state._reloading) return;
      handleBalanceModalIfAny(); // 余额为0 → 刷新续跑
      if (!state.lastActivity) return;
      const limitMs = Math.max(1, parseFloat(state.watchdogMin) || 20) * 60000;
      if (Date.now() - state.lastActivity > limitMs) {
        log(`⚠ 超过 ${state.watchdogMin} 分钟无进度，自动取消并刷新页面续跑…`, "err");
        state._reloading = true; // 防止重复触发
        (async () => {
          try {
            await cancelCurrentTask("看门狗超时", true);
          } catch (e) {
            log("看门狗恢复异常：" + e.message + "，强制刷新", "err");
            saveProgress({ active: true, index: state.index });
            location.reload();
          }
        })();
      }
    }, 15000);
  }
  function stopWatchdog() {
    if (state._watchdog) {
      clearInterval(state._watchdog);
      state._watchdog = null;
    }
  }

  async function enumerateDir(dirHandle, filterFn) {
    const out = [];
    for await (const entry of dirHandle.values()) {
      if (entry.kind === "file" && filterFn(entry.name)) out.push(entry);
    }
    out.sort((a, b) => naturalCompare(a.name, b.name));
    return out;
  }

  // 刷新后尝试续跑
  async function tryResume() {
    const data = loadProgress();
    if (!data || !data.active) return;

    // 恢复设置
    state.videoStart = data.videoStart || 1;
    state.imageMode = data.imageMode || "loop";
    state.randomSeed = data.randomSeed || 1;
    state.runMode = data.runMode != null ? data.runMode : CONFIG.runMode;
    state.infinite = !!data.infinite;
    state.modeOverride = data.modeOverride || "auto";
    state.watchdogMin = data.watchdogMin || 20;
    state.selectedSaveNodeIds = new Set((data.selected || []).map(String));
    syncOptionUI();

    const mode = currentMode();

    // 恢复目录句柄
    let ih, vh, sh;
    try {
      ih = await idbGet(dirKey("imageDir"));
      vh = await idbGet(dirKey("videoDir"));
      sh = await idbGet(dirKey("saveDir"));
    } catch (_) {}
    const needVideo = mode === "pair";
    if (!ih || (needVideo && !vh)) {
      log("检测到上次未完成，但找不到目录句柄，请手动重选文件夹后从第 " + (data.index + 1) + " 个继续", "err");
      return;
    }

    const grant = async (h) => {
      if (!h) return true;
      return (
        (await h.queryPermission({ mode: "read" })) === "granted" ||
        (await h.requestPermission({ mode: "read" })) === "granted"
      );
    };

    const doResume = async () => {
      if (!(await grant(ih)) || (needVideo && !(await grant(vh)))) {
        log("没拿到目录读取权限，无法自动续跑", "err");
        return;
      }
      state.imageDirHandle = ih;
      state.imageItems = await enumerateDir(ih, isImage);
      if (vh) {
        state.videoDirHandle = vh;
        state.videoItems = await enumerateDir(vh, isVideo);
      }
      if (sh) state.saveDirHandle = sh;
      recomputePairs(true);
      state.index = data.index || 0;
      updateProgress();
      log(`断点续跑：从第 ${state.index + 1} 个继续`, "ok");
      hideResumeUI();
      runBatch();
    };

    // 权限已就绪则自动续跑；否则给按钮（需一次点击授权）
    try {
      const okI = (await ih.queryPermission({ mode: "read" })) === "granted";
      const okV = !needVideo || !vh || (await vh.queryPermission({ mode: "read" })) === "granted";
      if (okI && okV) {
        await doResume();
        return;
      }
    } catch (_) {}
    showResumeUI(data.index, doResume);
  }

  // ============================================================
  // 悬浮面板 UI
  // ============================================================
  let panel, logBox, statEl, progressBar, progressText, btnStart, btnPause, btnStop, appStatEl;

  function buildPanel() {
    panel = document.createElement("div");
    panel.id = "rh-batch-panel";
    panel.innerHTML = `
      <div class="rhb-head">
        <span>RH 批量助手</span>
        <span class="rhb-min" title="折叠">—</span>
      </div>
      <div class="rhb-body">
        <div class="rhb-appstat">ComfyUI：检测中…</div>
        <div class="rhb-row">
          <button class="rhb-btn rhb-pick-img">📁 图片文件夹</button>
          <button class="rhb-btn rhb-pick-vid">🎬 视频文件夹(可选)</button>
        </div>
        <div class="rhb-stat">图片：未选 · 视频：未选</div>
        <div class="rhb-opts">
          <label>工作流模式
            <select class="rhb-wfmode">
              <option value="auto">自动检测</option>
              <option value="pair">视频换装(图+视频)</option>
              <option value="image">纯图片(可无限)</option>
            </select>
          </label>
          <label>从第 <input type="number" class="rhb-startidx" min="1" value="1"> 个开始</label>
          <label>取图方式
            <select class="rhb-imgmode">
              <option value="loop">顺序循环</option>
              <option value="random">随机</option>
            </select>
          </label>
          <label><input type="checkbox" class="rhb-infinite"> 无限循环（纯图片工作流）</label>
          <label>卡住刷新 <input type="number" class="rhb-watchdog" min="1" step="1" value="20"> 分钟</label>
          <label>运行模式 <input type="text" class="rhb-runmode" placeholder="留空=手动"></label>
        </div>
        <div class="rhb-resume" style="display:none"></div>
        <div class="rhb-sub">回收成品视频（成功/失败都下载）</div>
        <button class="rhb-btn rhb-dir">📥 选择保存目录</button>
        <div class="rhb-dirstat">未选择目录（将用浏览器默认下载）</div>
        <div class="rhb-nodes"><div class="rhb-nodes-empty">连接 ComfyUI 后显示视频节点…</div></div>
        <div class="rhb-progress"><div class="rhb-bar"></div><span class="rhb-ptext">0 / 0</span></div>
        <div class="rhb-row">
          <button class="rhb-btn rhb-start" disabled>开始</button>
          <button class="rhb-btn rhb-pause" disabled>暂停</button>
          <button class="rhb-btn rhb-stop" disabled>停止</button>
        </div>
        <button class="rhb-btn rhb-cancel" style="background:#b45309">⏹ 取消当前任务（卡住时点）</button>
        <div class="rhb-log"></div>
      </div>`;
    document.body.appendChild(panel);

    const style = document.createElement("style");
    style.textContent = `
      #rh-batch-panel{position:fixed;top:90px;right:16px;width:300px;z-index:2147483647;
        background:#1f1f24;color:#e8e8ea;border:1px solid #3a3a42;border-radius:10px;
        font:13px/1.5 -apple-system,Segoe UI,Arial,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.4);overflow:hidden}
      #rh-batch-panel .rhb-head{display:flex;justify-content:space-between;align-items:center;
        padding:8px 12px;background:#2b2b33;cursor:move;font-weight:600;user-select:none}
      #rh-batch-panel .rhb-min{cursor:pointer;padding:0 6px}
      #rh-batch-panel .rhb-body{padding:10px 12px;display:flex;flex-direction:column;gap:8px}
      #rh-batch-panel.rhb-collapsed .rhb-body{display:none}
      #rh-batch-panel .rhb-btn{background:#3b82f6;color:#fff;border:0;border-radius:6px;padding:7px 10px;cursor:pointer;font-size:13px}
      #rh-batch-panel .rhb-btn:hover{filter:brightness(1.1)}
      #rh-batch-panel .rhb-btn:disabled{background:#444;color:#888;cursor:not-allowed}
      #rh-batch-panel .rhb-row{display:flex;gap:6px}
      #rh-batch-panel .rhb-row .rhb-btn{flex:1}
      #rh-batch-panel .rhb-appstat{font-size:12px;color:#fbbf24}
      #rh-batch-panel .rhb-appstat.ok{color:#4ade80}
      #rh-batch-panel .rhb-stat{font-size:12px;color:#a8a8b0}
      #rh-batch-panel .rhb-opts{display:flex;flex-direction:column;gap:4px;font-size:12px;color:#cbd5e1}
      #rh-batch-panel .rhb-opts label{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
      #rh-batch-panel .rhb-opts input,#rh-batch-panel .rhb-opts select{background:#16161a;color:#e8e8ea;border:1px solid #3a3a42;border-radius:4px;padding:2px 6px;font-size:12px}
      #rh-batch-panel .rhb-opts input.rhb-startidx{width:64px}
      #rh-batch-panel .rhb-opts input.rhb-runmode{width:100px}
      #rh-batch-panel .rhb-resume{display:flex}
      #rh-batch-panel .rhb-resume .rhb-btn{flex:1;background:#16a34a}
      #rh-batch-panel .rhb-sub{font-size:12px;font-weight:600;color:#93c5fd;border-top:1px solid #3a3a42;padding-top:8px}
      #rh-batch-panel .rhb-dirstat{font-size:12px;color:#a8a8b0;word-break:break-all}
      #rh-batch-panel .rhb-nodes{max-height:96px;overflow:auto;background:#16161a;border-radius:6px;padding:4px 6px}
      #rh-batch-panel .rhb-node{display:block;font-size:12px;color:#d4d4d8;padding:2px 0;cursor:pointer}
      #rh-batch-panel .rhb-node input{margin-right:6px;vertical-align:middle}
      #rh-batch-panel .rhb-nodes-empty{font-size:11px;color:#777}
      #rh-batch-panel .rhb-progress{position:relative;height:18px;background:#33333b;border-radius:4px;overflow:hidden}
      #rh-batch-panel .rhb-bar{height:100%;width:0;background:#22c55e;transition:width .3s}
      #rh-batch-panel .rhb-ptext{position:absolute;inset:0;text-align:center;font-size:11px;line-height:18px}
      #rh-batch-panel .rhb-log{height:150px;overflow:auto;background:#16161a;border-radius:6px;padding:6px 8px;
        font-size:11px;font-family:Consolas,monospace;white-space:pre-wrap;word-break:break-all}
      #rh-batch-panel .rhb-log .ok{color:#4ade80}
      #rh-batch-panel .rhb-log .err{color:#f87171}
      #rh-batch-panel .rhb-log .info{color:#cbd5e1}`;
    document.head.appendChild(style);

    logBox = panel.querySelector(".rhb-log");
    statEl = panel.querySelector(".rhb-stat");
    appStatEl = panel.querySelector(".rhb-appstat");
    progressBar = panel.querySelector(".rhb-bar");
    progressText = panel.querySelector(".rhb-ptext");
    btnStart = panel.querySelector(".rhb-start");
    btnPause = panel.querySelector(".rhb-pause");
    btnStop = panel.querySelector(".rhb-stop");

    panel.querySelector(".rhb-min").addEventListener("click", () => panel.classList.toggle("rhb-collapsed"));
    makeDraggable(panel, panel.querySelector(".rhb-head"));
    panel.querySelector(".rhb-pick-img").addEventListener("click", () => pickMediaFolder("image"));
    panel.querySelector(".rhb-pick-vid").addEventListener("click", () => pickMediaFolder("video"));
    panel.querySelector(".rhb-dir").addEventListener("click", pickSaveDir);
    panel.querySelector(".rhb-cancel").addEventListener("click", () => {
      cancelCurrentTask("手动", state.running);
    });

    const startEl = panel.querySelector(".rhb-startidx");
    const modeEl = panel.querySelector(".rhb-imgmode");
    const runmodeEl = panel.querySelector(".rhb-runmode");
    const infEl = panel.querySelector(".rhb-infinite");
    const wdEl = panel.querySelector(".rhb-watchdog");
    const wfmodeEl = panel.querySelector(".rhb-wfmode");
    startEl.value = String(state.videoStart);
    modeEl.value = state.imageMode;
    runmodeEl.value = state.runMode;
    infEl.checked = state.infinite;
    wdEl.value = String(state.watchdogMin);
    wfmodeEl.value = state.modeOverride;
    wfmodeEl.addEventListener("change", () => {
      state.modeOverride = wfmodeEl.value;
      recomputePairs();
      saveSettings();
    });
    startEl.addEventListener("change", () => {
      state.videoStart = Math.max(1, parseInt(startEl.value, 10) || 1);
      startEl.value = String(state.videoStart);
      recomputePairs();
      saveSettings();
    });
    modeEl.addEventListener("change", () => {
      state.imageMode = modeEl.value;
      recomputePairs();
      saveSettings();
    });
    runmodeEl.addEventListener("change", () => {
      state.runMode = runmodeEl.value.trim();
      saveSettings();
    });
    infEl.addEventListener("change", () => {
      state.infinite = infEl.checked;
      recomputePairs();
      saveSettings();
    });
    wdEl.addEventListener("change", () => {
      state.watchdogMin = Math.max(1, parseFloat(wdEl.value) || 20);
      wdEl.value = String(state.watchdogMin);
      saveSettings();
    });

    btnStart.addEventListener("click", () => {
      if (state.paused) {
        state.paused = false;
        log("继续", "ok");
        setButtons();
        if (!state.running) runBatch();
        return;
      }
      runBatch();
    });
    btnPause.addEventListener("click", () => {
      state.paused = true;
      log("已暂停（点“开始/继续”恢复）", "info");
      setButtons();
    });
    btnStop.addEventListener("click", () => {
      state.stop = true;
      state.paused = false;
    });

    setButtons();
    pollComfyReady();
  }

  function syncOptionUI() {
    if (!panel) return;
    const q = (s) => panel.querySelector(s);
    if (q(".rhb-startidx")) q(".rhb-startidx").value = String(state.videoStart);
    if (q(".rhb-imgmode")) q(".rhb-imgmode").value = state.imageMode;
    if (q(".rhb-runmode")) q(".rhb-runmode").value = state.runMode;
    if (q(".rhb-infinite")) q(".rhb-infinite").checked = state.infinite;
    if (q(".rhb-watchdog")) q(".rhb-watchdog").value = String(state.watchdogMin);
    if (q(".rhb-wfmode")) q(".rhb-wfmode").value = state.modeOverride;
  }

  function showActionButton(text, onClick) {
    const box = panel.querySelector(".rhb-resume");
    if (!box) return;
    box.style.display = "flex";
    box.innerHTML = "";
    const b = document.createElement("button");
    b.className = "rhb-btn";
    b.textContent = text;
    b.addEventListener("click", () => onClick());
    box.appendChild(b);
  }
  function showResumeUI(index, onResume) {
    showActionButton(`▶ 继续上次（从第 ${index + 1} 个）`, onResume);
    log(`检测到上次未完成。点绿色按钮授予目录权限并从第 ${index + 1} 个继续。`, "ok");
  }
  function hideResumeUI() {
    const box = panel.querySelector(".rhb-resume");
    if (box) {
      box.style.display = "none";
      box.innerHTML = "";
    }
  }

  function pollComfyReady() {
    state.currentWfId = wfId();
    let resumeTried = false;
    let recomputed = false;
    const tick = () => {
      // 检测 SPA 切换了工作流（不刷新整页）
      const id = wfId();
      if (id !== state.currentWfId) {
        onWorkflowSwitched(id);
        resumeTried = false;
        recomputed = false;
      }

      const comfy = getComfy();
      const ok = !!comfy;
      if (appStatEl) {
        appStatEl.textContent = ok ? "ComfyUI：已连接 ✓" : "ComfyUI：等待画布加载…";
        appStatEl.classList.toggle("ok", ok);
      }
      if (ok) {
        populateSaveNodes();
        ensureActivityListeners(comfy.win);
        if (!recomputed) {
          recomputed = true;
          recomputePairs(); // 连接后按真实模式刷新统计文案
        }
        if (!resumeTried) {
          resumeTried = true;
          tryResume();
        }
      }
      setButtons();
    };
    tick();
    setInterval(tick, 2000);
  }

  // SPA 内切换到另一个工作流：停掉旧批量、重置本工作流相关状态
  function onWorkflowSwitched(newId) {
    log(`检测到切换工作流（${state.currentWfId} → ${newId}），重置面板`, "info");
    if (state.running) {
      state.stop = true;
      log("已停止上一个工作流的批量", "err");
    }
    state.running = false;
    state.paused = false;
    state.currentWfId = newId;
    // 清掉与上一个工作流绑定的运行态/选择（保留用户已选的目录，方便复用）
    state.pairs = [];
    state.index = 0;
    state.captured = {};
    state.selectedSaveNodeIds = new Set();
    // 重建输出节点勾选列表（签名清空，下次 populateSaveNodes 会按新工作流重建）
    const box = panel && panel.querySelector(".rhb-nodes");
    if (box) {
      box.dataset.sig = "";
      box.innerHTML = `<div class="rhb-nodes-empty">连接 ComfyUI 后显示输出节点…</div>`;
    }
    hideResumeUI();
    // 加载新工作流自己保存的选项 + 目录
    state.imageItems = [];
    state.videoItems = [];
    state.imageDirHandle = null;
    state.videoDirHandle = null;
    state.saveDirHandle = null;
    restoreSettings();
    syncOptionUI();
    recomputePairs();
    setButtons();
    restoreDirs();
  }

  async function pickSaveDir() {
    if (!window.showDirectoryPicker) {
      log("浏览器不支持目录选择（需 Chrome/Edge），将用默认下载文件夹", "err");
      return;
    }
    try {
      const h = await window.showDirectoryPicker({ mode: "readwrite" });
      state.saveDirHandle = h;
      panel.querySelector(".rhb-dirstat").textContent = "保存目录：" + h.name;
      log("保存目录已选：" + h.name, "ok");
      await idbSet(dirKey("saveDir"), h);
    } catch (_) {
      /* 用户取消 */
    }
  }

  function populateSaveNodes() {
    const comfy = getComfy();
    if (!comfy) return;
    const box = panel.querySelector(".rhb-nodes");
    if (!box) return;
    const nodes = getOutputNodes(comfy.app);
    const sig = nodes.map((n) => n.id).sort().join(",");
    if (box.dataset.sig === sig && sig !== "") return; // 节点没变，不重建（保留用户勾选）
    if (!nodes.length) {
      box.innerHTML = `<div class="rhb-nodes-empty">没找到输出节点（SaveImage/VHS_VideoCombine 等）</div>`;
      box.dataset.sig = "";
      return;
    }
    box.dataset.sig = sig;
    // 优先用上次保存的勾选；没有才用默认
    const saved = (loadProgress() || {}).selected;
    const useSaved = Array.isArray(saved);
    state.selectedSaveNodeIds = new Set();
    box.innerHTML = "";
    nodes.forEach((n) => {
      const idStr = String(n.id);
      const def = isDefaultChecked(n);
      const checked = useSaved ? saved.map(String).includes(idStr) : def;
      const label = document.createElement("label");
      label.className = "rhb-node";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = idStr;
      cb.checked = checked;
      if (checked) state.selectedSaveNodeIds.add(idStr);
      cb.addEventListener("change", (e) => {
        if (e.target.checked) state.selectedSaveNodeIds.add(idStr);
        else state.selectedSaveNodeIds.delete(idStr);
        saveSettings();
      });
      label.appendChild(cb);
      label.appendChild(
        document.createTextNode(`#${n.id} ${n.title || n.type}${def ? " (默认✓)" : ""}`)
      );
      box.appendChild(label);
    });
    log(`检测到 ${nodes.length} 个输出节点（${useSaved ? "已恢复上次勾选" : "默认勾选保存类"}）`, "ok");
  }

  // 刷新后恢复上次选的目录（保存目录显示名字；图片/视频目录若仍有读权限则直接可用，否则给“恢复授权”按钮）
  async function restoreDirs() {
    try {
      const sh = await idbGet(dirKey("saveDir"));
      if (sh) {
        state.saveDirHandle = sh;
        const el = panel && panel.querySelector(".rhb-dirstat");
        if (el) el.textContent = "保存目录：" + sh.name;
      }
      const ih = await idbGet(dirKey("imageDir"));
      const vh = await idbGet(dirKey("videoDir"));
      let needGrant = false;
      if (ih) {
        state.imageDirHandle = ih;
        if ((await ih.queryPermission({ mode: "read" })) === "granted") {
          state.imageItems = await enumerateDir(ih, isImage);
        } else needGrant = true;
      }
      if (vh) {
        state.videoDirHandle = vh;
        if ((await vh.queryPermission({ mode: "read" })) === "granted") {
          state.videoItems = await enumerateDir(vh, isVideo);
        } else needGrant = true;
      }
      recomputePairs();
      setButtons();
      const active = (loadProgress() || {}).active;
      if (needGrant && !active) {
        const names = [ih && ih.name, vh && vh.name].filter(Boolean).join("、");
        showActionButton("🔓 恢复目录授权（" + names + "）", regrantDirs);
        log("上次的目录需要重新授权一次（浏览器安全限制）。点绿色按钮即可恢复，不必重选。", "info");
      }
    } catch (_) {}
  }

  async function regrantDirs() {
    try {
      if (state.imageDirHandle) {
        await state.imageDirHandle.requestPermission({ mode: "read" });
        state.imageItems = await enumerateDir(state.imageDirHandle, isImage);
      }
      if (state.videoDirHandle) {
        await state.videoDirHandle.requestPermission({ mode: "read" });
        state.videoItems = await enumerateDir(state.videoDirHandle, isVideo);
      }
      if (state.saveDirHandle) {
        await state.saveDirHandle.requestPermission({ mode: "readwrite" });
      }
      hideResumeUI();
      recomputePairs();
      setButtons();
      log("目录授权已恢复", "ok");
    } catch (e) {
      log("恢复授权失败：" + (e.message || e), "err");
    }
  }

  // kind: "image" | "video"  —— 用目录句柄，刷新后可恢复
  async function pickMediaFolder(kind) {
    if (!window.showDirectoryPicker) {
      log("浏览器不支持目录选择（需 Chrome/Edge 109+）", "err");
      return;
    }
    const cn = kind === "image" ? "图片" : "视频";
    try {
      const h = await window.showDirectoryPicker({ mode: "read" });
      const want = kind === "image" ? isImage : isVideo;
      const items = await enumerateDir(h, want);
      if (kind === "image") {
        state.imageDirHandle = h;
        state.imageItems = items;
        await idbSet(dirKey("imageDir"), h);
      } else {
        state.videoDirHandle = h;
        state.videoItems = items;
        await idbSet(dirKey("videoDir"), h);
      }
      log(`已选${cn}目录「${h.name}」：${items.length} 个文件`, items.length ? "ok" : "err");
      recomputePairs();
      saveProgress({ active: state.running });
    } catch (e) {
      if (e && e.name !== "AbortError") log(`选${cn}目录失败：${e.message}`, "err");
    }
  }

  function makeDraggable(el, handle) {
    let sx, sy, ox, oy, drag = false;
    handle.addEventListener("mousedown", (e) => {
      if (e.target.classList.contains("rhb-min")) return;
      drag = true;
      sx = e.clientX; sy = e.clientY;
      const r = el.getBoundingClientRect();
      ox = r.left; oy = r.top;
      e.preventDefault();
    });
    document.addEventListener("mousemove", (e) => {
      if (!drag) return;
      el.style.left = ox + (e.clientX - sx) + "px";
      el.style.top = oy + (e.clientY - sy) + "px";
      el.style.right = "auto";
    });
    document.addEventListener("mouseup", () => (drag = false));
  }

  function appendLog(line, type) {
    if (!logBox) return;
    const div = document.createElement("div");
    div.className = type;
    div.textContent = line;
    logBox.appendChild(div);
    logBox.scrollTop = logBox.scrollHeight;
    while (logBox.children.length > 300) logBox.removeChild(logBox.firstChild);
  }

  function updateProgress() {
    if (!progressBar) return;
    if (currentMode() === "image") {
      if (state.infinite) {
        progressBar.style.width = "100%";
        progressText.textContent = `已完成 ${state.index}（无限）`;
      } else {
        const total = Math.max(0, state.imageItems.length);
        const done = Math.min(state.index, total);
        progressBar.style.width = total ? Math.round((done / total) * 100) + "%" : "0%";
        progressText.textContent = `${done} / ${total}`;
      }
      return;
    }
    const total = state.pairs.length;
    const pct = total ? Math.round((Math.min(state.index, total) / total) * 100) : 0;
    progressBar.style.width = pct + "%";
    progressText.textContent = `${Math.min(state.index, total)} / ${total}`;
  }

  function setButtons() {
    if (!btnStart) return;
    const comfyOk = !!getComfy();
    const mode = currentMode();
    const hasWork = mode === "image" ? state.imageItems.length > 0 : state.pairs.length > 0;
    const busy = state.running && !state.paused;
    btnStart.disabled = !hasWork || !comfyOk || busy;
    btnStart.textContent = state.paused ? "继续" : "开始";
    btnPause.disabled = !state.running || state.paused;
    btnStop.disabled = !state.running && !state.paused;

    // 置灰原因提示
    let reason = "";
    if (busy) reason = "正在运行中…";
    else if (!comfyOk) reason = "等待 ComfyUI 画布加载完";
    else if (!hasWork) {
      reason =
        mode === "image"
          ? "请先点“📁 图片文件夹”选输入图片"
          : "视频换装模式：需要同时选好图片文件夹和视频文件夹";
    }
    btnStart.title = reason || "开始批量";
  }

  // ============================================================
  // 启动
  // ============================================================
  function init() {
    if (document.getElementById("rh-batch-panel")) return;
    // 先恢复上次保存的选项（按工作流），刷新后不回默认
    if (!state.randomSeed || state.randomSeed === 1) {
      state.randomSeed = (Date.now() & 0x7fffffff) || 1;
    }
    const restored = restoreSettings();
    if (!state.runMode) state.runMode = CONFIG.runMode || "";
    buildPanel();
    // 页面卸载前再存一次，避免输入没失焦导致 change 未触发
    window.addEventListener("pagehide", saveSettings);
    window.addEventListener("beforeunload", saveSettings);
    if (restored) {
      log(
        `已恢复上次选项：模式=${state.modeOverride}，从第${state.videoStart}个，取图=${state.imageMode}，无限=${state.infinite}，看门狗=${state.watchdogMin}分`,
        "ok"
      );
    }
    restoreDirs(); // 恢复上次选的目录（保存目录显示名字；图片/视频目录给恢复授权按钮）
    log("已加载 build-2026061201。等「ComfyUI：已连接 ✓」后开始。", "ok");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
