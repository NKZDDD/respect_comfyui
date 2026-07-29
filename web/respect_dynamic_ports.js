import { app } from "/scripts/app.js";

// 动态输入口：按 countWidget 的数字增/减 `<prefix><N>` 输入槽
// 以后要给别的节点加，只需在 TABLE 里加一行
const TABLE = {
    RespectOpenAIImage: {
        countWidget: "inputcount",
        prefix: "image_",
        type: "IMAGE",
        label: "更新输入口",
        fallback: 4,
        max: 64,
    },
};

app.registerExtension({
    name: "Respect.DynamicPorts",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const conf = TABLE[nodeData.name];
        if (!conf) {
            return;
        }

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            const node = this;
            const re = new RegExp(`^${conf.prefix}\\d+$`);

            const countPorts = () =>
                (node.inputs || []).filter((i) => re.test(i.name)).length;

            const applyCount = (target) => {
                target = Math.max(1, Math.min(conf.max, Math.round(target || conf.fallback)));
                let cur = countPorts();
                while (cur < target) {
                    cur++;
                    node.addInput(`${conf.prefix}${cur}`, conf.type);
                }
                while (cur > target) {
                    const idx = (node.inputs || []).findIndex((i) => i.name === `${conf.prefix}${cur}`);
                    if (idx !== -1) {
                        node.removeInput(idx);
                    }
                    cur--;
                }
                node.setDirtyCanvas(true, true);
            };

            node.addWidget("button", conf.label, "update", () => {
                const w = (node.widgets || []).find((x) => x.name === conf.countWidget);
                applyCount(w ? w.value : conf.fallback);
            });
        };
    },
});
