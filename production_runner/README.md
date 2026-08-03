# production_runner — 灵感鸭生产执行器

`script-to-video-prompts-v2` skill（12环节体系）中**环节 9-10 的执行器模块**：
读环节 8 产出的 `tasks.json` → 调灵感鸭 API 生成故事板（gpt-image-2）与 15 秒段视频（sd-2.0 / sora-2）→ 按约定路径落盘 → 写注册表。

生产执行是可替换模块——本 runner 与 ComfyUI 工作流、平台手动操作等价可换，消费同一套契约：

```
进：tasks.json + 提示词文件 + 固定故事板
出：约定路径的文件 + storyboard_registry.json / video_registry.json 登记
```

## 迁移到其他电脑

整个 `production_runner/` 文件夹拷走即可。目标机器只需要：

1. Python 3.9+
2. `pip install -r requirements.txt`（就一个 requests；Pillow 可选）
3. API key（见下）

不依赖 ComfyUI、不依赖 torch、不依赖仓库其他文件。

## 配置

```
copy config.example.json config.json     # 然后填 api_key
```

或者不建 config.json，直接设环境变量（三选一，按序取用）：
`LINGGANYA_API_KEY` / `RESPECT_API_KEY` / `AICOPY_API_KEY`

## 用法

```bash
# 全部（先故事板后视频，按清单顺序串行）
python runner.py <项目目录> --tasks 06_生产提示词/tasks_EP01.json

# 只出故事板 / 只出视频
python runner.py <项目目录> --stage storyboard
python runner.py <项目目录> --stage video

# 只跑某几段
python runner.py <项目目录> --only EP01-SEG04,EP01-SEG05

# 演练（不调 API，只打印任务）
python runner.py <项目目录> --dry-run
```

`--tasks` 省略时自动找 `<项目>/06_生产提示词/tasks_*.json` 的第一个。
任务格式见 `sample_tasks.json`（即 v2 skill 环节 8.4 定义的格式）。

## 执行纪律（与 skill 环节 9/10 一致）

- **按清单顺序串行**（剧情顺序，便于逐段核对状态衔接）
- **输出已存在 → 跳过不覆盖**（生成即固定；要出修订版，把 tasks.json 里的 output 改成 `..._V02_...` 再跑）
- **技术失败同参重试 ≤2**（网络错误、任务失败、下载失败）
- **不判断内容质量**——注册表登记 `status: "generated"`，六格是否正确/身份是否混用等技术检查由 Agent 读图完成，通过后改 `fixed`；审美与剧情问题走环节 11 人工定向修订

## 灵感鸭 API 要点

| 项 | 值 |
| --- | --- |
| 故事板 | `gpt-image-2`，`size` 是像素（默认 1024x1536，竖版容纳 2×3 九比十六格） |
| 视频 | `sd-2.0`（支持 4-15 秒整数、顶层 `resolution` 720p/1080p）；`sora-2` 时长传字符串、常见 12 秒 |
| 视频 `size` | 宽高比（9:16），不是像素 |
| 参考图 `images[]` | ≤9 张。**官方要求公网 URL**；runner 把本地文件转 base64 data URI 兜底 |

### 参考图被拒怎么办

视频接口对 base64 参考图可能不接受（节点注释原话："官方要URL，可能不被接受"）。若报参考图相关错误：

1. 把故事板传到任意对象存储/图床拿公网 URL（仓库 ComfyUI 里有 `RespectCloudUpload` 节点，S3/R2/OSS/COS 通用）
2. 把 tasks.json 里该段的 `storyboard_ref` 从本地路径改成这个 URL
3. 重跑 `--stage video --only <该段>`

`reference_images` 条目同理：加 `"url": "https://..."` 字段即可（url 优先于 file_ref）。

## 产物

| 文件 | 说明 |
| --- | --- |
| tasks.json 里 `output` 指定的路径 | 故事板 png / 段视频 mp4 |
| `03_段落故事板/storyboard_registry.json` | 故事板登记（status: generated → fixed 由检查方改） |
| `04_段落视频/video_registry.json` | 视频登记 |
| `06_生产提示词/execution_log.jsonl` | 每次执行一行：成功/技术失败/重试次数/task_id |

## 换模型

改 `config.json`（全局默认）或单个任务的 `params.model`（按段覆盖）。
注意：换生成模型 ≠ 换执行器——模型换了要回环节 8 重新编译提示词模板，执行器本身不用动。
