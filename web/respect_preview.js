import { app } from "/scripts/app.js";

function buildViewUrl(ref) {
    const params = new URLSearchParams({
        filename: ref.filename || "",
        subfolder: ref.subfolder || "",
        type: ref.type || "output",
    });
    return `/view?${params.toString()}`;
}

app.registerExtension({
    name: "Respect.PreviewVideo",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "RespectPreviewVideo") {
            return;
        }

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);

            try {
                const videos = message?.videos || [];
                if (!videos.length) {
                    return;
                }

                // 复用或创建 video DOM widget
                if (!this.__respectVideoEl) {
                    const el = document.createElement("video");
                    el.controls = true;
                    el.loop = true;
                    el.muted = false;
                    el.playsInline = true;
                    el.style.width = "100%";
                    el.style.borderRadius = "6px";
                    el.style.background = "#000";

                    this.addDOMWidget("respect_video_preview", "video", el, {
                        serialize: false,
                        hideOnZoom: false,
                    });
                    this.__respectVideoEl = el;
                }

                const el = this.__respectVideoEl;
                el.src = buildViewUrl(videos[0]) + `&t=${Date.now()}`;
                el.load();

                // 给节点一个合理的初始高度
                if (this.size && this.size[1] < 260) {
                    this.setSize([Math.max(this.size[0], 320), 320]);
                }
                app.graph.setDirtyCanvas(true, true);
            } catch (e) {
                console.error("[Respect] 预览视频失败:", e);
            }
        };
    },
});
