# 视频模型原生镜头切换

## 目录

1. 目标与硬边界
2. 三层Transition语法
3. 原生转场类型
4. 选择逻辑与风险等级
5. Model Capability Gate
6. Model-Native Transition Contract
7. Transition Shield与状态切换
8. Storyboard编译规则
9. SEG与时间所有权
10. Video Prompt执行结构
11. 声音原生衔接
12. 失败降级与重新生成
13. 常见失败与修复

## 1. 目标与硬边界

本模块用于让视频模型在一次生成中直接输出包含多个Shot及镜头切换的完整SEG成片。

```text
ONE VIDEO TARGET
= ONE MODEL GENERATION
= ordered Shots
+ model-native transitions
+ performance / camera / sound
= final complete SEG output
```

项目启用：

```text
transition_execution_mode = MODEL_NATIVE_ONLY
external_transition_editing = FORBIDDEN
external_shot_assembly = FORBIDDEN
```

Video Model必须在生成过程中完成切镜、遮挡、甩镜、闪光、失焦、淡变或其他批准Transition。不得把镜头分段生成后交给生产人员拼接，也不得输出“供后期添加转场”的素材。

模型原生Transition属于Cinematic/Execution Canon，不创造Story Truth、人物状态或新空间。生成失败只能重新编译/重新生成，不得把错误提升为Canon。

## 2. 三层Transition语法

每个镜头切换同时声明三层：

```text
TRANSITION MECHANISM
+ EDITING / CINEMATIC GRAMMAR
+ EXECUTION MODE = MODEL_NATIVE_ONLY
```

### Mechanism

说明画面实际如何变化：瞬时切镜、完全遮挡、运动模糊、闪光、失焦、淡出入或VFX覆盖。

### Cinematic Grammar

说明为什么这样连接：动作匹配、视线匹配、反应切、图形匹配、声音匹配、强反差、平行线程或时间跳跃。

### Execution

说明模型如何在单条生成中执行。不得只写“电影感转场”或把Mechanism留给模型自由选择。

## 3. 原生转场类型

### NATIVE_CUT

模型在指定边界帧瞬时结束Shot A并开始Shot B。适用于Action Cut、Eyeline Match、Reaction Cut、Smash Cut、Graphic Match与Sound-driven Cut。

必须写`cut_at`。禁止模型把两个机位之间动画成无授权Camera移动，也禁止把两张KF做Morph。

### SHIELDED_OCCLUSION

人物、服装、车辆、墙、柱、门、雨伞、文件或其他有因果的前景元素完全遮挡画面，在100%遮挡期间完成Shot/Location/Thread/State切换。

### MOTION_BRIDGE

使用Whip Pan、快速Push/Pull、俯冲、抬升、转身或跟随运动形成全画面方向性模糊。Shot B必须继承批准的运动方向、速度趋势和进入节奏。

### OPTICAL_COVER

使用Dip to Black/White、Fade、Flash、Lightning、Lens Flare、Exposure Bloom或Full Defocus形成覆盖窗口。优先使用能够把画面清空的方式，避免人物和场景长时间混合。

### NATIVE_DISSOLVE

只在时间流逝、记忆、梦境、主观意识或明确风格理由下使用。两个画面是非叙事性的光学叠加，不代表两个Canonical State同时存在。禁止脸、身体、服装、伤口、Prop或Location发生Morph。

### VFX_THREAD_TRANSITION

镜面、水面、烟雾、粒子、能量或空间折叠等转场必须绑定已批准VFX Canon与Reality Thread。不能以转场为名自由设计新能力或新世界规则。

### CONTINUOUS_PORTAL

Camera穿门、绕墙、进入黑暗、经过前景或跟随人物进入另一Zone。若表现同一物理空间，路径必须符合Spatial/Geometry Proxy；若切换不同Location，必须在完整Shield后断开Physical Continuity，不能伪造不存在的连接。

## 4. 选择逻辑与风险等级

按叙事关系选择：

```text
同一动作 / 同一时空
→ NATIVE_CUT + Action/Eyeline/Reaction Match

同一情绪或因果、Location变化
→ Sound/Graphic Match、SHIELDED_OCCLUSION、MOTION_BRIDGE

明确时间跳跃
→ OPTICAL_COVER、Fade、受控Dissolve

强烈反差
→ NATIVE_CUT + Smash / Sound Drop

梦境、回忆、幻觉、超自然线程
→ OPTICAL_COVER或VFX_THREAD_TRANSITION
```

稳定性通常按下列顺序降低：

```text
NATIVE_CUT
> FULL SHIELDED OCCLUSION
> DIP / FLASH / FULL DEFOCUS
> MOTION BRIDGE
> NATIVE DISSOLVE
> CHARACTER / LOCATION MORPH
```

最后一项默认禁止，除非Morph本身是已批准的剧情/VFX事件。

转场数量动态决定。每个Transition必须有叙事、动作、声音、空间、时间或情绪功能；不得为“炫技”增加无功能转场。

## 5. Model Capability Gate

项目初始化冻结：

```text
native_multishot_support = RELIABLE | LIMITED | UNSUPPORTED | UNKNOWN
timecode_precision = HIGH | MEDIUM | LOW
native_audio_transition_support = YES | NO | UNKNOWN
reference_time_scope_support = YES | NO | UNKNOWN
full_occlusion_transition_support = YES | NO | UNKNOWN
```

执行路由：

- `RELIABLE`：允许NATIVE_CUT与批准的原生视觉Transition。
- `LIMITED`：优先Full Occlusion、Dip、Flash、Defocus或简单Whip；减少跨人物/跨Location直接混合。
- `UNSUPPORTED`：使用单镜头连续Camera/Blocking表达，或在同一生成内用完整遮挡完成变化；仍无法成立则`MODEL_NATIVE_TRANSITION_BLOCKED`。
- `UNKNOWN`：采用LIMITED策略，不假设模型具备多镜头能力。

禁止因模型不支持而改用外部剪辑。若用户以后授权外部剪辑，必须修改项目配置和执行模式，不能静默切换。

## 6. Model-Native Transition Contract

每个Transition使用完整Canonical Revision ID，例如：

```text
PRJ_NOVA__TRANS_EP01_SEG01_01_R01
```

合同字段：

```text
transition_revision_id
execution_mode = MODEL_NATIVE_ONLY
external_editing = FORBIDDEN
from_shot_revision_id
to_shot_revision_id
story / thread / location relation
transition_mechanism
cinematic_grammar
narrative_function
time_range
duration
cut_at_or_switch_point
exit_composition / exit_action
transition_trigger
shield_type / shield_coverage
camera_motion_vector
entry_composition / entry_action
from_cvs / from_active_state
target_cvs / target_active_state
spatial_relation
visual_coverage_requirement
audio_bridge
forbidden_state_mixing
completion_condition
failure_signature
```

不得使用`TRANS01`、`上一转场`或显示名称代替完整ID。

## 7. Transition Shield与状态切换

当Transition跨Location、Thread或外观状态时，优先建立`Transition Shield Window`：

```text
FROM-ONLY WINDOW
↓
SHIELD BUILD
↓
100% SHIELD / NEUTRALIZATION WINDOW
↓ STATE SWITCH POINT
SHIELD RELEASE
↓
TARGET-ONLY WINDOW
```

### Shield Frame

可使用全黑/全白、衣料、墙体、车辆、物体、全画面运动模糊、纯光或完全失焦。Shield Frame是Execution Anchor，不是CVS或新的世界状态。

### Shielded State Switch

- 完全遮挡前只允许From State。
- 只有达到合同要求的100% Shield后，才允许Location/Thread/State切换。
- Shield解除后只允许Target State。
- Shield期间不得出现混合脸、混合身体、混合服饰、混合伤口、混合Prop或混合Location。

### Optical Overlap Rule

```text
TRANSITION VISUAL OVERLAP
≠ CANONICAL STATE COEXISTENCE
```

Dissolve中的光学重叠没有Story Truth Authority。未来状态不能因为转场视觉叠加而提前进入From Shot；已激活状态也不能在Target Shot中被旧画面覆盖后重置。

## 8. Storyboard编译规则

### NATIVE_CUT

Storyboard提供：

```text
OUTGOING KF
+ exact cut boundary
+ INCOMING KF
```

无需虚构连续Camera路径。明确`DO NOT INTERPOLATE CAMERA BETWEEN SHOTS`。

### Shielded / Motion / Optical Transition

Storyboard Package提供：

```text
EXIT KF
+ TRANSITION TRIGGER FRAME
+ SHIELD / PEAK BLUR / PEAK LIGHT FRAME
+ ENTRY KF
```

只在中间视觉结构对执行不可替代时增加Transition Anchor Frame；不把它误记为SCSTATE或Stable CVS。

每个Transition Frame标记：完整Transition ID、Applicable Time、Mechanism、From/Target Authority、Forbidden Mixing和是否拥有World Truth。默认`WORLD TRUTH AUTHORITY = NONE`。

不同时间/线程的Reference继续使用Firewall。单条生成必须同时看到多个状态时，使用明确状态带、Applicable Window、Shielded Switch与模型支持的Reference Time Scope；不得假装未来Reference不存在。

## 9. SEG与时间所有权

Transition占用真实SEG时长，必须进入Timing Plan，不得额外叠加在时长之外。

每个Transition完整归属一个SEG：

```text
Exit Action
+ Transition Window
+ State Switch Point
+ Entry Establishment
```

不得把模型原生Transition拆在两个独立生成SEG之间。SEG边界只能放在转场完成后的稳定Shot/State，或转场开始前的稳定Shot/State。跨SEG转场意味着需要外部拼接，与`MODEL_NATIVE_ONLY`冲突。

如果固定SEG时长无法容纳必要Transition，重新分配Shot时长、调整SEG边界或减少非关键镜头；不得压缩关键动作、对白或状态成立到不可读。

## 10. Video Prompt执行结构

Video Prompt必须加入：

```text
【MODEL-NATIVE COMPLETE OUTPUT】
Generate one complete SEG in one model output. All ordered shots and transitions
must be generated inside this single video. No external editing, assembly,
transition insertion or post-production is permitted.

【SHOT TIMELINE】
{逐Shot写时间、状态、Camera、动作、Exit Condition}

【MODEL-NATIVE TRANSITION WINDOWS】
{逐Transition展开完整合同}

【SHIELDED STATE SWITCH】
{From-only、Shield Build、100% Shield、Switch Point、Target-only}

【NO SHOT MORPH】
Instant cuts are real cuts. Do not animate or morph between independent camera
setups. Shielded transitions may switch only at the approved shield point.

【NO EXTERNAL EDITING DEPENDENCY】
The returned video must already contain the complete shot sequence, transitions,
timing and native audio continuity.
```

输出一条完整视频，不输出单镜头素材包、多个候选片段、转场占位、剪辑点说明或“后期处理建议”。

## 11. 声音原生衔接

在`native_audio`模式下，J-Cut、L-Cut、Sound Match、Sound Drop和Ambience Bridge必须由同一次视频生成完成：

```text
audio_cue_id
source_sound
prelap_or_postlap_time
perspective_change
transition_sync_point
target_ambience
dialogue_lip_sync_boundary
```

J-Cut中Target声音可在画面切换前进入，但Target视觉状态仍受Future-State Embargo。L-Cut中From声音可延续到Target画面，但From人物/Location不得视觉重现。

`silent_video`模式只执行视觉Transition；不得生成随机声音。`separate_audio`与“不做额外剪辑”的项目存在组合风险：若最终要求完全成片，改用`native_audio`或明确音频不在当前交付范围。

## 12. 失败降级与重新生成

原生转场失败时按顺序降级：

1. 保留Narrative Function，简化为更清楚的NATIVE_CUT。
2. 改为Full Occlusion / Dip / Flash / Full Defocus Shield。
3. 降低运动复杂度、人物数量或跨Location混合程度。
4. 改为单镜头连续Camera/Blocking表达。
5. 仍无法执行时输出`MODEL_NATIVE_TRANSITION_BLOCKED`并重新设计SEG。

禁止的“修复”：

- 分别生成Shot A与Shot B后外部拼接。
- 后期补黑帧、叠化、声音桥或遮挡。
- 裁掉失败帧再假装模型原生完成。
- 用Morph掩盖转场失败。
- 修改人物、Location或状态以迁就模型。

## 13. 常见失败与修复

| 失败 | 根因 | 修复 |
|---|---|---|
| 模型把两个机位平滑运镜连接 | NATIVE_CUT未写瞬时边界 | `cut_at` + DO NOT INTERPOLATE CAMERA |
| 两个人物融合成一张脸 | 转场无Shield/Authority Gate | 100% Shield后再切Identity |
| 医院走廊和病房混成一处 | 不同Location直接Morph | Full Occlusion/Dip + Target-only Entry |
| 贴片在遮挡前提前出现 | State Switch Point不清 | From-only Window + Future Embargo |
| 遮挡后仍回到旧状态 | Target State未锁 | Target-only Window + Past-State Persistence |
| 甩镜后方向反转 | Motion Vector未配对 | 冻结Exit/Entry方向、速度趋势和峰值 |
| Dissolve导致身体/服装融化 | 把光学重叠当Morph | 限制用途；独立光学层，不改变实体几何 |
| 门后出现不可能连接的Location | Continuous Portal伪造空间 | 同空间服从Geometry；异地在Full Shield后断开 |
| 转场占用时长导致对白过快 | 未计入Timing Plan | Transition Window计入SEG真实时长 |
| 转场跨两个SEG | 把一次转场拆成两次生成 | 完整归属单一SEG，边界放稳定状态 |
| 模型能力不足后改用后期 | 未冻结执行模式 | 更安全原生降级或BLOCKED，不外部剪辑 |
| 输出多个镜头素材而非成片 | Task没有完整输出合同 | MODEL-NATIVE COMPLETE OUTPUT + 单条成片格式 |
