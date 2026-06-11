/* ============================================================
 * RunningHub 页面结构导出片段
 * 用法：登录后打开工作流页（让上传控件 + 运行按钮都显示出来），
 *      按 F12 → Console，把本文件整段粘贴回车。
 *      结果会打印并自动复制到剪贴板，粘到 live_dom.json 发给作者。
 * ============================================================ */
(() => {
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
  };

  // 收集一个 document 里的控件信息
  const scan = (doc, where) => {
    const fileInputs = [...doc.querySelectorAll('input[type="file"]')].map((i) => ({
      where,
      accept: i.accept || "",
      name: i.name || "",
      multiple: i.multiple,
      className: i.className || "",
      parentClass: i.parentElement ? i.parentElement.className : "",
      visible: vis(i),
    }));

    const buttons = [...doc.querySelectorAll('button, [role="button"], .ant-btn, a')]
      .map((b) => ({
        where,
        text: (b.innerText || b.textContent || "").trim().slice(0, 30),
        tag: b.tagName.toLowerCase(),
        className: (b.className || "").toString().slice(0, 120),
        disabled: !!b.disabled || b.getAttribute("aria-disabled") === "true",
        visible: vis(b),
      }))
      .filter((b) => b.text && b.text.length <= 20);

    return { fileInputs, buttons };
  };

  const result = {
    url: location.href,
    title: document.title,
    top: scan(document, "top"),
    iframes: [],
  };

  // 同源 iframe 也扫一遍（ComfyUI 常嵌在 iframe）
  [...document.querySelectorAll("iframe")].forEach((f, idx) => {
    let inner = null;
    try {
      const d = f.contentDocument;
      if (d) inner = scan(d, `iframe[${idx}]`);
    } catch (e) {
      inner = { error: "跨域无法读取: " + (e.message || e) };
    }
    result.iframes.push({ index: idx, src: f.src || "", inner });
  });

  const json = JSON.stringify(result, null, 2);
  console.log(json);
  try {
    copy(json);
    console.log("%c✅ 已复制到剪贴板，粘到 live_dom.json 发给作者", "color:#22c55e;font-weight:bold");
  } catch (e) {
    console.log("自动复制失败，请手动选中上面的 JSON 复制");
  }
  return result;
})();
