import { app } from "/scripts/app.js";

// 给 RespectShowText 节点在执行后把文字显示在节点上（只读多行框）
app.registerExtension({
    name: "Respect.ShowText",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "RespectShowText") {
            return;
        }

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);

            try {
                let texts = message?.text ?? [];
                if (!Array.isArray(texts)) {
                    texts = [texts];
                }
                const content = texts.join("\n");

                if (!this.__respectTextEl) {
                    const el = document.createElement("textarea");
                    el.readOnly = true;
                    el.style.width = "100%";
                    el.style.height = "100%";
                    el.style.minHeight = "80px";
                    el.style.resize = "none";
                    el.style.border = "none";
                    el.style.borderRadius = "6px";
                    el.style.padding = "6px";
                    el.style.background = "#181818";
                    el.style.color = "#e6e6e6";
                    el.style.fontSize = "12px";
                    el.style.lineHeight = "1.5";
                    el.style.whiteSpace = "pre-wrap";
                    el.style.overflowY = "auto";

                    this.addDOMWidget("respect_show_text", "text", el, {
                        serialize: false,
                        hideOnZoom: false,
                    });
                    this.__respectTextEl = el;
                }

                this.__respectTextEl.value = content;

                if (this.size && this.size[1] < 140) {
                    this.setSize([Math.max(this.size[0], 300), 180]);
                }
                app.graph.setDirtyCanvas(true, true);
            } catch (e) {
                console.error("[Respect] 显示文字失败:", e);
            }
        };
    },
});
