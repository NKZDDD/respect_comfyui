# Respect ComfyUI 扩展

把**多个中转 / 直连 API 网关**封装成 ComfyUI 节点（小裴 aicopy、一花 Codex、坤鸡、章鱼哥、零视工坊、灵感鸭），
并附带一整套文本 / PDF / 剪辑 / 分镜流水线工具节点。共 **61 个节点**。

节点按网关分在 **`Respect/小裴`**、`Respect/坤鸡`、`Respect/章鱼哥`、`Respect/零视工坊`、`Respect/灵感鸭`、`Respect/鹤`
子分类下；通用工具（配置、文本、剪辑、上传、预览）留在 **`Respect`** 根分类，分镜在 `Respect/分镜`、LLM 在 `Respect/LLM`。
**显示名都带网关名**（如「Respect 小裴 SD2.0 全系列视频」），一眼能看出属于谁。

覆盖能力：

- **图片**：文生图、单图/多图参考、image2（含 4K）、GPT 本地版、多模态对话兜底、章鱼哥/灵感鸭异步图片
- **视频**：Firefly Sora2 / VEO3.1 / Runway4.5 / 可灵3.0、Sora V3、即梦 SD2、Seedance 全系（含九图）、
  Grok（小裴 / 坤鸡 双分支）、快乐马、低价多渠道、章鱼哥、零视工坊 Sora2/VEO + 图生视频、灵感鸭统一视频
- **LLM**：Chat(OpenAI) / Responses(Codex) / Claude(Anthropic)，都带 `response_format` + `json_schema`
- **文本**：分段提取（动态输出口）、取第N段、文字输入 / 合并 / 显示、提取镜头秒数
- **素材**：PDF 批量转文字、关键词取素材（角色库）、ZIP 批量加载图片/视频
- **剪辑**：帧选择裁剪、mp4 裁剪、视频拼接（动态输入口）、加 BGM
- **流水线**：分镜存储 / 取任务 / 完成归档（文件系统队列，可断点续跑）
- **上传**：对象存储上传（R2 / OSS / COS / S3 / MinIO）、选择/上传本地视频

> 本项目仅用于学习与个人创作，请遵守各上游网关的使用条款。不写入任何明文密钥。

---

## 目录

- [安装](#安装)
- [鉴权配置](#鉴权配置)
- [网关对照表](#网关对照表)
- [节点总览](#节点总览)
- [基础加载节点](#基础加载节点)
- [图片节点](#图片节点)
- [视频节点](#视频节点)
- [多网关视频节点](#多网关视频节点)
- [LLM 对话节点](#llm-对话节点)
- [文本工具节点](#文本工具节点)
- [PDF 与素材节点](#pdf-与素材节点)
- [视频剪辑节点](#视频剪辑节点)
- [分镜流水线节点](#分镜流水线节点)
- [对象存储上传](#对象存储上传)
- [预览节点](#预览节点)
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
| `upload_base_url` | 参考图上传地址，默认 `https://api.aione.help`。**只有小裴系 Seedance / grok-video 节点会用**；用别家 Key 时这里会 401，改用「填公网 URL」的方式 |

> 强烈建议把 Key 放到环境变量，不要写进工作流再分享出去。

设置环境变量（Windows PowerShell，永久）：

```powershell
[Environment]::SetEnvironmentVariable("RESPECT_API_KEY", "你的Key", "User")
```

## 网关对照表

**同一个模型在不同网关的名字/字段都不一样，跨网关混用会 503 或参数丢失。** 先按这张表选对节点和 `base_url`：

| 网关 | `base_url` | 图片节点 | 视频节点 | demo |
|---|---|---|---|---|
| 小裴 / aicopy | `https://api.aicopy.top` | image2 等 5 个 | Firefly 系 / SD2 / Seedance 全系 / 快乐马 / 低价多渠道 | `H_xiaopei` |
| **坤鸡** | 图片 `https://img.yunfei.best`；视频=你的坤鸡网关 | **坤鸡 图片** | Grok-Video（坤鸡分支） | `I_kunji` |
| 章鱼哥 | 你的章鱼哥网关 | 章鱼哥 异步图片 | 章鱼哥 异步视频（+任务查询） | `J_octopus` |
| 零视工坊 | `https://zeroapi.ai-ren.cn` | **零视工坊 图片** | Sora2/VEO、图生视频 | `K_zero` |
| 灵感鸭 | `https://www.lingganyaapi.com` | 灵感鸭 统一图片 | 灵感鸭 统一视频 | `L_lingganya` |
| **鹤 / paisio** | `https://api.paisio.online` | **鹤 图片生成**、**鹤 图生图（≤16张）** | **鹤 视频**（+虚拟资产上传） | `M_he` |
| 一花 Codex | `https://llm.xxttt.com` | — | — | LLM 专用，见 `2_llm_*` |

各家的坑：

| 网关 | 要注意 |
|---|---|
| 小裴 | 参考图走 `upload_base_url` 上传换 URL（默认 api.aione.help），**非 aicopy 的 Key 会 401** |
| 坤鸡 | 视频参考图 **multipart 直传**不经图床；图片 `response_format` 必填（`b64_json`）。**图片和视频的 base_url 不同**，demo 里放了两个 API 设置节点 |
| 章鱼哥 | 图片/视频都是异步；参考图 `images[]` base64 |
| 零视工坊 | 图片接口**没写在文档索引里**（在「模型」页），且是**异步**的；`seconds` 是**字符串**类型（发数字会 400 invalid_json）；比例必须**显式发 `aspect_ratio`+`ratio`**，只给 `size` 它会回落 16:9；**sd 系已迁到新接口**（用「SD2 视频（新接口）」节点） |
| 灵感鸭 | 三步式：提交 → 查询 → `/content`；`size` 是**比例**、`seconds` 才是时长（sd 传整数、其余字符串）；每个模型 `seconds` 是**固定档位**（sora-2 只有 4/8/12、veo 只有 8、grok 只有 10/15）；SD 系要顶层 `resolution`，且**有参考图时 `extra.reference_mode` 必填**（`media`/`frame`）；吊炸天模型在**单独文档**里（`sd-2.0`/`sd-fast`/`-special`），不在统一接口的模型表 |
| 鹤 / paisio | 参考图**只吃 data URI 内联**（节点自动转 1024px JPEG q80），走外部图床会被拒；有**虚拟资产接口**可传参考视频/音频 |

**模型名典型坑**：

| 想要 | 小裴 | 坤鸡 | 零视工坊 | 灵感鸭 | 鹤 / paisio |
|---|---|---|---|---|---|
| Grok 视频 | `grok-video` | `grok-imagine-video-1.5-fast` / `-1.0-video` / `-1.5-preview` | `grok-1.5` | `grok-imagine-video-1.5-preview` 等 | — |
| SD 系 | `sd2-720p-fast` / `sd2-1080p` / `sd2-720p-mini` … | — | **`sd2-fast`**（新接口，720P固定） | `sd-2.0` / `sd-fast` / `sd-2.0-special` / `sd-fast-special` | `sd2-pro-720p` / `sd2-*` / `sd3-*` |
| VEO | `firefly-veo31-*` | — | `veo_3_1-fast`（连字符） | `veo_3_1_fast`（**下划线**） | — |

> 填错就会看到 `503 No available channel for model xxx under group default` —— 那是网关没这个模型，不是插件的错。

## 节点总览

**配置 / 基础**

| 节点 | 显示名 | 功能 |
|---|---|---|
| `RespectApiSettings` | Respect API 设置 | 输出 `RESPECT_CONFIG`，所有 API 节点入口 |
| `RespectLoadModels` | Respect 加载模型列表 | `GET /v1/models`，按关键字过滤 |
| `RespectLoadImagesFromZip` | Respect ZIP批量加载图片 | 从 ZIP 按批次取 IMAGE |
| `RespectLoadVideosFromZip` | Respect ZIP批量加载视频 | 从 ZIP 按批次取视频 |
| `RespectPreviewImage` | Respect 查看图像 | 节点内预览 IMAGE |
| `RespectPreviewVideo` | Respect 查看视频 | 节点内 `<video>` 播放（http URL 会先下载） |

**图片**

| 节点 | 显示名 | 功能 |
|---|---|---|
| `RespectImageGenerate` | Respect 小裴 图片生成 | `POST /v1/images/generations` |
| `RespectImageMultiRef` | Respect 小裴 多参考图编辑 | `POST /v1/responses`，最多 7 张 |
| `RespectGPTLocalImage` | Respect 小裴 GPT本地版生图 | `/responses` → 失败降级 `/images/generations` |
| `RespectImageChat` | Respect 小裴 多模态对话生图 | `POST /v1/chat/completions` (stream) |
| `RespectOpenAIImage` | Respect 小裴 image2 文生图/图生图 | gpt-image-2 / gpt-image-1-direct，支持 1k/2k/4k、参考图 |
| `RespectOctopusImage` | Respect 章鱼哥 异步图片 | gpt-image-2 / nano_banana，异步 → IMAGE |
| `RespectLingganyaImage` | Respect 灵感鸭 统一图片 | `POST /v1/images/generations?async=true` 三步式 |

**视频（小裴 / Firefly 系）**

| 节点 | 显示名 | 功能 |
|---|---|---|
| `RespectFireflySora2` | Respect 小裴 Firefly Sora2 视频 | chat stream，4/8/12 秒 |
| `RespectFireflyVeo31` | Respect 小裴 Firefly VEO3.1 视频 | chat stream，4/6/8 秒，720p/1080p |
| `RespectFireflyRunway45` | Respect 小裴 Firefly Runway 4.5 视频 | chat stream，5/10 秒 |
| `RespectFireflyKling3` | Respect 小裴 Firefly 可灵3.0 视频 | chat stream |
| `RespectSoraV3Video` | Respect 小裴 Sora V3 视频 | 异步 `/v1/videos` + `video_config` |
| `RespectSD2Video` | Respect 小裴 即梦/SD2 视频 | 异步 `/v1/videos`，有参考图自动 multipart |
| `RespectGrokVideo` | Respect 小裴 Grok 视频 | 1.0 体 / 1.5 体两种 body，最多 7 张参考图 |
| `RespectSD2AllVideo` | Respect 小裴 SD2.0 全系列视频 | 按秒计费全系，九图，支持 `ref_url_1..9` 直填 URL |
| `RespectSeedance9Video` | Respect 小裴 Seedance9 九图/稳定版视频 | fast / 官方稳定，九图，支持 `ref_url_1..9` |
| `RespectSeedanceFourRefVideo` | Respect 小裴 Seedance 四参考图视频 | `/v1/video/generations`，四图，支持 `ref_url_1..4` |
| `RespectSeedanceUniversal` | Respect 鹤 Seedance 通用异步视频（旧版） | 通用 `/v1/videos`，9 图（IMAGE 或 URL），自动补 `@ImageN` |
| `RespectGrokVideoXiaopei` | Respect 小裴 Grok-Video 视频 | 模型 `grok-video`，上传换公网 URL |
| `RespectGrokVideoNew` | Respect 坤鸡 Grok-Video 视频 | `grok-imagine-*` 三模型，multipart 直传参考图 |
| `RespectHappyHorseVideo` | Respect 小裴 HappyHorse 快乐马视频 | `/v1/videos`，`parameters` + 参考图 |
| `RespectLowCostMultiVideo` | Respect 小裴 低价多渠道视频（可灵/快乐马/omni） | 可灵 / 快乐马 / gemini-omni，含音频 |
| `RespectSaveVideo` | Respect 保存视频 | 下载视频 URL 到本地 |

**视频（其它网关）**

| 节点 | 显示名 | 功能 |
|---|---|---|
| `RespectOctopusVideo` | Respect 章鱼哥 异步视频 | sora / omni / veo，异步提交 |
| `RespectOctopusQuery` | Respect 章鱼哥 任务查询 | 用 `task_id` 单独查结果 |
| `RespectZeroSoraVeo` | Respect 零视工坊 Sora2/VEO 视频 | `size=WxH`，`input_reference` 多图 `\|` 分隔，`remix_id` 续 15 秒 |
| `RespectZeroImg2Video` | Respect 零视工坊 图生视频 | vad3 / omni_flash / grok-1.5 / seedance_2，**九图** |
| `RespectZeroSD2` | Respect 零视工坊 SD2 视频（新接口） | `sd2-fast`，`duration` 只能 5/10/15、`aspect_ratio` 必填、720P 固定；`images≤9` / `videos≤3` / `audios≤3` **只收 HTTPS URL** |
| `RespectZeroImage` | Respect 零视工坊 图片 | `/v1/images/generations`，异步自动轮询；quality/style/response_format |
| `RespectLingganyaVideo` | Respect 灵感鸭 统一视频（sora/SD） | `size`=比例、`seconds`=时长；SD 带顶层 `resolution` + `extra{}` |
| `RespectHeVideo` | Respect 鹤 视频 | sd2/sd3/seedance2.0 全系；参考图自动 data URI；`compat_metadata` |
| `RespectHeImage` | Respect 鹤 图片生成（统一接口） | `imageSize`(1K/2K/4K) + `aspectRatio` 自动换算像素，同步 |
| `RespectHeImageEdit` | Respect 鹤 图生图/多图融合 | `image[]` **最多 16 张** + 可选 `mask` 局部重绘 |
| `RespectHeAssetUpload` | Respect 鹤 虚拟资产上传 | 图/视频/音频 → `va_xxx`，轮询到 active；**传参考视频的官方途径** |
| `RespectKunjiImage` | Respect 坤鸡 图片 | `img.yunfei.best`，有参考图走 `/v1/images/edits` multipart |

**LLM / 文本**

| 节点 | 显示名 | 功能 |
|---|---|---|
| `RespectChatLLM` | Respect Chat 对话 (OpenAI) | `response_format` + `json_schema` |
| `RespectResponsesLLM` | Respect Responses 代码 (Codex) | 同上 |
| `RespectClaudeLLM` | Respect Claude 对话 (Anthropic) | 无原生 json_schema，用系统提示强制 JSON |
| `RespectSplitSegments` | Respect 分段提取 | json / regex_split / regex_findall / delimiter，**`outputcount` 动态输出口** |
| `RespectPickSegment` | Respect 取第N段 | 吃 `all_json` + `index`，动态取段 |
| `RespectTextInput` | Respect 文字输入 | 多行文本常量源 |
| `RespectShowText` | Respect 显示文字 | 把文字显示在节点上并透传 |
| `RespectMergeText` | Respect 文字合并 | 最多 8 路按分隔符拼接 |
| `RespectExtractSeconds` | Respect 提取镜头秒数 | 从文本抠出秒数 + 可填偏移（补删帧） |

**素材 / 剪辑 / 流水线 / 上传**

| 节点 | 显示名 | 功能 |
|---|---|---|
| `RespectLoadPdfText` | Respect PDF批量转文字 | 文件夹按序批量，pymupdf/pdfplumber/pypdf |
| `RespectAssetLibrary` | Respect 关键词取素材（角色库） | 「出场人物：小白，小黑」→ 按名字到素材库取图/视频/文本 |
| `RespectSelectFrames` | Respect 帧选择裁剪 (IMAGE) | 支持 `1-10` / `3,7` / `5-` / `-5` / 倒序 |
| `RespectTrimVideoFile` | Respect 视频文件裁剪 (mp4) | 删帧 + 自动转 H.264（避免预览黑屏） |
| `RespectConcatVideos` | Respect 视频拼接 (mp4) | **`inputcount` 动态输入口** + `folder` + `extra_paths`，可加 BGM |
| `RespectAddBGM` | Respect 视频加BGM (mp4) | mix / replace，音量可调 |
| `RespectStoryboardSave` | Respect 分镜存储 | 一图多提示词落盘成任务队列 |
| `RespectStoryboardNext` | Respect 分镜取任务 | 取一个待办（可配 Auto Queue 连跑） |
| `RespectStoryboardComplete` | Respect 分镜完成归档 | 提示词/图片按完成度归档，断点续跑 |
| `RespectCloudUpload` | Respect 对象存储上传（图床/S3） | R2 / OSS / COS / S3 / MinIO → 公网 URL |
| `RespectLoadVideoPath` | Respect 选择/上传本地视频 | 节点上「选择视频上传」按钮 → 输出本地路径 |

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

### Respect 小裴 图片生成

走 `/v1/images/generations`。选 `model_family` 自动拼模型 ID，或选 `自定义/custom` 后填 `custom_model`。
传入单张 `reference_image` 时会附加到 `image` 字段（Grok 风格通道用）。

模型 ID 已含 `1k/2k/4k` 或 `1024x1024` 时不会再加 `size`。

### Respect 小裴 多参考图编辑

走 `/v1/responses`，`image_1` ~ `image_7` 最多 7 张参考图，`model` 可填 `GPT本地版` 或任意支持 `/responses` 的模型。

### Respect 小裴 GPT本地版生图

`GPT本地版` 开头的模型优先 `/responses`，失败自动降级 `/images/generations`；其他应急模型直接走 `/images/generations`。

### Respect 小裴 多模态对话生图

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

## 多网关视频节点

### 参考图怎么传（最关键）

三种传法，**优先用公网 URL**：

| 传法 | 节点上的入口 | 说明 |
|---|---|---|
| **公网 URL（推荐）** | `ref_url_1..N` / `extra_image_urls` / `image_url` | 接 **对象存储上传** 的 `url`。所有网关都能拉，不会 401 |
| 上传换 URL | 接 IMAGE 槽（小裴系） | 自动传到 `upload_base_url`（默认 api.aione.help）。**非 aicopy 的 Key 会 401** |
| base64 内联 | 接 IMAGE 槽（通用/章鱼哥/零视/灵感鸭） | 不经图床。但**部分网关会静默忽略 base64** → 表现为「生成了但没参考图片」 |

> `ref_url_*` 默认是文本框；要连线得先**右键节点 → Convert `ref_url_N` to input**。
> 不想连一堆线，就把 URL 每行一个贴进 `extra_image_urls`。

### 九图支持

| 网关 / 模型 | 参考图上限 |
|---|---|
| 小裴 SD2.0 全系 / Seedance9 | 9 |
| Seedance 通用异步 | 9（`image_url` + `ref_url_2..9`，自动补 `@Image1..N`） |
| 零视工坊 `sd2-fast` / `sd2-pro` | 9 |
| 灵感鸭 `sd-2.0` / `sd-fast` | 9 |
| 零视工坊 grok **preview** | **只能 1 张**，且必须在 `images` 数组 |
| 零视工坊 sora / veo | `input_reference` 多图用 `\|` 分隔 |

### 零视工坊（`base_url=https://zeroapi.ai-ren.cn`）

- **Sora2/VEO 视频**：`{model, prompt, size(WxH), input_reference, remix_id}`。`remix_id` 填已有 veo 任务 ID 可续到 15 秒。
- **图生视频**：`{model, prompt, size, duration, image / images[]}`。`sd2` 只支持 **5/10/15 秒**；seedance 4–15。
- 统一 `POST /v1/videos` 提交 → `GET /v1/videos/{id}` 轮询，`completed` 时 `url` 为无水印地址。

### 灵感鸭（`base_url=https://www.lingganyaapi.com`）

三步式：`POST /v1/videos?async=true` → `GET /v1/videos/{id}` → 没直链再 `GET /v1/videos/{id}/content`。

- `size` 是**宽高比**（16:9），`seconds` 才是时长（sora 传字符串、SD 传整数，节点自动区分）
- SD（`sd-2.0`/`sd-fast`）额外带**顶层 `resolution`**（sd-2.0=1080p/720p，sd-fast=720p/480p），
  参考视频/音频/参考模式/是否生成音频只能放 `extra{}` —— 节点已按模型自动处理，sora 不会被污染
- 模型 / 尺寸 / 分辨率都是「下拉 + `custom_*` 可填覆盖」，上新模型自己填即可

## LLM 对话节点

`Chat 对话 (OpenAI)`、`Responses 代码 (Codex)`、`Claude 对话 (Anthropic)` 三个节点参数一致：

| 参数 | 说明 |
|---|---|
| `response_format` | `text` / `json_object` / `json_schema` |
| `json_schema` | 选 `json_schema` 时填 JSON Schema，强约束返回结构 |
| `schema_name` | schema 名称（如 `scenes`） |
| `system_prompt` / `temperature` / `max_tokens` | 常规参数；`temperature=-1` 表示不传 |

> Claude 没有原生 `json_schema`，节点通过系统提示强制输出合法 JSON。
> 配合 **分段提取（method=json）** 即可把 JSON 数组直接拆到多个输出口。

## 文本工具节点

### Respect 分段提取（动态输出口）

四种切法：`json`（自动去 ```json 围栏，`json_path` 定位数组、`json_field` 取字段）、
`regex_split`、`regex_findall`（每个匹配或第一个捕获组=一段）、`delimiter`（默认空行，支持 `\n` `\t` 转义）。

**输出口数量可变**：填 `outputcount` → 点节点上的 **「更新输出口」** 按钮 → `seg_1..seg_N`（1–200），后面固定跟 `count`、`all_json`。

嵌套内容分两步取。例如 `"关键物品": "1染血白婚纱，2主卧手机，3露台护栏"`：

```text
① method=json, json_path=关键物品     → seg_1 = "1染血白婚纱，2主卧手机，3露台护栏"
② method=regex_findall,
   pattern=\d+\s*([^，,]+)            → seg_1=染血白婚纱  seg_2=主卧手机  seg_3=露台护栏
```

段数不固定时用 `all_json` 接 **取第N段**，按 `index` 动态取。

### Respect 提取镜头秒数

从 LLM 文本里抠出秒数（认 `8秒` / `8s` / 时间段 / 纯数字），`offset` 可填 `+1` 补被删掉的首帧，
输出 `seconds` / `base_seconds` / `note`，直接接视频节点的时长。

### Respect 显示文字

把上游 STRING 显示在节点上（并原样输出），调 LLM / 分段结果不用翻控制台。依赖 `web/respect_showtext.js`。

## PDF 与素材节点

- **PDF批量转文字**：选文件夹**按顺序**批量取，`batch_size` / `mode(increment…)` / `index` 控制取哪一批；
  引擎 pymupdf → pdfplumber → pypdf 自动降级；输出 `text` / `filenames` / `count` / `stem`（可当保存文件名）。
- **关键词取素材（角色库）**：文本里写 `出场人物：小白，小黑，小红`，节点按 `keyword` 定位这段、
  在 `library_dir` 里按名字找文件（精确 / 前缀 / 包含），`file_type` 选图片 / 视频 / 文本 / 任意，
  输出 `images` / `text` / `paths` / `names` / `count`。

## 视频剪辑节点

- **帧选择裁剪 (IMAGE)**：帧区间语法 `1-10`（第1到10帧）、`3,7`、`5-`（第5帧到末尾）、`-5`、`7-3`（倒序）。
- **视频文件裁剪 (mp4)**：按帧裁剪并**自动转 H.264**（`libx264 + yuv420p + faststart`）；
  否则 cv2 写出的 mpeg4 在浏览器预览会黑屏 / 显示 0:00。
- **视频拼接 (mp4)**：三个入口可混用，顺序 = `folder`（按文件名排序）→ `video_1..N` → `extra_paths`。
  - **`inputcount` 动态输入口**：填数量 → 点「更新输入口」→ `video_1..video_N`（1–200）
  - `mode`：`auto`（有 ffmpeg 就重编码保音轨）/ `copy`（无损快，需同参）/ `reencode`（缩放对齐）/ `frames`（无音轨，免 ffmpeg）
  - `bgm_stage`：`none` / `after_merge`（合并后统一加）/ `per_video`（每段各加再合并）
- **视频加BGM (mp4)**：`mix` 叠加原声 / `replace` 替换，`bgm_volume` 可调，BGM 自动循环。

> ffmpeg 来源：优先 `imageio-ffmpeg`（`pip install imageio-ffmpeg`），否则找 PATH 里的 `ffmpeg`。

## 分镜流水线节点

文件系统任务队列，**关掉 ComfyUI 也能续跑**。目录结构：

```text
<root>/
├── 01_pending/<场景>/image.png + prompts/001.txt 002.txt ...
├── 02_done_prompts/     # 做完的提示词移到这里
├── 03_videos/<场景>/     # 产出的视频
└── 04_done_scenes/      # 该图所有提示词都做完，图片才归档
```

1. **分镜存储**：一张图 + 多条提示词（接分段的 `all_json`）落盘成任务。
2. **分镜取任务**：每次取 1 条待办，输出图片 / 提示词 / `scene_id` / `seq`。配 ComfyUI 的 **Auto Queue** 就能自动连跑。
3. **分镜完成归档**：提示词做完即移走；**该图的提示词全做完后图片才归档** —— 所以中断后重跑不会重复出片。

## 对象存储上传

**Respect 对象存储上传（图床/S3）** —— 一个节点覆盖 S3 兼容存储，把本地图片/视频变成公网 URL 喂给需要链接的接口。

| 存储 | `endpoint_url` | `region` |
|---|---|---|
| Cloudflare R2 | `https://<账户ID>.r2.cloudflarestorage.com` | `auto` |
| 阿里云 OSS | `https://oss-cn-<区域>.aliyuncs.com` | 如 `oss-cn-hangzhou` |
| 腾讯云 COS | `https://cos.<区域>.myqcloud.com` | 如 `ap-guangzhou` |
| AWS S3 | 留空 | 如 `us-east-1` |
| MinIO / 自建 | 你的地址 | 视情况 |

- 需要 `pip install boto3`
- **`file_path` 填了就上传该文件（视频等），优先于 `image`**；只接 `image` 时上传 JPEG
- **`public_base_url` 必须填**能公开访问的域名，否则返回的 URL 打不开：
  R2 要在桶设置里开 **R2.dev 子域**（得到 `https://pub-xxxx.r2.dev`）或绑定自定义域名
- R2 不支持 ACL → `set_public_acl=false`（带 ACL 失败会自动退回重试）
- ⚠️ 密钥会存进工作流 JSON，**别把带密钥的工作流分享出去**

> r2.dev 是**测试用**域名，有「每秒数百请求」的可变限流，超了返 429；正式用请绑自定义域名。

**Respect 选择/上传本地视频**：节点上有「选择视频上传」按钮 → 选本地 mp4 → 上传到 ComfyUI `input/` → 输出绝对路径 →
接到对象存储上传的 `file_path`，即可得到视频的公网 URL（用于「参考视频」）。
ComfyUI 官方只给图片做了上传按钮，视频这个按钮由 `web/respect_upload.js` 提供。

## 预览节点

### Respect 查看图像

输入 IMAGE，直接在节点内显示（行为同核心 PreviewImage）。可接任意输出 IMAGE 的节点，如
**Respect 小裴 图片生成**、**Respect ZIP批量加载图片**。

### Respect 查看视频

输入本地视频路径字符串，在节点内渲染一个 `<video>` 播放器，可直接播放/暂停。

- 入口 `video_path` 接 **Respect Firefly/SD2 视频** 的 `local_path`，或 **Respect ZIP批量加载视频** 的 `first_video`。
- 支持多行路径（取第一行）。
- 视频不在 ComfyUI `output/input/temp` 目录时，会自动复制一份到 `output/respect_preview/` 以便播放。
- 该节点依赖前端脚本 `web/respect_preview.js`，由 ComfyUI 自动加载；安装后需**完全重启**（不是刷新）才能生效。
- 同时透传 `video_path` 输出，方便继续接 **Respect 保存视频** 等节点。

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
Respect API 设置  →  Respect 小裴 图片生成  →  PreviewImage
```

### 批量参考图 → 批量出视频

```text
Respect ZIP批量加载图片 (mode=increment, batch=1)
        │ images
        ▼
Respect 小裴 Firefly VEO3.1 视频 (first_frame)
        │ local_path
        ▼
（每次 Queue 自动换下一张参考图，遍历整个 ZIP）
```

### 即梦 SD2 首尾帧

```text
Respect API 设置  →  Respect 小裴 即梦/SD2 视频
LoadImage(首) →  ref_image_1
LoadImage(尾) →  ref_image_2
model = sd2-720p, aspect_ratio = 16:9, duration = 5
```

### 本地视频 / 图片 → 公网 URL → 参考

```text
Respect 选择/上传本地视频 (点按钮选 mp4)
        │ file_path
        ▼
Respect 对象存储上传 (file_path，不要接 image)
        │ url
        ▼
Seedance 通用异步视频 / 零视工坊 图生视频 的 参考视频URL / ref_url_N
```

### 现成示例文件

`example_workflows/` 目录（导入即用，详见该目录下的 `README.md`）：

| 文件 | 内容 |
|---|---|
| `1_image2_4k_text2img.json` | image2 出 4K 图 |
| `2_llm_jsonschema_split_to_image.json` | LLM(json_schema) → 分段 → 生图 |
| `3_pdf_to_video_pipeline.json` | PDF → LLM → 分段 → 生图 → 出视频 → 保存 |
| `4_one_image_multi_video.json` | 一张图 + 多条提示词 → 多个视频 |
| `A_storyboard_save.json` | 分镜存储（生产者） |
| `B_video_produce.json` | 分镜取任务 → 提取秒数 → 出视频 → 归档（消费者，配 Auto Queue） |
| `C_merge_bgm_save.json` | 拼接 + BGM + 按 PDF 名保存 |
| `D_octopus_async.json` | 章鱼哥异步调用 |
| `E_extract_seconds_demo.json` | 提取镜头秒数 → 视频时长 |
| `F_asset_library_demo.json` | 关键词取素材 → 生图 |
| `G_split_json_items_demo.json` | JSON 字段 → 拆出每个物品（**不需要 API Key 就能跑**） |

**每个服务商一个「图片 → 视频」demo**（结构统一：API设置 → 图片节点 → 预览图像 →（图当参考）视频节点 → 查看视频）：

| 文件 | 服务商 | 图片节点 → 视频节点 |
|---|---|---|
| `H_xiaopei_image_video_demo.json` | 小裴 / aicopy | image2 → SD2.0 全系列视频 |
| `I_kunji_image_video_demo.json` | 坤鸡 | 坤鸡 图片 → Grok-Video（坤鸡分支）｜**两个 API 设置**（图片/视频域名不同） |
| `J_octopus_image_video_demo.json` | 章鱼哥 | 章鱼哥 异步图片 → 章鱼哥 异步视频 |
| `K_zero_image_video_demo.json` | 零视工坊 | 零视工坊 图片 → 零视工坊 图生视频 |
| `L_lingganya_image_video_demo.json` | 灵感鸭 | 灵感鸭 统一图片 → 灵感鸭 统一视频 |
| `M_he_image_video_demo.json` | 鹤 / paisio | 鹤 图片生成 → 鹤 视频 |

用前只需在「Respect API 设置」里填 Key（`base_url` 已按各家预填好）。

## 常见问题

- **节点没出现**：确认目录在 `custom_nodes` 下，启动日志里搜 `Respect` / `ImportError`，多半是依赖没装到 ComfyUI 用的那个 Python。
- **报 401 / 鉴权失败**：API Key 没填或过期；`curl https://api.aicopy.top/v1/models -H "Authorization: Bearer ..."` 测一下。
- **报 503 全部渠道不可提供当前模型**：上游暂时没渠道，不是本地问题，换模型或稍后重试（节点已内置 3 次重试）。
- **图片下载 400 Bad Request**：已修复——S3 预签名 URL 不再附加 Authorization 头。
- **中文错误乱码**：已修复——强制按 UTF-8 解析错误响应。
- **网络 / 443 错误**：海外接口，国内通常需要代理，在 API 设置节点填 `proxy`。
- **SD2 任务一直 processing**：异步任务，调大节点 `poll_timeout`（默认 1800 秒）。
- **视频链接失效**：保持 `auto_download=True`，立即下载到本地。
- **`503 No available channel for model xxx`**：网关没上架/没通道/分组无权限。多半是**跨网关混用模型名**
  （如把小裴的 `grok-video` 填给坤鸡/零视工坊）。见 [网关对照表](#网关对照表)。
- **参数错位（下拉框里出现 `true`、`pattern` 里出现数字）**：节点结构变了但工作流里存的是旧值。
  **重启 ComfyUI + Ctrl+F5，然后把该节点删掉重新拖一个**；用示例工作流的话重新导入最新 JSON。
  报错样式如 `Value not in list: match_mode: 'True' not in [...]`。
- **改了节点却没变化 / 新节点找不到**：确认改的是 ComfyUI **实际加载的那份目录**（多机同步时最常见），
  然后**完全重启**（不是刷新）；带前端 JS 的功能还要 **Ctrl+F5** 强刷浏览器。
- **生成了但没参考我的图片**：该网关**忽略了 base64**。改用公网 URL —— 用**对象存储上传**拿 URL 填 `ref_url_*` / `image_url`。
  另外部分接口要在 prompt 里用 `@Image1`、`@Image2` 引用（通用 Seedance 节点会自动补）。
- **上传参考图 401（`upstream_key_not_valid`）**：小裴系节点会传到 `upload_base_url`（默认 api.aione.help），
  非 aicopy 的 Key 在那边不通。改用「填公网 URL」的入口，或换 aicopy 的 Key。
- **R2 上传成功但链接打不开**：`<账户ID>.r2.cloudflarestorage.com` 只是 S3 接口、不能公开读。
  去 R2 桶设置开 **R2.dev 子域**或绑自定义域名，把它填进 `public_base_url`。
- **视频怎么上传**：上传节点的 `image` 只收图片；**视频要走 `file_path`**（接「选择/上传本地视频」的输出、
  接视频节点的 `local_path`，或直接粘贴本地 mp4 路径）。
- **裁剪后的视频预览黑屏 / 显示 0:00**：cv2 写出的是 mpeg4 Simple Profile。节点已自动转 H.264，
  需要 ffmpeg：`pip install imageio-ffmpeg`。
- **拼接/分段的口不够用**：视频拼接填 `inputcount` 点「更新输入口」；分段提取填 `outputcount` 点「更新输出口」。
  拼接也可以用 `folder`（整个文件夹）或 `extra_paths`（每行一个），无上限。

## 开源与贡献

- 代码结构：
  - `utils.py`：HTTP 客户端（重试 / UTF-8 / 代理）、tensor↔base64↔URL 转换、SSE 解析、文件下载、尺寸表
  - `api_settings.py`：配置与模型列表
  - `image_nodes.py` / `video_nodes.py`：图片 / 视频生成（含异步 `/v1/videos` 提交+轮询公用逻辑）
  - `loader_nodes.py`：ZIP 批量加载基础节点
  - `llm_nodes.py`：Chat / Responses / Claude 对话 + image2 生图
  - `seedance_nodes.py`：Seedance 全系 / Grok 双分支 / 快乐马 / 低价多渠道
  - 各服务商一个模块：`octopus_nodes.py`(章鱼哥)、`zeroapi_nodes.py`(零视工坊)、
    `lingganya_nodes.py`(灵感鸭)、`he_nodes.py`(鹤/paisio)、`kunji_nodes.py`(坤鸡图片)
  - `text_nodes.py`：分段 / 取段 / 输入 / 合并 / 显示 / 提取秒数
  - `pdf_nodes.py`：PDF 批量转文字；`asset_nodes.py`：关键词取素材
  - `video_edit_nodes.py`：帧选择 / 裁剪 / 拼接 / BGM（ffmpeg 封装）
  - `storyboard_nodes.py`：分镜文件系统队列
  - `upload_nodes.py`：对象存储上传 + 选择/上传本地视频
  - `preview_nodes.py`：图像 / 视频预览
  - `web/`：前端脚本 —— `respect_preview.js`（视频播放器）、`respect_upload.js`（视频上传按钮）、
    `respect_concat.js`（动态输入口）、`respect_split.js`（动态输出口）、`respect_showtext.js`（显示文字）
- 内部节点 ID 统一为 `Respect*`，配置类型为 `RESPECT_CONFIG`。
- 欢迎 issue / PR。提交前请确保 `python -m py_compile *.py` 通过。
- 发布到 ComfyUI Registry：`pyproject.toml` 已含 `[tool.comfy]` 字段，配合 `comfy-cli` 即可发布。

## 许可证

[Apache-2.0](./LICENSE)。
