# 架构与权威

## 目录

1. 系统目标与边界
2. 三类Canon
3. 八个Canonical核心对象
4. 六层冻结与合法回调
5. 叙事单位与生产单位
6. Scene、Beat、Shot定义
7. 17章输入输出
8. 信息缺失与视觉设计
9. Reality Thread与Presented Truth
10. Canon修订与长期生产
11. Canonical ID与资产注册表

## 1. 系统目标与边界

把故事转译成可长期复用的生产真相，再编译为图片和视频模型可执行的输入。优化不得改写未获授权的故事事实。

保留：

- 人物身份、关系、动机与关键选择。
- 事件施动者、动作目标、因果和结果。
- 核心冲突、反转、关键Reveal和结局。
- 世界规则、能力规则、死亡规则与资源规则。

允许在授权范围内调整：

- Scene边界、Beat密度和信息排序。
- Blocking、镜头、剪辑、节奏和声画表达。
- 为适配视频模型而形成的SEG包装与Reference Layout。
- 原文未定义但视觉必须确定的Open Design Degree。

禁止：

- 为凑时长删除关键剧情。
- 为画面方便改变施动者、受动者或动作结果。
- 用模型生成失败解释成新的Canon。
- 用淡入淡出、叠化或时间跳切掩盖不成立的因果。

## 2. 三类Canon

### Story Canon｜故事Canon

定义发生了什么、何时发生、谁知道什么、因果如何成立。它包含Story Truth、Reality Thread、Presented Truth、隐藏真相和未解信息。

### Visual Canon｜视觉Canon

定义人物、服装、地点、空间、道具等实体视觉身份，以及Story Canon未明确但画面必须稳定的视觉决定。

### Production Canon｜生产Canon

定义当前版本采用的CVS、SCSTATE、Shot、Model-Native Transition、KF、Storyboard Package、Reference Manifest和执行计划。Production Canon不能改写Story或Visual Canon。

三者关系：

```text
Story Canon决定真实与因果
↓
Visual Canon决定实体如何稳定可见
↓
Production Canon决定当前如何拍与如何生成
```

## 3. 八个Canonical核心对象

### 3.1 Story Truth

记录事实、因果、公开信息、隐藏信息、未解信息、事件顺序和Reality Thread。

### 3.2 Character / World Rules

记录长期人物逻辑、关系弧、能力、世界规则、文化地域和不可随意变化的限制。

### 3.3 Asset Canon

记录CHAR、PH、COST、LOOK、CT、LOC、GEO_PROXY、LOC_VIEW、PR、PROP、VEH、CRE、GRP、VFX等视觉身份、Visual Coverage，以及它们在唯一Canonical Asset Registry中的完整Family ID、Canonical Revision ID、状态和文件绑定。

### 3.4 Spatial Canon

记录World Origin/Axis/Unit、Topology、Zone、Anchor XYZ、Route、Landmark、尺度、固定结构、Geometry Proxy、批准机位覆盖、连接关系和版本修订。

### 3.5 Continuity Ledger

按事件记录所有State Delta和生命周期，是唯一历史状态真相。

### 3.6 Canonical Visual State

记录某Story Time的关键物理视觉真相，不包含Camera。

### 3.7 Cinematic Plan

记录Blocking、Performance Intent、Shot、Model-Native Transition、Timing、Sound与SEG表达方式。

### 3.8 Canonical Storyboard Package

记录KF内容、顺序、Source State、Action Phase和观察方式，是视频视觉编译真相。

## 4. 六层冻结与合法回调

### F1｜Story Freeze

冻结Story Truth与Narrative Facts。下游不得改故事。

### F2｜Visual Canon Freeze

冻结实体身份与空间：CHAR、PH、COST/Costume Contract、完整LOOK、LOC、PROP、SPATIAL、Geometry Proxy、Canonical LOC_VIEW与必要Visual Coverage；同时冻结Project命名空间、Canonical Revision ID和Registry Snapshot。多视角闭环不一致或会首次显露的区域未定义时不得通过F2。下游不得缩写或重造ID。

### F3｜Current State Freeze

冻结Continuity解析、Current Appearance、Blocking、CVS和VT结果。

### F4｜Cinematic Freeze

冻结Shot、Model-Native Transition、Timing和SEG。项目为`MODEL_NATIVE_ONLY`时，每个Transition必须在单一Video/SEG生成内完成，不得改由外部剪辑。

### F5｜Visual Compilation Freeze

冻结Canonical KF和Storyboard Package内容。

### F6｜Execution

生成已通过Reference Resolution与Compact Reference Identity Mapping的Prompt和AI Video；模型一次输出包含有序Shots、原生Transitions和声音连续性的完整SEG成片，只执行，不重新导演或重新设计。

### 禁止静默反向传播

禁止：

```text
Storyboard → 偷改CVS
Video → 偷改Storyboard
Camera → 移动Spatial Landmark
SEG → 改Story Truth
生成误差 → 改Character Bible
Production Reference → 改LOC Canon
```

当下游发现不可执行时，执行合法回调：

```text
发现问题
↓
定位最近有Authority的层
↓
明确提出最小修订
↓
重新冻结
↓
重编译受影响的全部下游
```

例如Camera没有合法位置表达关键动作：回到Directing Design最小调整Blocking，重新冻结CVS；不得在Storyboard里移动病床。

## 5. 叙事单位与生产单位

叙事链：

```text
Project
↓
Episode
↓
Scene
↓
Beat
↓
Shot表达
```

生产链：

```text
已完成的Scene / Beat / Shot / Timing
↓
按目标模型固定时长包装
↓
SEG
↓
Storyboard Package
↓
one-pass complete Video with model-native transitions
```

SEG不是Scene、Beat或故事段。`seg_duration`可选15秒、30秒或自定义固定时长，但在一次生产配置中保持稳定。不得用时长直接推导固定镜头数。

## 6. Scene、Beat、Shot定义

### Scene｜场次

定义：在相对连续时间和行动过程中，围绕一个主要戏剧目标展开并产生明确状态变化的完整戏剧单位。

Scene Contract：

```text
scene_id
story_time
reality_thread
location
entry_state
objective
conflict
tactics
turn
outcome
exit_state
unresolved_tension
```

切新Scene的常见条件：

- 时间、空间或Reality Thread发生有叙事意义的切换。
- 主要Objective结束或被替换。
- 前一Scene已经形成明确Outcome，新行动链开始。
- 叙事需要用离场/入场建立新的戏剧单位。

Location变化不必然等于新Scene；同一Location也可以包含多场戏。

### Beat｜戏剧节拍

定义：刺激或行动导致认知、目标、情绪、关系、权力或局势发生一次有意义变化的最小戏剧单位。

Beat判定问题：

> 节点结束后，相比开始前，什么重要东西改变了？

有效变化：

1. Knowledge / Information：未知变已知。
2. Objective：当前目标改变。
3. Emotion：情绪结果显著改变。
4. Relationship：信任、亲密、敌意或关系定义改变。
5. Power：优势、控制权或Holder改变。
6. Situation：危险、空间局势或资源状态改变。

只有动作、眨眼、走两步或抬手而无意义变化时，它们属于Beat内部动作。

### Shot｜镜头

Shot回答“如何让观众看到并理解Beat”。一个Beat可以一个镜头、多镜头或与相邻Beat共用镜头。镜头数量由信息量、动作复杂度、表演节奏、空间关系和导演意图决定。

## 7. 17章输入输出

| 章 | 主要输入 | 冻结输出 | 不得越权 |
|---|---|---|---|
| 0 初始化 | 用户请求、模型参数 | Project Config、ID Policy、Registry Snapshot | 不扩大授权/临时造ID |
| 1 源解析 | 原文 | Entity Map、事件原子 | 不补写事实 |
| 2 Story Truth | 事件原子 | Truth、因果、线程 | 不设计镜头 |
| 3 叙事结构 | Story Truth | Project/Episode/Scene/Beat | 不按SEG反推剧情 |
| 4 人物世界 | Story Truth | Rules、Bible | 不决定当前临时状态 |
| 5 资产 | Rules、视觉需求、Registry | Reserved ID、Asset Blueprint与Canon | 不决定Blocking/复用编号 |
| 6 空间 | Location需求 | World坐标、Spatial、Geometry Proxy、Canonical LOC_VIEW/PR | 不用独立生图决定几何/人物位置 |
| 7 连续性 | Events、Rules | Ledger、Resolved State | 不生成图片真相 |
| 8 导演 | Scene、Resolved State | Blocking、Performance | 不移动Canon空间 |
| 9 CVS | Current State、Blocking | Physical Visual Truth、World Placement | 不含Camera/Screen Position |
| 10 VT | 起终CVS、Event | Transition Contract | 不改因果 |
| 11 摄影 | Beat、CVS、Blocking | Shot Contract | 不改World |
| 12 剪辑时间 | Shot、Dialogue、模型能力 | Timing、Model-Native Transition、Sound | 不重写Beat/依赖外部剪辑 |
| 13 SEG | Cinematic Plan、模型时长 | SEG Package、Transition Ownership | 不切断Cause/Result/原生转场 |
| 14 生产解析 | Canon、Registry、模型容量 | Exact Resolved Reference Set、Manifest、六字段Identity Map | 不猜ID/文件/图中主体或创建新Canon |
| 15 故事板 | SCSTATE、Shot、Transition合同 | Storyboard Package、Transition Anchors、View Coverage | 不重新融合世界/发明新空间 |
| 16 执行计划 | Storyboard、时长 | Shot/Transition Windows、Switch Point、Reveal Envelope | 不改KF事实/把转场拆出SEG |
| 17 视频Prompt | Execution Plan | 一次生成完整多镜头成片Prompt | 不重新导演/依赖外部剪辑 |

## 8. 信息缺失与视觉设计

### Story Unresolved

原文有意保留或资料不足以确定的事实。保持`UNKNOWN`或`UNRESOLVED`，禁止擅自选择一个答案。

### Visual Underspecified

画面必须确定、但不改变故事的开放视觉维度，例如未描述的普通鞋款、墙面材质、非关键手机型号。建立Open Design Degree：

```text
design_question
story_constraints
world_constraints
selected_visual_answer
effective_scope
canonical_id_or_rule
```

一旦选定并投入生产，后续保持一致。不得让每张Storyboard重新随机决定。

### 关键文字

文件、短信、报告、标牌或屏幕文字若承载剧情事实，必须进入Story Truth和PROP Canon。Storyboard只决定何时看清，Video只执行显现时间，不得首次创造关键文字内容。

## 9. Reality Thread与Presented Truth

对客观现实、回忆、梦境、幻觉、想象、监控画面、伪造画面建立独立`reality_thread_id`。同一人物可以在不同线程拥有不同合法状态，但不得互相污染。

记录：

```text
objective_truth
presented_identity
character_knowledge
audience_knowledge
reveal_time
reality_thread
```

生产当前Episode时只下发当前合法Presented Truth。全剧隐藏身份、未来伤势和Reveal后信息不得因为系统“已经知道”而提前进入资产或提示词。

## 10. Canon修订与长期生产

Canon Revision必须写：

```text
revision_id
object
old_rule
new_rule
effective_story_time
reality_thread
affected_scope
```

区分：

- 设计修订：从指定Story Time起修改Canon解释。
- 剧情状态变化：由故事事件激活，不是设计修订。

长时间未出现不等于重置。人物重新登场时，根据Time Gap、PH进展、经历和当前Scene重新解析Appearance；Location重新出现时继续同一LOC/SPATIAL，除非存在搬迁、装修、破坏或合法时间变化。

区分Location回访：

- Same Visit / Continuous Return：临时Prop、环境状态和局部Anchor继续。
- New Visit / Time Gap：基础LOC/SPATIAL继续，临时状态按Lifecycle重新解析。

## 11. Canonical ID与资产注册表

读取[Canonical ID注册表与参考资产解析](10-canonical-id-registry-and-resolution.md)。Canonical Asset Registry是ID和真实文件的唯一索引；它不是第二套Visual Canon，而是Canonical对象、不可变Revision、文件角色、路径、Fingerprint和Authority之间的解析层。

执行关系：

```text
Canonical Object
↓ Registry allocates immutable Revision ID
Canonical File Promotion
↓ Registry binds exact filename / path / fingerprint
Production Resolution Gate
↓ exact match only
Reference Manifest + Prompt
```

每个有Reference的最终Prompt还必须在内部回显六字段`Compact Reference Identity Map`：完整ID、Who/What与可见内容、Story Time/Current State、Controls、Does Not Control、Applicable Scope。该映射只把现有Registry与Manifest信息翻译成模型可理解的语义，不是新的Canon对象。

架构硬边界：

- Family ID只表示语义对象；生产Reference只使用完整Canonical Revision ID。
- 显示名称、角色名和中文说明没有ID Authority。
- Candidate、Reserved、Deferred和Deprecated资产不能作为Reference。
- Canonical Revision不可覆盖；内容变化创建新Revision并显式回编下游。
- 文件移动只更新Registry路径；文件内容变化必须改变Revision。
- 查不到唯一ID、文件或Fingerprint时阻断Production Resolution，不允许模糊匹配或“用最近的一张”。
- 文件已解析但Image身份、当前状态、适用范围或上传顺序映射不完整时返回`REFERENCE_MAPPING_BLOCKED`，不得让模型自行判断“Image 1是谁”。
