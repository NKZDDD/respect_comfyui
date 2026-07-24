import { app } from "/scripts/app.js";

// 给 RespectConcatVideos 节点加「更新输入口」按钮：
// 按 inputcount 的数字，动态增/减 video_1..video_N 输入槽（KJNodes 风格）
app.registerExtension({
    name: "Respect.ConcatVideosDynamic",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "RespectConcatVideos") {
            return;
        }

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            const node = this;

            const countVideoInputs = () =>
                (node.inputs || []).filter((i) => /^video_\d+$/.test(i.name)).length;

            const applyCount = (target) => {
                target = Math.max(1, Math.min(200, Math.round(target || 2)));
                let cur = countVideoInputs();
                while (cur < target) {
                    cur++;
                    node.addInput(`video_${cur}`, "STRING");
                }
                while (cur > target) {
                    const idx = (node.inputs || []).findIndex((i) => i.name === `video_${cur}`);
                    if (idx !== -1) {
                        node.removeInput(idx);
                    }
                    cur--;
                }
                node.setDirtyCanvas(true, true);
            };

            node.addWidget("button", "更新输入口", "update", () => {
                const w = (node.widgets || []).find((x) => x.name === "inputcount");
                applyCount(w ? w.value : 2);
            });
        };
    },
});
