---
name: script-to-video-cinematic-v62
description: AI电影级短剧生产体系 V6.2·十七章（强制故事板时间骨架与导演级视频执行）。剧本 → Story Truth → Canonical ID 资产树 → 空间坐标与机位 → CVS/SCSTATE 逻辑合同 → 强制 Storyboard 时间骨架 → 导演级逐窗口视频执行卡 → 生成/审计/交付。当用户在 script-to-video-studio 里做电影级十七章的项目（n0..n14 环节、SBPKG、SCSTATE、LOGICAL_ONLY、物化门控、Reference Admission Gate、Canonical Revision ID、Temporal Spine 这些概念）时使用。改这套体系的程序或提示词模板前必须读它。
---

# AI 电影级短剧生产 Skill V6.2

**原文在 `references/` 里，一个字没改。** 这份 SKILL.md 只是索引 + 程序与它的差异记录。

来源：`AI电影级短剧生产Skill_V6.2_强制故事板时间骨架与导演级视频执行强化版.docx`（2026-08-15，27.8 万字）

## 核心关系（第十九部分的正式表述）

```
Mandatory Canonical Storyboard Temporal Spine
+ Selective Effective Character / Location / Prop References
+ Expanded Directorial Video Prompt
→ Model-Native Complete Video
```

> 不得以"视频模型很强"为由取消 Storyboard，也不得以"稳定"为由把 SCSTATE、
> 全部人物资产、全部 Location View 和 Prop 同时堆入 Video。

## 二十个部分怎么找

| 部分 | 内容 | 什么时候读 |
|---|---|---|
| [00-overview](references/00-overview.md) | 版本整合说明与总目录（原文） | 先读这个 |
| [01](references/01-part.md) | 核心工作流与触发规则 | 环节顺序、项目输入清单 |
| [02](references/02-part.md) | 架构、Authority 与 17 章职责 | 改环节表、改依赖关系 |
| [03](references/03-part.md) | 资产树、派生变换与参考图机制 | 改 n3/n4/n4b、参考图规则 |
| [04](references/04-part.md) | Continuity、CVS、VT 与 SCSTATE | 改 n6/n8/n11 |
| [05](references/05-part.md) | 导演、镜头、SEG 与 Storyboard | 改 n7/n9/n10/n12 |
| [06](references/06-part.md) | Video Execution、时间门控与声音 | 改 n13 |
| [07](references/07-part.md) | 完整 Production Prompt 模板库 | 改任何 prompts/*.md |
| [08](references/08-part.md) | PROP 规格、物理实例与数量连续性 | 道具对账 |
| [09](references/09-part.md) | 原子资产完整提示词模板 | 改 n4b |
| [10](references/10-part.md) | Canonical ID 注册表与参考资产解析 | 改 registry_v34.py |
| [11](references/11-part.md) | 空间坐标、机位 Rig 与多视角一致性 | 改 n5 |
| [12](references/12-part.md) | 服饰资产、完整 LOOK 与首次显露覆盖 | LOOK/CT/COST |
| [13](references/13-part.md) | 视频模型原生镜头切换 | 转场、多镜头能力 |
| [14](references/14-part.md) | 空间状态门控与 Authority 完整视频参考 | 视频参考图选择 |
| [15](references/15-part.md) | 同场景兼容机位合并生产 | 机位合并 |
| [16](references/16-part.md) | 场景机位覆盖规划与重复视图控制 | View 去重 |
| [17](references/17-part.md) | Story-First、Zone-Coherent SCSTATE 与故事板可读性门控 | 物化门控 |
| [18](references/18-part.md) | Logical-First、Canonical Boundary 与一致性调优 | LOGICAL_ONLY 判定 |
| [19](references/19-part.md) | **强制 Storyboard 时间骨架、有效参考选择与导演级 Video 执行** | V6.2 的新内容都在这 |
| [20](references/20-part.md) | 漏洞审计与最终回编条件 | 自检 |
| [99](references/99-appendix.md) | agents/openai.yaml 与 Skill 文件结构 | 交付形态 |

## 失败码

skill 定义了一整族失败码，模型拒绝产出时会返回它们。**它们的后缀是有规律的**：

```
_BLOCKED  _FAILED  _UNPROVEN  _INSUFFICIENT  _INCOMPLETE
_CONFLICT  _GAP  _MISMATCH  _OVERLOADED  _UNJUSTIFIED  _OVER_BUDGET
```

程序按这个形状识别（`core/llm.py` 的 `_REFUSAL_RE`）。**加新码不用改程序** ——
但如果 skill 以后出现别的后缀，那一条正则要跟着补，否则模型拒绝产出时
报的是「输出缺少必需字段」，方向完全错。

常撞到的几个：

| 码 | 意思 |
|---|---|
| `STORYBOARD_REFERENCE_CAPACITY_BLOCKED` | 完整骨架超过模型参考上限，且降级阶梯走完了还是超 |
| `STORYBOARD_REFERENCE_ADMISSION_FAILED` | 故事板错版、错时或错位 |
| `VIDEO_STORYBOARD_SPINE_MISSING` | 骨架缺失 |
| `VIDEO_REFERENCE_UNIQUE_UTILITY_UNPROVEN` | 补图证不出独有 Authority 贡献 |
| `REFERENCE_DIMENSION_COVERAGE_GAP` | 删图之后某个维度没有 Authority 了 |
| `REFERENCE_MAPPING_BLOCKED` | 文件解析对了，但身份/状态/范围/上传顺序不完整 |

---

# 程序与本 skill 的已知偏离

**这一节是给下一个人看的**：程序不是 skill 的完整实现，差异在这里，
不用去翻 git 或猜。每一条都写清是谁定的。

## 一、按用户决定偏离的

### 1. 「是否需要系统文字或剧情文字」这一栏删掉了

skill 第一部分的项目输入清单里有：

```
是否保留原对白：   是否需要画外音：   是否生成字幕：
是否需要系统文字或剧情文字：
```

程序删掉了最后一项，改成**剧情本身要求的文字一律允许**，只保留字幕开关。

用户原话（2026-08-20）：「你这个复杂了，实际上画面上的字都是要有的，
我需要控制的只是有没有字幕而已」。

理由：手机屏幕、招牌、信件、报纸、弹幕这些是剧情本身，不是一个要不要的选择。
让人一部剧一部剧去枚举，漏一类就被「画面内禁止出现文字」那条规则**静默拦掉**
（图出来了、字没了、不报错）。

### 2. 集数按总时长算，不是数剧本里有几章

skill 里「集数」只出现在 `full_episode + provisional`（单集分析时后续集数到位要复核），
没有「按总时长切集」这回事。程序加了总时长 / 集数 / 每集时长三量联动，
集数按节奏算出来，和剧本里写的「第几集」无关。

用户原话（2026-08-20）：「节奏已经被我修改了，所以集数就要跟着逻辑变，
总时间和总集数、每集的时间应该是互相影响的逻辑才对」。

## 二、和 skill 有张力的

### 自动改写（soften）

`references/04-generate.md`：

> **不在本环节增加新的提示内容。**

而程序在提示词被审核拒绝后会把它交给分析引擎改写重发（`core/soften.py`）。
字面上就是在这一环节改提示内容。

约束：只换呈现方式不改剧情；长度和身份映射行始终对着**最初的原文**比，
不合格就扔掉照原错抛出。但它确实是本地扩展里最越界的一个。

## 三、skill 不管的（工程层，不算偏离）

skill 管的是"生产什么、按什么权威"，这些管"怎么把它跑出来"：

```
就绪即派 / 并发 / 按账号排队 / 跨批等待
服务商适配：参考图上限按用途取、尺寸按各家 api 规范转换、base64/URL、下载校验
指纹与版本、手动放图、补生产、任务明细
装箱漏镜头 / 时间线跳秒 / 集数对账 —— 本地经验检查，skill 无对应条文
决策记录、必需占位符、错误目录
```

---

# 从实跑里长出来的四条元规则

这四条不是某个 bug 的补丁，是**那一类 bug 的成因**。skill 正文里没有，
而每一条都真实咬过一次以上。改这套体系的程序时按它们检查。

## 1. 环节之间的权威关系要写死，不许平权

用户原话（2026-08-21）：「要么十二听十一的，要么十一有十二的」。

实遇：第十一环节判某条 SCSTATE 只留文字合同（不出图），第十二环节又把它
当参考图 —— **两个环节各自都对，凑起来做不出来**，而程序只能在出图前才发现。

做法：要么下游结构上看不到上游禁止的东西（把可引用的和不可引用的分成两个
清单发过去，不靠模型的记性），要么把下游的结构性需求提前告诉上游。
**光靠模板散文约束模型拦不住** —— 实测同一次运行里 SEG04 遵守了、SEG05 没有。

## 2. 每个数值要说清是「谁的」上限

实遇：`ref_limit` 只有一个值，取的是**视频链**首选那家的上限，然后发给所有环节。
于是第十二环节（它自己的参考图是给**出图**用的）被告知了视频那家的上限 ——
出图是超模 9 张、视频是派欧 30 张，故事板被告知 30。按 30 引，到出图撞上限，
而那时提示词已经写好了。

一个数发给用途不同的两拨人，是「各自都对、凑起来做不出来」的又一种。

## 3. 下一环节能处理的情况，上一环节不许拦

我自己踩的：给第十一环节加了一道硬停「每段至少要有一张会出图的场景状态」，
而第十二环节模板里有一整节「本段 SCSTATE 没有图的时候（必读）」，写了完整的
替代路径（改引原子资产）。**下一环节本来就能处理**，停在上一环节等于凭空造出
一个要人工介入的点。

判据：加硬停之前先读下游模板，确认它没有合法的替代路径。

## 4. 一个字段两个用途，就得两个字段

实遇：`_worker_kind()` 里 p2（场景状态图）和 p3（故事板）返回同一个字符串
`"storyboard"`。对选 worker 是对的（都走同一个出图 worker），对「这一批活跑完了
没有」是错的（p2 完了不代表 p3 完了）。于是 p2 一跑完就解除了等故事板的所有等待，
视频被派早 4 分钟，撞空报「故事板不存在」——而那几张图 31 秒到 4 分钟之后就出好了。

这一类错不报：提前触发之后走的是一条**看着很正常的合法分支**。
