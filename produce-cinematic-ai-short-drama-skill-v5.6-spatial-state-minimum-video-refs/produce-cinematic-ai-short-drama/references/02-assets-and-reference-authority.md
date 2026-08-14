# 资产与参考权威

## 目录

1. 资产生产闭环
2. 资产树与命名
3. Canonical Reference最高规则
4. Derived Asset Transformation Contract
5. Production Reference Manifest
6. 参考容量与最小充分集
7. 人物资产
8. 地点与空间资产
9. 道具、载具、生物、群体和VFX
10. 生产状态与交付顺序
11. 资产常见失败

## 1. 资产生产闭环

执行：

```text
当前Production Scope
↓
解析真正需要的资产
↓
在Canonical Asset Registry检查/分配完整Revision ID
↓
建立Required Asset List
↓
标记NEW / EXISTING_CANONICAL / LOGICAL_ONLY / DEFERRED
↓
按依赖拓扑排序
↓
为每个NEW资产生成Reference Manifest
↓
生成ONE COMPLETE production_prompt
↓
生产并确认Canonical Asset
↓
登记精确文件名、路径、角色与Fingerprint
↓
作为下游Parent Authority
```

分析全剧、只生产EP01时，登记未来Blueprint，但不提前物化所有未来资产。避免资产爆炸、未来剧透和无效返工。

资产依赖不是固定“先人物再场景再道具”，而是有向无环依赖：

```text
Story / Character Rules → CHAR
CHAR → PH
World / Costume Rules → COST Visual Asset或LOGICAL_ONLY Costume Contract
selected PH + resolved COST → complete LOOK
LOOK或previous CT + Continuity Delta → CT
World / Location Rules → LOC
Topology / Scale / Coordinates → SPATIAL → GEO_PROXY
LOC + SPATIAL + GEO_PROXY → LOC_VIEW → LOC_VIEWSET / PR
Story Truth → PROP_SPEC → PROP_SET / PROP_INSTANCE → PROP_INSTANCE_CT
Story Truth → unique PROP / VEH / CRE / VFX
CVS + Canonical Components → SCSTATE
```

## 2. 资产树与命名

所有示意Local ID在实际生产时都必须解析为[Canonical ID注册表与参考资产解析](10-canonical-id-registry-and-resolution.md)规定的完整Canonical Revision ID。例如本节的`CHAR_001_PH01_LK01_CT01`实际输出为`PRJ_NOVA__CHAR_001_PH01_LK01_CT01_R01`。后续不得退回Local ID或缩成`CT01`。

### 人物树

```text
CHAR_001
├── CHAR_001_PH01
│   ├── CHAR_001_PH01_LK01
│   │   ├── CHAR_001_PH01_LK01_CT01
│   │   └── CHAR_001_PH01_LK01_CT02
│   └── CHAR_001_PH01_LK02
└── CHAR_001_PH02
```

PH是CHAR下的阶段分支，不是PH01连续生长为PH02。CT才是同一LOOK下的持续状态链。

### 地点树

```text
LOC_001
SPATIAL_001_R01
LOC_001_GEO01
LOC_001_VIEW_A01
LOC_001_VIEWSET01
LOC_001_PR01
LOC_001_CT01       # 仅当环境持续视觉状态需要独立资产
```

### 其他资产

```text
PROP_001 / PROP_001_CT01                    # 唯一且无同款歧义
PROP_SPEC_001_V01                           # 共同外观规格
PROP_SET_001                                # 未逐件追踪库存
PROP_INST_001 / PROP_INST_001_CT01          # 唯一物理实体及其状态
VEH_001 / VEH_001_CT01
CRE_001 / CRE_001_CT01
GRP_001
VFX_001
SCSTATE_EP01_SC03_ST01
```

同一Physical Entity改变功能或空间角色时继续同一Identity，除非它真的成为新实体。例如同一扇门从出口变成封锁点，不创建第二个PROP。

## 3. Canonical Reference最高规则

冻结：

```text
Canonical Reference ≠ Pixel Copy Target
Identity Lock ≠ Pixel Lock
State Lock ≠ Pose Lock
Geometry Lock ≠ Camera Lock
Costume Lock ≠ Composition Lock
SCSTATE Lock ≠ Shot Lock
Storyboard Lock ≠ Still-image Morph Target
```

下游继承Reference的Authority，不默认继承其表现形式。

统一执行：

```text
REFERENCE AUTHORITY EXTRACTION
↓
CANONICAL PRESERVATION
↓
TARGET DELTA RESOLUTION
↓
NEW ASSET RECONSTRUCTION
```

禁止默认：

```text
Reference → Copy → Minor Edit
```

参考图里的Pose、Camera、Composition、Background、Lighting、Expression、示例Blocking、Sheet Layout，仅在该Reference明确拥有对应Authority时才可继承。

## 4. Derived Asset Transformation Contract

任何有Parent Reference的派生任务必须写：

```text
REFERENCE ID
AUTHORITY TYPE
MUST PRESERVE
MUST TRANSFORM
MUST NOT COPY
DOES NOT CONTROL
APPLICABLE SCOPE
REQUIRED VISUAL DELTA
```

### MUST PRESERVE

列出Parent真正拥有的Canonical信息。例如CHAR保留骨相和五官几何，COST保留服装结构与材质。

### MUST TRANSFORM

列出本次目标需要产生的新阶段、新状态、新组合或新观察。例如PH改变年龄阶段，LOOK将COST穿到当前PH上。

### MUST NOT COPY

列出不得像素继承的Pose、Camera、构图、背景、灯光、无关表情、示例人物和Sheet排版。

### DOES NOT CONTROL

列出该Reference没有Authority的维度，防止模型用“看得到”替代“有权决定”。

### REQUIRED VISUAL DELTA

回答：

> 目标ID与Parent不同，画面上必须具体哪里不同？

如果无法回答，检查是否真的需要新资产。

## 5. Production Reference Manifest

每次生成调用都先给生产人员Manifest，再给Prompt。没有参考图也明确写`Reference Count: 0 / NONE`。

标准格式：

```text
【PRODUCTION TARGET】
Target Canonical Revision ID:
Target Type:
Parent Dependency:
Registry Snapshot ID:

【REFERENCE INPUT MANIFEST】
Reference Count: N

Image 1
Exact Canonical Revision ID:
Exact Canonical Filename:
File Role:
Canonical Relative Path:
Resolved Local Path / Asset URI:
SHA-256 Fingerprint:
Availability: VERIFIED
Asset Identity:
Who / What + Visible Content:
Story Time / Current State:
Authority Type:
MUST PRESERVE:
MUST TRANSFORM:
MUST NOT COPY:
DOES NOT CONTROL:
Applicable Scope:

Image 2
...

【UPLOAD ORDER】
Image 1 → Image 2 → ...

【COMPACT REFERENCE IDENTITY MAP】
Image 1 = {Exact Canonical Revision ID}
Who / What + Visible Content: {自然语言主体/资产身份及图中可见内容}
Story Time / Current State: {年龄/阶段/LOOK或CT/事件前后/Thread}
Controls: {本次有权控制内容}
Does Not Control: {本次无权控制内容}
Applicable Scope: {目标/KF/时间窗口}

【ONE COMPLETE production_prompt】
...
```

硬规则：

1. Image编号属于当前调用，不是全剧永久编号。
2. Target、Parent和Reference ID只能从同一Registry Snapshot逐字符复制完整Canonical Revision ID。
3. Manifest与Prompt内部ID、Image编号和文件角色完全一致。
4. 明确精确文件名、路径/URI、Fingerprint、Availability、用途、Authority、适用KF/时间范围和不控制范围。
5. 禁止缩写、别名、显示名称替代、模糊匹配和自动选择最新Revision。
6. 任一Reference未通过Exact Resolution时阻断Prompt，不要求生产人员自行猜图。
7. 不单独使用“完全按照Image 1”“保持Image 1不变”“严格复制Reference”。
8. 最终Prompt内逐Image回显六字段紧凑身份映射；`Image 1`不能只写Authority，必须用自然语言说明它是谁/是什么以及处于哪个Story Time与Current State。
9. 身份、状态或适用范围缺失，或上传顺序与映射不一致时输出`REFERENCE_MAPPING_BLOCKED`；该检查复用现有Manifest，不创建新资产类型或第二套注册表。
10. 单图含多人、多Panel或多时间状态时，在`Who / What + Visible Content`内按Panel/区域绑定完整ID和当前状态；不能把整图笼统写成“人物参考”。

## 6. 参考容量与最小充分集

Minimum Sufficient Reference Set不是越少越好，而是用最少冲突锁住全部关键Authority。

超出模型容量时按顺序降载：

1. 使用高层融合资产代替低层资产：CT代替CHAR+PH+LOOK。
2. 已融合进LOOK/CT的Wearable Prop不重复上传。
3. 非关键背景角色合并为GRP。
4. 非Hero Prop由PR/SCSTATE文字合同约束，不单独Reference。
5. 使用局部Composite Authority Reference，但明确它不是新Canon。
6. 按Thread、Location或Temporal Reference Window隔离执行输入。
7. 最后才调整SCSTATE/Storyboard呈现粒度，不删除关键Authority。

若两个Reference控制同一维度，必须明确Authority Priority；不能让模型平均融合。

## 7. 人物资产

### 7.1 CHAR｜Permanent Identity Root

回答“这个人是谁”。固定：

- 核心骨相与五官几何关系。
- 眼、鼻、嘴、下颌Identity。
- 基础身体Identity比例。
- 肤色与永久辨识特征。

不固定：

- 精确Story Age、当前长期发型、胡须、体型阶段。
- 剧情服装、伤势、污染、情绪、Pose和场景。

首次建立无参考图时，使用中性展示服，不把它认定为剧情COST。

### 7.2 PH｜Persistent Appearance Phase

回答“同一个人在某个长期时期是什么外观”。它是Identity-Preserving Appearance Transformation。

可控制：

- 明显年龄阶段。
- 长期发型、胡须、体型、长期生理阶段。
- 长期基础外观变化。

不控制剧情服装、伤口、污渍、当前Pose或当前情绪。

### 7.3 COST｜Costume Visual Identity或逻辑合同

定义服装结构、剪裁、层次、材质、颜色、纹样、固定配件、鞋履和穿着方式。COST不控制人物脸、身体、发型和Pose。

关键、复杂、复用、标志性、需要独立审批或会成为剧情对象的服装，物化独立Canonical COST图。一次性、简单、非关键服装可登记为`LOGICAL_ONLY`完整文字合同，直接与PH重建LOOK。两种路径都不得跳过LOOK。详细决策读取[服饰资产、完整LOOK与首次显露覆盖](12-costume-look-and-visual-coverage.md)。

当关键文字、徽章或标识具有剧情意义时，建立可读Canon；不要让生图模型随机生成。

### 7.4 LOOK｜PH + COST Reconstruction

回答“当前PH人物真实穿上某个COST后的完整人物视觉表现”。

```text
Character / PH Identity Authority
+ COST Authority
↓
NEW FULL CHARACTER LOOK RECONSTRUCTION
```

LOOK不是局部换衣编辑。任何单一Reference都不控制最终构图。LOOK形成后，Storyboard中当前服装Primary Authority属于LOOK；不要默认同时用LOOK和COST重复控制同一服装。

LOOK必须完整覆盖当前人物头到脚、身体比例、服装穿着比例、正侧背、下装、鞋履、衣长、层次和背面结构。视频会显露Storyboard裁切外区域时，LOOK/CT Coverage Package提供这些区域的唯一Authority。

### 7.5 CT｜Continuity Visual State Asset

定义：基于当前Production Representation，需要跨独立生产单元稳定复现的完整持续视觉状态。

```text
current LOOK或previous CT
+ all still-active previous state
+ new canonical delta
↓
NEW COMPLETE RESOLVED CHARACTER STATE
```

CT不是`clean LOOK + 伤口贴纸`，也不是并行的`CT_INJURY + CT_WET + CT_DIRTY`效果层。一个当前CT必须是完整合并状态。

CT可包含：伤口、血迹、贴片、湿度、泥污、妆容破坏、持续疲劳、烧伤、服装破损等。

CT不包含Scene Blocking，例如双手撑桌、躺地、抓住某人。持续影响外观的身体状态可进入CT；当前姿态进入CVS/SCSTATE。

生成CT02时，Parent必须是CT01而不是退回Clean LOOK，除非Canonical Replacement明确重置了所有旧状态。

## 8. 地点与空间资产

本节只定义分层；完整坐标、Geometry Proxy、Canonical Location View、闭环校验和World Placement规则读取[空间坐标、机位Rig与多视角一致性](11-spatial-rig-and-multiview-consistency.md)。

### 8.1 LOC｜Location Visual Identity

回答地点“长什么样”：建筑语言、材质、色彩、固定门窗/设施的视觉设计、地域文化和长期识别特征。

### 8.2 SPATIAL｜Spatial Master

回答地点“如何构成”：统一World坐标、单位、尺度、Topology、Zone、Anchor XYZ、Route、连接关系、固定结构位置和Landmark。高风险空间必须建立3D或2.5D Geometry Proxy。可用平面/轴测表达，但Sheet排版没有Camera Authority。

### 8.3 LOC_VIEW｜Canonical Location View

每个视角从同一Spatial Revision与Geometry Proxy按明确Camera Rig单独生成、闭环核对并登记。禁止用一句“同一场景多个角度”让图像模型同时自由设计多视角。多视图Sheet只能汇编已批准View，不得成为新的几何生成调用。

### 8.4 PR｜Location Production Reference

```text
LOC Appearance Authority
+ Current SPATIAL / GEO_PROXY Geometry Authority
+ approved LOC_VIEW index
↓
NEW LOCATION PRODUCTION REFERENCE
```

PR不是复制LOC图片，也不是复制Spatial示意图排版。它不能自动决定人物位置和最终Camera。若View之间无法由同一组World坐标解释，PR不得冻结为Canonical。

### 8.5 Location CT

仅当环境持续视觉状态跨生产单元、视觉重要且需要稳定复现时建立，例如烧焦墙面、长期积水、被封门、爆炸后结构损坏。临时可自然生成的小杂物不必资产化。

## 9. 道具、载具、生物、群体和VFX

### PROP

全剧唯一且不会与同款物件混淆的Hero Prop，可用`PROP_001`同时承载外观和单件物理身份。

出现两件以上同型号、同版式或同外观物件时，必须读取[PROP规格、物理实例与数量连续性](08-prop-spec-and-physical-instance.md)，并分离：

```text
PROP_SPEC = 共同外观规格
PROP_SET = 可选的未追踪同款库存
PROP_INSTANCE = 唯一Physical Entity
PROP_INSTANCE_CT = 该实例的完整持续状态
```

`PROP_SPEC`固定共同尺寸、材质、颜色、结构、版式、可读文字和产品身份；它不拥有Holder、Hand、Owner、Anchor、当前损坏或生命周期。

`PROP_INSTANCE`拥有自己的物理ID、Holder/Container、位置、状态、事件和连续性历史。同SPEC实例允许完全同外观，不得为模型区分而擅自改色、加划痕或改标签。

`PROP_SET`只用于背景批量库存。某一件开始被拿取、移动、损坏、特写或承担因果时，通过`SET_MATERIALIZATION`事件物化为唯一INSTANCE；SET数量减一、实例数量加一，总物理数量不变。

Logical Instance不等于必须生成独立图片。共同外观Reference使用SPEC；只有实例存在可见、持续、独有状态时才生成INSTANCE CT Reference，防止20件同款道具产生20张无意义重复资产。

### VEH

固定车型/结构、比例、材质、颜色、永久损伤与内外空间关系。当前车门、灯光、载荷、破损等用VEH CT或CVS表达。

### CRE

固定非人类生物Identity、骨骼/身体结构、材质和永久特征。长期变异阶段可用PH式分支，临时伤势用CT。

### GRP

定义群体类型、人数范围、服装逻辑、密度、队形或行为类别。GRP不替代重要个体角色资产。

### VFX

定义能力/效果的视觉语言、颜色、形态、尺度、运动规律和可见生命周期。VFX必须有Activation Event；未来VFX不得从第一帧存在。

## 10. 生产状态与交付顺序

每项资产输出：

```text
asset_family_id
canonical_revision_id
asset_type
status
registry_snapshot_id
canonical_filename / file_role
relative_path / resolved_path
sha256 / availability
story_scope
dependency
canonical_authority
reference_manifest
production_prompt
required_visual_delta
downstream_usage
```

状态：

- `NEW`：本次必须生产并确认。
- `EXISTING_CANONICAL`：调用已有Canon，不重复生成。
- `LOGICAL_ONLY`：逻辑阶段存在，但当前无需单独图片。
- `DEFERRED`：未来范围需要，本次只登记Blueprint。

禁止把“已经生成过”自动等同于`CANONICAL`。只有用户选定或体系明确确认的版本才能进入Production Resolution。

## 11. 资产常见失败

| 失败 | 原因 | 修正 |
|---|---|---|
| PH像Root重画 | 把Identity Lock写成Pixel Lock | 明确年龄/阶段Target Delta和MUST NOT COPY |
| LOOK像贴衣服 | 把派生当局部编辑 | 要求完整人物重建，分离PH与COST Authority |
| 服装图存在但视频穿着比例漂移 | 把COST当下游人物服饰主权威 | 先生成穿在当前PH上的完整LOOK |
| 简单服装资产爆炸 | 所有COST都强制出图 | 简单非关键COST设LOGICAL_ONLY，仍生成LOOK |
| 故事板半身、视频全身随机 | LOOK/CT覆盖不完整 | First Reveal Coverage Gate；补覆盖或限制Camera |
| CT旧伤消失 | Parent退回LOOK | 使用previous CT并展开Active State |
| CT继承地面Pose | 把Scene Blocking误当人物状态 | 将Pose移到CVS/SCSTATE |
| PR复制LOC机位 | 未区分Geometry与Camera | 写Geometry Lock ≠ Camera Lock |
| 同一Location不同视角拼不起来 | 多视角分别自由生成 | 同一Spatial/GEO_PROXY逐View投影并闭环核对 |
| 人物随视角换Zone | 只用画面左右描述位置 | CVS/SCSTATE写World XYZ、Anchor Offset和朝向 |
| Prop样式变化 | 未绑定同一PROP ID | 固定Identity、版式、尺寸、文字Canon |
| 两件同款被当成一件 | SPEC与Physical Instance未分离 | SPEC共享外观，INSTANCE独立持有状态与历史 |
| 遮挡后多出/少一道具 | 未维护Existence与Count | Instance Registry + Object Count Lock |
| 同款实例被随机改色 | 用视觉差异代替物理ID | 允许同外观，用ID、Holder、Anchor与事件区分 |
| 批量道具资产爆炸 | 每件同款都生成图片 | PROP_SET + 单一SPEC Reference，交互时物化 |
| 前面完整ID后面写CT01 | 把ID当显示名称 | 所有ID从Registry复制完整Revision ID，禁止缩写 |
| ID存在但找不到图片 | ID与文件未登记一对一关系 | Manifest输出精确文件名、路径、角色、Fingerprint和Availability |
| 同一ID指向新旧两张图 | Canonical文件被覆盖 | Revision不可变；修改创建R02并显式回编 |
| Reference自动选相近资产 | 使用模糊/最近匹配 | Exact Resolution失败即阻断，不猜测 |
| Image 1控制范围明确但身份不明 | Prompt只回显槽位与Authority | 增加六字段Compact Reference Identity Map；缺字段即REFERENCE_MAPPING_BLOCKED |
| 参考图混色/混人 | Authority范围不清 | Reference Firewall与Applicable Scope |
| 资产数量爆炸 | 每个微变化都物化 | 只生产当前可见、持续、重要且下游需要的状态 |
