# Part D 实施计划：题库知识库系统

> 跨会话交接文档，供新开发会话直接使用。写作时间：2026-08-27。
> **状态更新（2026-08-27）：Part D 已实现并通过 E2E（17/17）与后端单测（54/54）**。
> 实际入库：145 话题（PDF 59+77 + 种子保留 9）/ 747 题 / 707 篇范文 /
> 947 条高分表达 / 50 条串联关系；解析与导入脚本用法、实测结构规则与
> 踩坑记录见附一及 README「Part D 题库知识库」。
> 前置状态：Part A/B 完成并真机验收；Part C 计划在 `docs/part-c-plan.md`（可能正在另一会话并行开发，见第八节协调规则）。

## 一、现状盘点（新会话必读）

### 已就绪的基础
- **数据库**：`topics`（name_en/name_zh/category/tag + uq_name_en）、`questions`（topic_id/part/content_en/cue_card JSONB/followup_seeds JSONB/sort）已建（alembic 0002）；种子数据 13 话题/62 题（`app/seed/topics_seed.json` + `python -m app.seed.load`，按 name_en 幂等）
- **题库 UI 基础版已存在**：`TopicsView.vue`（Part 1/2/3 tabs、标签徽章 必考/保留/新题、话题卡片、开始练习）——本 Part 做完整版（搜索/筛选/分页）
- **练习链路已消费题库**：Part 1 取 topic 下 part=1 题目前 4 道；Part 2 取 cue_card；Part 3 用 followup_seeds 作 LLM 出题种子（见 `services/practice_engine/engine.py`）
- **PDF 素材在本地**（已 gitignore，不入库）：`D:\Code\雅思口语教练\2026年5-8月雅思口语素材P123\` 三份：
  | 文件 | 页数 | 结构（PRD 描述） |
  |------|------|------------------|
  | p1.pdf | 73 | Part 1：40+ 话题，每话题 6-8 问 + 英文范文 |
  | p2和p3.pdf | 206 | Part 2&3：50+ 话题（人物/事件/事物/地点），Cue Card + 中文概要 + 英文范文 + P3 追问 |
  | p2串联版.pdf | 27 | 10+ 串联组：一份范文适配多个 Cue Card |
- **LLM 可用**：方舟已连通（`doubao-seed-2-1-turbo-260628`），BYOK Key 在本地 PG（解密方式参考 `scripts/ark_diagnose.py` 的做法，勿打印 Key）
- **环境**：Docker/PG/Redis 就绪；Windows 下中文路径在 shell 传参有 GBK 坑（Python 内处理无碍）；PyMuPDF 需新装（`pip install pymupdf`，国内可加清华源）

### 注意
- 当前本地后端可能由用户手动启动且带 `VOLC_MOCK=1`（健康检查显示 volc_mock:on）——解析题库不依赖语音，无碍；真机验练习时提醒用户用真实模式启动
- 我的开发 shell 推 GitHub 常被 reset；push 失败请用户在其终端执行

## 二、目标与验收（PRD）

解析三份 PDF 为结构化数据入库（**覆盖全部话题**），构建话题练习库完整版 + 参考语料库：话题浏览（搜索/分类/标签/分页）、范文查看、高分表达库、个人词汇本（基础版）、Part 2 串联提示。

## 三、关键架构决策

1. **解析管线四段式**（`scripts/` 下独立脚本，与 Web 服务解耦）：
   - **抽取**：PyMuPDF 按页提取文本 → 合并、清洗（去页眉页脚/页码）
   - **分段**：规则定位话题边界（标题模式：中文名+英文名/编号；先人工看 10 页样本定规则）
   - **结构化**：规则优先（问题列表、"You should say" Cue Card、范文标记），**LLM 兜底**——不规则段落分块送 turbo 模型按 JSON Schema 提取（话题名/问题/范文/中文概要），温度 0
   - **落盘中间 JSON**（`scripts/parsed/{p1,p2p3,linked}.json`）→ **用户人工抽查** → 导入脚本写库
   解析一次、导入可重复（JSON 是唯一事实源，改解析重跑即可）
2. **幂等导入与种子合并**：按 name_en upsert——PDF 数据替换种子话题的题目与字段；种子独有话题保留；`tag`（new/retained/must）从 PDF 的颜色/标记解析（P1 PDF 用蓝/黑/红区分，若文本层无颜色信息则用 LLM 根据标记字样判断，无标记默认 retained）
3. **LLM 解析的 Key**：读 .env 平台 Key 或复用库内 BYOK Key（`resolver.py` 模式）；PDF 内容只含雅思学习材料，外发 LLM 无合规风险
4. **范文按"话题+Part"挂载**：P1 范文挂在 question 级（每题答案）或话题级（解析时按实际结构定，p1.pdf 需抽查）；P2 范文挂 topic 级
5. **表达库自动生成**：对每篇范文跑一次 LLM 提取 5-8 个高分表达（英文+中文释义+原句例句），随导入一并入库
6. **错题本依赖 Part C**（错误数据来自逐句分析）——本 Part 只建表和空页面占位，C 完成后接数据（已写入 C 计划集成点）

## 四、数据模型（Alembic 迁移，编号见第八节）

- `sample_answers`：id、topic_id、question_id（可空，P2 话题级范文化为 null）、part、text_en（范文）、summary_zh（中文概要）、source（p1/p2p3/linked）、created_at
- `topic_links`：id、group_name（串联组名）、shared_answer_id（→sample_answers）、topic_id、note（适配说明）
- `expressions`：id、topic_id、text_en、meaning_zh、example_en、created_at；索引 topic_id
- `user_vocab_words`：id、user_id、word、context_en（来源句）、source_topic_id、is_favorite、created_at；uq(user_id, word)
- `mistake_notes`（占位空表，Part C 接数据）：id、user_id、turn_id、issue_type、severity、original、suggestion、created_at

## 五、后端工作项

1. **M1 PDF 解析 spike**：PyMuPDF 提取三份 PDF 前 10 页文本，人工（你+用户）确认结构与分段规则；输出规则备忘到本文件附录
2. **M2 解析脚本**：`scripts/parse_pdf.py`（抽取+分段+结构化+LLM 兜底）产出三个中间 JSON + **校验报告**（每份 PDF 话题数/题目数/缺字段清单，对照 PRD 数量：40+/50+/10+）
3. **M3 导入与模型**：迁移建表；`scripts/import_topics.py`（幂等 upsert + 种子合并 + 表达库生成）；导入后 `GET /topics` 抽查
4. **M4 API 增强**：`GET /topics` 支持 search/category/part/分页；`GET /topics/{id}` 返回题目+范文+表达+串联关系；`GET /expressions?topic_id=`；词汇本 CRUD（`POST/GET/DELETE /vocab-words`，收藏切换）
5. 题库管理：暂不做后台管理 UI（新考季=重跑脚本换 PDF）

## 六、前端工作项

1. **TopicsView 完整版**（按 `docs/design/pages/topics.html`）：搜索框 + 主题下拉（P2 按人物/事件/事物/地点）+ 标签筛选 + 数字分页；卡片显示题目数/标签/上次得分（得分字段 Part C 后有值，先占位 "--"）
2. **话题详情页** `/topics/:id`：题目列表预览（P2 显示 Cue Card）、范文折叠面板（收起/展开 + 跟读按钮=调 TTS 播放范文，复用现有合成通道）、高分表达列表（收藏按钮→词汇本）、串联提示（"此范文可适配 N 个话题"）
3. **词汇本页** `/vocab`：列表 + 来源话题跳转 + 收藏筛选 + 删除
4. **错题本页占位**（空状态"评分模块上线后自动收录"）
5. **集成点（Part C 落地后）**：报告页底部范文组件（C 计划已标注）；P2 练习开始时推荐串联话题（读 topic_links）
6. 路由与侧边栏：话题库保持现入口；词汇本挂侧边栏（设计稿 5 项导航之外新增第 6 项或并入"我的"分组——按现有 MainLayout 结构加一项即可）

## 七、测试与验收

- 解析校验：三份 PDF 话题全覆盖（对照 PRD 数量级）+ 抽查 10 个话题人工核对字段
- 后端单测：导入幂等（跑两遍结果一致）、种子合并、topics 筛选分页、词汇本 CRUD
- Playwright E2E：话题搜索/筛选/翻页 → 详情 → 范文展开 → 表达收藏 → 词汇本可见
- 验收口径（PRD）：题库覆盖三份 PDF 全部话题；用户可浏览话题、查看范文、使用词汇本

## 八、与 Part C 的并行协调（重要）

**强烈建议 C、D 顺序执行**（C 先 D 后，或反之），单人开发并行收益低、冲突成本高。若坚持并行，遵守：

1. **各自开分支**（`part-c` / `part-d`），完成后按 C→D 顺序合并 main，后合并者 rebase
2. **Alembic 迁移编号冲突**：两计划都可能占用 0003——后动工的会话把迁移编号顺延（0004），down_revision 指向当时的 head
3. **易冲突文件**：`router.py`、`README.md`、`tests/conftest.py`、前端 `router/index.ts`、`MainLayout.vue`——改动保持小而聚焦
4. **集成点双向已标注**：C 读 D 的 sample_answers（评分参照）与 mistake_notes；D 的报告页范文组件等 C 的报告页存在——先各自用空数据/占位开发，合并后联调一次

## 九、里程碑顺序

M1 解析 spike（含用户抽查样本）→ M2 解析脚本 + 中间 JSON + 校验报告（用户抽查）→ M3 模型 + 导入 → M4 API → M5 前端话题库完整版 + 详情/范文/表达 → M6 词汇本 + 串联提示 + 占位页 → M7 E2E + 文档 + 提交推送

## 十、风险与预案

| 风险 | 预案 |
|------|------|
| PDF 文本层质量差（扫描图/排版乱） | M1 先验证可抽取性；若为扫描件需换 OCR 方案（pymupdf 自带 OCR 或告知用户换文本版 PDF） |
| 话题边界规则脆弱 | LLM 兜底分段；解析结果全量落中间 JSON 供人工抽查后才入库 |
| P1 题目与范文对应关系歧义 | M1 抽样定结构；歧义时范文挂话题级并标注 |
| 标签颜色信息丢失 | 默认 retained + 导入报告列出无标签话题供人工补 |
| 与 C 并行冲突 | 第八节规则；优先顺序执行 |
| LLM 解析成本/限流 | 全量约 300 页文本 ≈ 数十万 token，turbo 模型成本几元内；失败重试 + 断点续跑（JSON 分片） |

## 十一、用户配合事项

1. M1/M2 各需一次人工抽查（看 10 页结构样本 / 抽查 10 个解析结果，5-10 分钟）
2. 决定 C/D 执行顺序（建议顺序：C→D 或 D→C，勿并行）
3. PDF 文件保持现路径不动（已 gitignore 不会入库）

---

## 附一：M1 解析 spike 结论（2026-08-27 实测，新会话直接使用）

文本层质量良好（非扫描件），规则可靠，无需 OCR。三份 PDF 结构：

### p1.pdf（73 页 → 60 话题）
- 话题边界：**22 号字行**（跨 span 拼接，含中文 span "新题"），模式 `Part 1 [新题]: {name_en}`；正文从 page 6 起
- 标签（must/new/retained）：**page 5 总览页（index 4）span 颜色**——`#e00000`=必考（6 话题）、`#1880e2`=新题（30 span）、黑=保留；总览 span 有碎片（两列云图），用「话题名规范化后为组文本子串」匹配；must 优先于 new
- 题目：`\d+\. ` 开头行，其后英文段落为该题范文直到下一编号/标题
- 清洗：页首页码（9 号 `#868686` 灰字单独数字行）；标题中 `【海外】【疑似淘汰】` 是附加标记
- 范文挂 **question 级**

### p2和p3.pdf（206 页 → 77 话题）
- 话题边界：**>15 号字行**，模式 `&Part 2&3 [新题]: {name_zh}`；正文 page 8 起
- 话题内结构顺序：中文名行 → `Describe ...`（Cue Card 主题句）→ `You should say:` + 要点行 → **中文概要**（CJK 占优行）→ **英文范文**（ASCII 占优行，可含中文括注如 `master level(大师级)`）→ `笔记区：`
- P3 部分：`笔记区：` + `Part 2&3` 标记行之后，`\d+\. ` 编号问题（**可能同行多问**，如 `1. ... ? 2. ...?`）+ 英文答案
- 分类（人物/事件/事物/地点）：**page 6-7 总览**按四个分组标题切分 span 流、拼接文本后子串匹配话题中文名
- name_en：中文话题名需 LLM 批量生成英文名（一次调用）；范文挂 **topic 级**（P2）与 question 级（P3）

### p2串联版.pdf（27 页 → 12 组）
- 组边界：**>15 号字行**，模式 `Part 2串题 [新题]: {名A + 名B + ...}`；标题可跨 2 行（同页相邻大字号合并）；`+` 分隔
- 组内：3 行固定说明（清洗掉）→ 中文概要 → 英文范文 → `笔记区：` 结束
- 话题名是**别名**（如"新法律"→"想颁布的新法律"、"动物故事书"→"包含动物的故事或书"），规则模糊匹配 + LLM 兜底对到 p2p3 话题
- 结构：shared_answer（topic 级 sample_answers，source=linked）+ topic_links 多行

### 实测计数（校验基线）
p1=59 话题（must 4 / new 25 / retained 30；303 题）；p2p3=77 话题（77 Describe / 77 You should say / 77 笔记区，完美对齐；321 P3 问）；linked=13 组（"同学可以结合"出现 13 次印证；53 别名规则+LLM 匹配 50，3 个在题库无对应）。均超 PRD 数量（40+/50+/10+）。

### 解析踩坑记录（2026-08-27 实测，换 PDF 重跑时注意）
1. **保留题标题无冒号**：`Part 1 Hobby`、`&Part 2&3 受欢迎的人`——标题 regex 的冒号必须可选，否则 1/3 话题丢失
2. **P3 问题会跨行**：问题行可能断在句中（下一行才是 `...childhood? Why or why not?`），判定用"行首编号 + 行内含问号"，无编号行拼接到未以 `?` 结尾的上一问；**个别话题编号从 0 起**（高建筑），不要再加"编号从 1 递增"约束
3. **Cue 句与 You should say 粘连**（高建筑话题）：`...you like or dislikeYou should say:` 同行，需按子串切分处理
4. **总览页云图 span 碎片 + 两列乱序**：颜色组匹配只能做"话题名 in 组拼接文本"单向子串，反向（组碎片 in 话题名）会误伤；p1 的红组（必考）实际是 4 个话题 6 个 span
5. **PDF 自身缺陷**：个别话题无 P3 部分（想提升的天赋）、个别问题无答案（发小#1 等 7 处）、高建筑 P3 部分答案行被 PDF 文本框裁剪缺字——均为素材本身问题，校验报告如实列出
6. **种子别名映射**：PDF 与种子话题名不一致（`Home/Accommodation` vs `Home & Accommodation`），导入用 `SEED_ALIAS` 映射后 upsert，保住 practice_sessions.topic_id 外键
7. **Windows 旧后端占端口**：杀掉旧 uvicorn 后其 multiprocessing 子进程可能仍持有 8000 端口 socket（netstat 显示已死 PID），需找到孤儿 python 进程一并杀掉

---

## 附二：新对话开场 Prompt（复制即用）

> 你好，我正在开发 AI 雅思口语教练项目，Part A/B 已完成，现在开始 Part D（题库知识库系统）。
>
> 【重要】请先完整阅读仓库中的 `docs/part-d-plan.md`（上一阶段交接文档，含现状盘点、解析管线设计、与 Part C 的并行协调规则），以及 `docs/part-c-plan.md` 第八节了解另一条并行线的集成点。然后按计划开始开发。
>
> 背景：Vue3+TS+Element Plus / FastAPI+PG+Redis / 火山引擎；GitHub 仓库 Arreb-01/IELTS-speaking-coach；本地目录 d:\Code\雅思口语教练（Windows+Git Bash）。三份 PDF 素材在 `2026年5-8月雅思口语素材P123\` 目录。
>
> 注意：① 开工前 `git status` 检查未推送提交（push 失败是我的代理问题，提醒我）；② 我用中文沟通，独立开发者，后端小白——需要我做的操作和涉及的概念请用简单语言解释"是什么、为什么、怎么做"；③ 解析 PDF 需要 PyMuPDF，安装请用国内镜像源。
>
> 验收：题库覆盖三份 PDF 全部话题；可浏览话题、查看范文、使用词汇本。完成的代码提交并推送 GitHub。
