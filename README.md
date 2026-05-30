# Respect ComfyUI 扩展

把 `https://api.aicopy.top` 中转 API 封装成 ComfyUI 节点，并附带一组基础工具节点。
所有节点都在 ComfyUI 的 **`Respect`** 分类下。

覆盖能力：

- **图片**：文生图、单图参考、多图参考、GPT 本地版/应急通道、多模态对话兜底
- **视频**：Firefly Sora2、Firefly VEO3.1、Firefly Runway 4.5、即梦 SD2（异步轮询、首尾帧、多参考图）
- **基础**：ZIP 批量加载图片 / 视频，支持递增 / 递减 / 随机 / 固定取样

> 本项目仅用于学习与个人创作，请遵守上游 `api.aicopy.top` 的使用条款。不写入任何明文密钥。

---

## 目录

- [安装](#安装)
- [鉴权配置](#鉴权配置)
- [节点总览](#节点总览)
- [基础加载节点](#基础加载节点)
- [图片节点](#图片节点)
- [视频节点](#视频节点)
- [模型 ID 速查](#模型-id-速查)
- [工作流示例](#工作流示例)
- [常见问题](#常见问题)
- [开源与贡献](#开源与贡献)
- [许可证](#许可证)

## 安装

### 方式一：手动安装

把整个目录复制到 ComfyUI 的 `custom_nodes` 下（目录名随意，建议 `respect_comfyui`）：

```text
ComfyUI/
└── custom_nodes/
    └── respect_comfyui/
        ├── __init__.py
        ├── api_settings.py
        ├── image_nodes.py
        ├── video_nodes.py
        ├── loader_nodes.py
        ├── utils.py
        ├── requirements.txt
        ├── pyproject.toml
        ├── LICENSE
        └── README.md
```

安装依赖（秋叶 / 便携版务必用内置 Python）：

```bash
# 通用
pip install -r requirements.txt

# 秋叶整合包（在整合包根目录执行）
.\python_embeded\python.exe -m pip install -r .\ComfyUI\custom_nodes\respect_comfyui\requirements.txt
```

重启 ComfyUI，节点出现在分类 `Respect` 下。

### 方式二：git clone

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/NKZDDD/respect_comfyui.git
pip install -r respect_comfyui/requirements.txt
```

## 鉴权配置

所有 API 节点都需要先连接一个 **Respect API 设置** 节点，得到 `RESPECT_CONFIG`：

| 参数 | 说明 |
|---|---|
| `api_key` | Bearer Token。留空时自动读环境变量 `RESPECT_API_KEY` 或 `AICOPY_API_KEY` |
| `base_url` | 默认 `https://api.aicopy.top`，会自动补 `/v1` |
| `timeout` | 默认 600 秒（图片）；视频节点内部会进一步放宽 |
| `proxy` | 可选，如 `http://127.0.0.1:7890`，国内访问海外通常需要 |

> 强烈建议把 Key 放到环境变量，不要写进工作流再分享出去。

设置环境变量（Windows PowerShell，永久）：

```powershell
[Environment]::SetEnvironmentVariable("RESPECT_API_KEY", "你的Key", "User")
```

## 节点总览

| 节点 | 显示名 | 接口 / 功能 |
|---|---|---|
| `RespectApiSettings` | Respect API 设置 | 输出 `RESPECT_CONFIG`，所有 API 节点入口 |
| `RespectLoadModels` | Respect 加载模型列表 | `GET /v1/models`，按关键字过滤 |
| `RespectImageGenerate` | Respect 图片生成 | `POST /v1/images/generations` |
| `RespectImageMultiRef` | Respect 多参考图编辑 | `POST /v1/responses`，最多 7 张 |
| `RespectGPTLocalImage` | Respect GPT本地版生图 | `/responses` → 失败降级 `/images/generations` |
| `RespectImageChat` | Respect 多模态对话生图 | `POST /v1/chat/completions` (stream) |
| `RespectFireflySora2` | Respect Firefly Sora2 视频 | chat stream，4/8/12 秒 |
| `RespectFireflyVeo31` | Respect Firefly VEO3.1 视频 | chat stream，4/6/8 秒，720p/1080p |
| `RespectFireflyRunway45` | Respect Firefly Runway 4.5 视频 | chat stream，5/10 秒 |
| `RespectSD2Video` | Respect 即梦/SD2 视频 | `POST /v1/videos` + 轮询，异步 |
| `RespectSaveVideo` | Respect 保存视频 | 下载视频 URL 到本地 |
| `RespectLoadImagesFromZip` | Respect ZIP批量加载图片 | 从 ZIP 按批次取 IMAGE |
| `RespectLoadVideosFromZip` | Respect ZIP批量加载视频 | 从 ZIP 按批次取视频 |

## 基础加载节点

### Respect ZIP批量加载图片 / 视频

把素材打包成 `.zip` 放到 `ComfyUI/input/` 目录，节点 `zip_file` 下拉里选；或在 `zip_path` 填绝对路径（优先）。

公共参数：

| 参数 | 取值 | 说明 |
|---|---|---|
| `batch_size` | 1~256 | 一次输出几张图 / 几个视频 |
| `mode` | `increment` / `decrement` / `random` / `fixed` | 取样模式 |
| `index` | 整数 | 起点位置（0 开始），fixed/increment/decrement 使用 |
| `seed` | 整数 | random 的随机种子；0=每次不同，非 0=可复现 |
| `sort` | `natural` / `name` / `name_desc` / `none` | 文件排序方式，`natural` 能正确处理 `img2 < img10` |
| `recursive` | 开/关 | 是否包含 ZIP 内子目录的文件 |
| `zip_path` | 字符串 | 可选，绝对/相对路径，填了优先 |
| `extract_dir` | 字符串 | 仅视频节点：解压目录，留空=`output/respect_zip` |

取样模式行为（假设 5 个文件，`batch_size=2`）：

| 模式 | 第1次 | 第2次 | 第3次 | 用途 |
|---|---|---|---|---|
| `fixed` | `[0,1]` | `[0,1]` | `[0,1]` | 反复调同一组 |
| `increment` | `[0,1]` | `[2,3]` | `[4,0]` | 逐批遍历整个 ZIP，自动回绕 |
| `decrement` | `[0,4]` | `[3,2]` | `[1,0]` | 倒序遍历 |
| `random` | 随机 | 随机 | 随机 | 每次随机抽 |

`batch_size` 大于文件总数时自动返回全部。

**输出**：

- 图片节点：`images` (IMAGE 批次) / `filenames`（换行分隔）/ `count`
- 视频节点：`video_paths`（换行分隔的本地绝对路径）/ `first_video` / `count`；
  若 ComfyUI 版本支持 VIDEO 类型，额外输出 `video` 端口，可直接接 SaveVideo / 预览。

> 视频解压到本地是因为 ComfyUI 视频处理需要真实文件路径。`first_video` 可直接接
> [VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) 的 `VHS_LoadVideoPath`。

## 图片节点

### Respect 图片生成

走 `/v1/images/generations`。选 `model_family` 自动拼模型 ID，或选 `自定义/custom` 后填 `custom_model`。
传入单张 `reference_image` 时会附加到 `image` 字段（Grok 风格通道用）。

模型 ID 已含 `1k/2k/4k` 或 `1024x1024` 时不会再加 `size`。

### Respect 多参考图编辑

走 `/v1/responses`，`image_1` ~ `image_7` 最多 7 张参考图，`model` 可填 `GPT本地版` 或任意支持 `/responses` 的模型。

### Respect GPT本地版生图

`GPT本地版` 开头的模型优先 `/responses`，失败自动降级 `/images/generations`；其他应急模型直接走 `/images/generations`。

### Respect 多模态对话生图

走 `/v1/chat/completions`（流式），从返回文本里解析图片 URL / base64，适合 firefly-nano-banana 等通过 chat 返回的模型。

## 视频节点

所有视频节点都支持 `custom_model`（填了优先）、`save_dir`、`filename` 三个可选参数：

- `save_dir`：留空=`output/respect`；相对路径基于 output；支持绝对路径。
- `filename`：留空=`<前缀>_<时间戳>_<6位hash>.mp4`；填了没扩展名自动补 `.mp4`；支持子目录。
- `auto_download`：默认开，拿到 URL 立刻下载本地（远端链接有时效）。

| 节点 | 模型模板 | 可选参数 |
|---|---|---|
| Sora2 | `firefly-sora2[-pro]-{秒}s-{比例x}` | 秒 4/8/12，比例 16:9 / 9:16 |
| VEO3.1 | `firefly-veo31[-fast\|-ref]-{秒}s-{比例x}-{清晰度}` | 秒 4/6/8，720p/1080p，default/fast/ref |
| Runway 4.5 | `firefly-runway45-{秒}s-{比例x}-720p` | 秒 5/10，多比例 |
| 即梦 SD2 | `sd2-720p[-fast]` / `sd2-1080p[-fast]` / `sd2-720p-min[-fast]` | 4-15 秒，min 模型≥5 秒，支持首尾帧/多参考图 |

输出统一为 `video_url`（远端）+ `local_path`（本地）+ `model_used` / `task_id`。

## 模型 ID 速查

### 图片家族（节点内自动拼接）

| 家族 | 拼接规则 | 示例 |
|---|---|---|
| `firefly-nano-banana` | `firefly-nano-banana-{1k\|2k\|4k}-{1x1\|16x9\|...}` | `firefly-nano-banana-1k-1x1` |
| `firefly-nano-banana-pro` | `firefly-nano-banana-pro-{...}` | `firefly-nano-banana-pro-2k-16x9` |
| `firefly-nano-banana2` | `firefly-nano-banana2-{...}` | `firefly-nano-banana2-4k-9x16` |
| `gpt-image-1` | `firefly-gpt-image-{...}` | `firefly-gpt-image-1k-1x1` |
| `grok-imagine-1.0` | 直接传 | `grok-imagine-1.0` / `grok-imagine-1.0-edit` |

不确定账号有哪些模型时，先跑 **Respect 加载模型列表** 看 `/v1/models` 返回，再把 ID 填到对应节点的 `custom_model`。

## 工作流示例

### 文生图

```text
Respect API 设置  →  Respect 图片生成  →  PreviewImage
```

### 批量参考图 → 批量出视频

```text
Respect ZIP批量加载图片 (mode=increment, batch=1)
        │ images
        ▼
Respect Firefly VEO3.1 视频 (first_frame)
        │ local_path
        ▼
（每次 Queue 自动换下一张参考图，遍历整个 ZIP）
```

### 即梦 SD2 首尾帧

```text
Respect API 设置  →  Respect 即梦/SD2 视频
LoadImage(首) →  ref_image_1
LoadImage(尾) →  ref_image_2
model = sd2-720p, aspect_ratio = 16:9, duration = 5
```

## 常见问题

- **节点没出现**：确认目录在 `custom_nodes` 下，启动日志里搜 `Respect` / `ImportError`，多半是依赖没装到 ComfyUI 用的那个 Python。
- **报 401 / 鉴权失败**：API Key 没填或过期；`curl https://api.aicopy.top/v1/models -H "Authorization: Bearer ..."` 测一下。
- **报 503 全部渠道不可提供当前模型**：上游暂时没渠道，不是本地问题，换模型或稍后重试（节点已内置 3 次重试）。
- **图片下载 400 Bad Request**：已修复——S3 预签名 URL 不再附加 Authorization 头。
- **中文错误乱码**：已修复——强制按 UTF-8 解析错误响应。
- **网络 / 443 错误**：海外接口，国内通常需要代理，在 API 设置节点填 `proxy`。
- **SD2 任务一直 processing**：异步任务，调大节点 `poll_timeout`（默认 1800 秒）。
- **视频链接失效**：保持 `auto_download=True`，立即下载到本地。

## 开源与贡献

- 代码结构：
  - `utils.py`：HTTP 客户端（重试 / UTF-8 / 代理）、tensor↔base64↔URL 转换、SSE 解析、文件下载、尺寸表
  - `api_settings.py`：配置与模型列表
  - `image_nodes.py` / `video_nodes.py`：图片 / 视频生成
  - `loader_nodes.py`：ZIP 批量加载基础节点
- 内部节点 ID 统一为 `Respect*`，配置类型为 `RESPECT_CONFIG`。
- 欢迎 issue / PR。提交前请确保 `python -m py_compile *.py` 通过。
- 发布到 ComfyUI Registry：`pyproject.toml` 已含 `[tool.comfy]` 字段，配合 `comfy-cli` 即可发布。

## 许可证

[Apache-2.0](./LICENSE)。
