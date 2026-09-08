// 运行按钮档位选择的回归测试。
//
// 为什么需要它：RunningHub 的运行按钮结构是插件唯一「点下去就花钱」的地方，
// 2026-09 改版把「1 个按钮 + 模式下拉」换成了三个并排 .run-btn（Standard/Plus/Ultra），
// 旧逻辑 /^运行$/ 恰好命中最贵那档。这类回归不能靠肉眼看代码，必须拿真实 DOM 跑一遍。
//
// 用法：
//   1) 在工作流页面 Ctrl+S 存一份「网页，完整」或复制 <html> 的 outerHTML 存成 .html
//   2) npm install jsdom          （只需一次，装在本目录即可）
//   3) node run_button_test.js <那份 html 的路径>
//      不传路径则读环境变量 RH_FIXTURE，都没有就报错退出。
//
// 它加载的是真实的 ../content.js，只做两处 harness 级 stub（jsdom 的能力缺口，非业务逻辑）：
//   getBoundingClientRect 恒为 0 → 会让 isVisible() 判所有元素不可见，给个非零尺寸；
//   没有 indexedDB → restoreDirs() 会异步炸，塞个最小假实现让它安静失败。
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const fixture = process.argv[2] || process.env.RH_FIXTURE;
if (!fixture) {
  console.error("用法: node run_button_test.js <保存下来的工作流页面.html>（或设 RH_FIXTURE 环境变量）");
  process.exit(2);
}
const SRC = path.join(__dirname, "..", "content.js");

let code = fs.readFileSync(SRC, "utf8");
// 只为测试暴露内部函数：在 IIFE 结束前插一行（不改仓库里的文件）
const anchor = '  if (document.readyState === "loading") {';
if (!code.includes(anchor)) throw new Error("找不到插桩锚点，content.js 结构变了，请更新本测试");
code = code.replace(
  anchor,
  "  window.__test = { findRunButton, getRunTierButtons, normTier, state, diagnoseRunButtons };\n" + anchor
);

const dom = new JSDOM(fs.readFileSync(fixture, "utf8"), {
  runScripts: "outside-only",
  pretendToBeVisual: true,
});
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
process.on("unhandledRejection", () => {}); // restoreDirs 的异步失败，与本测试无关

win.eval(code);
const T = win.__test;
if (!T) throw new Error("content.js 里的 IIFE 没跑到插桩点");

let fail = 0;
const bevel = (b) => (b ? ((b.className || "").toString().match(/beveled-btn-\w+/) || ["?"])[0] : "null");
const check = (name, got, want) => {
  const ok = got === want;
  if (!ok) fail++;
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : `\n        got=${got} want=${want}`}`);
};

const tiers = T.getRunTierButtons();
console.log("=== 识别到的运行档位 ===");
for (const t of tiers) console.log(`  ${t.key.padEnd(9)} ${JSON.stringify(t.label).padEnd(18)} ${bevel(t.btn)}`);
if (tiers.length < 2) {
  console.log("\n(这份页面只有 0/1 个档位按钮 —— 旧版页面或改版后又变了，后面的断言跳过)");
  process.exit(tiers.length ? 0 : 1);
}

console.log("\n=== normTier() 归一化（含改版前存下的旧值） ===");
check('"Lite/Plus" → plus', T.normTier("Lite/Plus"), "plus");
check('"Lite/Standard" → standard', T.normTier("Lite/Standard"), "standard");
check('"Ultra·6000D" → ultra', T.normTier("Ultra·6000D"), "ultra");
check('"" → ""（自动，合法值）', T.normTier(""), "");
check('无法识别的值 → ""', T.normTier("垃圾值"), "");

console.log("\n=== findRunButton() 按档位挑 ===");
check("默认档位＝Lite/Standard（不是最贵的 Plus）", bevel(T.findRunButton()), "beveled-btn-right");
T.state.runMode = "plus";
check("选 plus → Lite/Plus", bevel(T.findRunButton()), "beveled-btn-left");
T.state.runMode = "ultra";
check("选 ultra → Ultra", bevel(T.findRunButton()), "beveled-btn-ultra");
T.state.runMode = "";
check("自动 → DOM 第一个（新版即最便宜的 Standard）", bevel(T.findRunButton()), "beveled-btn-right");

console.log("\n=== 钱的安全性：指定档位不可点时必须放弃，绝不改点别档 ===");
T.state.runMode = "standard";
const std = tiers.find((t) => t.key === "standard").btn;
std.disabled = true;
check("standard 被禁用 → null（等恢复/超时报错）", bevel(T.findRunButton()), "null");
T.state.runMode = "plus";
check("此时选 plus 仍点得到", bevel(T.findRunButton()), "beveled-btn-left");
std.disabled = false;

T.state.runMode = "standard";
console.log("\n=== 超时报错时的诊断文案 ===\n  " + T.diagnoseRunButtons());

console.log(fail ? `\n❌ ${fail} 条断言失败` : "\n✅ 全部断言通过");
process.exit(fail ? 1 : 0);
