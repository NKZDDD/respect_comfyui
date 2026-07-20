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
