---
name: produce-cinematic-ai-short-drama
description: 将小说、剧本或故事资料编译为电影级AI短剧生产包，覆盖项目初始化、故事真相、场次与节拍、人物与世界、Canonical资产、空间坐标与多视角Rig、服饰与完整LOOK、连续性、视觉覆盖、CVS、SCSTATE、导演、镜头、SEG、故事板、视频模型原生多镜头切换、声音与完整production_prompt。用于新建或更新AI短剧生产Skill、生成资产/故事板/视频提示词，以及修复人物漂移、空间多视角无法拼合、人物无事件瞬移或换位、座椅/支撑关系丢失、SCSTATE与故事板位置穿帮、视频参考图过多或Authority冲突、服饰Authority冲突、故事板裁切外区域被视频想象、只会硬切、模型内转场融合人物或场景、转场跨SEG、状态丢失、未来状态前置、道具实例混淆、Canonical ID缩写漂移、参考资产找不到、Image编号身份不明和时间逻辑错误。
---

# 电影级AI短剧生产

## 核心任务

把输入故事逐层编译为唯一、连续、可执行的影视生产真相。保持原故事的核心事实、人物关系、因果、关键剧情点和结局；只在用户授权范围内优化节奏、导演表达、镜头、分段与AI生产适配。

始终执行下列总原则：

1. 先确定Canon，再生成视觉；不得让下游生成误差反向改写上游事实。
2. 把“是什么”与“怎么表现”分开；参考图提供指定Authority，不是像素复制目标。
3. 把叙事结构与生产容器分开；Scene、Beat、Shot由剧情决定，SEG时长由目标视频模型参数决定。
4. 每个生成调用都交付实际参考图清单、上传顺序、六字段`Compact Reference Identity Map`和一段完整可复制的`production_prompt`；`Image N`必须明确是谁/是什么，不能只写控制范围。
5. 对所有状态执行双向时间保护：未激活状态不得提前出现，已激活持续状态不得无事件消失。
6. 使用动态数量：不得固定每SEG镜头数、KF数或SCSTATE数。
7. 只把已确认的Canonical资产投入下游；草图、测试图和失败版本没有生产Authority。
8. 所有资产、状态和生产对象ID只能从Canonical Registry读取并逐字符完整复用；禁止缩写、别名、模糊匹配和人工改写。
9. 同一Location的所有视角必须由同一个Spatial坐标系与Geometry Proxy投影；不得分别自由生成后再假设能够拼合。
10. 下游当前服饰权威必须是穿在当前PH人物身上的完整LOOK/CT；视频首次显露的身体或服饰区域必须已有视觉覆盖，否则限制Camera或阻断生产。
11. 每个VIDEO/SEG由视频模型一次生成完整多镜头成片及批准的原生Transition；禁止依赖外部镜头拼接、后期补转场或剪掉失败帧。
12. 人物与道具的位置、姿态支撑和Zone必须持续继承；没有批准的移动事件、Route与完成条件，不得跨SCSTATE或KF静默换位。
13. Video默认只上传Canonical Storyboard执行图；SCSTATE是上游编译中间态，不与Storyboard同时作为同一世界状态的Video参考。人物LOOK/CT、Prop或Location只在故事板存在明确覆盖缺口时按最小充分集补充。

## 开始前解析项目参数

从用户输入、已有项目文件和上下文中尽量解析下列参数。只在缺失值会实质改变结果且无法安全推断时询问；其他情况采用明确标注的默认值。

```text
project_id
id_policy = FQID_CANONICAL_REVISION_REQUIRED
asset_registry_path
registry_snapshot_id
source_type = novel | screenplay | outline | existing_assets
adaptation_authority = preserve | optimize_pacing | authorized_rewrite
instruction_language = 中文
dialogue_language
cultural_setting
visual_medium = live_action | 3d | 2d | mixed
visual_style
aspect_ratio = 9:16
target_image_model
target_video_model
seg_duration = 15s | 30s | custom fixed duration
video_audio_mode = native_audio | silent_video | separate_audio
production_scope = full_project | episode_range | current_episode
current_episode
existing_canon
reference_capacity_per_call
spatial_consistency_mode = geo_proxy | measured_2_5d | text_only
costume_asset_mode = auto | separate_cost | direct_look
reveal_coverage_policy = require_coverage_or_constrain_camera
transition_execution_mode = MODEL_NATIVE_ONLY
external_transition_editing = FORBIDDEN
external_shot_assembly = FORBIDDEN
native_multishot_support = reliable | limited | unsupported | unknown
native_audio_transition_support = yes | no | unknown
output_depth = analysis | plan | production_ready
```

不要把提示词语言等同于文化设定。地域、服饰、医院、建筑、货币、称谓等只服从World Bible和Story Truth。

## 选择工作路径

### 全流程生产

按第0至17章顺序执行，并读取全部参考文件：

- [架构与权威](references/01-architecture-and-authority.md)
- [资产与参考权威](references/02-assets-and-reference-authority.md)
- [连续性、CVS与SCSTATE](references/03-continuity-cvs-scstate.md)
- [导演、镜头、SEG与故事板](references/04-directing-seg-storyboard.md)
- [视频执行与声音](references/05-video-execution.md)
- [完整提示词与交付模板](references/06-production-prompt-library.md)
- [PROP规格、物理实例与数量连续性](references/08-prop-spec-and-physical-instance.md)
- [原子资产完整提示词模板](references/09-atomic-asset-prompt-templates.md)
- [Canonical ID注册表与参考资产解析](references/10-canonical-id-registry-and-resolution.md)
- [空间坐标、机位Rig与多视角一致性](references/11-spatial-rig-and-multiview-consistency.md)
- [服饰资产、完整LOOK与首次显露覆盖](references/12-costume-look-and-visual-coverage.md)
- [视频模型原生镜头切换](references/13-model-native-shot-transition.md)
- [空间状态门控与视频参考最小化](references/14-spatial-state-gating-and-video-reference-minimization.md)
- [漏洞审计与冲突处理](references/07-loophole-audit.md)

### 单项资产生产

先读[Canonical ID注册表与参考资产解析](references/10-canonical-id-registry-and-resolution.md)、[资产与参考权威](references/02-assets-and-reference-authority.md)和[原子资产完整提示词模板](references/09-atomic-asset-prompt-templates.md)。Location/SPATIAL/PR或同场景多视角任务同时读[空间坐标、机位Rig与多视角一致性](references/11-spatial-rig-and-multiview-consistency.md)；COST/LOOK/CT或人物服饰覆盖任务同时读[服饰资产、完整LOOK与首次显露覆盖](references/12-costume-look-and-visual-coverage.md)。如果资产包含持续状态、空间组合或跨时间继承，同时读[连续性、CVS与SCSTATE](references/03-continuity-cvs-scstate.md)。若出现两件以上同款道具、背景库存、道具交接/损坏/消耗或物体数量漂移，同时读[PROP规格、物理实例与数量连续性](references/08-prop-spec-and-physical-instance.md)。

### 故事板生产或修复

读取[Canonical ID注册表与参考资产解析](references/10-canonical-id-registry-and-resolution.md)、[连续性、CVS与SCSTATE](references/03-continuity-cvs-scstate.md)、[导演、镜头、SEG与故事板](references/04-directing-seg-storyboard.md)、[空间坐标、机位Rig与多视角一致性](references/11-spatial-rig-and-multiview-consistency.md)、[空间状态门控与视频参考最小化](references/14-spatial-state-gating-and-video-reference-minimization.md)、[服饰资产、完整LOOK与首次显露覆盖](references/12-costume-look-and-visual-coverage.md)、[视频模型原生镜头切换](references/13-model-native-shot-transition.md)和[完整提示词与交付模板](references/06-production-prompt-library.md)。

### 视频提示词生产或时间逻辑修复

读取[Canonical ID注册表与参考资产解析](references/10-canonical-id-registry-and-resolution.md)、[连续性、CVS与SCSTATE](references/03-continuity-cvs-scstate.md)、[视频执行与声音](references/05-video-execution.md)、[空间状态门控与视频参考最小化](references/14-spatial-state-gating-and-video-reference-minimization.md)、[视频模型原生镜头切换](references/13-model-native-shot-transition.md)、[服饰资产、完整LOOK与首次显露覆盖](references/12-costume-look-and-visual-coverage.md)和[完整提示词与交付模板](references/06-production-prompt-library.md)。若Camera移动、转身或扩大取景会暴露新空间，同时读[空间坐标、机位Rig与多视角一致性](references/11-spatial-rig-and-multiview-consistency.md)。

### 体系更新或漏洞检查

读取全部参考文件，最后逐条执行[漏洞审计与冲突处理](references/07-loophole-audit.md)。

## 17章生产编译流程

### 0｜项目初始化（Project Initialization）

冻结任务参数、生产范围、目标模型、固定SEG时长、画幅、语言、文化设定、视觉媒介、已有Canon和用户授权。建立唯一Canonical Asset Registry，冻结`project_id`、ID Policy和Registry Snapshot；不得在下游自行扩大改编权限或临时造ID。

### 1｜源文本解析与实体消歧（Source Parsing & Entity Resolution）

解析时间、地点、人物、别名、关系、道具、事件、对白、画外信息和现实线程。把同一实体的别名合并；不要因空间角色变化重复创建同一Physical Entity。

### 2｜故事真相（Story Truth）

建立客观事实、Presented Truth、隐藏真相、未解信息和因果链。当前生产提示词只能使用当前Story Time合法呈现的信息；不得用全剧隐藏真相提前剧透。

区分：

- `Story Unresolved`：故事本身尚未确定，禁止补写成事实。
- `Visual Underspecified`：故事未规定但画面必须决定，允许建立Open Design Degree并冻结为视觉Canon。

### 3｜叙事结构（Narrative Structure）

按`Project → Episode → Scene → Beat → Shot表达需求`解析，不把SEG放入叙事层级。

- Scene：相对连续时间/行动中，围绕一个主要目标并产生明确状态变化的戏剧单位。
- Beat：刺激或行动导致认知、目标、情绪、关系、权力或局势发生有意义变化的最小戏剧单位。
- Shot：表达Beat，不创造新的Story Truth。

不得固定“一Beat一镜头”。

### 4｜人物与世界规则（Character & World Rules）

建立人物长期动机、关系、弧光、能力、身体限制、表演边界、文化规则和世界运行规则。把永久规则与当前状态分开。

### 5｜资产系统（Asset System）

建立资产Blueprint并按当前生产范围物化。使用依赖拓扑生产：

```text
CHAR → PH
关键/复杂/复用COST → Canonical COST Visual Asset
简单COST → LOGICAL_ONLY Costume Contract
selected PH + COST Visual Asset或Costume Contract → 完整LOOK
LOOK / previous CT + state delta → CT
LOC + SPATIAL + Geometry Proxy → 单一Canonical LOC_VIEW → LOC_VIEWSET / PR
PROP_SPEC → PROP_SET / PROP_INSTANCE → PROP_INSTANCE_CT
PROP / VEH / CRE / GRP / VFX及其必要状态
CVS + component authorities → SCSTATE
```

每项先从Registry分配完整Asset Family ID和Canonical Revision ID，再标记`RESERVED | NEW | EXISTING_CANONICAL | LOGICAL_ONLY | DEFERRED`。只为当前范围实际需要且视觉差异有生产价值的状态创建资产。编号一经占用不得回收或转给另一实体。

### 6｜空间主表（Spatial Master）

冻结Location坐标原点、轴向、单位、拓扑、Zone、Anchor XYZ、Route、Barrier/Portal、Seat/Support Anchor、连接关系、门窗、固定结构、尺度、Landmark和当前空间修订。高风险场景先建立3D或2.5D Geometry Proxy，再从同一Proxy逐个生成、闭环核对和批准Canonical Location View；禁止一次自由生成互相矛盾的多视角Sheet。区分Location视觉身份与Spatial几何真相；PR/View Set只索引已批准视角，不取代二者。

### 7｜标准连续性（Canonical Continuity）

维护唯一Continuity Ledger。按Story Time与Reality Thread解析Resolved World State。所有状态必须有来源事件、激活条件、持续规则、失活/替换条件或合法自然生命周期。人物位置同样是状态：Zone、Anchor、Support Binding、Posture Class与Orientation在没有合法移动事件时持续不变。

### 8｜导演设计（Directing Design）

确定Scene Objective、Conflict、Tactic、Turn、Outcome、Performance Intent、Blocking和空间行动。每次Blocking改变都写Start Anchor、Release Support、Route、Barrier/Portal Crossing、End Anchor与Completion；Director读取当前LOOK/CT和物理限制，不能为构图擅自移动Canon实体。

### 9｜标准视觉状态（Canonical Visual State / CVS）

冻结当前关键物理视觉真相：人物当前有效视觉根、World Position State、姿态、World Root/Foot XYZ或Anchor Offset、Zone、Seat/Support Binding、朝向、占地/支撑点、视线、手占用、Prop Holder、空间状态、持续视觉状态和关键结果。CVS不包含景别、构图、镜头角度或镜头运动；画面左右不能取代World坐标。

### 10｜视觉过渡（Visual Transition / VT）

定义两个稳定CVS之间的合法变化：起点、事件、物理过程、同步Delta、终点和不可逆结果。位置变化必须通过Authorized Spatial Transition：解除支撑、起身、沿批准Route移动、穿越合法Portal并在目标Anchor完成。中间动作可以不成为SCSTATE，但关键结果必须进入终点CVS。

### 11｜摄影与镜头设计（Cinematography & Shot Design）

根据Beat、Performance、Blocking和空间可拍性决定景别、机位、角度、构图、焦点、景深、运动和屏幕方向。Physical Direction属于CVS/空间，Screen Direction属于Shot。

### 12｜剪辑与时间（Editing & Timing）

分配镜头时长、动作节奏、反应停顿、对白速度、切点、声画关系和模型原生Transition。根据叙事关系与模型能力选择NATIVE_CUT、遮挡、甩镜、光学覆盖、受控Dissolve或VFX Transition；不得固定只用硬切，也不得用转场掩盖逻辑断裂。每个Transition写Mechanism、Cinematic Grammar、Narrative Function与模型内执行方法。

### 13｜SEG包装（SEG Packaging）

把已经设计好的影视内容装入所选固定时长生产容器。镜头数和转场数动态决定。每个Model-Native Transition完整归属一个SEG并占用真实时长；SEG边界只能放在转场前后稳定状态，禁止把一次原生转场拆到两个独立生成视频。尽量让Cause与Canonical Result归属同一SEG。

### 14｜生产解析（Production Resolution）

从Canon解析本次调用的Minimum Sufficient Reference Set。先执行Exact Registry Lookup、Canonical状态、真实文件路径、文件角色、Fingerprint和Authority Scope检查，再输出Image编号、完整Canonical Revision ID、精确文件名、路径、Authority、上传顺序和适用范围。随后在最终Prompt内部为每个槽位写六字段紧凑身份映射：`Exact ID / Who or What + Visible Content / Story Time + Current State / Controls / Does Not Control / Applicable Scope`。Location机位必须解析到批准的LOC_VIEW/Geometry Proxy；人物服饰必须解析到当前完整LOOK/CT。Video先执行Composite Authority Deduplication：Storyboard已包含的SCSTATE、Location、Prop和人物组合不得重复上传；只补充可证明的Coverage/Identity/文字缺口。任一Reference未解析时输出`REFERENCE_RESOLUTION_BLOCKED`；任一Image缺少身份、状态或范围映射时输出`REFERENCE_MAPPING_BLOCKED`。Image编号每次调用重新从1开始。

### 15｜标准故事板（Canonical Storyboard）

用SCSTATE作为主要世界状态来源，通过新的Camera Observation产生KF。每个KF绑定同一Spatial Revision、批准的Location View/Geometry Proxy、实体World Position State和相对上一KF的Authorized Position Delta；没有移动事件时精确继承Zone/Anchor/Support。Camera只投影World，不能为了同框把人物移到前场。NATIVE_CUT冻结Outgoing/Incoming KF与瞬时边界；遮挡/运动/光学Transition仅在必要时加入Trigger、Shield/Peak和Entry Anchor，且Transition Frame没有World Truth Authority。一个SEG只有一个Canonical Storyboard Package，可用有序Continuation Sheets但不得创建第二套Canon。

### 16｜视频执行计划（Video Execution Plan）

把KF顺序映射到精确Shot与Transition Window，明确Entry State、Allowed State、Activation Event、Target State、Forbidden Future State、Position State、Authorized Movement、Action Causality、Camera Execution、Sound Cue和Exit State。每个Transition使用完整ID，冻结Exit、Trigger、Shield/Peak、State Switch Point和Target-only Entry。逐Window建立Camera Reveal Envelope并核对LOOK/CT Visual Coverage；Video输入默认只保留Storyboard执行图，SCSTATE不再重复占槽。

### 17｜视频生产提示词（Video Production Prompt）

输出一段完整可执行Prompt，要求视频模型一次生成一条包含全部有序Shot、原生Transition、动作、表演、Camera和声音连续性的完整SEG成片。Storyboard控制Camera/Blocking/Time，补充LOOK/CT只控制视觉覆盖。NATIVE_CUT不得动画连接机位；Shielded Transition只在100%遮挡后切换状态。禁止输出多段镜头素材、转场占位或依赖任何外部剪辑。

## Authority与冻结顺序

严格执行：

```text
F1 Story Freeze
Story Truth / Narrative Facts
↓
F2 Visual Canon Freeze
CHAR / PH / COST / LOOK / LOC / PROP / SPATIAL / Geometry Proxy / LOC_VIEW / Visual Coverage
↓
F3 Current State Freeze
Continuity / Current Appearance / Blocking / CVS / VT Result
↓
F4 Cinematic Freeze
Shot / Model-Native Transition / Timing / SEG
↓
F5 Visual Compilation Freeze
Canonical KF / Storyboard Package
↓
F6 Execution
Video Prompt / AI Video
```

禁止下游静默反向传播。若下游暴露上游不可执行，显式回到最近有Authority的层做最小修订，重新冻结并重编译受影响的下游。

## Canonical核心对象

维护八类核心对象：

1. Story Truth
2. Character / World Rules
3. Asset Canon
4. Spatial Canon
5. Continuity Ledger
6. Canonical Visual State
7. Cinematic Plan
8. Canonical Storyboard Package

Video是Execution Output，不是新的Canon。生成得更晚不代表Authority更高。

## 命名与ID完整性

新项目使用项目命名空间、完整对象路径和不可变Revision：

```text
PRJ_NOVA__CHAR_001_R01
PRJ_NOVA__CHAR_001_PH01_R01
PRJ_NOVA__COST_001_R01
PRJ_NOVA__CHAR_001_PH01_LK01_R01
PRJ_NOVA__CHAR_001_PH01_LK01_CT01_R01
PRJ_NOVA__LOC_001_PR01_R01
PRJ_NOVA__SPATIAL_001_R01
PRJ_NOVA__LOC_001_GEO01_R01
PRJ_NOVA__LOC_001_VIEW_A01_R01
PRJ_NOVA__LOC_001_VIEWSET01_R01
PRJ_NOVA__PROP_SPEC_001_V01_R01
PRJ_NOVA__PROP_INST_001_CT01_R01
PRJ_NOVA__SCSTATE_EP01_SC03_ST01_R01
PRJ_NOVA__CVS_EP01_SC03_01_R01
PRJ_NOVA__SBPKG_EP01_SEG01_R01
PRJ_NOVA__KF_EP01_SEG01_01_R01
PRJ_NOVA__TRANS_EP01_SEG01_01_R01
```

生产字段只使用完整Canonical Revision ID。`CT01`、`LOOK01`、`KF03`、“女主状态图”和“上一张图”均不是合法ID。SCSTATE属于Story State，不因SEG切分改ID；同一Scene跨SEG且状态未变时继续调用同一完整Revision ID。

全剧唯一且无同款歧义的Hero Prop可继续使用`PROP_001`对象路径，但实际生产ID必须是如`PRJ_NOVA__PROP_001_R01`的完整Revision ID。出现重复同款物件时，`PROP_SPEC`只控制共同外观，`PROP_INST`才是唯一Physical Entity；批量未追踪库存使用`PROP_SET`，交互时通过事件物化实例。不得要求完全同款实例为了区分身份而随机改色、加划痕或改标签。

维护[Canonical ID注册表与参考资产解析](references/10-canonical-id-registry-and-resolution.md)规定的唯一Registry。Canonical文件名必须以完整Revision ID开头；Target、Parent、Reference、CVS、SCSTATE、KF、Storyboard和Video中的ID都从Registry原样复制。不得用前缀/后缀搜索、最近匹配、自动别名或最新版本替代指定ID。

## 全局参考图规则

每个有或无参考图的生成调用都先输出`REFERENCE INPUT MANIFEST`：

```text
Production Target
Reference Count
Image N / Reference ID
Exact Canonical Filename / File Role
Canonical Relative Path / Resolved Path
SHA-256 Fingerprint / Availability
Who / What + Visible Content
Story Time / Current State
Authority Type
MUST PRESERVE
MUST TRANSFORM
MUST NOT COPY
DOES NOT CONTROL
Applicable Scope
Upload Order
```

随后输出一段`ONE COMPLETE production_prompt`，并复用完全一致的Image编号。Prompt内部必须包含下列紧凑映射；它只是现有Manifest的语义回显，不创建新资产、新ID或新注册表：

```text
【COMPACT REFERENCE IDENTITY MAP】
Image N = {Exact Canonical Revision ID}
Who / What + Visible Content: {自然语言说明这张图中的人、物或场景及画面可见内容}
Story Time / Current State: {年龄/阶段/LOOK或CT/事件前后/Thread}
Controls: {本次调用中有权控制的维度}
Does Not Control: {无权控制的维度}
Applicable Scope: {目标、KF或绝对时间窗口}
```

禁止让生产人员或模型自行猜测参考图；禁止孤立使用“完全按照Image 1”“保持Image 1不变”“严格复制参考图”等表达。只有ID、文件解析正确但上述语义映射不完整时，才使用`REFERENCE_MAPPING_BLOCKED`；不要重复建设另一套Reference系统。

若单张Image包含多个人物、多个Panel或多个时间状态，`Who / What + Visible Content`必须用Panel/区域与完整ID逐项消歧；无法消歧时阻断，不把整图概括成一个身份。

Manifest和Prompt交付前执行Exact ID Echo Audit。Reference Count大于0时，任何ID、文件、路径、Fingerprint或Authority未通过解析，输出`REFERENCE_RESOLUTION_BLOCKED`，不得猜图继续。

## 时间状态完整性

对人物、道具、Location、VFX、Holder和环境状态统一执行：

```text
NOT_ACTIVE
↓ Activation Event
ACTIVE
↓ Persistence
DEACTIVATION / REPLACEMENT / LIFECYCLE END
INACTIVE
```

生效前禁止完整、部分、弱化、模糊、预示或融合形式的未来状态；剧情明确要求Foreshadowing时，把预示本身单独定义为合法状态。生效后持续继承，直到有合法结束原因。

## 输出纪律

根据用户范围交付相应深度，但生产级输出至少包含：

1. 本次Scope与Assumptions。
2. Canonical事实和未解信息。
3. 当前范围资产计划与依赖顺序。
4. Registry Snapshot、每个资产的完整Canonical Revision ID、文件定位和状态。
5. 每个NEW资产的Reference Resolution Manifest、Compact Reference Identity Map和完整Prompt。
6. Spatial、Continuity、CVS、SCSTATE和VT。
7. Scene、Beat、Blocking、Shot、Timing和SEG。
8. Storyboard Package的Reference Manifest、KF合同和完整Prompt。
9. Video执行计划、Reference Manifest和完整Prompt。
10. 每个原生Transition的完整ID、Mechanism、Transition Window、State Switch Point和禁止外部剪辑合同。
11. 明确区分Canon、生产适配和模型输出。

不得只输出模板骨架或要求用户自行补齐关键字段。若信息不足，保留明确占位状态并说明缺口，不能把推测伪装成Canon。

## 结束前自检

在交付前执行[漏洞审计与冲突处理](references/07-loophole-audit.md)，至少确认：

- 没有第二套当前世界状态。
- CVS没有Camera字段。
- CT不是并行效果贴层。
- Reference Authority没有被写成像素复制。
- Storyboard内容唯一，Sheet数量只是版式承载。
- SCSTATE数量、KF数量和Shot数量均为动态。
- 关键单一Delta不会被“至少两类变化”规则错误过滤。
- 每项状态都有时间边界与合法生命周期。
- 每次生成调用都给出真实参考图和上传顺序。
- Storyboard与Video分别处理Reference Firewall和Temporal State Gating。
- 不存在Action Replay、未来污染、持续状态丢失或下游静默改Canon。
- 同款道具已分离Appearance Specification、Physical Instance与Instance CT。
- Active物体总数能由Visible、Partial、Occluded与Off-frame实例完整对账。
- 遮挡、装入容器或离画不会被误判为消失，重新入画恢复同一实例历史。
- 所有生产ID均为Registry中的完整Canonical Revision ID，没有缩写、别名或漏Revision。
- 每个Reference ID都解析到唯一Canonical文件、角色、路径、Fingerprint和Availability。
- Manifest与Prompt通过Exact ID Echo Audit，不存在Dangling Reference或Silent Redirect。
- 每个Prompt中的`Image N`都有完整ID、Who/What、当前时间状态、Controls、Does Not Control和Applicable Scope；不存在只有“Image 1控制什么”却没有说明它是谁/是什么的槽位。
- 身份映射缺失、错序或与Manifest不一致时已输出`REFERENCE_MAPPING_BLOCKED`，没有猜图继续，也没有新增重复资产系统。
- 每个高风险Location使用同一Spatial坐标系和Geometry Proxy生成所有必要视角，多视角Landmark、尺度、门窗、固定家具和连接关系闭环一致。
- CVS/SCSTATE/KF中的人物和关键Prop使用World XYZ或Anchor Offset定位；切镜不会静默改变真实Zone或朝向。
- 每个相邻SCSTATE/KF完成Position Delta审计；没有Authorized Movement Event时，Zone、Anchor、Seat/Support Binding、Posture Class和Orientation逐项继承。
- 所有跨Barrier或离开座椅/床/车辆的换位均有Release、Route、Portal Crossing、到达Anchor和Action Completion；不存在为同框或争吵构图直接把人物搬到前场。
- 每个当前人物造型均有穿在当前PH上的完整LOOK；独立COST只按关键度、复杂度和复用价值物化。
- 每个Video Window完成Camera Reveal Envelope与First Reveal Coverage Gate；未定义区域已补当前LOOK/CT覆盖或明确禁止显露。
- 每个Video先执行Reference Conflict Audit：默认只上传Storyboard执行图；同一状态的SCSTATE未与Storyboard重复上传；人物/Prop/Location补图均对应一个明确缺口且不夺取Camera、Blocking或Time Authority。
- Video Reference Count遵守最小充分原则；超过5张时必须逐张证明不可由Storyboard覆盖，否则先去重再交付。
- 每个VIDEO/SEG配置为`MODEL_NATIVE_ONLY`并由模型一次生成完整多镜头成片；不存在外部镜头拼接、后期补转场或失败帧裁除依赖。
- 每个Transition有完整Canonical Revision ID、叙事功能、Mechanism、时间所有权、Exit/Entry与状态隔离；Shielded Switch只在100%遮挡后发生。
- 模型能力不足时已降级到更安全的原生Transition、单镜头连续表达或明确BLOCKED，没有静默改用后期。
