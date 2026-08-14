# PROP规格、物理实例与数量连续性

## 目录

1. 适用问题与核心结论
2. 三层对象模型
3. 何时拆分、何时合并
4. Authority边界
5. ID、派生树与兼容规则
6. 数据合同
7. 实例物化与视觉资产节制
8. Object Count与Existence Ledger
9. Holder、Owner、Container与空间关系
10. 状态、事件与生命周期
11. 遮挡、离画与重新出现
12. 破坏、消耗、拆分与合并
13. SCSTATE执行合同
14. Storyboard执行合同
15. Video执行合同
16. 生产提示词模块
17. 示例
18. 硬规则与审计

## 1. 适用问题与核心结论

当故事里出现多件同型号、同版式、同外观的道具时，不得让一个`PROP`同时承担“它们长什么样”和“具体是哪一件”两种职责。

正式拆分为：

```text
PROP_SPEC = 外观规格真相，不是故事世界中的一件实物
PROP_SET = 未逐件追踪的同规格库存集合，不是单个物体
PROP_INSTANCE = 故事世界中唯一的一件物理实体
PROP_INSTANCE_CT = 该实体当前完整持续视觉状态
```

同规格实例允许完全相同。生产系统依靠ID、事件、Holder、Anchor、容器关系和连续性历史区分它们，不要求用随机划痕、不同颜色或错误标签制造视觉差异。

## 2. 三层对象模型

```text
PROP_SPEC_001
├── PROP_SET_001               # 可选：背景库存或批量同款物件
├── PROP_INST_001
│   ├── PROP_INST_001_CT01
│   └── PROP_INST_001_CT02
└── PROP_INST_002
    └── PROP_INST_002_CT01
```

规则：

1. `SPEC`定义共同外观，不拥有Holder、位置、损坏、生命周期或事件历史。
2. `SET`记录可交换的未追踪库存数量、区域和规格，不参与单件动作。
3. `INSTANCE`是唯一Physical Entity，拥有自己的Holder、位置、状态和历史。
4. `INSTANCE_CT`只属于一个实例；不得把A的破损状态套到B。
5. 实例从SPEC物化，不从另一个实例派生。

## 3. 何时拆分、何时合并

### 使用PROP_SPEC + PROP_INSTANCE

满足任一项即拆分：

- 两件及以上道具明确共享同一型号、版式或产品身份。
- 它们会同时出现，但拥有不同Holder、位置、状态或命运。
- 某件会被交接、损坏、消耗、丢失、重新出现或成为因果关键物。
- 观众需要知道“是同款，但不一定是同一件”。

### 使用PROP_SET

大量同款物件只作为背景库存，且暂时不需要逐件追踪时使用。例如会议室20把同款椅子、仓库50个未开封纸箱。

`PROP_SET`只保存数量、范围、区域和可交换性。任何一件开始被角色拿取、移动、损坏、特写或承担剧情信息时，必须通过事件从SET物化为唯一INSTANCE。

### 保持单一PROP

全剧唯一、不会与同款实体产生身份歧义的Hero Prop，可以继续使用`PROP_001`，把Appearance与Physical Identity合并，避免过度建模。

### 不建立Canonical对象

随机背景杂物若不承担识别、数量、交互或连续性价值，保持生成级环境细节，不进入PROP系统。

## 4. Authority边界

| 维度 | 权威对象 |
|---|---|
| 产品类别、几何、比例、材质、颜色 | PROP_SPEC |
| 标签、版式、固定文字、共同永久标记 | PROP_SPEC |
| 合法款式/颜色变体 | PROP_SPEC revision或独立SPEC |
| 物理唯一身份 | PROP_INSTANCE |
| 当前Holder、Hand、Carrier、Container | PROP_INSTANCE + Continuity |
| 当前Zone、Anchor、Orientation | PROP_INSTANCE + CVS |
| 当前完整/破损/染血/开合/余量 | PROP_INSTANCE_CT或Resolved State |
| 背景库存数量与分布范围 | PROP_SET |
| 镜头可见性 | KF / SCSTATE / Shot Observation |

强制分权：

```text
SPEC Appearance Authority
≠ Instance Physical Identity
≠ Current Physical State
≠ Holder / Position
≠ Camera Visibility
```

## 5. ID、派生树与兼容规则

新项目使用：

```text
PROP_SPEC_001_V01
PROP_SET_001
PROP_INST_001
PROP_INST_001_CT01
```

SPEC修订不得静默覆盖：

- 共同外观Canon改变时创建`V02`并写生效范围。
- 已物化实例继续绑定其合法的SPEC revision，除非故事事件明确改装或替换。
- 颜色、标签或尺寸差异若会影响识别、剧情或Reference，应拆为独立SPEC或正式variant；不得临时漂移。

兼容旧项目：

- 已冻结的`PROP_001`视为一个单一Physical Instance，并隐含自己的单件规格。
- 不为命名整齐批量重命名旧Canon。
- 当旧`PROP_001`后来出现第二件同款时，显式建立PROP_SPEC，并以Revision记录迁移映射。

## 6. 数据合同

### PROP_SPEC Contract

```text
prop_spec_id
spec_revision
category / product_identity
geometry / dimensions / proportion
material / finish
color_system
structure / moving_parts
canonical_text / label_layout
shared_permanent_marks
allowed_variants
forbidden_variation
canonical_reference_id
effective_scope
canon_status
```

`PROP_SPEC`不得含：

```text
holder
hand
owner
current_location
current_damage
current_fill_level
instance_lifecycle
camera_visibility
```

### PROP_SET Contract

```text
prop_set_id
prop_spec_id + revision
reality_thread
scene_scope / location_scope
canonical_supply_count
available_untracked_count
distribution_zone
exchangeability_rule
materialized_instance_ids
entry_event / exit_event
count_reconciliation_status
```

### PROP_INSTANCE Contract

```text
prop_instance_id
prop_spec_id + revision
source_set_id_or_none
materialization_event
instance_identity_marks_or_none
existence_status
current_state_id
holder
hand
owner
carrier_or_container
zone / anchor
orientation
physical_relation
visibility_status
activation / replacement / lifecycle_end
continuity_history
```

`instance_identity_marks`只记录Story Truth或正式设计要求的独有序列号、裂纹、签名等，不得为了让模型好分辨而擅自添加。

### PROP_INSTANCE_CT Contract

```text
prop_instance_ct_id
prop_instance_id
parent_state_id
activation_event / story_time
still_active_previous_state
new_delta
complete_resolved_state
persistence
replacement / deactivation
forbidden_future_state
visual_reference_id_or_logical_only
```

## 7. 实例物化与视觉资产节制

Logical Instance不等于必须生成一张独立资产图。

执行：

```text
共同外观Reference = PROP_SPEC
具体物理绑定 = PROP_INSTANCE文字合同 + Continuity
实例特有持续外观 = 必要时生成PROP_INSTANCE_CT Reference
```

不要为20把完全相同且无独有状态的椅子生成20张相同图片。只生成一份SPEC视觉资产，并在逻辑层登记SET或INSTANCE。

实例需要单独视觉资产的条件：

- 有稳定、可见、跨生产单元的独有状态。
- 有剧情关键的独有文字、划痕、签名或改装。
- 其状态差异无法仅靠SCSTATE/KF合同稳定执行。

从SET物化实例时记录：

```text
EVENT_PROP_MATERIALIZE_01
Source Set: PROP_SET_001
New Instance: PROP_INST_007
Set Available Count: 20 → 19
Materialized Active Count: 0 → 1
Total Physical Supply: unchanged
```

## 8. Object Count与Existence Ledger

对象数量是世界状态，不是构图要求。

对当前Scope内所有Active实例执行：

```text
ACTIVE_INSTANCE_TOTAL
= VISIBLE_FULL
+ VISIBLE_PARTIAL
+ OCCLUDED
+ OFF_FRAME
```

每个Active实例在一个时间点只能落入一个Visibility bucket。遮挡、离画、装入包内不会减少世界中的Active数量。

SET与实例执行库存守恒：

```text
CANONICAL_SUPPLY
= AVAILABLE_UNTRACKED_IN_SET
+ MATERIALIZED_ACTIVE
+ MATERIALIZED_INACTIVE
```

只有合法事件可以改变总量：

- `WORLD_ENTRY / WORLD_EXIT`：进入或离开当前追踪范围。
- `CREATION / ACQUISITION`：故事中新增。
- `DESTRUCTION / CONSUMPTION`：物理终止或被消耗。
- `SPLIT / MERGE / TRANSFORMATION`：实体结构改变，并记录父子映射。
- `SET_MATERIALIZATION`：只改变追踪形式，不改变总量。

每个SCSTATE、Storyboard Package Entry/Exit和Video Window都要输出：

```text
Object Count Lock
Active Instance IDs
Visibility Bucket by Instance
Set Available Count
Count-changing Event in this interval
Exit Reconciliation
```

## 9. Holder、Owner、Container与空间关系

不要混用：

- `Holder`：此刻直接握持或控制物体的人。
- `Hand`：具体左手、右手、双手或NONE。
- `Owner`：法律、叙事或归属关系，不等于当前持有。
- `Carrier`：携带物体的人或载具，但可能未直接手持。
- `Container`：包、盒、抽屉、口袋等包含关系。
- `Anchor`：物体在空间中的具体支撑点或固定点。

交接事件必须同步更新原Holder、新Holder、双方Hand Occupancy、物体位置、可见性和结果状态。没有可见交接或合法画外事件，不得换Holder。

嵌套关系使用唯一链：

```text
PROP_INST_010 inside PROP_INST_003
PROP_INST_003 carried_by CHAR_001
```

不得同时把内层物体写成“桌上”和“包内”。

## 10. 状态、事件与生命周期

同规格实例状态彼此独立：

```text
PROP_INST_001 = unopened
PROP_INST_002 = broken
PROP_INST_003 = blood-stained
```

事件必须绑定实例ID：

```text
EVENT_031
Actor: CHAR_001
Target: PROP_INST_002
Delta:
- PROP_INST_002 intact → broken
- holder CHAR_001 → NONE
- hand occupancy right_hand → free/injured
- spatial floor clear → fragment obstacle active
```

只写“她打碎一个杯子”但不绑定实例，不能进入生产执行。若Story Truth故意不确定是哪一件，记录`INSTANCE_IDENTITY_UNRESOLVED`和候选集合，不得伪造确定答案。

## 11. 遮挡、离画与重新出现

```text
Presence ≠ Visibility
Occluded ≠ Destroyed
Off-frame ≠ Removed
Inside Container ≠ Nonexistent
```

实例离画或被遮挡时保持最后合法状态、Holder/Container和Anchor历史。重新进入画面必须恢复：

- 同一INSTANCE ID。
- 同一SPEC revision。
- 所有仍Active的CT状态。
- 合法Holder/Container/Anchor。
- 与离画期间事件一致的变化。

若两件完全同款在遮挡区发生交换且故事未揭示具体身份，标记身份未决；不要让模型随机决定后再反写Canon。

## 12. 破坏、消耗、拆分与合并

### 破损但仍是同一实体

瓶子凹陷、文件撕裂但残片仍作为整体剧情对象追踪时，保持同一INSTANCE并进入新CT。

### 拆分为多个可追踪实体

若破碎后某块碎片单独承担剧情作用，创建子实例并记录：

```text
SPLIT_EVENT
parent_instance
parent_exit_status = TRANSFORMED
child_instance_ids
mass/count interpretation
```

不得同时保留完整父物体和无来源碎片。

### 消耗品与容器

容器和内容物分开：

```text
Bottle Instance = 物理容器
Content State = 液体类型、余量、污染、温度
```

喝掉液体通常改变内容余量，不会让瓶子实例消失。用完药片可让药片实例/批次`CONSUMED`，药瓶仍存在。

### 合并与替换

维修、灌装、装配或合并必须写输入实例、事件、结果实例/状态和退出身份。不得用外观变得相似来替代物理身份规则。

## 13. SCSTATE执行合同

SCSTATE按实例读取：

```text
Appearance Source: PROP_SPEC_001_V01
Physical Entity: PROP_INST_002
Current State: PROP_INST_002_CT01
Holder / Hand: CHAR_001 / right
Zone / Anchor: ZONE_A / TABLE_EDGE
Visibility: VISIBLE_FULL
Forbidden: PROP_INST_001_CT01, future breakage, extra duplicate
```

SCSTATE必须同时冻结：

- 当前Active Instance ID清单。
- 每个实例的Appearance Source、状态、Holder和位置。
- `Object Count Lock`及Visibility bucket。
- SET库存与本状态已物化实例。
- 未激活、已销毁或属于其他线程的实例禁入。

同款实例可呈现相同外观，但不得融合成一件、复制成额外一件或交换状态。

## 14. Storyboard执行合同

每个有道具的KF写：

```text
PROP INSTANCE BINDING
- instance_id
- appearance_spec_id + revision
- current_state_id
- holder / hand / container
- zone / anchor / orientation
- action_role
- visibility_bucket
- entry_state / exit_state

OBJECT COUNT LOCK
- active_instance_total
- visible_full / visible_partial / occluded / off_frame
- count-changing_event_or_none
```

Storyboard图上不需要显示内部ID水印；ID属于生产合同。动作路径和相邻KF连续性必须让目标实例可追踪。

一个实例离画后重新入画，仍沿用同一ID和状态。不得因不同机位或遮挡生成“同款替身”。

## 15. Video执行合同

每个时间窗口使用实例绑定动作：

```text
Actor: CHAR_001
Target Instance: PROP_INST_002
Source Holder/Anchor: TABLE_A
Trajectory: table → right hand → floor
First Contact: 06.2s
State Activation: PROP_INST_002_CT01 broken at 06.4s
Exit Holder: NONE
Exit Anchor: FLOOR_A
Object Count: unchanged; one instance transformed, no duplicate
```

Video必须：

1. 保持SPEC外观一致。
2. 保持INSTANCE物理身份和动作轨迹一致。
3. 只把Delta施加给事件绑定实例。
4. 遮挡期间继续维护存在和状态。
5. 只有Count-changing Event才能增减物体总量。
6. 禁止瞬移、克隆、融合、无交接换手、销毁后完整重生。

## 16. 生产提示词模块

### PROP_SPEC生成

```text
【TASK】创建{PROP_SPEC_ID} Canonical Prop Appearance Specification。

该资产只定义所有同规格实例共享的产品外观，不代表故事世界中的某一件实物。

【SPEC AUTHORITY】
类别/产品身份：{...}
尺寸与比例：{...}
几何与结构：{...}
材质与表面：{...}
颜色系统：{...}
固定标签/文字/版式：{...}
共同永久标记：{...}
合法变体：{...或NONE}

【PRESENTATION】
以中性多视图清楚展示同一规格；不加入Holder、Hand、场景、损坏、污渍、余量、实例序号或剧情动作。

【OUTPUT】
输出{PROP_SPEC_ID} Canonical Prop Specification Sheet。
```

### PROP_INSTANCE逻辑物化

```text
Target Instance: {PROP_INST_ID}
Appearance Source: {PROP_SPEC_ID + revision}
Source Set: {SET_ID_or_NONE}
Materialization Event: {event}
Instance Identity Marks: {canon marks_or_NONE}
Entry Holder / Container / Anchor: {...}
Entry State: {...}
Lifecycle Rule: {...}
Visual Asset: LOGICAL_ONLY，除非满足独有持续外观条件
```

### PROP_INSTANCE_CT生成

```text
【TASK】创建{PROP_INST_CT_ID}，表现{PROP_INST_ID}在{story_time}的完整持续状态。

Image 1 = {PROP_SPEC_REFERENCE或previous_CT}
MUST PRESERVE：SPEC revision与所有仍Active的实例状态。
MUST TRANSFORM：{仅属于该INSTANCE的新Delta}。
MUST NOT COPY：Holder、Hand、Pose、Camera、Background和无关场景。
FORBIDDEN：把Delta施加到其他同规格实例；恢复旧状态；提前出现未来状态；擅自增加独有划痕。

输出{PROP_INST_CT_ID} Canonical Instance State Reference。
```

## 17. 示例

### 会议室20把同款椅子

```text
PROP_SPEC_CHAIR_01_V01
PROP_SET_MEETING_CHAIRS_01: supply=20, zone=meeting_room
```

角色拉出一把椅子坐下：

```text
EVENT_MATERIALIZE_CHAIR_01
PROP_SET available 20 → 19
PROP_INST_CHAIR_07 created and bound to chair position A7
Total chairs remains 20
```

不生成20张椅子资产图。只生成SPEC Reference；`PROP_INST_CHAIR_07`通过合同和SCSTATE保持位置与状态。

### 两支同款医疗注射器

```text
PROP_SPEC_SYRINGE_01_V01
PROP_INST_SYRINGE_01: tray, sealed, clean
PROP_INST_SYRINGE_02: doctor right hand, opened, used
```

两者外观规格相同，但Holder、包装、内容状态、事件和生命周期完全独立。`PROP_INST_SYRINGE_02`被使用不能让`PROP_INST_SYRINGE_01`同步变空。

## 18. 硬规则与审计

### 十二条核心硬规则

1. PROP_SPEC不是Physical Entity。
2. PROP_INSTANCE必须绑定一个Appearance Source。
3. 同SPEC实例拥有独立物理ID、状态、Holder、位置和生命周期。
4. 实例从SPEC物化，不从另一个实例物化。
5. 同SPEC允许完全同外观，不得擅自制造差异。
6. CT绑定具体INSTANCE，不绑定整个SPEC。
7. Event必须绑定具体INSTANCE或明确未决候选集。
8. Holder/Owner/Container/Anchor必须分开记录。
9. Occluded、Off-frame和Contained都不等于不存在。
10. Object Count只能由合法事件改变。
11. SCSTATE、Storyboard和Video必须继承INSTANCE Binding与Count Lock。
12. 已销毁、消耗或退出的实例不得无事件完整重现。

### 交付审计

- [ ] 重复同款物件是否建立了SPEC，而不是共用一个Physical ID？
- [ ] 背景批量物件是否优先使用SET，避免资产爆炸？
- [ ] 每个交互、状态变化和Holder变化是否绑定具体INSTANCE？
- [ ] 同款实例是否错误共享CT或被人工改色区分？
- [ ] 每个时间点的Active Instance Count能否对账？
- [ ] 可见、部分可见、遮挡和离画是否与存在状态分开？
- [ ] 破坏、消耗、拆分、合并和容器内容是否有父子/余量记录？
- [ ] SPEC revision是否有生效范围，旧实例是否避免被反向改版？
- [ ] SCSTATE、KF与Video Window是否写了Instance Binding与Object Count Lock？
- [ ] 重新入画的物体是否恢复同一ID、状态和合法空间历史？
