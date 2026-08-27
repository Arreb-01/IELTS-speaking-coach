# Part E 实施计划：学习路径与 Dashboard

> 跨会话交接文档，供新开发会话直接使用。写作时间：2026-08-27。
> 前置状态：Part A/B/C/D 全部完成并通过验收（含腾讯云口语评测真实评分上线，提交 cc4597a）。
> 依赖关系已满足：Part C 提供 score_reports 四维评分历史；Part D 提供题库（145 话题）供推荐。

## 一、现状盘点（新会话必读）

### 数据侧已有（本 Part 直接消费，勿重复建设）
- **users 表**：`target_band` 字段已预留（Numeric(2,1)，schema 校验 4.0-9.0），顶栏已显示"目标 Band X"/"未设置目标分数"；**没有任何机制写入它**（注册流程不含），需测评流程内补齐
- **score_reports**：status(pending/processing/completed/failed)、四维 Numeric(2,1)、overall_band、low_confidence JSONB——统计源表
- **practice_sessions**：mode("practice"/"mock", native_enum=False 的字符串，新增枚举值无需迁移)、part、topic_id、status(completed/abandoned)、started_at/ended_at——打卡/次数/时长统计源
- **topics**（Part D）：145 话题含 tag(must/new/retained)、category（人物/事件/事物/地点）；`GET /api/v1/topics` 支持 search/category/tag/分页
- **已有 API**：`GET /reports/trend`（按时间升序四维+综合序列，limit 上限 200）、`GET /reports`（列表）、`GET /practices`（会话列表）
- **Alembic head = 0004_knowledge_base**，本 Part 迁移占用 **0005**

### 前端侧已有
- **DashboardView.vue 是纯静态占位**（4 个 stat 卡 + welcome 卡，数值全是 "--"）——本 Part 全量重写
- **设计稿 `docs/design/pages/dashboard.html`** 已明确版块：学习概览 Hero（目标 Band / 预测 Band·较上周±X / 今日已完成 N 次练习 / 单次练习平均）→ 四维能力雷达 → 提分趋势 → 今日推荐（3 张卡：Part 1 话题 / Part 2 话题 / 发音专项）→ 最近练习记录
- ECharts Radar/Line 已按需注册（`frontend/src/plugins/echarts.ts`，Part C 建）；ReportView/ReportsView 有现成图表用法可抄
- MainLayout navItems 现为 7 项，路由守卫/布局成熟；PracticeView 支持 `query.topic/part` 直入话题练习
- Part B 练习引擎关键事实：**题目由 API 层选好后以 questions 注入会话**（ws 协议不关心来源）；mode 仅用于 strict 开关（mock 禁暂停/重来）——测评可完全复用引擎

### 环境要点
- 本地后端可能正由我方后台运行（uvicorn --reload --reload-dir app，端口 8000）；前端 dev server 5173
- Playwright 冒烟脚本模式见 `C:\Users\10285\.zcode\skills\webapp-testing\smoke_part_c.py`（伪麦克风 + VOLC_MOCK=1 后端环境变量启动），Part E E2E 沿用
- 我的 shell 推 GitHub 偶发被 reset；push 失败提醒用户在其终端执行

## 二、目标与验收（来自 PRD）

**工作项五大块**：初始能力测评（新用户 5 题 Part 1 简短问答 + 设置目标分数 → 生成初始路径）；学习路径引擎（评分趋势 + 话题覆盖度 + 目标差距 → 每日 2-3 项任务，难度自适应，跳过重排）；Dashboard 首页（雷达图/提分趋势/今日推荐/最近练习/连续打卡/预测 Band）；学习日历（本周视图 + 任务状态 + 目标 vs 当前 + 预计达成时间）；薄弱项分析（四维趋势 + 按弱项筛选推荐话题）。

**验收标准（PRD 原文）**：新用户完成测评后获得推荐路径；Dashboard 正确展示练习数据和趋势。

**关联 PRD 规则**（实现必须遵守）：新用户未测评时 Dashboard 只显示测评引导卡，不出雷达和推荐；连续打卡=当日任意一次完整练习；预测 Band=最近 5 次综合评分加权、不足 5 次标注"数据不足"；每日任务 2-3 项、建议总时长 15-30 分钟；难度自适应：连续 3 次某维 ≥7.0 降低该维频率、≤5.5 增加专项；跳过的任务不计完成并重新安排；每日任务完成率目标 ≥60%。

## 三、关键架构决策

1. **初始测评 = 复用现有练习引擎的一次特殊练习**，不另起炉灶：
   - `POST /api/v1/placement/start` 创建 part=1、topic_id=None 的 practice 会话，题目从题库固定选取（`app/services/scoring/placement_pool.py` 维护一份按 category × must 标签手工挑定的 5 道 P1 题清单，落库其 question_id，覆盖面稳定且可控）
   - 前端 `practice?placement=1` 进入现有 PracticeView；仅两处轻特判：① 顶部徽标显示"能力测评"替代进度标签；② 5 题答完 finish 后照常自动跳报告页，报告上方追加"设定你的目标分数"对话框（users.target_band 为空才弹出）→ 保存后跳 Dashboard 领取路径
   - 测评会话的评分管线零改动：run_scoring 照常产出初始四维报告 = 能力基线
   - `users` 加 `placement_at DateTime NULL` 标记已完成测评（判 needs_placement），不加新表
2. **学习路径用确定性规则引擎，LLM 只出一段中文建议语**（可选 turbo 单调用、3 秒内失败静默跳过）：
   - 弱项判定：近 5 次 completed 报告的四维各自取均值，最低者为一号弱项（展示全部排序）；无报告时不判定，走"新手任务"
   - 推荐话题：一号弱项对应维度过滤题库——lexical/grammar 任一维度弱 → tag=new/must 未练过话题优先；pronunciation 弱 → 推荐跟读任务（TopicDetail 的范文 TTS 跟读，Part D 已有能力）；fluency 弱 → 推荐一个 Part 2 话题练独白
   - 已练话题排除：`SELECT DISTINCT topic_id FROM practice_sessions WHERE user_id=` 且 completed
   - 自适应即规则的输入随窗口滑动自然生效（每次重新生成都看近 5 次）；"连续 3 次 ≥7.0 降频"显式实现：检查最近 3 次同维是否 ≥7.0，是则该维任务间隔排（放到明后天任务里），否则密集排
3. **任务持久化 + 双时机再生成**：
   - `daily_tasks` 表存任务（见第四节）；生成幂等策略：同日重跑删除 pending 保留 done/skipped
   - 时机 A：每次报告 completed 后 `asyncio.create_task` 重排未来任务（挂进 Part C 管线末端，勿改 _run_pipeline 内部——在 engine.run_scoring 最终 commit 后追加）
   - 时机 B：`GET /plan/week` 惰性生成（当日/其后无任务时现场生成）
4. **Dashboard 一站式聚合端点** `GET /api/v1/dashboard/overview`：一次请求返回 hero 统计 + 雷达 + 推荐 + 最近记录，避免前端拼 4 个接口;详细趋势仍复用 `/reports/trend`
5. **统计口径统一定义**（放 `services/progress/stats.py`，全部纯函数 + 单测）：
   - streak：今日起往回数连续"daily complete"天数；daily complete=当日（Asia/Shanghai）存在任一 completed 会话；今天还没练不打断 streak（昨天断了才断）
   - predicted_band：近 5 次 overall_band 权重 [5,4,3,2,1]/15 加权；<5 次 → null + hint"数据不足"；0 次 → 引导态
   - 较上周变化：本周最后报告 vs 上周最后报告 overall_band 差值（不足两周则隐藏该项）
   - 单次练习平均：近 7 天会话平均分钟数 `(ended_at-started_at)`
   - 目标差距/预计达成：target - predicted；预计达成时间=差距 ÷ 近 28 天每周均提升（<0.05 每周时显示"保持当前频率稳步提升"，不做拍脑袋承诺）

## 四、数据模型（Alembic 迁移 0005）

- `users` 追加：`placement_at DateTime(timezone=True) NULL`
- **`daily_tasks`**（新表）：
  - id Uuid PK、user_id FK(users, CASCADE, idx)
  - plan_date Date（任务所属日，本地时区日期）
  - task_type Enum("topic","special","corpus", name="daily_task_type", native_enum=False)
  - dimension String(20) NULL（fluency/lexical/grammar/pronunciation，针对哪个弱项）
  - topic_id FK(topics, SET NULL) NULL、part SmallInteger NULL
  - title_zh String(100)、desc_zh String(200)（生成时就地固化文案，前端免拼）
  - payload JSONB NULL（如 {"followup": "跟读范文"} 扩展位）
  - status Enum("pending","done","skipped", native_enum=False) default pending
  - sort SmallInteger、created_at、completed_at DateTime NULL
  - 索引 (user_id, plan_date)
- 不建表：能力快照（报告即快照）、streak/覆盖度（现算现查，量级小）

## 五、后端工作项

1. **M1 统计与聚合**：`services/progress/stats.py`（第五节口径纯函数）+ `services/progress/recommender.py`（弱项/话题推荐/任务生成，规则版）；`api/v1/dashboard.py`（`GET /overview`、`GET /weakness`——后者返回四维近 5 序列 + 一号弱项 + 该维推荐话题 6 个）
2. **M2 测评链路**：迁移 0005 + User 加字段；`api/v1/placement.py`（start/checkpoint 两端点）；`services/scoring/placement_pool.py` 从题库挑 5 题的固定逻辑（按 name_en 白名单查库，缺题自动用同类 must 话题补——导入了 145 话题不会缺）；practices 创建处兼容 topic_id=None + placement 题集；`PATCH /api/v1/users/me` 放开 target_band 更新（Part A 可能已有 nickname 更新端点，扩展即可）
3. **M3 路径引擎 API**：`api/v1/plan.py`（`GET /plan/week?date=`、`POST /plan/tasks/{id}/complete`、`POST /plan/tasks/{id}/skip`）；生成器在报告完成后挂钩 + 惰性生成；「跳过重排」= 把被跳任务的 topic/dimension 并入下一未被跳过任务的 desc 或顺延插入次日（从简：立即生成一条同型替补任务占剩余名额）
4. 注册路由（api_v1 总路由）+ tests/conftest 兼容

## 六、前端工作项

1. **DashboardView 全量重写**（严格对齐设计稿版块与 ielts token）：
   - needs_placement（overview 返回）→ 置顶大引导卡（"约 3 分钟 · 5 道题 · 定制专属练习计划"按钮 → placement/start → 跳练习页），隐藏其余板块
   - 无练习记录（已测评）→ 空状态插画 + "开始第一次练习"
   - 正常态：Hero 行（目标 Band 可点击弹窗修改 el-dialog + 预测卡"较上周 ±X" + 今日 N/X 进度环 + 单次平均分钟）｜左列：雷达卡（ECharts Radar max9，点击维度角标跳 `/topics?weak=<dim>`）+ 趋势折线卡 ｜右列：今日推荐 3 卡（title/desc/时长，点击 → practice?topic=&part=）+ 最近练习记录 5 条（点击 → report/:sessionId）
2. **PlanView** `/plan`（MainLayout navItems 在"话题练习"前插 `{ name:'plan', label:'学习路径', icon: CalendarCheck }`）：
   - 顶栏：当前 Band · 目标 Band · 预计达成时间
   - 本周日历条（7 格，日期高亮今天，完成 X/Y 徽标）→ 点选切换查看当日任务
   - 任务卡：类型图标/中文标题/描述/"开始"（话题类直跳练习）/完成打勾/跳过；done 置灰划线
   - 底部固定"本周完成率 ≥60%"进度提示
3. **PracticeView 测评特判**：query.placement=1 时进度区显示"能力测评 x/5"徽标、总结页文案改为"测评完成"
4. **ReportView 增设目标分弹窗**：`/me` 返回 target_band 为空 && 本次为 placement 会话 → 提交后跳 dashboard
5. TopicsView 增加 `?weak=` 入口兼容（URL 有 weak 参数时 tab 高亮并在标题处显示"针对〈维度〉推荐"筛选说明——实现从简：仅传参展示，不新增后端行为）
6. api 层：`api/dashboard.ts`、`api/plan.ts` 类型与请求封装

## 七、测试与验收

- **单测（stats 与 recommender 全纯函数）**：streak（今天没练不断签/昨断清零）、predicted_band 加权与<5 次空值、弱项均值排序、任务生成幂等（同日二次调用 pending 替换、done 保留）、降频规则（3×≥7.0 后该维落到隔日）、skip 后替补生成、时区边界（UTC 23:30 北京 07:30 归属本地日期）
- **E2E（Playwright，VOLC_MOCK=1）**：①新注册账号 → Dashboard 出测评引导 → 完成 5 题（伪麦克风）→ 报告出分 → 设目标 6.5 → Dashboard 出现雷达+3 推荐卡；②/dashboard→/plan 存在今日任务 → 点"开始"回练习页 → 完成一次短练习 → plan 页任务可打勾、streak≥1
- 回归：既有 59 后端测试全绿；ReportsView/ReportView 不受路由改动影响
- **真机验收（用户）**：全新邮箱注册走完整新用户旅程；老账号登录确认 Dashboard 数据与真实练习一致；对推荐合理性主观反馈

## 八、里程碑顺序

M1 统计聚合服务 + overview API → M2 迁移 0005 + 测评链路 → M3 路径引擎 + plan API → M4 Dashboard 前端 → M5 PlanView + 测评特判 + 导航 → M6 单测/E2E/README/提交推送

## 九、风险与预案

| 风险 | 预案 |
|------|------|
| 测评改动侵入练习主链路引入回归 | 严格限定：题目注入发生在 API 层，ws 协议零改动；前端特判只读 query 参数；E2E 回归 Part B 场景 |
| 小样本下规则不稳定（首周推荐抖动） | <5 次报告统一走"固定新手计划"（P1 必考话题×2+表达学习），攒够样本才启用自适应 |
| 时区/日期口径错乱导致打卡误判 | stats.py 内聚单一 `local_date(dt)` 工具；单测覆盖 UTC/北京跨界样例 |
| 推荐话题池枯竭（用户练遍题库） | 池空时回退全题库 tag=retained 且上次练习 >7 天的话题；文案注明"巩固复习" |
| daily_tasks 生成并发竞态（完成回调+懒加载同时触发） | 生成函数加 per-user asyncio.Lock；表层靠幂等策略兜底 |
| 预计达成时间过度承诺 | 阈值兜底文案（第三条第 5 点），永不输出具体日期除非样本 ≥4 周 |

## 十、需要用户配合的事项

1. `scripts/tencent_soe_probe.py` 所需密钥已在 .env（无新增依赖），本 Part **不需要任何新的云服务开通**
2. 真机验收：用一个新邮箱注册走"测评 → 目标分 → Dashboard → 学习路径"完整新客旅程（约 10 分钟），老账号复核数据正确性
3. 默认练习偏好确认：每日任务数默认 3、建议时长 20 分钟——不合意请告知改默认值
4. push 失败时在您的终端执行 `git push`

---

## 附一：新对话开场 Prompt（复制即用）

> 你好，我正在开发 AI 雅思口语教练项目，Part A/B/C/D 已全部完成并通过真机验收（Part C 发音评测已接腾讯云智聆口语评测真实评分），现在开始 Part E（学习路径与 Dashboard）。
>
> 【重要】请先完整阅读仓库中的 `docs/part-e-plan.md`（上一阶段交接文档，含现状盘点、架构决策、统计口径定义与里程碑），再动手开发。
>
> 背景：Vue3+TS+Element Plus+ECharts（Radar/Line 已按需注册）/ FastAPI+PG+Redis；GitHub 仓库 Arreb-01/IELTS-speaking-coach；本地目录 d:\Code\雅思口语教练（Windows+Git Bash+Docker）。
>
> 注意：① 开工前 `git status` 检查未推送提交（push 失败是我的代理问题，提醒我）；② 我用中文沟通，独立开发者，后端小白——需要我做的操作和涉及的概念用大白话讲清"是什么、为什么、怎么做"；③ 本地环境已就绪（Docker PG/Redis、backend/.venv、npm 镜像、Playwright）。
>
> 验收：新用户完成测评后获得推荐路径；Dashboard 正确展示练习数据和趋势。完成的代码提交并推送到 GitHub。
