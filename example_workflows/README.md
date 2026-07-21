# Respect 示例工作流

ComfyUI 里「工作流 → 打开」选这些 `.json` 即可载入（LiteGraph 图格式）。载入后把 `Respect API 设置` 节点里的 **api_key / base_url** 换成你自己的。

## 1. `1_image2_4k_text2img.json` —— image2 文生 4K 图

```
Respect API 设置 ──api_config──▶ Respect image2 文生图/图生图 ──image──▶ 预览图像
```
- base_url 默认 `https://api.aicopy.top`
- image2 节点：`model=gpt-image-2`、`resolution=4k`（长边 4096，如 16:9 → 4096×2304）
- 想图生图：给 image2 的 `image_1` 接一个「加载图像」，会自动走 `/v1/images/edits`

## 2. `2_llm_jsonschema_split_to_image.json` —— LLM 结构化分段 → 驱动生图

```
Respect API 设置 ─┬─api_config─▶ Respect Chat 对话 ──text──▶ Respect 分段提取 ─seg_1─▶ image2.prompt ─▶ 预览图像
                 └─api_config──────────────────────────────────────────────▶ image2.api_config
```
- Chat 节点：`response_format=json_schema`，`json_schema` 已填：
  ```json
  {"type":"object","properties":{"segments":{"type":"array","items":{"type":"string"}}},"required":["segments"],"additionalProperties":false}
  ```
  让 GPT 稳定返回 `{"segments":[...]}`
- 分段提取：`method=json`、`json_path=segments` → 切出 `seg_1..seg_8`
- 这里把 `seg_1` 接到 image2 的 `prompt`（第 1 段画面提示词直接生图）；换 `seg_2/seg_3` 即用其它段
- base_url 需用**同时有 chat 和 image 模型**的网关（示例填 `https://llm.xxttt.com`，按你实际网关改）

## 3. `3_pdf_to_video_pipeline.json` —— PDF → GPT分段 → 多图/多视频 → 拼接 → BGM → 保存（完整流水线）

一条龙示例（2 个场景为例，可自行加节点扩展更多场景）：

```
PDF批量转文字 ─text─┐
文字输入(提示词) ─┴─ 文字合并 ─▶ Chat(json_schema) ─▶ 分段提取(json, segments)
                                                          ├ seg_1 + 文字输入 → 合并 → image2_A → 图A ─┐
                                                          │                                          ├→ Grok视频A(首帧=图A) → 删首帧(2-) ─┐
                                                          ├ seg_2 + 文字输入 → 合并 ──────────prompt──┘                                   │
                                                          ├ seg_3 + 文字输入 → 合并 → image2_B → 图B ─┐                                   ├→ 视频拼接 → 加BGM ─┬→ 查看视频
                                                          │                                          ├→ Grok视频B(首帧=图B) → 删首帧(2-) ─┘                   └→ 保存视频(名=PDF stem)
                                                          └ seg_4 + 文字输入 → 合并 ──────────prompt──┘
PDF.stem ───────────────────────────────────────────────────────────────────────────────────────────────────▶ 保存视频.filename
```

要点：
- **PDF**：`folder_path` 已填测试文件 `巴西抛.pdf`，换成你的文件夹即可（`mode=increment` 逐个取）。
- **提示词 + PDF**：`文字输入(提示词)` 与 PDF 正文经 `文字合并` 一起进 Chat。
- **Chat**：`response_format=json_schema`，schema 为 `{"segments":[...]}`；提示词里要求「按顺序输出 4 段：场景1画面/场景1运镜/场景2画面/场景2运镜」。
- **分段**：`method=json`、`json_path=segments` → `seg_1..seg_4`。
- **每个场景**：画面段 + 一个 `文字输入`（风格）→ image2 出图；运镜段 + 一个 `文字输入` → Grok，**首帧 = image2 出的图**。
- **删首帧**：Grok 视频首帧就是那张图，用 `视频文件裁剪` `select=2-` 去掉第 1 帧。
- **拼接 → 加BGM**：两段去首帧后 `视频拼接`，再 `视频加BGM`（把 `audio_path` 换成你的音乐）。
- **预览 + 保存**：`查看视频` 播放；`保存视频` 的 `filename` 由 **PDF 的 stem**（无扩展名文件名）连过来，输出如 `巴西抛.mp4`。

> 想要更多场景：复制「文字输入×2 + 合并×2 + image2 + Grok + 删首帧」一组，把 `seg_5/seg_6…` 接上，再把删首帧的输出接到 `视频拼接` 的 `video_3/4…`。

## 4. `4_one_image_multi_video.json` —— 单张图 → 多个视频

和 #3 类似，但**只生成一张图**，这张图作为**多个 Grok 视频的首帧**，产出多个视频：

```
PDF批量转文字 ┐
文字输入(提示词) ┴→ 文字合并 → Chat(json_schema) → 分段提取(json, segments)
   ├ seg_1 + 文字输入(风格) → 合并 → image2 → 一张图 ─┬─首帧─▶ Grok视频A(seg_2+运镜文字) → 删首帧(2-) ┐
   │                                                  └─首帧─▶ Grok视频B(seg_3+运镜文字) → 删首帧(2-) ┤
   ├ seg_2 + 文字输入 → 合并 ─────prompt──────────────────────────▶ Grok视频A                        ├→ 视频拼接 → 加BGM ┬→ 查看视频
   └ seg_3 + 文字输入 → 合并 ─────prompt──────────────────────────▶ Grok视频B                        │                  └→ 保存视频(名=PDF stem)
PDF.stem ────────────────────────────────────────────────────────────────────────────────────────▶ 保存视频.filename
```

差别只在：**image2 只有一个**，它的 `image` 输出**同时连到 GrokA 和 GrokB 的 `first_frame`**（一张图喂多个视频）。让 GPT 输出 3 段：画面提示词 + 视频A运镜 + 视频B运镜。想更多视频就再复制「文字输入+合并+Grok+删首帧」一组，`first_frame` 都连同一个 image2 的输出，`prompt` 接 seg_4/seg_5…，删首帧后接 `视频拼接` 的 video_3/4…。

## 分镜三段式（文件系统任务队列，可断点续跑、防重复）

把复杂流程拆成三个工作流，用一个 root 路径（默认 `output/respect_storyboard`）传递任务。目录结构：

```
<root>/01_pending/<scene>/image.png + prompts/00X.txt   # 待做
       02_done_prompts/<scene>/00X.txt                  # 提示词做完移这
       03_videos/<scene>/00X.mp4                          # 删帧后视频，按 scene 成批
       04_done_scenes/<scene>/image.png                   # 该 scene 全做完，图移这
```

### A. `A_storyboard_save.json` —— 分镜存储（生产者）
```
PDF + 文字输入(提示词) → 合并 → Chat(json_schema: {image, videos[]})
  ├ 分段提取(json_path=image)  → seg_1 → image2 → 图
  └ 分段提取(json_path=videos) → all_json ─┐
                                    图 + all_json → Respect 分镜存储 → 写入 01_pending/<scene>/
```
Chat 按 schema 返回「一个画面提示词 image + 多个视频提示词 videos[]」；一张图绑定多个视频提示词（一对多）落盘。跑一次存一个 scene。

### B. `B_video_produce.json` —— 视频制作（消费者，每次跑 1 个任务）
```
Respect 分镜取任务(root) → image + prompt + scene_id + seq
  → Grok-Video(aicost, 图生视频, first_frame=image, prompt=prompt) → 视频文件裁剪(select=2- 删首帧)
  → Respect 分镜完成归档(scene_id, seq, video_path)
```
每次运行处理**一个** (图,提示词)：出视频→删首帧→归档到 `03_videos/<scene>`，提示词移到 `02_done_prompts`；该 scene 提示词全做完，图片才移到 `04_done_scenes`。**重复运行/挂 `/loop` 就能把整个队列跑完**（`has_job=false` 表示空了）。做完即移走，不会重复。

### C. `C_merge_bgm_save.json` —— 合并 + BGM + 保存
```
Respect 视频拼接(folder=<root>/03_videos/<scene>, bgm_audio, bgm_stage) → 查看视频 + 保存视频
```
- `folder` 填某个 scene 的 `03_videos` 目录 → 自动按名排序**整批拼接**
- `bgm_stage`：`none` 不加 / `after_merge` 合并后统一加 / `per_video` 每个视频各加再合并（这就是「单视频 or 合并后」的**开关**）
- 拼好 → 预览 + 保存

> 用前改：三个工作流的 `root_dir` 保持一致；A 的 base_url 用有 chat+image 的网关，B 的用 aicost（grok）；C 的 `folder`/`bgm_audio` 按实际填。

### 循环运行 B（把整个队列一次跑完）
B 每次运行只做 1 个任务。要一次跑完整批：
- 在 ComfyUI 里开 **Auto Queue（自动队列）**：队列区的 `Extra options → Auto Queue`，勾上后每执行完会自动再排一次，直到队列空/你关闭。
- `Respect 分镜取任务` 设了 `IS_CHANGED`（每次强制重扫目录），所以每次自动排队都会取到**下一个**未做任务；`01_pending` 清空后 `has_job=false`，此时再跑不产出（手动停 Auto Queue 即可）。

> 注意：这个「循环」是 **ComfyUI 前端的 Auto Queue**，不是 Claude 的 `/loop`——`/loop` 跑在助手侧、驱动不了你本机的 ComfyUI。

## 文字合并接法（在 UI 里手接，2 步）

分段/多路文字合成一段：

```
Respect 文字输入 ──text──▶ Respect 文字合并.text_1
Respect 文字输入 ──text──▶ Respect 文字合并.text_2   ──text──▶ 下游节点
```
或把 `Respect 分段提取` 的 `seg_1 / seg_2 / seg_3` 分别接到 `Respect 文字合并` 的 `text_1 / text_2 / text_3`，`separator` 填 `\n\n`。

超过 8 段：用 `Respect 分段提取` 的 `all_json` 接多个 `Respect 取第N段`（各填不同 `index`，1 起），分别路由到不同下游。

## 提示
- OpenAI 系（Chat/Responses）的 `json_schema` 严格模式要求 schema 带 `"additionalProperties": false` 且 `required` 覆盖所有字段（示例已满足）。
- Claude（Anthropic）无原生 `response_format`，节点会自动往 system 注入「只输出 JSON」的强制指令。
- 这些 JSON 是图格式；若你的 ComfyUI 版本较老载入异常，按上面的连线关系手接即可（节点都在 `Respect` 分类下）。
