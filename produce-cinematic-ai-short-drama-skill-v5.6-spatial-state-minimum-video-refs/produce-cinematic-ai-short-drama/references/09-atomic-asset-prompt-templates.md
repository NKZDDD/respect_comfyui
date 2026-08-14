# 原子资产完整提示词模板

## 目录

1. 使用规则
2. CHAR完整模板
3. PH完整模板
4. COST完整模板
5. LOOK完整模板
6. Character CT完整模板
7. LOC、SPATIAL、GEO_PROXY、LOC_VIEW与PR模板
8. Unique PROP与其他资产模板

## 1. 使用规则

本文件提供原子资产Prompt正文。每次生产仍须先使用[完整提示词与交付模板](06-production-prompt-library.md)中的单次调用格式，输出真实Reference Manifest、Upload Order、六字段`COMPACT REFERENCE IDENTITY MAP`和ONE COMPLETE `production_prompt`。每个Image槽必须说明完整ID、Who/What与可见内容、Story Time/Current State、Controls、Does Not Control和Applicable Scope；不能只写`Image 1 = {ID}`后让模型猜图中主体。

所有花括号在交付前解析为具体内容；资料确实未决时写`UNRESOLVED`或`OPEN DESIGN DEGREE REQUIRED`，不得保留空占位符。

若Reference文件已正确解析但上述语义映射缺失、错序或与Manifest不一致，返回`REFERENCE_MAPPING_BLOCKED`，不释放原子资产Prompt。该规则复用现有Manifest，不增加新资产层级。

重复同款道具不得使用本文件的Unique PROP模板，改读[PROP规格、物理实例与数量连续性](08-prop-spec-and-physical-instance.md)。

## 2. CHAR完整模板

```text
【TASK】

创建{CHAR_ID}的Canonical Character Identity Root，用于全剧后续PH、LOOK、CT、SCSTATE与Storyboard的人物身份继承。

本资产只建立“这个人是谁”，不表现具体Story Time、剧情服装、伤势、污渍、当前情绪、动作或场景。

【CANONICAL IDENTITY】

角色：{角色名}
性别与基础身份：{信息}
核心骨相：{脸型、颧骨、下颌、额头关系}
五官几何：{眼、鼻、嘴的形态与相对位置}
肤色：{信息}
基础身体Identity比例：{身高感、肩宽、躯干与四肢比例}
永久辨识特征：{信息或NONE}
地域/族裔/文化约束：{来自Story/World Bible}

原文未定义但为了稳定识别必须确定的非剧情细节，可建立自然可信的视觉答案；一旦被确认为Canonical，后续不得随机改写。

【NEUTRAL PRESENTATION】

使用简单、中性、纯色、无剧情身份属性的展示服。该服装只显示身体比例，不属于正式COST。

人物自然直立，中性表情、灯光和背景。输出FRONT、L45、PROFILE、BACK；高频主角可增加R45。所有视图必须是同一真实人物实例，完整显示头、手、脚，不裁切。

【AUTHORITY】

控制：Permanent Identity Anchors与基础身体Identity。
不控制：精确Story Age、长期发型阶段、剧情服装、伤势、妆容状态、表情、Pose、Location、Blocking、Camera或Lighting Style。

【FORBIDDEN】

不得加入剧情道具、剧情场景、伤口、血迹、污渍、文字、水印、其他人物或动作姿态。不得把展示服定义成正式造型。

【OUTPUT】

输出一张完整、清晰、无裁切的{CHAR_ID} Canonical Character Identity Sheet。
```

## 3. PH完整模板

Manifest：`Image 1 = {CHAR_ID}`，Authority为Permanent Identity。

```text
【TASK】

基于Image 1的Permanent Character Identity，重建{PH_ID}，表现同一个人物在{目标长期外观阶段}的Canonical Persistent Appearance Phase。

这不是复制Image 1或局部修图；执行Identity-Preserving Appearance Transformation。

【REFERENCE AUTHORITY】

Image 1 = {CHAR_ID}
MUST PRESERVE：核心骨相、五官几何、肤色、基础身体Identity与永久辨识特征。
MUST TRANSFORM：{年龄阶段、长期发型、胡须、体型、长期生理外观等}。
MUST NOT COPY：Root Pose、Camera、Composition、Background、Lighting、Sheet Layout、展示服和像素表情。
DOES NOT CONTROL：剧情COST、伤势、污渍、Scene Blocking、当前情绪和最终Camera。

【TARGET DELTA】

与Image 1相比必须清楚可见：{具体阶段差异}；同时一眼识别为同一个人。

【PRESENTATION】

中性展示服、站姿、表情和背景。输出FRONT、L45、PROFILE、BACK一致视图；完整显示身体，不裁切。

【FORBIDDEN】

不得改变Identity，不得加入剧情服装、伤势、道具或场景，不得复制Root构图或把目标变成另一个相似人物。

【OUTPUT】

输出{PH_ID} Canonical Persistent Appearance Phase Sheet。
```

## 4. COST完整模板

先按[服饰资产、完整LOOK与首次显露覆盖](12-costume-look-and-visual-coverage.md)判断是否物化。简单、一次性、非关键服装可将COST登记为`LOGICAL_ONLY`完整合同并直接生成LOOK；关键、复杂、复用、标志性或需要独立审批的服装使用下列Canonical Visual Asset模板。

```text
【TASK】

创建{COST_ID} Canonical Costume Visual Identity。该资产只定义服装本体，不绑定具体人物脸、身体、Pose或场景。

【STORY / WORLD CONSTRAINTS】

穿着者身份：{角色/职业/阶层/时期}
Story阶段：{阶段}
文化与地域：{信息}
功能需求：{行动、天气、身份、叙事用途}

【COSTUME DESIGN】

轮廓与层次：{信息}
上装：{领口、袖型、长度、闭合方式}
下装：{结构、长度、版型}
材质：{信息}
主色/辅色：{信息}
纹样/固定细节：{信息}
鞋履与必要配件：{信息}
剧情关键标识/文字：{明确Canon或NONE}

【PRESENTATION】

以正面、侧面、背面和关键细节清楚展示同一套服装；背景中性，避免人物脸成为Authority。使用无Identity人台、幽灵模特或平铺组合，完整显示鞋履、背面、内外层和衣长。

【AUTHORITY】

控制服装结构、材质、颜色、纹样、固定配件和穿着方式；不控制人物Identity、PH、身体、发型、Pose、Location、伤势、污渍和当前Lighting。

【OUTPUT】

输出{COST_ID} Canonical Costume Identity Sheet。
```

## 5. LOOK完整模板

Manifest：路径A为`Image 1 = {PH_ID}`、`Image 2 = {COST_ID}`；路径B为`Image 1 = {PH_ID}`并在Prompt中展开已解析的`LOGICAL_ONLY Costume Contract`。

```text
【TASK】

创建{LOOK_ID}。重新构建Image 1中的同一人物真实穿上Image 2服装后的完整Canonical Character LOOK。

LOOK不是对Image 1局部换衣，不复制任一Reference构图；必须生成新的完整人物资产。

【REFERENCE ROLE MAP】

Image 1 = {PH_ID}
Authority：Character Identity + Current PH。
MUST PRESERVE：脸、骨相、五官、目标年龄感、长期发型、身体比例和永久特征。
DOES NOT CONTROL：剧情服装、最终Pose、Camera、Background。

Image 2 = {COST_ID}
Authority：Costume Visual Identity。
MUST PRESERVE：轮廓、领口、袖型、长度、层次、材质、颜色、纹样、鞋履和固定细节。
DOES NOT CONTROL：人物脸、身体、年龄、发型、Pose和Camera。

若COST为LOGICAL_ONLY：不得伪造Image 2；在此处逐项展开服装轮廓、层次、领口、袖型、闭合、材质、颜色、长度、背面、鞋履、固定配件和穿着方式，并声明该合同控制服装设计但不控制人物Identity与Pose。

【TARGET RECONSTRUCTION】

让Image 1的同一人物自然、完整地穿着Image 2。处理衣物与当前身体比例、肩线、腰线和动作自由度的真实结合，不得改成相似款。

Required Visual Delta：{人物完整进入该剧情服装的具体结果}。

【MUST NOT COPY】

不得复制任一Reference的Sheet排版、Pose、Camera、Background、Lighting或无关示例。

【PRESENTATION】

中性站姿和表情，输出FRONT、L45、PROFILE、BACK；完整显示头、双手、双腿和双脚，不得裁切。所有视图保持同一Identity、PH和COST，并明确肩线、腰线、臀部贴合、衣长、下装、背面结构、鞋履和固定穿戴配件。必要时增加验证穿着功能的抬臂/坐姿细节，但不形成Scene Blocking。

【VISUAL COVERAGE MAP】

DEFINED：face/head、front torso、back torso、left/right profile、arms/hands、waist/hip、legs、footwear、rear full body。
若任一区域无法定义，不得将本LOOK标记为Coverage-complete。

【FORBIDDEN】

不得重新设计脸、身体、发型或服装；不得加入未来伤势、泥污、血迹、剧情道具、Scene Blocking或其他人物。

【OUTPUT】

输出{LOOK_ID} Canonical Character LOOK Sheet。
```

## 6. Character CT完整模板

Manifest：`Image 1 = {current_LOOK_or_previous_CT}`。生成CT02及以后必须优先使用previous CT。

```text
【TASK】

创建{CT_ID}，把Image 1重建为当前Story Time下完整、合并、可跨生产单元持续复现的Character Continuity Visual State。

CT不是在Clean LOOK上贴伤口；必须重建人物皮肤、服装、湿度、污染、疲劳和所有Active State之间一致的完整视觉结果。

【STORY TIME】

Activation Event：{事件}
Activation Story Time：{时间}
Persistence：{持续规则}
Replacement / Deactivation：{条件或UNKNOWN}

【REFERENCE AUTHORITY】

Image 1 = {parent_id}
MUST PRESERVE：人物Identity、当前PH、LOOK、服装和仍Active的Previous State：{逐条列出}。
MUST TRANSFORM：新增Canonical Delta：{位置、形态、程度、材质/湿度/血迹关系}。
MUST NOT COPY：Parent Pose、Camera、Composition、Background、Lighting和Scene Blocking。
DOES NOT CONTROL：具体Location位置、手持关系、动作过程和最终Shot。

【COMPLETE RESOLVED STATE】

皮肤/伤势：{信息}
治疗/贴片/纱布：{信息}
血迹：{信息}
污染/泥污：{信息}
湿度：{信息}
服装破损：{信息}
妆容/头发持续变化：{信息}
疲劳/生理状态：{信息}
Not Yet Active：{未来状态}

【TARGET DELTA】

清楚显示：{与Parent相比的具体结果}；所有未被替换的旧状态保留原位置、形态和程度关系。

【PRESENTATION】

中性展示姿态和简单背景，输出能清楚复现状态的多视图。只为覆盖重要状态调整展示角度，不引入Scene Blocking。

【CURRENT VISUAL COVERAGE】

继承Parent完整身体与服饰覆盖。列出本CT中`DEFINED / TEXT_ONLY / UNDEFINED`区域，以及所有Active State在正侧背、下装、鞋履或其他可能显露区域的表现。大范围湿衣、泥污、破损或血迹必须生成Coverage-complete CT；不得让Clean LOOK覆盖Current CT。

【FORBIDDEN】

不得恢复Clean LOOK，不得丢失、移动、减弱或重设计仍Active状态，不得提前加入未来状态，不得改变Identity、PH、服装和身体比例。

【OUTPUT】

输出{CT_ID} Canonical Complete Character Continuity State Sheet。
```

## 7. LOC、SPATIAL、GEO_PROXY、LOC_VIEW与PR模板

### LOC

```text
【TASK】创建{LOC_ID} Canonical Location Visual Identity。

地点身份：{名称/功能/地域/时代/社会阶层}
建筑语言：{信息}
材质与色彩：{信息}
固定门窗/设备/家具视觉设计：{信息}
长期Landmark：{信息}
世界规则与文化约束：{信息}

以中性、可读的Appearance Reference展示建筑语言、材质、色彩和固定设施设计。LOC可包含风格示例，但不把示例透视和摆放提升为Geometry Canon；不得要求模型在一张Sheet里独立发明互相矛盾的完整多视角。不得加入剧情人物、临时Prop、未来破坏、水印或无关场景。

控制Location Appearance，不控制人物位置、Current Spatial State、Blocking或最终Camera。

输出{LOC_ID} Canonical Location Identity Sheet。
```

### SPATIAL

```text
【TASK】创建{SPATIAL_ID} Canonical Spatial Master Reference。

Topology：{空间拓扑}
Coordinate Origin / Axis / Unit：{原点、+X/+Y/+Z、meter}
Zones：{列表}
Anchors XYZ：{完整ID、xyz、朝向、所属Zone}
Routes：{有序Anchor路径与连接}
Fixed Geometry：{墙、门、窗、走廊、床位等的尺寸/BBox}
Landmarks：{列表}
Scale / Distance：{关键尺寸关系}
Revision：{R01及修订原因}

使用平面、轴测和必要方向视图清楚表达同一Physical Location。所有视图保持几何一致。示意排版不拥有最终Camera或Composition Authority。

输出{SPATIAL_ID} Canonical Spatial Master Reference。
```

### GEO_PROXY

Manifest：`Image 1 = {SPATIAL_ID}`；LOC仅可作为材质标签参考，不得改变几何。

```text
【TASK】

创建{GEO_PROXY_ID}，把{SPATIAL_ID}物化为可从任意批准机位一致投影的Geometry Proxy。

严格使用指定World Origin、Axis、Meter Scale、Level、Boundary、Wall/Openings、Fixed Furniture BBox、Anchor XYZ和Route。使用简化中性材质，以几何、遮挡、比例和连接关系可验证为目标。

输出平面、轴测和必要立面/3D块模视图。所有视图必须来自同一物理模型；不得改变门窗数量、镜像、补建房间、移动家具或复制示意图排版。

输出{GEO_PROXY_ID} Canonical Geometry Proxy。
```

### LOC_VIEW

Manifest：`Image 1 = {LOC_ID}`、`Image 2 = {SPATIAL_ID}`、`Image 3 = {GEO_PROXY_ID}`，以及必要的相邻已批准View。

```text
【TASK】

创建单一视角{LOC_VIEW_ID}。从Image 3同一Geometry Proxy的指定Camera Rig投影空间，并应用Image 1的Location Appearance。不得独立重新设计空间。

【CAMERA RIG】

Camera XYZ：{xyz meter}
Look-at XYZ：{xyz meter}
Height / Yaw / Pitch / Roll：{信息}
Lens mm / Horizontal FOV：{信息}
Aspect Ratio：{信息}

【VIEW CONTRACT】

Visible Zones：{列表}
Occluded Zones：{列表}
Visible Landmarks：{列表}
Scale Anchors：{列表}
Overlap Landmarks with Approved Adjacent Views：{至少两个或NONE}

Image 1控制材质、色彩、建筑语言和固定设施视觉Identity；Image 2/3控制World Geometry、尺度、透视、遮挡和相对位置。相邻View只用于Overlap校验，不控制本View Camera。

禁止人物、临时Prop、未来破坏、空间镜像、门窗增减、固定家具移位和多格新视角。输出一张{LOC_VIEW_ID} Canonical Location View。
```

### PR

Manifest：`Image 1 = {LOC_ID}`，`Image 2 = {SPATIAL_ID}`，后续Image为已批准`LOC_VIEW`；高风险场景同时解析`GEO_PROXY`。

```text
【TASK】

创建{PR_ID}，把Image 1的Location Appearance、Image 2的Spatial Geometry和已批准Canonical Location Views登记为新的Location Production Reference。

Image 1控制建筑语言、材质、色彩、门窗/设施视觉Identity和文化地域。
Image 2控制Topology、Zone、Anchor、Route、Landmark和固定结构位置。

保留各自Authority；PR只汇编/索引已经通过闭环的View，不重新自由生成另一套多视角。不得复制Image 1原始Camera或Image 2示意排版。不得加入人物、当前Prop Holder、临时剧情动作或未来Location CT。不得移动固定结构、镜像空间或改变连接关系。

使用已批准的中性广角/中广角View清楚展示关键Landmark与空间连接。任何View若无法由同一World坐标解释，停止输出并返回`MULTIVIEW_RECONCILIATION_BLOCKED`。

输出{PR_ID} Canonical Location Production Reference。
```

## 8. Unique PROP与其他资产模板

### Unique PROP

仅用于全剧唯一且无同款身份歧义的物理道具。

```text
【TASK】创建{PROP_ID} Canonical Unique Hero Prop Identity。

剧情身份与用途：{信息}
尺寸比例：{信息}
结构与材质：{信息}
颜色与永久特征：{信息}
Canonical文字/版式：{逐字内容或NONE}
可动/开合结构：{信息}

多角度展示同一件物理道具；关键文字使用明确、稳定、可读版式。控制Unique Prop Identity，不控制Holder、Hand、Anchor、动作或当前损坏状态。

若发现第二件同款，停止使用本模板并切换PROP_SPEC / PROP_INSTANCE系统。

输出{PROP_ID} Canonical Unique Prop Sheet。
```

### Unique PROP / VEH / CRE CT

沿用Character CT的Parent、Active Previous State、New Delta、Lifecycle、MUST NOT COPY和Complete Resolved State结构。对重复同款道具必须改用`PROP_INSTANCE_CT`。

### VEH

定义外观、比例、车型/结构、材质、颜色、永久识别与内外空间；不控制当前车门、乘员、速度、Camera和临时损坏。

### CRE

定义物种/个体Identity、骨骼结构、表皮/毛发/甲壳、比例、永久特征和运动限制；不把示例Pose变成Blocking。

### GRP

定义群体身份、人数范围、密度、服装规则、队形类别和行为边界；不得复制出多个主角或用GRP替代需要Identity的角色。

### VFX

定义效果身份、Activation Event、形态、颜色、尺度、运动规律、与人物/环境的物理关系、持续和结束条件。禁止第一帧提前存在。
