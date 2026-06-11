/* ============================================================
 * RunningHub / ComfyUI 工作流节点导出片段（第 2 个）
 * 用途：把 iframe 里 ComfyUI 工作流的所有节点 + widget 导出，
 *      让作者知道哪个节点装图片、哪个装视频、widget 叫什么名字。
 *
 * 用法：在工作流页面按 F12 → Console，整段粘贴回车。
 *      结果会打印并自动复制到剪贴板，粘到 live_nodes.json 发给作者。
 * ============================================================ */
(() => {
  // 找到 ComfyUI 所在的 iframe（同源才能读取）
  let app = null;
  let ifrSrc = "";
  const ifrs = [...document.querySelectorAll("iframe")];
  for (const f of ifrs) {
    try {
      if (f.contentWindow && f.contentWindow.app && f.contentWindow.app.graph) {
        app = f.contentWindow.app;
        ifrSrc = f.src || "";
        break;
      }
    } catch (e) {
      /* 跨域，跳过 */
    }
  }
  // 也可能本页就是 ComfyUI（直接在 iframe 里跑控制台）
  if (!app && window.app && window.app.graph) {
    app = window.app;
    ifrSrc = location.href;
  }

  if (!app || !app.graph) {
    console.error(
      "%c没找到 ComfyUI 的 app。请确认：1) 在工作流页面；2) 画布已加载完；" +
        "3) 若仍不行，把控制台左上角的执行环境从 top 切到 comfyUI.html 再跑一次。",
      "color:#f87171;font-weight:bold"
    );
    return;
  }

  const nodes = (app.graph._nodes || []).map((n) => ({
    id: n.id,
    type: n.type,
    title: n.title || (n.constructor && n.constructor.title) || "",
    widgets: (n.widgets || []).map((w) => ({
      name: w.name,
      type: w.type,
      value:
        typeof w.value === "string" ? w.value.slice(0, 100) : w.value,
      // combo 下拉的可选项（比如已上传的文件名列表）
      options_values:
        w.options && Array.isArray(w.options.values)
          ? w.options.values.slice(0, 50)
          : undefined,
    })),
  }));

  const out = {
    url: location.href,
    comfyuiFrame: ifrSrc,
    nodeCount: nodes.length,
    nodes,
  };

  const json = JSON.stringify(out, null, 2);
  console.log(json);
  try {
    copy(json);
    console.log(
      "%c✅ 已复制到剪贴板，粘到 live_nodes.json 发给作者",
      "color:#22c55e;font-weight:bold"
    );
  } catch (e) {
    console.log("自动复制失败，请手动选中上面的 JSON 复制");
  }
  return out;
})();
