完整技能规范
AI电影级短剧生产 Skill
V6.2｜强制故事板时间骨架与导演级视频执行强化版
Storyboard始终作为Video的Canonical时间与镜头骨架；人物、场景、道具与边界图只按独有作用补充，Video Prompt以导演级逐窗口执行卡承载细腻动作、微表演、镜头语言与声画同步。
完整版 · 可执行Skill包同步交付
2026-08-15

版本整合说明与自检结论
本版是可独立使用的完整Skill。它保留Story Truth、Canonical ID、空间状态、人物与场景位置锁、非冗余机位、完整LOOK、PROP实例、CVS、时间连续性、Canonical Boundary和模型原生镜头切换体系，并建立V6.2统一执行口径：每个Video SEG必须有Mandatory Storyboard Temporal Spine；所有Storyboard图先通过Admission；人物、场景、Prop与BNDANCHOR只按独有作用选择；Video Prompt改为导演级逐窗口执行卡。
本版吸收的核心升级
Production Reference Manifest：每次调用明确上传哪张图、上传顺序、Authority与适用范围。
SCSTATE Logical Compiler：把CVS、人物状态、Prop、空间、Blocking、可见性和时间锁完整编译为逻辑合同；只有通过门控时才物化视觉Slice。
Past-State Persistence + Future-State Embargo：已发生状态持续继承，未来状态绝不前置。
Derived Asset Transformation Contract：参考图继承Authority，但不得默认复制Pose、Camera、Composition或像素。
Canonical Storyboard Package：保留一个SEG一个视觉真相，同时允许动态KF和有序Continuation Sheets。
PROP Specification / Set / Instance：共同外观、批量库存、唯一物理实体与实例CT分别拥有明确Authority。
Object Count Lock：可见、部分可见、遮挡与离画实例完整对账，只有合法事件能增减总量。
Canonical Asset Registry：一个项目只有一套ID、Revision、文件角色、路径、Fingerprint与状态索引。
Exact ID Echo Contract：Manifest、Prompt、CVS、SCSTATE、KF和Video逐字符复用完整Revision ID。
Reference Resolution Gate：ID、Canonical状态、文件、路径、Fingerprint和Authority全部通过后才释放Prompt。
Compact Reference Identity Map：每个Image槽以六字段明确完整ID、Who/What与可见内容、Story Time/Current State、Controls、Does Not Control和Applicable Scope。
Reference Mapping Gate：文件解析正确但身份、状态、范围或上传顺序不完整时返回REFERENCE_MAPPING_BLOCKED，禁止模型猜图。
Spatial World Coordinate Contract：每个Location统一原点、轴向、单位、Anchor XYZ、Route、尺度和固定Geometry。
Geometry Proxy + Canonical LOC_VIEW：高风险空间由同一3D/2.5D代理逐机位投影，闭环核对后才汇编View Set。
Location View Coverage Plan：从Scene、Blocking、Shot、KF与Camera Reveal提取所需Zone、Portal、Route、Barrier、Anchor与动作轴。
View Utility Contract：每个候选View必须声明Role、独有Coverage、完整消费者、与已有View的差异及不可由Crop替代的理由。
View Distinctness Gate：仅焦段、Zoom、轻微横移、升降或裁切不同的View不得进入Canonical生产。
Dynamic View Count：简单场景可以只有2个View，复杂空间按真实消费者扩展，不再固定三视图。
Neighbor Reference Firewall：相邻View只校验固定Identity、Landmark、尺度与Overlap，不控制当前Camera、Crop、Composition或Visible Zone。
Distinctness before Batching：先证明View必要，再执行VIEW_BATCH/VIEWPACK合并资格；不得为填满格位创造重复机位。
World Placement Lock：人物和关键Prop使用XYZ/Anchor Offset/Orientation定位，Camera只投影不重排World。
Costume Dual Path：关键复杂服饰独立COST，简单服饰LOGICAL_ONLY，但两者都必须生成当前人物完整LOOK。
Visual Coverage Map：LOOK/CT明确正侧背、下装、手脚、鞋履和当前状态的覆盖来源。
Camera Reveal Envelope + First Reveal Gate：视频扩大取景前先验证将首次显露的身体、服饰和空间区域。
Model-Native Complete Output：一个VIDEO/SEG由模型一次输出完整多镜头成片，禁止外部镜头拼接和后期补转场。
Transition Grammar：分离Mechanism、Cinematic Grammar与MODEL_NATIVE_ONLY执行层，不再固定只用硬切。
Transition Window：每个转场冻结Exit、Trigger、Shield/Peak、State Switch Point和Target-only Entry。
Shielded State Switch：只有100%遮挡后才允许Identity、Location、Thread或状态切换。
World Position State：人物Zone、Anchor、Seat/Support Binding、Barrier Side与姿态类别在无事件时持续继承。
Authorized Spatial Transition：起身、解除支撑、Route、Portal Crossing、Target Anchor与Completion共同授权换位。
SCSTATE Delta Inheritance：每个状态明确上一状态、保持位置、获准移动者和禁止位置Delta。
Story-First Prompt Order：SCSTATE、Storyboard和Video先写完整故事、确切时刻、Before/Now/After与唯一主焦点，再写技术合同。
Zone-Coherent SCSTATE Slice：CVS保持全局唯一；跨远距离、不同高度或Barrier的状态按Camera-coherent Cluster物化，其他实体登记为OFF-FRAME ACTIVE。
Narrative Sufficiency Gate：隐藏ID后仍必须能判断原文确切时刻、主角、动作、前因和下一刻禁入事件。
Storyboard Readability Gate：每张Sheet最多3个KF；禁止九宫格和高密度缩人排版，更多关键时刻使用Continuation Sheet。
Image Materialization Gate：SCSTATE、KF和空间View先证明独有Authority、稳定结果或风险价值；中间动作默认TEXT_CANON_ONLY或DEFER_TO_VIDEO。
Image Complexity Budget：多人、手部、精确Blocking、连续动作、高密度排版和复杂道具不会无理由叠加在单次图片生成中。
Mandatory Storyboard Temporal Spine：每个Video SEG都以当前SBPKG的有序Continuation Sheets或有序Canonical KF Anchors覆盖完整关键时间推进。
Storyboard Reference Admission Gate：逐图验证Revision、SEG、Thread、时间、状态、位置、Prop、Boundary与排序，错误故事板不得进入Video。
Effective Reference Selection Gate：人物LOOK/CT、LOC_VIEW、Hero Prop和BNDANCHOR只在解决独有Authority缺口时补充。
Director-Level Video Prompt：每个时间窗口展开Beat目的、人物目标、微表演、动作阶段、物理反应、Camera Grammar、声音同步与窗口出口。
Reference Dimension Coverage Gate：Identity、LOOK/CT、Spatial/Geometry、Position/Blocking、State/Temporal与Prop/Count/Holder六维必须完整。
Authority-Complete Nonconflicting Execution Set：每张Video Reference有唯一Role、时间窗和独有贡献；图像上限和最少张数都不是目标。
Canonical SEG Boundary：相邻SEG在视频生产前建立BNDPLAN及可选BNDANCHOR OUT/IN；生成视频截图、尾帧与Frame Grab禁止回流参考。
Video Story Recompile：Video Prompt重新写完整SEG摘要和逐秒施受因果，不把故事理解外包给KF标签。
Composite Authority Deduplication：人物、Location与Prop补图只针对可证明的Coverage/Identity/关键细节缺口。
Capability Gate：根据模型多镜头能力选择Native Cut、遮挡、运动、光学覆盖或单镜头连续表达。
Native Audio Transition：J/L Cut、Sound Match/Drop和Ambience Bridge在同一次生成中完成。
完整Prompt Library：CHAR、PH、COST、LOOK、CT、LOC、SPATIAL、PR、PROP、SCSTATE/SLC、≤3 KF Storyboard与Story-First Video均有可执行模板。
本次自检后修复的关键漏洞
旧的“一SEG一张Sheet”与动态KF、线程隔离冲突：改为一个Canonical Storyboard Package可承载1至N张有序Sheet，Canon内容仍唯一。
旧的“新SCSTATE至少两类变化”可能漏掉单一但关键状态：保留默认两类阈值，新增受严格条件约束的Single-Delta Critical Override。
Reference First容易演变为Pixel Copy：所有派生任务统一加入MUST PRESERVE / MUST TRANSFORM / MUST NOT COPY / DOES NOT CONTROL。
Presence与Visibility混淆会让伤口、贴片在遮挡后消失：加入可见、部分可见、遮挡、画外和未激活五类状态。
一张故事板同时包含未来状态仍会污染Video：保留Canonical Package，执行层增加State Timeline Lock和Temporal Reference Window。
同款道具共用一个PROP ID会串状态：SPEC只控制外观，INSTANCE独立持有Holder、位置、CT、事件和历史。
批量同款逐件出图会造成资产爆炸：新增PROP_SET，只有发生交互时才通过事件物化INSTANCE。
遮挡、离画或装入容器后物体会复制/消失：Existence与Visibility分离，并在SCSTATE、KF和Video窗口交接Instance Register。
破坏、消耗与容器内容容易混淆：增加Destruction、Consumption、Split/Merge父子映射和容器/内容物分权。
前面使用完整ID、后面缩成CT01会断开Reference：新项目强制PROJECT命名空间和Canonical Revision ID。
ID存在但生产人员找不到图：Manifest必须给精确文件名、角色、相对/解析路径、Fingerprint和Availability。
同一ID覆盖成新图会污染旧下游：Canonical Revision不可变，内容改变必须创建R02并回编。
查不到时自动选近似或最新图会静默串资产：Exact Lookup失败即阻断，不允许模糊匹配或Silent Redirect。
只写Image 1控制什么仍无法让模型识别图中主体：在Manifest与Prompt内加入同一份六字段身份映射，不新建资产或注册表。
同一场景多视角各自自由生成会无法拼合：改为同一Spatial/Geometry Proxy逐View单独生成并以共享Landmark闭环批准。
同一场景A01/A02/A03高度相似：新增Location View Coverage Plan与View Utility Contract，要求每张图有独有空间Authority和明确消费者。
把焦段、Zoom或轻微横移当成新机位：可由已有高分辨率View安全裁切的构图改用allowed_crop，不创建新LOC_VIEW。
相邻View参考会复制旧构图：新增Neighbor Reference Firewall，明确邻图不控制当前Camera XYZ、Look-at、Lens、Crop、Composition和Visible Zone。
为了VIEWPACK三格而凑第三个机位：Distinctness Gate前置，空格位保留校验用途，没有独有Coverage的View直接拒绝。
故事板融合效果可能掩盖上游空间错误：无法回投World坐标的Location View不得冻结为Canonical。
人物位置只写画面左右会在切镜时换Zone：CVS、SCSTATE和KF统一写World XYZ、Anchor Offset与朝向。
孤立COST图无法锁定穿着比例：下游人物服饰Primary Authority改为穿在当前PH上的完整LOOK/CT。
所有简单服装都独立出图会资产爆炸：增加LOGICAL_ONLY服饰合同，但仍完整生成LOOK。
半身故事板转视频全身会随机想象：逐Window建立Reveal Envelope；补当前LOOK/CT覆盖或限制Camera。
补全身图容易覆盖故事板Pose/Camera：明确Storyboard管时空，LOOK/CT只管Identity、比例、服饰和首次显露区域。
旧规则默认硬切限制镜头语言：改为按叙事、动作、声音、空间、时间和模型能力动态选择模型原生Transition。
转场只写名称会由模型自由发挥：新增完整TRANS ID、时间窗口、Mechanism、Grammar、Exit/Entry与Failure Signature。
原生切镜容易被模型做成连续运镜：NATIVE_CUT强制exact cut_at并禁止Camera插值和Shot Morph。
遮挡前出现未来状态或混合场景：新增From-only、100% Shield、Switch Point、Target-only门控。
原生转场跨SEG仍需后期拼接：完整Transition必须归属一个SEG并计入真实时长。
模型能力不足后静默改用后期：只允许安全原生降级、单镜头连续表达或明确BLOCKED。
人物坐在桌后却下一状态直接出现在前场：新增Seat/Support Binding与Position State Gate，未发生起身和Route事件时禁止换Zone。
SCSTATE为显示争吵而重新站位：每个状态必须从上一状态继承位置，只允许Authorized Movers产生明确Delta。
Video同时给Storyboard、SCSTATE、人物、Location和Prop导致平均融合：保留Mandatory Storyboard Temporal Spine，Supplemental必须证明独有Authority和Does Not Control。
CVS全局完整性被误当单图同框：跨远距离、不同高度或不相容动作轴时建立共享同一CVS的Zone-Coherent SLC，不移动人物或融合地点。
SCSTATE技术字段完整但看不懂故事：新增Narrative Sufficiency Gate，隐藏ID后仍需明确时刻、主角、动作、前因和下一刻。
故事板九宫格导致关键交互不可检查：每Sheet硬限制最多3个KF，更多时刻增加Continuation Sheet且保持一个SBPKG。
错误SCSTATE在Storyboard里偷修会形成两套World State：必须新建Revision/SLC并重编全部受影响下游。
Video只看标签不会自行理解30秒剧情：强制重写完整SEG摘要与逐秒施动者、动作、受动者、结果和反应。
SCSTATE和每个KF默认出图把图片模型推到超负荷：新增Image Materialization Gate，逻辑合同完整保留，中间动作交给视频。
少传图片容易被误解成少写控制：Video仍必须重写完整SEG摘要、逐秒因果、位置、Count、Holder、状态门控、声音和Exit。
视频能力强就只给入口图会丢失时间与镜头骨架：任何可靠度都强制Storyboard，可靠度只调整骨架颗粒度、补图和Prompt冗余度。
故事板本身错误仍被Video采用：新增Storyboard Reference Admission Gate，错版、错时、错位置或未来状态图立即阻断。
为稳定而把所有人物、场景、SCSTATE和Prop都塞给Video：新增Effective Reference Selection Gate，逐图证明独有作用。
Video动作、表演和镜头不够细：新增Temporal Window Execution Card、Micro-Performance、Action Phase、Camera Grammar和声画同步合同。
视频结果直接沿用会传播偶然错误：彻底禁止生成视频截图、尾帧和Frame Grab进入下一SEG参考；QC只能决定是否重生成。
同场连续边界若依赖像素续接会产生跳帧或重复动作：新增BNDPLAN、Canonical Cut Pair、Shared Stable Anchor、Motivated Hard Cut与Opaque Buffer Pair。
减图可能误删人物和场景位置Authority：把完整LOOK/CT、相关LOC_VIEW、World XYZ、Zone、Anchor、Support、Route、Barrier/Portal与Orientation提升为不可降级底座。
文档结构
第一部分：SKILL.md核心工作流与触发规则
第二部分：架构、Authority与17章职责
第三部分：资产树、派生变换与参考图机制
第四部分：Continuity、CVS、VT与SCSTATE
第五部分：导演、镜头、SEG与Storyboard
第六部分：Video Execution、时间门控与声音
第七部分：完整Production Prompt模板库
第八部分：PROP规格、物理实例与数量连续性
第九部分：原子资产完整提示词模板
第十部分：Canonical ID注册表与参考资产解析
第十一部分：空间坐标、机位Rig与多视角一致性
第十二部分：服饰资产、完整LOOK与首次显露覆盖
第十三部分：视频模型原生镜头切换
第十四部分：空间状态门控与Authority完整视频参考
第十五部分：同场景兼容机位合并生产
第十六部分：场景机位覆盖规划与重复视图控制
第十七部分：Story-First、Zone-Coherent SCSTATE与故事板可读性门控
第十八部分：Logical-First、Video-Weighted执行与图片减压
第十九部分：强制Storyboard时间骨架、有效参考选择与导演级Video执行
第二十部分：漏洞审计与最终回编条件
附录：agents/openai.yaml与Skill文件结构
