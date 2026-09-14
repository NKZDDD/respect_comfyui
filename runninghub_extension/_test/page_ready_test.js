// 「页面未就绪 / 掉号」检测的回归测试。
//
// 为什么需要它：2026-09-08 实测到一次事故——账号掉号后页面外壳照常渲染，
// 但所有要登录态的接口都没返数据（运行按钮的档位标签 .plus-tags 全没了、
// Ultra 按钮不渲染、任务列表「暂无数据」）。插件当时毫无察觉，照样上传图片、
// 照样点运行，任务根本提交不出去，然后干等 20 分钟再静默跳过。
// 这道检查必须能分辨「正常页面」和「掉号页面」，否则那次事故会原样重演。
//
// 用法：
//   npm install jsdom                                  （只需一次）
//   node page_ready_test.js <正常页面.html> <掉号页面.html>
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const [good, bad] = process.argv.slice(2);
if (!good || !bad) {
  console.error("用法: node page_ready_test.js <正常页面.html> <掉号页面.html>");
  process.exit(2);
}

const SRC = path.join(__dirname, "..", "content.js");
let code = fs.readFileSync(SRC, "utf8");
const anchor = '  if (document.readyState === "loading") {';
if (!code.includes(anchor)) throw new Error("找不到插桩锚点，content.js 结构变了，请更新本测试");
code = code.replace(
  anchor,
  "  window.__test = { pageNotReadyReason, getRunTierButtons, findRunButton, state };\n" + anchor
);

function load(file) {
  const dom = new JSDOM(fs.readFileSync(file, "utf8"), { runScripts: "outside-only", pretendToBeVisual: true });
  const win = dom.window;
  win.Element.prototype.getBoundingClientRect = function () {
    const s = win.getComputedStyle(this);
    const hidden = s.display === "none" || s.visibility === "hidden";
    return { width: hidden ? 0 : 100, height: hidden ? 0 : 40, top: 0, left: 0, right: 100, bottom: 40 };
  };
  win.indexedDB = {
    open() {
      const req = {};
      setTimeout(() => req.onerror && req.onerror(new Error("no indexedDB in jsdom")), 0);
      return req;
    },
  };
  win.eval(code);
  if (!win.__test) throw new Error("content.js 里的 IIFE 没跑到插桩点：" + file);
  return win;
}
process.on("unhandledRejection", () => {});

let fail = 0;
const check = (name, cond, extra) => {
  if (!cond) fail++;
  console.log(`  ${cond ? "PASS" : "FAIL"}  ${name}${cond ? "" : "\n        " + (extra || "")}`);
};

const G = load(good).__test;
const B = load(bad).__test;

console.log("=== 正常页面 ===");
const gTiers = G.getRunTierButtons();
console.log(`  档位按钮 ${gTiers.length} 个：${gTiers.map((t) => t.label).join(" / ")}`);
console.log(`  pageNotReadyReason() = ${JSON.stringify(G.pageNotReadyReason())}`);
check("正常页面判定为就绪", G.pageNotReadyReason() === null, "误报会让插件在好页面上罢工");
check("正常页面认得出 3 个档位", gTiers.length === 3);

console.log("\n=== 掉号页面 ===");
const bTiers = B.getRunTierButtons();
console.log(`  档位按钮 ${bTiers.length} 个`);
console.log(`  .run-btn 共 ${B.state ? "" : ""}${bTiers.length}/${2} 带档位标签`);
console.log(`  pageNotReadyReason() = ${JSON.stringify(B.pageNotReadyReason())}`);
check("掉号页面被判定为未就绪", typeof B.pageNotReadyReason() === "string", "漏报＝事故原样重演：白传图、干等 20 分钟、静默跳过");
check("掉号页面认不出任何档位", bTiers.length === 0);

console.log("\n=== 事故复现：掉号页上旧逻辑会点哪个按钮 ===");
// 掉号页没有档位标签 → getRunTierButtons() 为空 → findRunButton() 回落旧逻辑
const picked = B.findRunButton();
const txt = picked ? (picked.textContent || "").trim() : "null";
console.log(`  findRunButton() → ${txt}（日志会打成「点击运行：「运行」」，与 2026-09-08 截图一致）`);
check("掉号页确实仍能挑出一个按钮（所以才会打空气）", !!picked, "");

console.log(fail ? `\n❌ ${fail} 条断言失败` : "\n✅ 全部断言通过");
process.exit(fail ? 1 : 0);
