import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

// 给 RespectLoadVideoPath 节点加「选择视频上传」按钮：
// 选本地视频 -> 上传到 ComfyUI 的 input/ -> 加入 video 下拉框并选中 -> 节点输出其绝对路径
app.registerExtension({
    name: "Respect.LoadVideoUpload",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "RespectLoadVideoPath") {
            return;
        }

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            const node = this;

            // 隐藏的文件选择框
            const fileInput = document.createElement("input");
            fileInput.type = "file";
            fileInput.accept = "video/*";
            fileInput.style.display = "none";
            document.body.appendChild(fileInput);

            fileInput.addEventListener("change", async () => {
                if (!fileInput.files || !fileInput.files.length) {
                    return;
                }
                const file = fileInput.files[0];
                const body = new FormData();
                body.append("image", file);       // ComfyUI /upload/image 用 image 字段（接受任意文件）
                body.append("type", "input");
                body.append("overwrite", "false");
                try {
                    const resp = await api.fetchApi("/upload/image", { method: "POST", body });
                    if (resp.status !== 200) {
                        alert("[Respect] 视频上传失败：HTTP " + resp.status);
                        return;
                    }
                    const data = await resp.json();
                    let name = data.name;
                    if (data.subfolder) {
                        name = data.subfolder + "/" + name;
                    }
                    const w = node.widgets?.find((x) => x.name === "video");
                    if (w) {
                        w.options = w.options || {};
                        w.options.values = w.options.values || [];
                        if (!w.options.values.includes(name)) {
                            w.options.values.push(name);
                        }
                        w.value = name;
                        w.callback?.(name);
                    }
                    app.graph.setDirtyCanvas(true, true);
                    console.log("[Respect] 视频已上传到 input/：" + name);
                } catch (e) {
                    console.error("[Respect] 视频上传出错：", e);
                    alert("[Respect] 视频上传出错：" + e);
                } finally {
                    fileInput.value = "";
                }
            });

            node.addWidget("button", "选择视频上传", "upload", () => fileInput.click());
        };
    },
});
