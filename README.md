# 小裴 ComfyUI 扩展（Xiaopei ComfyUI）

把 `https://api.aicopy.top` 中转 API 封装成 ComfyUI 节点，参考 [Comfyui-zhenzhen](https://github.com/T8mars/Comfyui-zhenzhen) 的形态。
覆盖：

- **图片**：文生图、单图参考、多图参考、GPT 本地版/应急通道、多模态对话兜底
- **视频**：Firefly Sora2、Firefly VEO3.1、Firefly Runway 4.5、即梦 SD2（含异步轮询、首尾帧、多参考图）

接口规范来自 `小裴api图片接口文档.md` 与 `小裴视频文档.md`。

---

## 1. 安装

把整个 `xiaopei_comfyui` 目录复制到 ComfyUI 的 `custom_nodes` 下：

```text
ComfyUI/
└── custom_nodes/
    └── xiaopei_comfyui/
        ├── __init__.py
        ├── api_settings.py
        ├── image_nodes.py
        ├── video_nodes.py
        ├── utils.py
        ├── requirements.txt
        ├── pyproject.toml
        └── README.md
```

安装依赖（如 ComfyUI 自带的 Python 环境已经有 `requests`/`Pillow`/`numpy` 可以跳过）：

```bash
pip install -r requirements.txt
```

重启 ComfyUI，节点会出现在分类 `小裴/Xiaopei` 下。

## 2. 鉴权

所有节点都需要先连接一个 **小裴 API 设置** 节点，得到 `XIAOPEI_CONFIG`：

- `api_key`：Bearer Token。留空时自动读取环境变量 `XIAOPEI_API_KEY` 或 `AICOPY_API_KEY`。
- `base_url`：默认 `https://api.aicopy.top`，会自动补 `/v1`。
- `timeout`：默认 600 秒（图片）。视频节点内部会再放宽。
- `proxy`：可选，形如 `http://127.0.0.1:7890`。

> 不要把 API Key 写到工作流里然后分享，建议改成环境变量。

## 3. 节点一览

| 节点 | 接口 | 说明 |
|---|---|---|
| 小裴 API 设置 | — | 输出 `XIAOPEI_CONFIG`，所有节点的入口 |
| 小裴 加载模型列表 | `GET /v1/models` | 拉取并按关键字过滤模型 ID |
| 小裴 图片生成 | `POST /v1/images/generations` | 文生图 / 单图参考，支持家族自动拼接 |
| 小裴 多参考图编辑 | `POST /v1/responses` | 最多 7 张参考图 |
| 小裴 GPT本地版生图 | `POST /v1/responses` → `/images/generations` | 应急通道，自动降级 |
| 小裴 多模态对话生图 | `POST /v1/chat/completions` (stream) | firefly-nano-banana 等的兜底通道 |
| 小裴 Firefly Sora2 视频 | `POST /v1/chat/completions` (stream) | 4/8/12 秒，可切 Pro |
| 小裴 Firefly VEO3.1 视频 | `POST /v1/chat/completions` (stream) | 4/6/8 秒，720p/1080p，default/fast/ref |
| 小裴 Firefly Runway 4.5 视频 | `POST /v1/chat/completions` (stream) | 5/10 秒，多比例 |
| 小裴 即梦/SD2 视频 | `POST /v1/videos` + 轮询 `/v1/videos/{id}` | 异步，支持首尾帧 / 多参考图 |
| 小裴 保存视频 | — | 把任意视频 URL 下载到 `output/xiaopei/` |

## 4. 模型 ID 速查

### 图片家族（节点内自动拼接）

| 家族 | 拼接规则 | 示例 |
|---|---|---|
| `firefly-nano-banana` | `firefly-nano-banana-{1k\|2k\|4k}-{1x1\|16x9\|...}` | `firefly-nano-banana-1k-1x1` |
| `firefly-nano-banana-pro` | `firefly-nano-banana-pro-{...}` | `firefly-nano-banana-pro-2k-16x9` |
| `firefly-nano-banana2` | `firefly-nano-banana2-{...}` | `firefly-nano-banana2-4k-9x16` |
| `gpt-image-1` | `firefly-gpt-image-{...}` | `firefly-gpt-image-1k-1x1` |
| `grok-imagine-1.0` | 直接传 | `grok-imagine-1.0` / `grok-imagine-1.0-edit` |

模型 ID 已经包含 `1k/2k/4k` 或 `1024x1024` 时，节点不会再加 `size` 字段。

### 视频家族（节点内自动拼接）

| 家族 | 模板 | 可选参数 |
|---|---|---|
| Sora2 | `firefly-sora2[-pro]-{秒}s-{比例x}` | 秒 4/8/12，比例 16x9 9x16 |
| VEO3.1 | `firefly-veo31[-fast\|-ref]-{秒}s-{比例x}-{清晰度}` | 秒 4/6/8，720p/1080p |
| Runway 4.5 | `firefly-runway45-{秒}s-{比例x}-720p` | 秒 5/10，多比例 |
| 即梦 SD2 | `sd2-720p[-fast]` / `sd2-1080p[-fast]` / `sd2-720p-min[-fast]` | 4-15 秒，min 模型 ≥5 秒 |

## 5. 工作流示例

### 文生图

```text
小裴 API 设置  →  小裴 图片生成  →  PreviewImage
```

参数：`model_family = firefly-nano-banana`，`aspect_ratio = 16:9`，`resolution = 1k`，写好 `prompt`。

### 图生图（单参考）

把上一步 `LoadImage` 连到 **小裴 图片生成** 的 `reference_image` 输入端，模型选 `grok-imagine-1.0-edit` 或带 `-edit` 的模型。

### 多图参考编辑

用 **小裴 多参考图编辑**：把多个 `LoadImage` 节点接到 `image_1 ... image_7`，模型可以填 `GPT本地版` 或任意支持 `/responses` 的模型。

### Firefly VEO3.1 图生视频

```text
小裴 API 设置  →  小裴 Firefly VEO3.1 视频
LoadImage      →  first_frame
                ↓
              video_url, local_path（自动下载到 output/xiaopei/）
```

### 即梦 SD2 首尾帧

```text
小裴 API 设置  →  小裴 即梦/SD2 视频
LoadImage(首) →  ref_image_1
LoadImage(尾) →  ref_image_2
model = sd2-720p, aspect_ratio = 16:9, duration = 5
```

## 6. 视频后处理

- 节点输出 `video_url`（远端地址）+ `local_path`（自动下载后的本地 mp4 路径）。
- 本地 mp4 默认保存在 `ComfyUI/output/xiaopei/`。
- 想把视频送进 `VideoHelperSuite` 等节点，可把 `local_path` 接到 `VHS_LoadVideo` 的文件名输入。
- 如果想跳过自动下载，把 `auto_download` 关掉，再用 **小裴 保存视频** 节点单独下载。

## 7. 常见问题

- **节点没出现**：确认目录名是 `xiaopei_comfyui` 并放在 `custom_nodes` 下；查看 ComfyUI 启动日志有没有报 import 错误。
- **报 401 / 鉴权失败**：API Key 没填或者 Token 已过期；本地直接 `curl https://api.aicopy.top/v1/models -H "Authorization: Bearer ..."` 测一下。
- **图片返回 base64 但没显示**：节点会优先识别 `b64_json` / `data:image` 并直接转 tensor；如果失败可以把响应日志贴出来。
- **SD2 任务一直 processing**：轮询超时默认 1800 秒；可以在节点里调大 `poll_timeout`，或者改 `poll_interval` 减少压力。
- **视频地址有时效性**：开启 `auto_download` 会立刻下载到本地，避免链接过期。

## 8. 许可证

Apache-2.0。仅服务于学习与个人创作，请遵守上游 `api.aicopy.top` 的使用条款。
