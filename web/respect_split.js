import { app } from "/scripts/app.js";

// 给 RespectSplitSegments 节点加「更新输出口」按钮：
// 按 outputcount 的数字，动态增/减 seg_1..seg_N 输出槽（对齐视频拼接的 inputcount 设计）
// 布局固定为：seg_1..seg_N, count, all_json
app.registerExtension({
    name: "Respect.SplitSegmentsDynamic",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "RespectSplitSegments") {
            return;
        }

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            const node = this;

            const countSegOutputs = () =>
                (node.outputs || []).filter((o) => /^seg_\d+$/.test(o.name)).length;

            const snapshotTailLinks = () => {
                const outs = node.outputs || [];
                const snap = {};
                for (const name of ["count", "all_json"]) {
                    const idx = outs.findIndex((o) => o.name === name);
                    if (idx === -1) {
                        snap[name] = [];
                        continue;
                    }
                    const links = outs[idx].links || [];
                    snap[name] = links
                        .map((linkId) => {
                            const link = app.graph.links[linkId];
                            return link
                                ? { targetId: link.target_id, targetSlot: link.target_slot }
                                : null;
                        })
                        .filter(Boolean);
                }
                return snap;
            };

            const restoreTailLinks = (snap) => {
                const outs = node.outputs || [];
                for (const name of ["count", "all_json"]) {
                    const idx = outs.findIndex((o) => o.name === name);
                    if (idx === -1) continue;
                    for (const c of snap[name] || []) {
                        const target = app.graph.getNodeById(c.targetId);
                        if (target) {
                            node.connect(idx, target, c.targetSlot);
                        }
                    }
                }
            };

            const stripTail = () => {
                while (node.outputs?.length) {
                    const last = node.outputs[node.outputs.length - 1];
                    if (last.name === "count" || last.name === "all_json") {
                        node.removeOutput(node.outputs.length - 1);
                    } else {
                        break;
                    }
                }
            };

            const ensureTail = () => {
                const outs = node.outputs || [];
                if (!outs.some((o) => o.name === "count")) {
                    node.addOutput("count", "INT");
                }
                if (!outs.some((o) => o.name === "all_json")) {
                    node.addOutput("all_json", "STRING");
                }
            };

            const applyCount = (target) => {
                target = Math.max(1, Math.min(200, Math.round(target || 8)));
                const snap = snapshotTailLinks();
                stripTail();

                let cur = countSegOutputs();
                while (cur < target) {
                    cur++;
                    node.addOutput(`seg_${cur}`, "STRING");
                }
                while (cur > target) {
                    const idx = (node.outputs || []).findIndex((o) => o.name === `seg_${cur}`);
                    if (idx !== -1) {
                        node.removeOutput(idx);
                    }
                    cur--;
                }

                ensureTail();
                restoreTailLinks(snap);
                node.setDirtyCanvas(true, true);
            };

            node.addWidget("button", "更新输出口", "update", () => {
                const w = (node.widgets || []).find((x) => x.name === "outputcount");
                applyCount(w ? w.value : 8);
            });
        };
    },
});
