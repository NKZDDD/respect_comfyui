# 漏洞审计与冲突处理

## 目录

1. 审计方法
2. Authority漏洞
3. 叙事与SEG漏洞
4. 资产与Reference漏洞
5. Continuity与时间漏洞
6. CVS、SCSTATE与Storyboard漏洞
7. Video与声音漏洞
8. 长剧与修订漏洞
9. 交付完整性审计
10. 最终一票回编条件

## 1. 审计方法

交付前沿生产链从上到下检查一次，再从最终视频合同反向追溯一次：

```text
Forward:
Story → Assets → Continuity → CVS → SCSTATE → Shot → SEG → Storyboard → Video

Backward:
Video每个事实 → KF/CVS/Asset/Story来源
```

任何无法追溯到合法Authority的关键事实都不是Canon。任何下游与上游冲突都回到最近有修改权的层修正，禁止用后写的Prompt覆盖早期真相。

## 2. Authority漏洞

### 2.1 两套当前世界状态

失败：同时维护`Current World State`与`Continuity Current State`。

修正：只维护Continuity Ledger；`Resolved World State`是按Story Time和Thread的查询结果。

### 2.2 下游静默反向传播

失败：Storyboard为构图移动门；Video生成新伤口后续沿用；资产失败导致Character Bible改变。

修正：显式回调最近Authority层、最小修改、重新冻结、重编译下游。

### 2.3 最新生成等于最高Authority

失败：把attempt 2或最新视频自动当Canon。

修正：区分`DESIGN DRAFT`与`CANONICAL`。Video不是Canon。

### 2.4 关键事实首次出现在Video Prompt

失败：Storyboard看不清手机内容，Video Prompt第一次写关键短信。

修正：关键文字进入Story Truth、PROP Canon和KF；Video只控制出现时间。

### 2.5 Instruction Language污染文化设定

失败：中文Prompt自动生成中国式医院，故事实际在印尼。

修正：文化、地域、服饰、建筑与Prop只服从World Bible。

## 3. 叙事与SEG漏洞

### 3.1 把SEG当叙事层级

失败：每15秒必须一个完整Beat或固定剧情量。

修正：Scene/Beat/Shot由剧情决定，SEG只包装已完成的Cinematic Plan。

### 3.2 固定镜头数量

失败：15秒必须4至6镜头。

修正：镜头数动态，按信息、动作、表演和节奏决定。

### 3.3 一Beat一镜头

失败：Beat与Shot机械一一对应。

修正：一个Beat可一镜、多镜或与相邻Beat共镜。

### 3.4 Cause与Result跨SEG失主

失败：SEG01枪响，SEG02重新决定谁中枪。

修正：关键State Change归属唯一SEG；优先Cause、Activation和Canonical Result同SEG。

### 3.5 平行线程只保存全局Exit

失败：屏幕最后是Thread A，误以为Thread B状态丢失。

修正：Continuity保留每个Active Thread最新状态；SEG仅记录屏幕Entry/Exit和相关Thread Handoff。

### 3.6 Model-Native Transition跨SEG

失败：SEG01输出遮挡开始，SEG02输出遮挡解除，仍需要外部拼接才能形成转场。

修正：完整Exit、Transition Window、State Switch Point和Entry Establishment归属同一SEG；边界只放在转场前后稳定状态。

### 3.7 转场不计入SEG时长

失败：镜头时长已经填满SEG，又要求模型额外生成甩镜/淡变，导致对白和动作被压缩。

修正：Transition占用真实Timeline时长；重新分配Shot时长或SEG边界。

## 4. 资产与Reference漏洞

### 4.1 CHAR过度绑定Story Age和服装

失败：用28岁Root强行改24岁，或Root展示服成为默认COST。

修正：CHAR只固定Permanent Identity；年龄/长期外观进入PH，服装进入COST/LOOK。

### 4.2 PH、LOOK、CT被当局部修图

失败：换衣贴图、伤口贴纸、像素复制。

修正：Derived Asset执行Authority Extraction、Target Delta和New Reconstruction。

### 4.3 CT并行效果层

失败：`CT_INJURY + CT_WET + CT_DIRTY`分开叠加，顺序和继承冲突。

修正：当前CT是所有Active State的完整合并状态；新CT以前一CT为Parent。

### 4.4 Scene Blocking进入CT

失败：CT把“双手撑桌/躺地”固定为人物状态。

修正：人物持续外观进入CT；姿态、位置和Holder进入CVS/SCSTATE。

### 4.5 Reference Authority等于Composition

失败：Atomic Sheet的中性站姿污染Blocking；SCSTATE中景限制所有KF。

修正：Identity Lock ≠ Pose Lock；SCSTATE Lock ≠ Shot Lock；写MUST NOT COPY和DOES NOT CONTROL。

### 4.6 生产人员不知道上传什么

失败：只给Prompt，不给真实文件、顺序和范围。

修正：每次调用输出Reference Input Manifest；Image编号按调用重置并与Prompt一致。

### 4.7 多个Reference控制同一维度

失败：LOOK与COST同时控制服装，两个SCSTATE平均融合。

修正：明确Primary Authority和Applicable Scope；只保留Minimum Sufficient Set。

### 4.8 参考容量超限

失败：随意删除CT、Hero Prop或Location Authority。

修正：用高层资产替代低层、合并背景角色、移除已融合Wearable、按Thread/Window隔离，最后才调呈现粒度。

### 4.9 PROP规格被当成物理实体

失败：两支同款注射器共用一个PROP ID，导致一支被使用后另一支也变空。

修正：读取[PROP规格、物理实例与数量连续性](08-prop-spec-and-physical-instance.md)；SPEC只管共同外观，INSTANCE独立拥有状态和历史。

### 4.10 同款实例被人工制造差异

失败：为了区分两件同款文件，模型随机改色、加划痕或改标签。

修正：允许完全同外观；用INSTANCE ID、Holder、Anchor、动作路径和事件区分。独有标记必须来自Canon。

### 4.11 批量同款物件导致资产爆炸

失败：会议室20把同款椅子生成20张重复资产图。

修正：使用一个PROP_SPEC Reference与PROP_SET；只有产生交互时才物化INSTANCE，实例默认可为LOGICAL_ONLY。

### 4.12 SPEC静默改版

失败：后期修改标签版式，旧时间线里的全部实例也被反向替换。

修正：SPEC使用Revision和effective scope；实例绑定合法revision，禁止静默覆盖。

### 4.13 Canonical ID后段缩写

失败：前面登记`PRJ_NOVA__CHAR_001_PH01_LK01_CT01_R01`，SCSTATE或Video后面写成`CT01`、`女主CT01`或`CHAR_001_CT01`。

修正：读取[Canonical ID注册表与参考资产解析](10-canonical-id-registry-and-resolution.md)；所有ID字段只能从Registry逐字符复制完整Canonical Revision ID。

### 4.14 ID存在但Reference文件找不到

失败：Manifest只有内部ID或“上一张定妆图”，生产人员不知道具体上传哪个文件。

修正：每个Image槽输出完整Revision ID、精确文件名、File Role、相对/解析路径、Fingerprint和Availability。

### 4.15 同一ID覆盖成新图

失败：保留R01名称但文件内容已被修改，旧Storyboard仍认为它是原Canon。

修正：Canonical Revision不可变；Fingerprint变化必须建立R02并显式回编受影响下游。

### 4.16 模糊匹配或自动最新版本

失败：找不到完整ID时自动选择名字最像或修改时间最新的资产。

修正：Exact Registry Lookup失败即`REFERENCE_RESOLUTION_BLOCKED`；不得猜测、Silent Redirect或自动升级Revision。

### 4.17 Candidate被当成Reference

失败：刚生成但未确认的TRY图直接进入下游。

修正：只有Registry状态为CANONICAL且文件解析通过的Revision可以占Image槽。

### 4.18 同一场景多视角独立生成

失败：正面、侧面、背面各自漂亮，但门窗、家具、距离和连接关系无法拼合。

修正：读取[空间坐标、机位Rig与多视角一致性](11-spatial-rig-and-multiview-consistency.md)；同一Spatial坐标和Geometry Proxy逐View投影、闭环核对。多视图Sheet只能汇编批准View。

### 4.19 用故事板融合掩盖上游空间错误

失败：Location资产互相矛盾，但故事板暂时看起来融合较好，就把空间标记Canonical。

修正：资产必须在F2独立通过几何闭环；无法回投World坐标的View保持CANDIDATE，不进入下游。

### 4.20 COST与LOOK策略倒置

失败：孤立服装图直接作为视频人物服饰主参考，或每套简单服装都生产独立资产。

修正：读取[服饰资产、完整LOOK与首次显露覆盖](12-costume-look-and-visual-coverage.md)；关键/复杂/复用服装独立COST，简单服装LOGICAL_ONLY，但下游都必须形成当前PH的完整LOOK。

### 4.21 LOOK或CT视觉覆盖不完整

失败：人物板裁掉鞋或没有背面，视频首次显露时自由发明。

修正：维护Visual Coverage Map；可能首次显露的头、手、脚、正侧背和当前状态区域必须在LOOK/CT中定义。

## 5. Continuity与时间漏洞

### 5.1 Active State只写ID不展开

失败：模型不知道CT03包含伤口、贴片、破损。

修正：展开Persistent Visible State Checklist。

### 5.2 Presence等于Visibility

失败：镜头没拍到脖子，贴片被当成消失。

修正：区分Visible、Partial、Occluded、Off-frame和Not Active。

### 5.3 未来状态前置

失败：后期KF贴片污染0秒。

修正：Future-State Embargo、Activation Event、Timeline Window和必要时Temporal Reference Window。

### 5.4 弱化预现未被禁止

失败：完整贴片没出现，但前面已有淡淡白块。

修正：禁止未来状态以完整、部分、弱化、模糊、预示或融合形式出现；合法预示单独建状态。

### 5.5 状态无事件恢复

失败：伤口、湿衣、烧焦墙面为了下场方便消失。

修正：所有失活来自Deactivation、Replacement、Time Gap或Lifecycle Rule。

### 5.6 同步Delta错位

失败：瓶子碎了但仍在手里，地面下一场才出现玻璃。

修正：同一Event同步更新Character、Prop、Holder、Spatial和Environment。

### 5.7 长期不出现后重置

失败：角色EP20复出自动用EP03旧LOOK；房屋17集未出现被重新设计。

修正：按Time Gap、PH、Events和Current Scene重新解析；LOC/SPATIAL无修订则继续。

### 5.8 遮挡或离画等于不存在

失败：道具被身体挡住后消失，重新入画时生成一件新副本。

修正：Existence与Visibility分离；Occluded、Off-frame、Contained均保持同一INSTANCE与Active State。

### 5.9 Object Count不可对账

失败：一件道具经过切镜变成两件，或未销毁却减少。

修正：每个SCSTATE、Storyboard Entry/Exit和Video Window执行`Full + Partial + Occluded + Off-frame = Active Total`；总量仅由合法事件改变。

### 5.10 破坏、消耗与容器内容混淆

失败：喝完水后瓶子也消失；玻璃破碎后完整瓶和碎片同时存在。

修正：容器与内容物分开；破坏、消耗、Split/Merge记录父子身份、余量、存在状态和同步Delta。

## 6. CVS、SCSTATE与Storyboard漏洞

### 6.1 CVS包含Camera

失败：CVS同时拥有Physical Truth和Camera Truth。

修正：删除shot_size、camera、composition、screen_direction；使用`CVS + Shot → KF`。

### 6.2 CVS第一次决定穿什么

失败：Director和Blocking不知道当前服装/伤势限制。

修正：Current Appearance Resolution在Director前完成，CVS绑定active_visual_asset_id。

### 6.3 SCSTATE成为第二套状态真相

失败：SCSTATE图片决定有无伤、谁拿文件。

修正：SCSTATE只是CVS视觉物化；冲突时重生成SCSTATE。

### 6.4 SCSTATE记录Transition

失败：手靠近门、碰门、开一半分别建SCSTATE。

修正：只建Stable Before和Stable After，中间交给VT/Storyboard/Video。

### 6.5 “至少两类Delta”漏掉单一关键变化

失败：炸弹启动灯、唯一关键门锁状态因只有Prop Delta被过滤。

修正：默认两类；满足关键、可读/可执行、持续/因果、删除会丢真相四条件时使用`SINGLE_DELTA_CRITICAL_OVERRIDE`。

### 6.6 SCSTATE数量固定

失败：每SEG强制3至4张，造成资产爆炸。

修正：按Stable State Change与下游价值动态1...N。

### 6.7 Storyboard固定9个KF

失败：为凑3×3加入重复情绪格。

修正：动态KF；3×3只是常用版式。

### 6.8 “一SEG一张Sheet”与动态容量冲突

失败：超过9个KF或多Thread仍塞一页，降低可读性并增加污染。

修正：一SEG一个Canonical Storyboard Package，允许1...N有序Continuation Sheets；内容仍唯一。

### 6.9 多Location/Thread同板融合

失败：医院、雨夜、病房状态互相污染。

修正：Reference Applicable KF、Thread Firewall、状态带或分Continuation Sheet。

### 6.10 Storyboard复制SCSTATE机位

失败：所有KF都是相同中全景。

修正：`SCSTATE + New Camera Observation = KF`。

### 6.11 动作重复

失败：签字/跌倒/拔针在后续KF再次从头发生。

修正：Action Phase和No Action Replay；Completion后进入Post/Reaction/Exit。

### 6.12 终点结果未冻结

失败：只画爆炸前后大概，Video自行决定墙坏成什么样。

修正：关键结果进入Target CVS和终点KF。

### 6.13 人物空间位置只写画面左右

失败：切换机位后“左边的人”被重放到门的另一侧或另一个Zone。

修正：CVS/SCSTATE/KF写World Root/Foot XYZ、Anchor Offset、Orientation和支撑/占地；Camera只重新投影。

### 6.14 Storyboard新机位首次发明空间

失败：资产只定义走廊一面，Storyboard从反方向生成后门窗和家具重新排列。

修正：KF绑定批准LOC_VIEW或Geometry Proxy。新方向先建立View；未覆盖时`NEW_VIEW_REQUIRED`。

### 6.15 半身Storyboard未声明视频显露范围

失败：KF只有上半身，视频拉远或人物起身后下装、鞋履和身体比例漂移。

修正：每个KF/Window建立Camera Reveal Envelope和First Reveal Coverage Gate；补当前LOOK/CT覆盖或限制Camera。

### 6.16 Storyboard没有Transition Anchor

失败：Prompt要求遮挡或甩镜转场，但Package只有两个稳定KF，模型不知道何时遮满、何时切换。

修正：读取[视频模型原生镜头切换](13-model-native-shot-transition.md)；按需要加入Exit、Trigger、Shield/Peak和Entry Anchor，明确它们不是新CVS。

### 6.17 NATIVE_CUT被当连续运镜

失败：模型从近景平滑移动到另一个独立机位，造成空间穿越或人物漂移。

修正：冻结瞬时`cut_at`并声明`DO NOT INTERPOLATE CAMERA BETWEEN SHOTS`。

## 7. Video与声音漏洞

### 7.1 Storyboard变成Morph

失败：人物滑动、融化、网格进入视频。

修正：明确Temporal Performance Reconstruction和MUST NOT COPY Sheet Layout。

### 7.2 Video再次上传全部Atomic资产

失败：多重Reference覆盖Storyboard状态和时间。

修正：默认Storyboard为Primary Composite Authority，只补最小必要细节。

### 7.3 Prompt只写“保持一致”

失败：时间窗口无Allowed/Forbidden/Activation。

修正：逐Window写Entry State、Event、State Gate、Target和Exit。

### 7.4 对白翻译改剧情事实

失败：改姓名、职务、金额、地名或关系。

修正：翻译只改变语言表达，Canon事实不变。

### 7.5 固定时长造成异常语速

失败：大量对白塞进15秒。

修正：在授权范围内精炼文本、调整SEG边界或镜头节奏；不机械快说。

### 7.6 音频模式不明

失败：Silent Video出现随机口型/音乐，Separate Audio没有Cue。

修正：初始化冻结`video_audio_mode`，Prompt与Audio Cue Sheet一致。

### 7.7 补充全身参考抢夺Camera Authority

失败：为防全身漂移加入LOOK后，模型复制中性站姿、背景或构图。

修正：Storyboard控制Camera、Pose、Blocking、Action和Time；LOOK/CT只控制Identity、比例、服饰和首次显露区域，写清`DOES NOT CONTROL`。

### 7.8 Camera越出空间或人物视觉覆盖

失败：模型随机环绕、拉远，出现另一套场景或未定义服饰。

修正：空间使用批准Geometry/View Coverage，人物使用Visual Coverage；Coverage不足时执行Framing Expansion Embargo。

### 7.9 Video只会硬切

失败：所有Shot无论叙事关系都机械直接切，错失动作、遮挡、运动、光线、声音与主观线程的原生镜头语言。

修正：每个Transition写Mechanism + Cinematic Grammar + Narrative Function，按模型能力动态选择，不固定硬切。

### 7.10 转场依赖外部剪辑

失败：Video Prompt输出多个镜头素材、黑帧占位或“后期添加叠化/声音桥”。

修正：`transition_execution_mode = MODEL_NATIVE_ONLY`；模型一次输出完整SEG成片，禁止External Shot Assembly与Transition Editing。

### 7.11 遮挡转场中人物/场景融合

失败：遮挡未达到100%时未来人物、贴片或Target Location已经出现，形成混合状态。

修正：From-only → Shield Build → 100% Shield → Switch Point → Target-only；Shield Frame没有World Truth Authority。

### 7.12 Dissolve被当Canonical共存

失败：光学叠加导致两张脸、两套服装、两个Location或两个时间状态融化成一个中间世界。

修正：Transition Visual Overlap不等于State Coexistence；限制Dissolve用途，禁止实体Morph并保持双方独立视觉层。

### 7.13 模型能力不足后静默改后期

失败：模型不能稳定多镜头，于是分别生成Shot再拼接，违背用户的无额外剪辑要求。

修正：按Capability Gate降级为Full Occlusion/Dip/Flash/Defocus、低复杂度Motion或单镜头连续表达；仍失败则`MODEL_NATIVE_TRANSITION_BLOCKED`。

## 8. 长剧与修订漏洞

### 8.1 Revision无生效时间

失败：EP10开始戴戒指被反向应用到EP01。

修正：所有Revision写effective_story_time与reality_thread。

### 8.2 自然演化无限制造CT

失败：伤口每天阶段都生成资产，即使当前没镜头展示。

修正：Ledger记录阶段；只在当前Scope需要稳定可见且差异有生产价值时物化CT。

### 8.3 Same Visit与New Visit混淆

失败：两个月后临时杯子仍完全原位，或两分钟返回房间临时状态被重置。

修正：按Time Gap与Lifecycle解析临时状态，基础LOC/SPATIAL保持。

### 8.4 Hidden Truth泄漏

失败：全剧分析知道反派身份，EP01资产/表演提前暴露。

修正：生产使用Presented Identity、Character Knowledge和Audience Knowledge。

## 9. 交付完整性审计

逐项确认：

- [ ] Project Config、Scope、seg_duration、画幅、模型、语言和音频模式明确。
- [ ] Story Unresolved与Visual Underspecified分开。
- [ ] Entity ID唯一，同一Physical Entity未重复创建。
- [ ] Project ID、ID Policy、Registry Snapshot与唯一Canonical Asset Registry已冻结。
- [ ] 所有生产字段使用完整Canonical Revision ID，没有缩写、显示名称替代或漏Revision。
- [ ] Target为RESERVED/CANONICAL，全部Reference状态为CANONICAL。
- [ ] 每个Reference有精确文件名、角色、路径、Fingerprint和VERIFIED Availability。
- [ ] Manifest ↔ Prompt通过Exact ID Echo Audit，没有Dangling、Duplicate或Silent Redirect。
- [ ] 重复同款道具已分离PROP_SPEC、PROP_SET/INSTANCE和INSTANCE CT。
- [ ] 同款实例没有被擅自改色、加划痕或共享物理状态。
- [ ] Current Scope资产按依赖排序，状态标记正确。
- [ ] 每个Location有统一World坐标、尺度、Geometry Proxy或批准的降级方案。
- [ ] 同一Location的必要视角从同一Proxy逐View生成，Landmark、门窗、固定家具、尺度和连接关系闭环一致。
- [ ] 每个LOC_VIEW有完整Revision ID、Camera Rig、覆盖范围、文件路径与Fingerprint。
- [ ] 关键/复杂/复用COST已物化；简单COST可LOGICAL_ONLY，但每个当前造型都有完整on-body LOOK。
- [ ] LOOK/CT Visual Coverage Map包含将被首次显露的正侧背、下装、手脚、鞋履和Active State区域。
- [ ] 每个NEW项有真实Manifest、Upload Order和Complete Prompt。
- [ ] Reference Authority、Preserve、Transform、Not Copy、Does Not Control、Scope齐全。
- [ ] Continuity Ledger可追溯到Event，状态有Lifecycle。
- [ ] Active Character Visual Root和Persistent Checklist展开。
- [ ] CVS不含Camera，绑定当前视觉资产和物理状态。
- [ ] 人物与关键Prop位置使用World XYZ或Anchor Offset，不以Screen Left/Right代替Physical Truth。
- [ ] VT同步Delta，Target CVS明确。
- [ ] SCSTATE来自CVS，不含动作半程。
- [ ] SCSTATE Delta默认阈值与Single-Delta例外正确。
- [ ] Shot数量、KF数量、SCSTATE数量动态。
- [ ] Project Config冻结`MODEL_NATIVE_ONLY`、外部剪辑禁令与目标模型原生多镜头能力等级。
- [ ] 每个Transition使用完整Canonical Revision ID，并有From/To Shot、Narrative Function、Mechanism、Grammar和时间范围。
- [ ] SEG边界不拆关键Cause/Result。
- [ ] 每个Transition完整归属一个SEG并计入真实时长，边界没有拆开Shield/Switch/Entry。
- [ ] Storyboard Package内容唯一，Sheet只是承载。
- [ ] 每个KF有Source、Thread、Phase、Active/Forbidden State与Exit。
- [ ] 每个Prop动作绑定INSTANCE ID，Object Count与Visibility Bucket可对账。
- [ ] Storyboard Reference Firewall与Video Temporal Gate分别存在。
- [ ] Video每时间窗有Activation、Allowed、Forbidden、Target和No Replay。
- [ ] 每个Video Window有Camera Reveal Envelope、First Reveal Coverage结果和必要的Framing Expansion Embargo。
- [ ] NATIVE_CUT有精确cut_at且禁止Camera插值；遮挡/运动/光学Transition有Trigger、Shield/Peak、Switch Point和Target-only Entry。
- [ ] Video Prompt要求一次返回完整多镜头SEG成片，没有镜头素材包、转场占位、外部拼接、后期补救或失败帧裁除依赖。
- [ ] 原生声音模式下J/L Cut、Sound Match/Drop和Ambience Bridge在同一次生成中完成。
- [ ] Final State能作为下一SEG Entry。
- [ ] 没有占位符、内部引用标记、测试图或失败版本进入最终生产包。

## 10. 最终一票回编条件

出现下列任一项，不得交付生产执行，必须回编：

1. Story因果、施动者、目标或关键结果被改变。
2. 同一Story Time出现互斥的两个Canonical State。
3. Reference无法确定哪张图控制哪个对象/范围。
4. Future State在Activation之前可见。
5. Active Persistent State无合法原因丢失。
6. CVS或SCSTATE与Spatial/Continuity冲突。
7. 关键Prop身份、文字、Holder或状态未冻结。
8. Storyboard KF重复动作、漏关键结果或跨Thread污染。
9. Video Prompt首次创造关键剧情事实。
10. 下游修改上游但未显式Revision与重编译。
11. 同款道具未绑定Physical Instance，或Object Count无法由事件和可见性对账。
12. 任何ID被缩写、改写、漏命名空间/Revision，或无法在唯一Registry完全匹配。
13. Reference未解析到唯一Canonical文件、路径与Fingerprint，或使用了非CANONICAL状态资产。
14. 同一Location的两个必要视角无法由同一Spatial坐标和Geometry Proxy解释，或View在闭环失败后仍进入下游。
15. 人物/Prop的World Placement缺失，切镜只能依赖画面左右猜测真实位置。
16. 当前人物造型没有完整LOOK，或视频会显露未定义的身体、服饰、鞋履/背面区域且没有限制Camera。
17. Model-Native Transition被拆到两个SEG，或输出需要任何外部镜头拼接、后期转场/声音桥或失败帧裁除。
18. Transition缺少完整ID、时间所有权、Mechanism、Exit/Entry或State Switch Point，导致模型自由决定切换。
19. Shield达到100%之前Target人物/Location/状态已经出现，或Transition产生混合Identity、混合空间、未来状态前置。
20. 目标模型原生多镜头能力不足，却没有安全降级或`MODEL_NATIVE_TRANSITION_BLOCKED`。
