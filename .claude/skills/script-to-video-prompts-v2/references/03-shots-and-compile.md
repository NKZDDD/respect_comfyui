# 环节 7-8：正式分镜生成 → 生产提示词编译

---

# 环节 7：正式分镜生成

## 目标

把 15 秒段落转换成明确可执行的镜头序列。输入：段落剧情 + 资产绑定包 + 进入/退出状态 + 项目视频规则。

## 镜头设计字段（每镜头）

```
shot_id            SHxx（段内编号）
time_range         如 0-5s（镜头时长加总必须 = 15秒）
景别 / 机位 / 镜头主体
人物位置           来自绑定包的关系层
动作过程
对白               标说话人与落点秒数
表情与反应
镜头结果           本镜头结束时画面停在什么状态
bound_asset_ids    本镜头调用的资产（asset_id 列表）
state_changes      本镜头内发生的状态变化
transition         固定 hard_cut
```

## AI 适配处理（为生成模型改写分镜的六条规则）

1. **复杂动作拆镜** —— 一个镜头只承载一个动作单元
2. **动作前与结果硬切** —— 高难度过程（碎裂、倒地、撕扯）拆成「动作前」和「结果」两镜，跳过中间过程
3. **避免过长手部交互** —— 手部特写/交接物品的镜头 ≤3 秒
4. **对白期间保持嘴部可见** —— 说话人正面或侧面，不给背面/遮挡
5. **避免同镜头互斥状态** —— 同一镜头里不出现「又哭又笑」「既站又坐」类矛盾指令
6. **所有镜头直接硬切** —— 不写推拉摇移之外的转场效果

## 输出

`shots.json`（正式分镜包），按段组织。

---

# 环节 8：故事板与视频提示词编译

## 目标

把正式分镜转换成直接可生产的提示词。本环节**只编译不创作**——所有内容来自上游产物的拼装。

## 8.1 故事板提示词编译

要点：6 格 2×3 排布、KFxx→SHxx 一一映射、每格 9:16 构图、资产调用（从注册表复制核心描述）、进入→退出状态演化（首格=进入状态，末格=退出状态）、`forbidden_future` 禁止项。

**参考图绑定关系（REFERENCE ROLE MAP）也在本环节编好**——故事板生成要上传该段用到的资产图，提示词里必须逐张绑定身份，上传顺序与编号严格对应：

```
参考图上传顺序与身份绑定：
Image 1 = C001-E01-A01 张角基础身份（四视图）
Image 2 = C002-E01-A01 官兵首领
Image 3 = S001-E01 巨鹿荒村
Image 4 = AT002-C003 少女倒地昏迷连续状态
...
每张参考图只提供对应身份/空间/状态信息，不得互相混用。
```

通用人物/场景/负面/镜头提示词**全部整合进这一份完整提示词**，执行环节不再另加任何内容。

存 `06_生产提示词/02_段落故事板提示词/EPxx/EPxx-SEGxx_STORYBOARD_PROMPT.txt`：

```
【段落故事板提示词记录】

segment_id：
{段落ID}

duration：
15秒

storyboard_prompt_id：
{提示词ID}

frame_count：
{关键帧数量}

frame_shot_map：
KF01 → SH01
KF02 → SH02
KF03 → SH03

【调用资产】

人物资产：
{asset_id 列表}

场景资产：
{asset_id 列表}

道具资产：
{asset_id 列表}

附属资产：
{asset_id 列表}

【段落进入状态】

{本段进入状态}

【段落退出状态】

{本段退出状态}

【完整故事板生成提示词】

{可直接投喂图片模型的提示词本体，见 04-storyboard-video.md 的模板}
```

## 8.2 视频提示词编译

要点：15 秒时间顺序、逐镜头动作、原始对白、口型同步、状态变化、硬切要求、退出状态。

存 `06_生产提示词/03_段落视频提示词/EPxx/EPxx-SEGxx_VIDEO_PROMPT.txt`：

```
【段落视频提示词记录】

segment_id：
{段落ID}

duration：
15秒

video_prompt_id：
{提示词ID}

storyboard_id：
{对应故事板ID}

storyboard_file_ref：
{对应故事板文件}

【镜头映射】

SH01：
{时间范围}

SH02：
{时间范围}

SH03：
{时间范围}

【段落进入状态】

{本段进入状态}

【段落退出状态】

{本段退出状态}

【完整15秒视频生成提示词】

{可直接投喂视频模型的提示词本体，见 04-storyboard-video.md 的模板}
```

## 8.3 段落生产提示词包

为避免后续调用时分别查找多个文件，每段再汇总一份自包含的生产包。
存 `06_生产提示词/04_段落可编辑生产包/EPxx/EPxx-SEGxx_PRODUCTION_PACKAGE.txt`：

```
【段落生产提示词包】

segment_id：
episode_id：
segment_order：
duration：15秒

【资产调用清单】
character_asset_ids：
scene_asset_ids：
prop_asset_ids：
attachment_asset_ids：
reference_asset_file_refs：

【原始剧情】
【剧情目标】
【必须剧情点】
【原始对白】

【段落进入状态】
【段落退出状态】

【正式分镜】
{shots.json 中本段的完整分镜}

【故事板关键帧与镜头映射】

【完整故事板生成提示词】

【完整15秒视频生成提示词】

【文件引用】
storyboard_file_ref：
video_file_ref：
```

这份文件是环节 12 人工修改的入口——改任何一段，先打开它。

## 8.4 执行任务清单（tasks.json）

三种提示词文件是给模型看的；再产出一份**机器可读**的任务清单，让任何执行器（Agent 直调 API / ComfyUI / 手动）消费同一套任务。存 `06_生产提示词/tasks_EPxx.json`：

```json
{
  "episode": "EP01",
  "project": "PDZJ-001",
  "storyboard_tasks": [
    {
      "segment_id": "EP01-SEG04",
      "prompt_ref": "06_生产提示词/02_段落故事板提示词/EP01/EP01-SEG04_STORYBOARD_PROMPT.txt",
      "reference_images": [
        { "image_n": 1, "asset_id": "C001-E01-A01", "file_ref": "02_全剧资产/Characters/..." },
        { "image_n": 2, "asset_id": "C002-E01-A01", "file_ref": "..." }
      ],
      "params": { "cells": 6, "layout": "2x3", "cell_ratio": "9:16" },
      "output": "03_段落故事板/EP01/PDZJ-001_EP01_SEG04_STORYBOARD_V01_FIXED.png"
    }
  ],
  "video_tasks": [
    {
      "segment_id": "EP01-SEG04",
      "prompt_ref": "06_生产提示词/03_段落视频提示词/EP01/EP01-SEG04_VIDEO_PROMPT.txt",
      "storyboard_ref": "03_段落故事板/EP01/PDZJ-001_EP01_SEG04_STORYBOARD_V01_FIXED.png",
      "aux_reference": null,
      "params": { "duration": 15, "ratio": "9:16", "subtitles": false, "watermark": false },
      "output": "04_段落视频/EP01/PDZJ-001_EP01_SEG04_VIDEO_V01.mp4"
    }
  ]
}
```

`reference_images` 的 `image_n` 顺序 = 提示词 ROLE MAP 的 Image 编号——执行器按此顺序上传即可自动满足「逐张核对」要求。
