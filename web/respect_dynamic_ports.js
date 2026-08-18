import { app } from "/scripts/app.js";

// 动态输入口：按 countWidget 的数字增/减 `<prefix><N>` 输入槽
// 以后要给别的节点加，只需在 TABLE 里加一行
const IMAGE_PORTS = {
    countWidget: "inputcount",
    prefix: "image_",
    type: "IMAGE",
    label: "更新输入口",
    fallback: 4,
    max: 64,
};

// 只收公网 URL 的接口：动态增减 ref_url_N（接「对象存储上传」的 url 输出）
const URL_PORTS = {
    countWidget: "inputcount",
    prefix: "ref_url_",
    type: "STRING",
    label: "更新输入口",
    fallback: 4,
    max: 30,
};

const TABLE = {
    RespectOpenAIImage: IMAGE_PORTS,     // image2 文生图/图生图
    RespectOctopusImage: IMAGE_PORTS,    // 章鱼哥 异步图片
    RespectLingganyaImage: IMAGE_PORTS,  // 灵感鸭 统一图片
    RespectZeroImage: IMAGE_PORTS,       // 零视工坊 图片
    RespectHeVideo: IMAGE_PORTS,         // 鹤 视频（参考图）
    RespectHeImageEdit: IMAGE_PORTS,     // 鹤 图生图/多图融合（≤16）
    RespectKunjiImage: IMAGE_PORTS,      // 坤鸡 图片
    RespectZeroSD2: IMAGE_PORTS,         // 零视工坊 SD2（IMAGE 槽保留，但按文档只发 ref_url_*）
    RespectM86Video: IMAGE_PORTS,        // M86 seed-2.0（本地图走 multipart）
    RespectHeSeedance25: URL_PORTS,      // 鹤 Seedance 2.5（只收公网URL，≤30张）
    RespectYishouVideo: URL_PORTS,       // 一手 ONE API（只收公网HTTPS）
    RespectAkeVideo: URL_PORTS,          // 阿珂 snumom（reference_images 走URL；≤7）
    RespectChaomoVideo: URL_PORTS,       // 超模（content 块只收公网URL；≤9）
    RespectChaomoImageEdit: IMAGE_PORTS, // 超模 图生图（multipart image[]；≤9）
    RespectXiaobalongVideo: URL_PORTS,   // 小霸龙（HTTPS 或 asset:// URI；≤9）
    RespectXiaobalongImage: URL_PORTS,   // 小霸龙 图片（reference_images 只收URL；≤9）
    RespectXPSd25: IMAGE_PORTS,          // 小裴 SD2.5 不卡脸（图≤30）
    RespectXPSd900: IMAGE_PORTS,         // 小裴 900 不售后（只多参考，≤9）
};

// 自动识别：节点只要有 inputcount 组件 + image_1 或 ref_url_1 输入，就自动装按钮。
// 这样以后新加节点不用再回来改这张表 —— 漏注册过好几次了，表只留给要改上限的特例。
function detectConf(nodeData) {
    const named = TABLE[nodeData.name];
    if (named) {
        return named;
    }
    const spec = nodeData?.input || {};
    const keys = [...Object.keys(spec.required || {}), ...Object.keys(spec.optional || {})];
    if (!keys.includes("inputcount")) {
        return null;
    }
    // 同时有两种口时以 ref_url_ 为准：那类接口只收公网 URL，IMAGE 槽是给能吃图片内容的
    if (keys.some((k) => /^ref_url_\d+$/.test(k))) {
        return URL_PORTS;
    }
    if (keys.some((k) => /^image_\d+$/.test(k))) {
        return IMAGE_PORTS;
    }
    return null;
}

app.registerExtension({
    name: "Respect.DynamicPorts",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const conf = detectConf(nodeData);
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
