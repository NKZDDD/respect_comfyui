第二十部分｜漏洞审计与冲突处理
目录
审计方法
Authority漏洞
叙事与SEG漏洞
资产与Reference漏洞
Continuity与时间漏洞
CVS、SCSTATE与Storyboard漏洞
Video与声音漏洞
长剧与修订漏洞
交付完整性审计
最终一票回编条件
1. 审计方法
交付前沿生产链从上到下检查一次，再从最终视频合同反向追溯一次：
[text]Forward:Story → Assets → Continuity → CVS → SCSTATE → Shot → SEG → Storyboard → VideoBackward:Video每个事实 → KF/CVS/Asset/Story来源
任何无法追溯到合法Authority的关键事实都不是Canon。任何下游与上游冲突都回到最近有修改权的层修正，禁止用后写的Prompt覆盖早期真相。
2. Authority漏洞
2.1 两套当前世界状态
失败：同时维护Current World State与Continuity Current State。
修正：只维护Continuity Ledger；Resolved World State是按Story Time和Thread的查询结果。
2.2 下游静默反向传播
失败：Storyboard为构图移动门；Video生成新伤口后续沿用；资产失败导致Character Bible改变。
修正：显式回调最近Authority层、最小修改、重新冻结、重编译下游。
2.3 最新生成等于最高Authority
失败：把attempt 2或最新视频自动当Canon。
修正：区分DESIGN DRAFT与CANONICAL。Video不是Canon。
2.4 关键事实首次出现在Video Prompt
失败：Storyboard看不清手机内容，Video Prompt第一次写关键短信。
修正：关键文字进入Story Truth、PROP Canon和KF；Video只控制出现时间。
2.5 Instruction Language污染文化设定
失败：中文Prompt自动生成中国式医院，故事实际在印尼。
修正：文化、地域、服饰、建筑与Prop只服从World Bible。
3. 叙事与SEG漏洞
3.1 把SEG当叙事层级
失败：每15秒必须一个完整Beat或固定剧情量。
修正：Scene/Beat/Shot由剧情决定，SEG只包装已完成的Cinematic Plan。
3.2 固定镜头数量
失败：15秒必须4至6镜头。
修正：镜头数动态，按信息、动作、表演和节奏决定。
3.3 一Beat一镜头
失败：Beat与Shot机械一一对应。
修正：一个Beat可一镜、多镜或与相邻Beat共镜。
3.4 Cause与Result跨SEG失主
失败：SEG01枪响，SEG02重新决定谁中枪。
修正：关键State Change归属唯一SEG；优先Cause、Activation和Canonical Result同SEG。
3.5 平行线程只保存全局Exit
失败：屏幕最后是Thread A，误以为Thread B状态丢失。
修正：Continuity保留每个Active Thread最新状态；SEG仅记录屏幕Entry/Exit和相关Thread Handoff。
3.6 Model-Native Transition跨SEG
失败：SEG01输出遮挡开始，SEG02输出遮挡解除，仍需要外部拼接才能形成转场。
修正：完整Exit、Transition Window、State Switch Point和Entry Establishment归属同一SEG；边界只放在转场前后稳定状态。
3.7 转场不计入SEG时长
失败：镜头时长已经填满SEG，又要求模型额外生成甩镜/淡变，导致对白和动作被压缩。
修正：Transition占用真实Timeline时长；重新分配Shot时长或SEG边界。
4. 资产与Reference漏洞
4.1 CHAR过度绑定Story Age和服装
失败：用28岁Root强行改24岁，或Root展示服成为默认COST。
修正：CHAR只固定Permanent Identity；年龄/长期外观进入PH，服装进入COST/LOOK。
4.2 PH、LOOK、CT被当局部修图
失败：换衣贴图、伤口贴纸、像素复制。
修正：Derived Asset执行Authority Extraction、Target Delta和New Reconstruction。
4.3 CT并行效果层
失败：CT_INJURY + CT_WET + CT_DIRTY分开叠加，顺序和继承冲突。
修正：当前CT是所有Active State的完整合并状态；新CT以前一CT为Parent。
4.4 Scene Blocking进入CT
失败：CT把“双手撑桌/躺地”固定为人物状态。
修正：人物持续外观进入CT；姿态、位置和Holder进入CVS/SCSTATE。
4.5 Reference Authority等于Composition
失败：Atomic Sheet的中性站姿污染Blocking；SCSTATE中景限制所有KF。
修正：Identity Lock ≠ Pose Lock；SCSTATE Lock ≠ Shot Lock；写MUST NOT COPY和DOES NOT CONTROL。
4.6 生产人员不知道上传什么
失败：只给Prompt，不给真实文件、顺序和范围。
修正：每次调用输出Reference Input Manifest；Image编号按调用重置并与Prompt一致。
4.7 多个Reference控制同一维度
失败：LOOK与COST同时控制服装，两个SCSTATE平均融合。
修正：明确Primary Authority和Applicable Scope；保留Authority-Complete Nonconflicting Set。可以删除冗余，但六维Coverage不得出现缺口。
4.8 参考容量超限
失败：随意删除CT、Hero Prop或Location Authority。
修正：用高层资产替代低层、合并背景角色、移除已融合Wearable、按Thread/Window隔离，最后才调呈现粒度。
4.9 PROP规格被当成物理实体
失败：两支同款注射器共用一个PROP ID，导致一支被使用后另一支也变空。
修正：读取[PROP规格、物理实例与数量连续性](08-prop-spec-and-physical-instance.md)；SPEC只管共同外观，INSTANCE独立拥有状态和历史。
4.10 同款实例被人工制造差异
失败：为了区分两件同款文件，模型随机改色、加划痕或改标签。
修正：允许完全同外观；用INSTANCE ID、Holder、Anchor、动作路径和事件区分。独有标记必须来自Canon。
4.11 批量同款物件导致资产爆炸
失败：会议室20把同款椅子生成20张重复资产图。
修正：使用一个PROP_SPEC Reference与PROP_SET；只有产生交互时才物化INSTANCE，实例默认可为LOGICAL_ONLY。
4.12 SPEC静默改版
失败：后期修改标签版式，旧时间线里的全部实例也被反向替换。
修正：SPEC使用Revision和effective scope；实例绑定合法revision，禁止静默覆盖。
4.13 Canonical ID后段缩写
失败：前面登记PRJ_NOVA__CHAR_001_PH01_LK01_CT01_R01，SCSTATE或Video后面写成CT01、女主CT01或CHAR_001_CT01。
修正：读取[Canonical ID注册表与参考资产解析](10-canonical-id-registry-and-resolution.md)；所有ID字段只能从Registry逐字符复制完整Canonical Revision ID。
4.14 ID存在但Reference文件找不到
失败：Manifest只有内部ID或“上一张定妆图”，生产人员不知道具体上传哪个文件。
修正：每个Image槽输出完整Revision ID、精确文件名、File Role、相对/解析路径、Fingerprint和Availability。
4.15 同一ID覆盖成新图
失败：保留R01名称但文件内容已被修改，旧Storyboard仍认为它是原Canon。
修正：Canonical Revision不可变；Fingerprint变化必须建立R02并显式回编受影响下游。
4.16 模糊匹配或自动最新版本
失败：找不到完整ID时自动选择名字最像或修改时间最新的资产。
修正：Exact Registry Lookup失败即REFERENCE_RESOLUTION_BLOCKED；不得猜测、Silent Redirect或自动升级Revision。
4.17 Candidate被当成Reference
失败：刚生成但未确认的TRY图直接进入下游。
修正：只有Registry状态为CANONICAL且文件解析通过的Revision可以占Image槽。
4.18 同一场景多视角独立生成
失败：正面、侧面、背面各自漂亮，但门窗、家具、距离和连接关系无法拼合。
修正：读取[空间坐标、机位Rig与多视角一致性](11-spatial-rig-and-multiview-consistency.md)；同一Spatial坐标和Geometry Proxy逐View投影、闭环核对。多视图Sheet只能汇编批准View。
4.19 用故事板融合掩盖上游空间错误
失败：Location资产互相矛盾，但故事板暂时看起来融合较好，就把空间标记Canonical。
修正：资产必须在F2独立通过几何闭环；无法回投World坐标的View保持CANDIDATE，不进入下游。
4.20 COST与LOOK策略倒置
失败：孤立服装图直接作为视频人物服饰主参考，或每套简单服装都生产独立资产。
修正：读取[服饰资产、完整LOOK与首次显露覆盖](12-costume-look-and-visual-coverage.md)；关键/复杂/复用服装独立COST，简单服装LOGICAL_ONLY，但下游都必须形成当前PH的完整LOOK。
4.21 LOOK或CT视觉覆盖不完整
失败：人物板裁掉鞋或没有背面，视频首次显露时自由发明。
修正：维护Visual Coverage Map；可能首次显露的头、手、脚、正侧背和当前状态区域必须在LOOK/CT中定义。
4.22 Image槽位身份映射不完整
失败：Prompt只写“Image 1控制人物LOOK”，但没有说明Image 1中的人物是谁、处于哪个年龄/LOOK/CT、图中可见什么以及在哪个KF或时间窗有效。
修正：在现有Manifest和Prompt中加入六字段Compact Reference Identity Map：Exact ID、Who / What + Visible Content、Story Time / Current State、Controls、Does Not Control、Applicable Scope。映射缺失、错序或与Manifest不一致时输出REFERENCE_MAPPING_BLOCKED；不新增资产类型或第二套注册表。
5. Continuity与时间漏洞
5.1 Active State只写ID不展开
失败：模型不知道CT03包含伤口、贴片、破损。
修正：展开Persistent Visible State Checklist。
5.2 Presence等于Visibility
失败：镜头没拍到脖子，贴片被当成消失。
修正：区分Visible、Partial、Occluded、Off-frame和Not Active。
5.3 未来状态前置
失败：后期KF贴片污染0秒。
修正：Future-State Embargo、Activation Event、Timeline Window和必要时Temporal Reference Window。
5.4 弱化预现未被禁止
失败：完整贴片没出现，但前面已有淡淡白块。
修正：禁止未来状态以完整、部分、弱化、模糊、预示或融合形式出现；合法预示单独建状态。
5.5 状态无事件恢复
失败：伤口、湿衣、烧焦墙面为了下场方便消失。
修正：所有失活来自Deactivation、Replacement、Time Gap或Lifecycle Rule。
5.6 同步Delta错位
失败：瓶子碎了但仍在手里，地面下一场才出现玻璃。
修正：同一Event同步更新Character、Prop、Holder、Spatial和Environment。
5.7 长期不出现后重置
失败：角色EP20复出自动用EP03旧LOOK；房屋17集未出现被重新设计。
修正：按Time Gap、PH、Events和Current Scene重新解析；LOC/SPATIAL无修订则继续。
5.8 遮挡或离画等于不存在
失败：道具被身体挡住后消失，重新入画时生成一件新副本。
修正：Existence与Visibility分离；Occluded、Off-frame、Contained均保持同一INSTANCE与Active State。
5.9 Object Count不可对账
失败：一件道具经过切镜变成两件，或未销毁却减少。
修正：每个SCSTATE、Storyboard Entry/Exit和Video Window执行Full + Partial + Occluded + Off-frame = Active Total；总量仅由合法事件改变。
5.10 破坏、消耗与容器内容混淆
失败：喝完水后瓶子也消失；玻璃破碎后完整瓶和碎片同时存在。
修正：容器与内容物分开；破坏、消耗、Split/Merge记录父子身份、余量、存在状态和同步Delta。
6. CVS、SCSTATE与Storyboard漏洞
6.1 CVS包含Camera
失败：CVS同时拥有Physical Truth和Camera Truth。
修正：删除shot_size、camera、composition、screen_direction；使用CVS + Shot → KF。
6.2 CVS第一次决定穿什么
失败：Director和Blocking不知道当前服装/伤势限制。
修正：Current Appearance Resolution在Director前完成，CVS绑定active_visual_asset_id。
6.3 SCSTATE成为第二套状态真相
失败：SCSTATE图片决定有无伤、谁拿文件。
修正：SCSTATE只是CVS视觉物化；冲突时重生成SCSTATE。
6.4 SCSTATE记录Transition
失败：手靠近门、碰门、开一半分别建SCSTATE。
修正：只建Stable Before和Stable After，中间交给VT/Storyboard/Video。
6.5 “至少两类Delta”漏掉单一关键变化
失败：炸弹启动灯、唯一关键门锁状态因只有Prop Delta被过滤。
修正：默认两类；满足关键、可读/可执行、持续/因果、删除会丢真相四条件时使用SINGLE_DELTA_CRITICAL_OVERRIDE。
6.6 SCSTATE数量固定
失败：每SEG强制3至4张，造成资产爆炸。
修正：按Stable State Change与下游价值动态1...N。
6.7 Storyboard固定9个KF
失败：为凑3×3加入重复情绪格。
修正：动态KF；每张Sheet最多3个KF，更多关键时刻增加Continuation Sheet。
6.8 “一SEG一张Sheet”与动态容量冲突
失败：4个以上KF、多Thread或多个关键动作Phase仍塞一页，人物和交互细节不可检查。
修正：一SEG一个Canonical Storyboard Package，允许1...N有序Continuation Sheets；内容仍唯一。
6.9 多Location/Thread同板融合
失败：医院、雨夜、病房状态互相污染。
修正：Reference Applicable KF、Thread Firewall、状态带或分Continuation Sheet。
6.10 Storyboard复制SCSTATE机位
失败：所有KF都是相同中全景。
修正：SCSTATE + New Camera Observation = KF。
6.11 动作重复
失败：签字/跌倒/拔针在后续KF再次从头发生。
修正：Action Phase和No Action Replay；Completion后进入Post/Reaction/Exit。
6.12 终点结果未冻结
失败：只画爆炸前后大概，Video自行决定墙坏成什么样。
修正：关键结果进入Target CVS和终点KF。
6.13 人物空间位置只写画面左右
失败：切换机位后“左边的人”被重放到门的另一侧或另一个Zone。
修正：CVS/SCSTATE/KF写World Root/Foot XYZ、Anchor Offset、Orientation和支撑/占地；Camera只重新投影。
6.14 Storyboard新机位首次发明空间
失败：资产只定义走廊一面，Storyboard从反方向生成后门窗和家具重新排列。
修正：KF绑定批准LOC_VIEW或Geometry Proxy。新方向先建立View；未覆盖时NEW_VIEW_REQUIRED。
6.15 半身Storyboard未声明视频显露范围
失败：KF只有上半身，视频拉远或人物起身后下装、鞋履和身体比例漂移。
修正：每个KF/Window建立Camera Reveal Envelope和First Reveal Coverage Gate；补当前LOOK/CT覆盖或限制Camera。
6.16 Storyboard没有Transition Anchor
失败：Prompt要求遮挡或甩镜转场，但Package只有两个稳定KF，模型不知道何时遮满、何时切换。
修正：读取[视频模型原生镜头切换](13-model-native-shot-transition.md)；按需要加入Exit、Trigger、Shield/Peak和Entry Anchor，明确它们不是新CVS。
6.17 NATIVE_CUT被当连续运镜
失败：模型从近景平滑移动到另一个独立机位，造成空间穿越或人物漂移。
修正：冻结瞬时cut_at并声明DO NOT INTERPOLATE CAMERA BETWEEN SHOTS。
6.18 SCSTATE人物无事件换位
失败：人物前一状态坐在发布会桌后，下一SCSTATE因为需要争吵同框，直接站到观众区前场。
修正：读取[空间状态门控与Authority完整视频参考](14-spatial-state-gating-and-video-reference-minimization.md)；锁定World Position State与Seat/Support Binding。相邻状态只允许Authorized Movers按Release→Route→Portal→Target Anchor→Completion换位；没有事件则精确继承。
6.19 Storyboard为构图重新Blocking
失败：SCSTATE位置正确，但故事板为了显示三个人全身，把人物搬到房间中央或桌子另一侧。
修正：KF写Position Delta与Authorized Movement Event ID。Camera可以换机位、允许遮挡或拆镜，人物不能为可见性换Zone。
6.20 场景多视图高度相似
失败：A01、A02、A03都处于相近眼平高度、使用相近焦段并看向房间中心；只有轻微左右平移或Zoom，看到的Zone、Portal、Route和Landmark几乎相同。
修正：读取[场景机位覆盖规划与重复视图控制](16-location-view-coverage-and-redundancy-control.md)。先从Scene/Shot/KF提取Spatial Demand，建立Location View Coverage Plan与逐View Utility Contract。没有独有消费者、独有Zone/关系、动作轴、视差或遮挡价值的Candidate触发REDUNDANT_VIEW_REJECTED。
6.21 用焦段或裁切冒充新LOC_VIEW
失败：同一Camera Position只改变Lens、Shot Size或裁切，却创建新的Canonical View ID。
修正：保留一个LOC_VIEW并登记allowed_crop或Derived Crop；只有无法由裁切替代的真实空间Authority才创建新View。
6.22 相邻View参考复制构图
失败：为了保持跨View一致性上传已批准邻图，模型把邻图的Camera、Look-at、Crop和Composition复制到当前View，最终每张图越来越像。
修正：相邻Image只控制固定结构Identity、材质、Landmark、尺度与Overlap；明确Does Not Control: Camera XYZ / Height / Look-at / Lens / Crop / Composition / Visible Zone / Shot Size并禁止复现邻图构图。
6.23 先定VIEWPACK再凑机位
失败：为了填满2×2 Atlas或一次生成三个输出，额外创建没有独有用途的第三张相似View。
修正：Distinctness Gate先于Merge Eligibility；只把已证明必要的View放入Batch/Pack，空格位留作Geometry Check或空白校验区。
6.24 CVS全局完整性被误解为单图同框
失败：同一CVS横跨远距离、不同楼层或Barrier，SCSTATE为了显示全部Active实体而缩短距离、移动人物或融合地点。
修正：读取[Story-First、Zone-Coherent SCSTATE与故事板可读性门控](17-story-first-zone-coherent-scstate-and-storyboard-readability.md)。CVS保持唯一全局真相；按Camera-coherent Spatial Cluster派生多个SLC，其他Zone实体登记为OFF-FRAME ACTIVE。
6.25 SCSTATE只有技术字段没有故事
失败：Prompt充满ID、坐标与Count，但隐藏ID后无法判断原文时刻、主角、动作、前因和下一刻。
修正：先写FULL SCENE STORY CANON、EXACT VISUAL MOMENT、BEFORE/NOW/AFTER、PRIMARY NARRATIVE SUBJECT，再写Reference Map与技术合同；否则SCSTATE_STORY_CONTEXT_INSUFFICIENT。
6.26 一张SCSTATE承担两个不相容剧情焦点
失败：一个中性画面同时验证楼上追逐和楼下对话、远端骑兵冲突和近端手部交互，导致两个焦点都不可读。
修正：返回SCSTATE_SPATIAL_SLICE_REQUIRED，从同一CVS建立多个SLC；不得使用分屏、蒙太奇或超广角压缩代替。
6.27 Storyboard偷修错误SCSTATE
失败：SCSTATE人物在错误Zone或因果不符，Storyboard通过重新Blocking看似修正，造成上游和下游两套世界状态。
修正：返回SCSTATE_STORY_MISMATCH；建立新SCSTATE Revision/SLC并重新编译全部受影响Storyboard、KF、Shot、Transition和Video。
6.28 Storyboard高密度排版
失败：一张Sheet包含4格以上或九宫格，为塞入更多镜头而把人物、兵器、表情、伤势、手部、马匹或关键Prop缩到不可检查。
修正：STORYBOARD_DENSITY_BLOCKED；每Sheet最多3个KF，增加Continuation Sheet且保持同一SBPKG。
7. Video与声音漏洞
7.1 Storyboard变成Morph
失败：人物滑动、融化、网格进入视频。
修正：明确Temporal Performance Reconstruction和MUST NOT COPY Sheet Layout。
7.2 Video再次上传全部Atomic资产
失败：多重Reference覆盖Storyboard状态和时间。
修正：先提供覆盖完整关键推进的Mandatory Storyboard Temporal Spine，再完成六维Coverage Matrix与Effective Reference Selection。不得为填满槽位重复上传SCSTATE、LOOK、Location、LOC_VIEW、PR、马匹或Prop；只有记录独有Identity、Coverage、Geometry、Prop、State Result或Boundary缺口后，才加入Supplemental。
7.3 Prompt只写“保持一致”
失败：时间窗口无Allowed/Forbidden/Activation。
修正：逐Window写Entry State、Event、State Gate、Target和Exit。
7.4 对白翻译改剧情事实
失败：改姓名、职务、金额、地名或关系。
修正：翻译只改变语言表达，Canon事实不变。
7.5 固定时长造成异常语速
失败：大量对白塞进15秒。
修正：在授权范围内精炼文本、调整SEG边界或镜头节奏；不机械快说。
7.6 音频模式不明
失败：Silent Video出现随机口型/音乐，Separate Audio没有Cue。
修正：初始化冻结video_audio_mode，Prompt与Audio Cue Sheet一致。
7.7 补充全身参考抢夺Camera Authority
失败：为防全身漂移加入LOOK后，模型复制中性站姿、背景或构图。
修正：Storyboard控制Camera、Pose、Blocking、Action和Time；LOOK/CT只控制Identity、比例、服饰和首次显露区域，写清DOES NOT CONTROL。
7.8 Camera越出空间或人物视觉覆盖
失败：模型随机环绕、拉远，出现另一套场景或未定义服饰。
修正：空间使用批准Geometry/View Coverage，人物使用Visual Coverage；Coverage不足时执行Framing Expansion Embargo。
7.9 Video只会硬切
失败：所有Shot无论叙事关系都机械直接切，错失动作、遮挡、运动、光线、声音与主观线程的原生镜头语言。
修正：每个Transition写Mechanism + Cinematic Grammar + Narrative Function，按模型能力动态选择，不固定硬切。
7.10 转场依赖外部剪辑
失败：Video Prompt输出多个镜头素材、黑帧占位或“后期添加叠化/声音桥”。
修正：transition_execution_mode = MODEL_NATIVE_ONLY；模型一次输出完整SEG成片，禁止External Shot Assembly与Transition Editing。
7.11 遮挡转场中人物/场景融合
失败：遮挡未达到100%时未来人物、贴片或Target Location已经出现，形成混合状态。
修正：From-only → Shield Build → 100% Shield → Switch Point → Target-only；Shield Frame没有World Truth Authority。
7.12 Dissolve被当Canonical共存
失败：光学叠加导致两张脸、两套服装、两个Location或两个时间状态融化成一个中间世界。
修正：Transition Visual Overlap不等于State Coexistence；限制Dissolve用途，禁止实体Morph并保持双方独立视觉层。
7.13 模型能力不足后静默改后期
失败：模型不能稳定多镜头，于是分别生成Shot再拼接，违背用户的无额外剪辑要求。
修正：按Capability Gate降级为Full Occlusion/Dip/Flash/Defocus、低复杂度Motion或单镜头连续表达；仍失败则MODEL_NATIVE_TRANSITION_BLOCKED。
7.14 Video同时上传Storyboard与SCSTATE
失败：Storyboard规定最终Shot与Blocking，SCSTATE提供中性验证构图，两者同时作为Composite Reference导致模型平均融合、回退机位或重排人物。
修正：SCSTATE/SLC不默认进入Video；当前SEG已批准的Storyboard载体共同形成唯一有序时间/镜头骨架。原子缺口先证明独有Authority，不能用重复图“投票”；生成视频帧没有Reference资格。
7.15 Video参考图装满上限
失败：平台允许10张就上传9至10张，多个身份、空间、道具与状态Authority互相竞争。
修正：图像上限是容量，不是目标，最少张数也不是目标。先保留完整Mandatory Storyboard Temporal Spine，再建立六维Coverage Matrix。每张Supplemental必须有唯一Reference Role与Applicable Window；无独有贡献即VIDEO_REFERENCE_UNIQUE_UTILITY_UNPROVEN，删图后缺维即REFERENCE_DIMENSION_COVERAGE_GAP。容量不足先去重、换等价故事板载体或在稳定Beat拆SEG。
7.16 Video没有重新讲清完整剧情
失败：Prompt只有Shot/KF标签、Camera和技术字段，假定模型会从故事板自行理解谁对谁做什么以及动作为什么发生。
修正：返回VIDEO_STORY_CONTEXT_INSUFFICIENT；重新写完整SEG剧情摘要，并逐秒说明施动者、动作、受动者、结果、反应与下一触发。
7.17 Video补充参考未经证明
失败：Storyboard之外例行上传人物LOOK、Location、Prop或马匹，形成重复Authority。
修正：只有记录缺失Authority、适用时间窗、Storyboard为何不能充分提供、独有Authority Contribution以及该补图不控制什么后，才允许原子补图，否则VIDEO_REFERENCE_UNIQUE_UTILITY_UNPROVEN。若缺口属于中间姿势或动作，优先交给视频执行；若属于稳定身份/状态结果，再回编Storyboard或独立Anchor。
7.18 图片层承担了过多中间动作
失败：SCSTATE、每个KF和多格Sheet都要求出图，图片模型同时承担多人、手部、Blocking、连续动作、精确道具和高密度排版，错误被固化后传给视频。
修正：执行Image Materialization Gate。SCSTATE默认是逻辑合同；中间动作KF标记TEXT_CANON_ONLY或DEFER_TO_VIDEO；只有独有Identity、Geometry、不可逆State Result或高风险入口/出口通过门控后才出独立Anchor。超出image_complexity_budget返回IMAGE_COMPLEXITY_OVER_BUDGET，不得继续下游。
7.19 把“少图”误解成“少控制”
失败：减少图片后同时删除CVS、位置、Holder、Count、Temporal Gate和逐秒因果，导致视频自由改写故事。
修正：逻辑控制完整度不得下降。无论上传几张图，Video Prompt都必须完整重述Entry、逐秒因果、Authorized Route、状态门控、Transition、Audio和Exit；Hero Identity与当前LOOK/CT、Location Master与相关LOC_VIEW、World XYZ、Zone、Anchor、Support、Route、Orientation、Count和Holder均为不可降级底座。少的是重复像素Authority，不是Story/Continuity/Spatial Authority。
7.20 未验证视频模型就过度减弱Storyboard
失败：仅凭模型宣传或一次成功样片，将复杂SEG设为HIGH并只给入口图，导致中段动作、人物或出口漂移。
修正：任何可靠度都保留Mandatory Storyboard Temporal Spine。记录video_reliability_evidence；可靠度只改变骨架颗粒度、Supplemental数量与Prompt冗余度。证据不足返回VIDEO_RELIABILITY_UNVERIFIED。
7.21 把视频输出直接升格为Canon
失败：生成视频中偶然正确的一帧被直接当成下一SEG参考，错误身份、位置或Prop随之传播。
修正：任何生成视频截图、尾帧或Frame Grab只用于QC，Reference Authority恒为NONE。相邻SEG必须在两条视频生产前，从Story Truth、CVS、Spatial、当前LOOK/CT、Prop Ledger与Shot Intent编译BNDPLAN及可选BNDANCHOR OUT/IN。发现生成帧引用返回GENERATED_FRAME_REFERENCE_FORBIDDEN。
7.22 把连续动作拆到两个SEG
失败：前一SEG结束在挥拳、跌倒、交接、换装、状态激活、对白半句或Transition中间，后一SEG试图靠尾帧续动作，拼接点出现重复、跳跃或状态冲突。
修正：边界只能位于完成的稳定Beat。动作、对白单元、状态激活、Prop交接和原生Transition必须归属一个SEG。不能满足时返回SEG_BOUNDARY_DESIGN_BLOCKED并回编SEG，不得用上一视频尾帧补救。
7.23 减图后丢失人物与场景位置锁
失败：删除SCSTATE或Storyboard图片时，同时删除了World Position、Zone、Anchor、Support、Route、Barrier/Portal、Orientation或相关LOC_VIEW，视频只能重新想象人物和场景关系。
修正：执行REFERENCE DIMENSION COVERAGE GATE。位置合同始终由CVS/BNDPLAN逐项继承，视觉空间由当前Anchor、必要LOC_VIEW或BNDANCHOR覆盖；无Authorized Movement Event不得换位。缺任一维返回REFERENCE_DIMENSION_COVERAGE_GAP。
7.24 Video缺少Storyboard时间骨架
失败：Video只上传人物LOOK、场景图、SCSTATE或入口图，要求模型从文字自行发明镜头顺序、构图推进与不可逆结果。
修正：返回VIDEO_STORYBOARD_SPINE_MISSING。补齐当前SBPKG有序Continuation Sheets或等价有序Canonical KF Anchors，覆盖入口、关键转折、不可逆结果与出口。
7.25 错误Storyboard进入Video
失败：故事板来自旧Revision、另一SEG/Thread、错误时间状态、错误World Position或包含未来CT。
修正：执行Storyboard Reference Admission Gate。逐图核对Revision、SEG、Thread、Time Range、Source State、LOOK/CT、World Position、Prop、Boundary与排序；失败返回STORYBOARD_REFERENCE_ADMISSION_FAILED。
7.26 Video Prompt缺少导演执行密度
失败：只有剧情摘要、镜头标签和“紧张、电影感、细腻”等形容词，没有微表演、动作阶段、物理反应、Camera Grammar、声音同步和窗口出口。
修正：返回VIDEO_PROMPT_EXECUTION_DETAIL_INSUFFICIENT。逐时间窗口写Beat目的、人物目标/阻力、眼神/呼吸/重心/反应延迟、动作Phase、Camera动机/轴线/焦点/切点、声画同步与Next Trigger。
8. 长剧与修订漏洞
8.1 Revision无生效时间
失败：EP10开始戴戒指被反向应用到EP01。
修正：所有Revision写effective_story_time与reality_thread。
8.2 自然演化无限制造CT
失败：伤口每天阶段都生成资产，即使当前没镜头展示。
修正：Ledger记录阶段；只在当前Scope需要稳定可见且差异有生产价值时物化CT。
8.3 Same Visit与New Visit混淆
失败：两个月后临时杯子仍完全原位，或两分钟返回房间临时状态被重置。
修正：按Time Gap与Lifecycle解析临时状态，基础LOC/SPATIAL保持。
8.4 Hidden Truth泄漏
失败：全剧分析知道反派身份，EP01资产/表演提前暴露。
修正：生产使用Presented Identity、Character Knowledge和Audience Knowledge。
9. 交付完整性审计
逐项确认：
[ ] Project Config、Scope、seg_duration、画幅、模型、语言和音频模式明确。
[ ] Story Unresolved与Visual Underspecified分开。
[ ] Entity ID唯一，同一Physical Entity未重复创建。
[ ] Project ID、ID Policy、Registry Snapshot与唯一Canonical Asset Registry已冻结。
[ ] 所有生产字段使用完整Canonical Revision ID，没有缩写、显示名称替代或漏Revision。
[ ] Target为RESERVED/CANONICAL，全部Reference状态为CANONICAL。
[ ] 每个Reference有精确文件名、角色、路径、Fingerprint和VERIFIED Availability。
[ ] Manifest ↔ Prompt通过Exact ID Echo Audit，没有Dangling、Duplicate或Silent Redirect。
[ ] 每个有Reference的Prompt都包含六字段Compact Reference Identity Map；Image编号、完整ID、Who/What、Current State、Controls和Applicable Scope一致。
[ ] 身份映射缺失或上传错序会触发REFERENCE_MAPPING_BLOCKED，模型不会猜图继续。
[ ] 重复同款道具已分离PROP_SPEC、PROP_SET/INSTANCE和INSTANCE CT。
[ ] 同款实例没有被擅自改色、加划痕或共享物理状态。
[ ] Current Scope资产按依赖排序，状态标记正确。
[ ] 每个Location有统一World坐标、尺度、Geometry Proxy或批准的降级方案。
[ ] 每个Location已从Scene、Blocking、Shot、KF和Camera Reveal提取Spatial Demand，并建立Location View Coverage Plan、Coverage Matrix和逐View Utility Contract。
[ ] 每个批准LOC_VIEW有明确View Role、独有Coverage、完整消费者ID、与已有View的差异和不可由Allowed Crop替代的理由；视图数量动态，没有固定三视图。
[ ] 仅焦段、Zoom、轻微横移或裁切差异没有被创建为新LOC_VIEW；高Overlap且无独有Authority的Candidate已触发REDUNDANT_VIEW_REJECTED。
[ ] 相邻View Reference只控制固定结构Identity、Landmark、尺度和Overlap；不控制当前Camera、Crop、Composition或Visible Zone，Prompt明确禁止复现邻图构图。
[ ] 同一Location的必要视角都来自同一Proxy；先通过View Distinctness Gate，再执行View Merge Eligibility Audit。兼容机位可用VIEW_BATCH/VIEWPACK合并生产，不兼容机位保持单View；Landmark、门窗、固定家具、尺度和连接关系闭环一致。
[ ] 每个合并组最多3个机位，且共享相同Location/Spatial/GEO Revision、Reality Thread、Story Time、天气、光照与环境状态。
[ ] VIEWPACK具备固定Panel Identity Map、Output Index/格位、子LOC_VIEW完整ID、Camera Rig、裁切框和最低派生分辨率。
[ ] VIEWPACK产出已裁切/导出为独立LOC_VIEW文件并分别计算Fingerprint；SCSTATE、Storyboard和Video默认没有上传整张多机位Atlas作为单一Camera Authority。
[ ] 每个LOC_VIEW有完整Revision ID、Camera Rig、覆盖范围、文件路径与Fingerprint。
[ ] 关键/复杂/复用COST已物化；简单COST可LOGICAL_ONLY，但每个当前造型都有完整on-body LOOK。
[ ] LOOK/CT Visual Coverage Map包含将被首次显露的正侧背、下装、手脚、鞋履和Active State区域。
[ ] 每个NEW项有真实Manifest、Upload Order和Complete Prompt。
[ ] Reference Authority、Preserve、Transform、Not Copy、Does Not Control、Scope齐全。
[ ] Continuity Ledger可追溯到Event，状态有Lifecycle。
[ ] Active Character Visual Root和Persistent Checklist展开。
[ ] CVS不含Camera，绑定当前视觉资产和物理状态。
[ ] 人物与关键Prop位置使用World XYZ或Anchor Offset，不以Screen Left/Right代替Physical Truth。
[ ] 相邻CVS/SCSTATE/KF的位置变化均绑定Authorized Movement Event；没有事件时Zone、Anchor、Seat/Support、Posture Class与Barrier Side逐项继承。
[ ] 人物离开座椅/床/车辆或跨桌、墙、门等Barrier时有Release、Route、Portal与Completion，不存在为构图瞬移。
[ ] VT同步Delta，Target CVS明确。
[ ] SCSTATE来自CVS，不含动作半程。
[ ] 每个SCSTATE/SLC Prompt先写FULL SCENE STORY CANON、EXACT VISUAL MOMENT、BEFORE/NOW/AFTER与唯一PRIMARY NARRATIVE SUBJECT，隐藏ID后仍能理解原文时刻和因果。
[ ] 跨远距离、不同高度、Barrier或不相容动作轴的CVS已派生Zone-Coherent SLC；全部Slice共享Story Time、Object Count、Instance Register与Spatial Revision，其他Zone实体登记为OFF-FRAME ACTIVE。
[ ] SCSTATE Delta默认阈值与Single-Delta例外正确。
[ ] Shot数量、KF数量、SCSTATE数量动态。
[ ] Project Config冻结MODEL_NATIVE_ONLY、外部剪辑禁令与目标模型原生多镜头能力等级。
[ ] 每个Transition使用完整Canonical Revision ID，并有From/To Shot、Narrative Function、Mechanism、Grammar和时间范围。
[ ] SEG边界不拆关键Cause/Result。
[ ] 每个Transition完整归属一个SEG并计入真实时长，边界没有拆开Shield/Switch/Entry。
[ ] Storyboard Package内容唯一，Sheet只是承载；每张Sheet最多3个KF，没有九宫格或高密度缩人排版。
[ ] 每张Sheet有完整SEG摘要、SEG/Sheet时间范围、Source SLC和唯一Primary Narrative Subject。
[ ] 每个KF有自然语言剧情句、Speaker/Dialogue、Source SLC、Thread、Phase、Position Delta、Active/Forbidden State与Exit。
[ ] 每个Prop动作绑定INSTANCE ID，Object Count与Visibility Bucket可对账。
[ ] Storyboard Reference Firewall与Video Temporal Gate分别存在。
[ ] Video每时间窗有Activation、Allowed、Forbidden、Target和No Replay。
[ ] 每个Video Window有Camera Reveal Envelope、First Reveal Coverage结果和必要的Framing Expansion Embargo。
[ ] NATIVE_CUT有精确cut_at且禁止Camera插值；遮挡/运动/光学Transition有Trigger、Shield/Peak、Switch Point和Target-only Entry。
[ ] Video Prompt要求一次返回完整多镜头SEG成片，没有镜头素材包、转场占位、外部拼接、后期补救或失败帧裁除依赖。
[ ] Video重新写了完整SEG剧情摘要和逐秒施动者→动作→受动者→结果→反应→下一触发因果。
[ ] 每个SCSTATE与KF先经过Image Materialization Gate；LOGICAL_ONLY、TEXT_CANON_ONLY和DEFER_TO_VIDEO没有伪造Image槽。
[ ] 图片复杂度没有超过项目预算；多人、手部、精确Blocking、连续动作与多格排版没有被无理由叠加给图片模型。
[ ] 每个Video SEG都有覆盖完整关键推进的Mandatory Storyboard Temporal Spine；可靠度只调整骨架颗粒度、补图和Prompt冗余度。
[ ] 每张Storyboard参考均通过Revision、SEG、Thread、时间、状态、位置、Prop、Boundary与排序Admission。
[ ] 六维Coverage Matrix完整；Identity、LOOK/CT、Spatial/Geometry、Position/Blocking、State/Temporal、Prop/Count/Holder均有唯一Authority。
[ ] 每张Supplemental有唯一Reference Role、Applicable Window与独有Authority；同一状态SCSTATE/SLC、LOOK、Location、LOC_VIEW、PR、马匹或Prop未重复争夺主权。
[ ] 每张例外Supplemental都有缺口、时间窗、独有贡献和Does Not Control的书面证明。
[ ] 少图没有减少完整SEG摘要、逐秒因果、位置、Count、Holder、状态门控、声音和Exit合同。
[ ] 所有生成视频截图、尾帧和Frame Grab只用于QC，没有进入任何下一SEG或图片生成Reference Manifest。
[ ] 相邻SEG在生产前已有BNDPLAN；同场连续高风险边界使用来自上游Canon的BNDANCHOR OUT/IN或合法共享Anchor。
[ ] 人物和场景的位置锁定没有因减图消失；World XYZ、Zone、Anchor、Support、Route、Barrier/Portal与Orientation均已继承。
[ ] Video Prompt具备完整戏剧弧和逐窗口导演执行卡；微表演、动作阶段、物理反应、Camera Grammar、声画同步与窗口出口均可检查。
[ ] 原生声音模式下J/L Cut、Sound Match/Drop和Ambience Bridge在同一次生成中完成。
[ ] Final State能作为下一SEG Entry。
[ ] 没有占位符、内部引用标记、测试图或失败版本进入最终生产包。
10. 最终一票回编条件
出现下列任一项，不得交付生产执行，必须回编：
Story因果、施动者、目标或关键结果被改变。
同一Story Time出现互斥的两个Canonical State。
Reference无法确定哪张图控制哪个对象/范围。
Future State在Activation之前可见。
Active Persistent State无合法原因丢失。
CVS或SCSTATE与Spatial/Continuity冲突。
关键Prop身份、文字、Holder或状态未冻结。
Storyboard KF重复动作、漏关键结果或跨Thread污染。
Video Prompt首次创造关键剧情事实。
下游修改上游但未显式Revision与重编译。
同款道具未绑定Physical Instance，或Object Count无法由事件和可见性对账。
任何ID被缩写、改写、漏命名空间/Revision，或无法在唯一Registry完全匹配。
Reference未解析到唯一Canonical文件、路径与Fingerprint，或使用了非CANONICAL状态资产。
同一Location的两个必要视角无法由同一Spatial坐标和Geometry Proxy解释，或View在闭环失败后仍进入下游。
人物/Prop的World Placement缺失，切镜只能依赖画面左右猜测真实位置。
当前人物造型没有完整LOOK，或视频会显露未定义的身体、服饰、鞋履/背面区域且没有限制Camera。
Model-Native Transition被拆到两个SEG，或输出需要任何外部镜头拼接、后期转场/声音桥或失败帧裁除。
Transition缺少完整ID、时间所有权、Mechanism、Exit/Entry或State Switch Point，导致模型自由决定切换。
Shield达到100%之前Target人物/Location/状态已经出现，或Transition产生混合Identity、混合空间、未来状态前置。
目标模型原生多镜头能力不足，却没有安全降级或MODEL_NATIVE_TRANSITION_BLOCKED。
任一Image槽没有明确Who/What、当前Story Time/State、Controls、Does Not Control或Applicable Scope，或映射与上传顺序不一致。
人物Position State改变但没有Authorized Movement Event、合法Route、Portal Crossing或足够完成时间。
SCSTATE或Storyboard为同框/构图擅自解除Seat/Support Binding或把人物移动到另一Zone。
Video缺少Mandatory Storyboard Temporal Spine，或同一状态的SCSTATE/SLC、LOOK、Location、LOC_VIEW、PR、马匹或Prop与故事板重复争夺主权威。
为节省调用强行合并不同Location/Reality Thread/永久Geometry/时间或环境状态，或合并组超过3个机位。
VIEWPACK没有固定Panel Identity Map、子LOC_VIEW独立文件/完整ID/Fingerprint，或裁切后分辨率低于项目门槛。
下游把整张VIEWPACK当作单一机位参考，导致多个Camera、透视或构图Authority同时进入同一SCSTATE/KF/Video。
Location没有View Coverage Plan，或Candidate View没有独有消费者、独有空间Authority与不可由Crop替代的理由却仍进入生产。
仅焦段、Zoom、轻微横移、升降或裁切不同的高度相似视图被登记为多个Canonical LOC_VIEW。
相邻View Reference控制了当前Camera/Composition/Visible Zone，导致不同View复制同一构图。
为填满VIEW_BATCH/VIEWPACK格位新增冗余View，或在Distinctness Gate之前执行合并资格判断。
隐藏ID后无法从SCSTATE、Storyboard或Video Prompt判断原文确切时刻、主叙事对象、当前动作、前因与下一刻禁入事件。
同一CVS横跨远距离、不同高度、Barrier或不相容动作轴，却未建立Zone-Coherent SLC，或为了同框移动人物、缩短距离、融合地点。
同一CVS派生的SLC具有不同Story Time、Object Count、Instance Register或Spatial Revision。
SCSTATE承担两个无法由同一中性Camera清楚观察的剧情焦点，或与Source CVS/原文因果不符。
错误SCSTATE没有建立新Revision/SLC，却在Storyboard阶段被静默修正。
任一Storyboard Sheet超过3个KF、使用九宫格或通过缩小人物使关键动作/交互不可检查。
Storyboard缺少完整SEG剧情摘要，或KF缺少自然语言剧情句、Speaker/Dialogue、Source Slice、Action Phase、Position Delta或Forbidden Future State。
Video没有重新写完整SEG剧情摘要与逐秒因果，只依赖Storyboard标签让模型猜剧情。
Storyboard参考未通过Revision、SEG、Thread、时间、状态、位置、Prop、Boundary和顺序Admission，或为填满上限上传冗余图。
Video补充原子Reference没有书面证明缺口、Storyboard不足原因、独有Authority Contribution与Does Not Control。
SCSTATE或KF未经过Image Materialization Gate就被默认出图，或图片复杂度超过预算仍进入下游。
减少图片后同步删减Story Truth、CVS、位置、Count、Holder、Temporal Gate、完整逐秒因果或声音合同。
以HIGH视频可靠度为由省略Storyboard、只给Start或降低关键时间推进覆盖。
任一生成视频截图、尾帧或Frame Grab进入了下一SEG或图片生成Reference Manifest。
相邻SEG没有预编译BNDPLAN，或BNDANCHOR来自视频输出而不是上游Canon。
动作、对白、状态激活、Prop交接或原生Transition跨SEG未完成，仍试图依赖帧续接。
减图后Identity、LOOK/CT、Spatial/Geometry、Position/Blocking、State/Temporal、Prop/Count/Holder任一维没有Authority。
没有Authorized Movement Event，人物或关键Prop却跨Zone、离开Support、改变Anchor或Orientation。
Video Prompt没有逐时间窗口的Beat目的、微表演、动作Phase、物理反应、Camera Grammar、声画同步与Exit Condition。
