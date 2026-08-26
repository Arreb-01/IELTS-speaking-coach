# Part C 实施计划：评分与反馈系统

> 本文档为跨会话交接文档，供新开发会话直接使用。写作时间：2026-08-27。
> **状态更新（2026-08-27）：Part C 已实现并通过 E2E（18/18）**，架构有两处与本文
> 计划不同的重要演进，详见 README「Part C 评分流水线」：
> ① LLM 评分拆为两阶段（10s 内快速出分 + 深度分析异步补齐）——根因是 seed-2.1
> 默认深度思考，思考 token 不受 max_tokens 限制，单次调用 >30s；
> ② 口语评测协议已实证到 `POST /api/v1/mdd`（app 鉴权 + request.reqid/sequence
> + ref_text），服务开通前走 Mock，开通后校准 VOLC_EVALUATION_CLUSTER 一处即可。
> 前置状态：Part A（用户系统/API Key 管理）与 Part B（语音对话引擎）已完成并通过真机验收。

## 一、现状盘点（新会话必读）

### 已就绪的基础设施
- **数据**：`practice_sessions` / `practice_turns` 表已有真实练习数据——每轮含 `question_text`、`user_transcript`、`speech_events`（前端 VAD 事件：speech_start/speech_end/silence/noisy + 相对毫秒）、`audio_path`（16kHz/16bit/单声道 WAV，存 `backend/storage/audio/`）
- **前端**：ECharts + vue-echarts 已安装未使用；报告页设计稿在 `docs/design/pages/report.html`（Hero Band 卡 + 雷达图 + 薄弱项分析 + 逐句分析表 + 中文建议 + 高分表达替换）
- **后端模式**：BYOK 解析器（`services/volcengine/resolver.py` + `speech.py`）、LLM 调用含 JSON 抽取（`services/examiner/examiner.py` 的 `_ask_llm`）、Mock 适配器模式（`VOLC_MOCK=1`）、API Keys 页四卡片（evaluation 卡的测试连接目前返回"待集成"）
- **跑通的真机凭据**（存在本地 PG 的 user_api_keys 表，用户已配置）：
  - LLM：方舟 `doubao-seed-2-1-turbo-260628`（日常）/ `doubao-seed-2-1-pro-260628`（高质量）
  - ASR：语音识别 1.0（`volc.bigasr.sauc.duration`，2.0 未开通）
  - TTS：语音合成 2.0 Seed-TTS（`volc.seedtts.default`，v3 unidirectional 接口，PCM 输出）

### 火山引擎 API 真机校准结论（血泪经验，勿重复踩坑）
- 方舟模型：`doubao-1.5-pro-32k-250115` 已退役（Retiring），调通的可选模型见 `scripts/ark_diagnose.py` 输出
- TTS：v3 `POST https://openspeech.bytedance.com/api/v3/tts/unidirectional`，头 `X-Api-App-Key/X-Api-Access-Key/X-Api-Resource-Id`，响应是 **NDJSON 流**（每行 `{code, data(base64)}`，code 0=音频块、20000000=结束）；音色 `en_female_zendaya_p1_uranus_bigtts` / `en_male_michael_kevin_uranus_bigtts`（账号内全是美音）
- ASR：SAUC v3 WS（`wss://.../api/v3/sauc/bigmodel`），websockets≥14 用 `additional_headers`
- 语音控制台凭据形态：APPID + Access Token（存 user_api_keys.config.appid + key 主字段）
- **口语评测（service_type 81）尚未开通、尚未验证**——这是 Part C 的 M1 spike 任务

### 环境要点
- Windows + Git Bash；中文路径会坑 Docker Compose 项目名（已用 `name: ielts-coach` 显式声明）和 alembic.ini（已改纯 ASCII）
- Docker Desktop 已可用；PG/Redis 容器健康；npm 已切 npmmirror
- 后端 venv：`backend/.venv`（Python 3.14）；启动：`backend` 下 `.venv/Scripts/python -m uvicorn app.main:app --port 8000`；前端 `npm run dev`（5173，/api 已代理含 ws）
- Playwright + Chromium 已装（`C:\Users\10285\.zcode\skills\webapp-testing\`，含 Part A/B 的冒烟脚本可参考）
- **Git：我的开发 shell 直连 github.com 常被重置，提交后如 push 失败请用户在其终端执行 `git push`，或重试**

## 二、Part C 目标与验收（来自 PRD）

练习/会话结束后 **10 秒内**生成评分报告：四维评分（流利度/词汇/语法/发音，各 0-9 精确 0.5）+ 综合 Band + 逐句分析（问题类型/严重度）+ 中文深度反馈 + 高分表达替换 + 录音回放；评分历史与趋势折线图。

降级：LLM 超 15 秒 → 规则引擎先出四维基础分，深度反馈异步补齐后推送。低置信度标注：回答过短（<30 词）、音频质量差、四维极差>2。

## 三、关键架构决策

1. **评分流水线（异步任务）**：练习 `finished` 时自动触发（也支持手动重评）。流程：
   - 并行 A：**流利度规则引擎**（纯 Python，零成本）——从 transcript + speech_events 计算：语速（词/分）、长停顿次数/占比（>2s）、填充词频（um/uh/like/you know）、有效发言时长
   - 并行 B：**发音评测**（火山口语评测，每轮一次：音频 WAV + 参考文本=该轮 transcript）→ 发音分 + 词/音素级详情（粒度以 spike 实测为准）
   - 并行 C：**LLM 四维评分**（turbo 模型，JSON 输出）——注入：题目、转写、流利度统计、（可选）发音评测摘要；产出四维 band + 证据 + 逐句问题标注
   - 串行 D：**LLM 中文深度反馈**（pro 模型）——综合以上全部数据，产出中文总评/ strengths / improvements / 高分表达替换
   - 融合：综合 Band = 四维加权（发音以评测分为主、LLM 为辅），规则见下；低置信度标注
2. **评分 Prompt 对齐雅思官方标准**：system prompt 内嵌官方 band descriptors 摘要（流利与连贯/词汇资源/语法范围与准确性/发音四个维度 5-9 分描述），要求输出严格 JSON Schema；temperature 0.2
3. **口语评测 spike 先行（M1）**：真实凭据直连验证（接口形态预计为 HTTP/WS 携带 ref_text + 音频，`service_type 81`）；协议细节全部隔离在 `services/volcengine/evaluation.py`；mock 适配器同步提供
4. **BYOK**：评测凭据沿用 config JSONB（appid + access_token）；平台默认走 .env；API 设置页 evaluation 卡实现真实测试连接
5. **报告数据全部持久化**（重评分不重算 LLM 结果可复用），趋势图从历史 report 聚合

## 四、数据模型（Alembic 迁移 0003）

- `score_reports`：id、session_id(unique)、user_id、status(pending/processing/completed/failed)、overall_band、fluency/lexical/grammar/pronunciation（Numeric(2,1)）、fluency_metrics JSONB（wpm/pauses/fillers 原始统计）、overall_comment_zh Text、strengths JSONB（中文列表）、improvements JSONB、low_confidence JSONB、model_versions JSONB（用了哪些模型，便于回归）、error、created_at/completed_at
- `turn_analyses`：id、report_id、turn_id、seq、sentences JSONB（[{text, issues:[{type(grammar|vocab|fluency|pronunciation), severity(minor|moderate|major), explanation_zh, suggestion}]}]）、pronunciation_detail JSONB（评测原始返回，含词级分数/音素，若支持）、filler_hits JSONB
- 趋势不建新表：按 user 聚合 score_reports 即可

## 五、后端工作项

1. **M1 口语评测 spike + 客户端**（用户前置：语音控制台开通「口语评测（英文）」服务，用同一应用 8535993573）
   - `services/volcengine/evaluation.py`：单轮评测（WAV + ref_text → 分数/详情）、`test_evaluation_connection`
   - mock 适配器（固定 6.0 分 + 假词级数据）
   - API 设置页 evaluation 卡接真实测试连接
2. **M2 评分服务** `services/scoring/`：
   - `fluency.py` 规则引擎；`prompts.py`（四维评分 schema + 中文反馈 schema）；`engine.py`（编排 + 融合 + 降级）；`llm_scorer.py`
   - 单测：流利度统计、LLM 输出解析容错、融合规则、降级路径（mock LLM 超时）
3. **M3 REST + 自动触发**：
   - 引擎 `finished` 时创建 pending 报告并起 asyncio 任务（注册表模式已在 registry.py，勿重复）
   - `POST /api/v1/practices/{id}/rescore`、`GET /api/v1/practices/{id}/report`（前端轮询 status）、`GET /api/v1/reports?limit=`（历史列表）、`GET /api/v1/reports/trend`（按日期的 band/四维序列）
4. 前端 `finished` 消息附带 `report_available: true` 提示前端跳报告页加载态

## 六、前端工作项

1. **ReportView**（按 `docs/design/pages/report.html`）：
   - Hero：综合 Band 圆环大数字 + 总结语 + 四维小分格
   - ECharts 雷达图（四维 max 9）+ 薄弱项分析卡（error/warning/success 三色）
   - 逐句分析表：时间/句子（错误文本红色删除线）/问题类型徽章/严重度；行内音频回放入口（已有 TurnAudioPlayer）
   - 中文改进建议（编号列表）+ 高分表达替换（红删→绿替三行对比）
   - 加载态：进度条 + 文案（"正在分析您的发音…/正在生成反馈…"），≤10s
   - 顶部"再练一次"（回练习页）
2. **ReportsView 升级**（现在是占位）：报告列表（时间/话题/Part/Band/查看）+ ECharts 提分趋势折线（综合 + 四维切换）
3. PracticeView finished → 自动进入报告加载（替换现在的轻量总结；轻量总结保留为报告失败时的兜底）
4. 路由：`/reports`、`/reports/:sessionId`

## 七、测试与验收

- 后端单测：流利度统计（构造 speech_events 用例）、评分 JSON 解析容错（缺字段/超界钳制）、融合与低置信度规则、降级路径、rescore 幂等
- Playwright E2E（VOLC_MOCK=1）：练完 P1 → 报告页 10s 内出全要素断言（雷达 canvas 存在、四维分值合理区间、逐句非空、建议非空、回放按钮存在）；报告列表与趋势页渲染
- 真机验收（需用户配合）：真实练一次 → 报告 ≤10s、发音分来自真实评测、中文反馈质量人工评审

## 八、里程碑顺序

M1 评测 spike（含用户开通服务）→ M2 数据模型 0003 + 评分服务 → M3 API + 自动触发 → M4 前端报告页 + 列表/趋势 → M5 E2E + 真机验收 + README/文档 + 提交推送

## 九、风险与预案

| 风险 | 预案 |
|------|------|
| 口语评测接口形态与假设不符 | M1 spike 先行；协议隔离在 evaluation.py；mock 保全流程；用户控制台截图核对资源 ID（沿用 TTS 的排障方法论） |
| 评测无词级/音素级数据 | 发音维度以总分 + LLM 文本侧观察为主，逐句发音标注降级为整轮级别 |
| LLM 评分漂移/不稳 | 低 temperature + band descriptors 注入 + 输出钳制到 [3,9] 步长 0.5；model_versions 落库便于回归 |
| 10s 时限不达标 | 评测与 LLM 并行 + turbo 模型打分；深度反馈超时异步补（PRD 降级条款） |
| 用户练习数据是中文/空转写 | 空轮跳过评分；报告标注"有效作答轮次不足" |

## 十、需要用户配合的事项（提前告知）

1. 语音控制台开通「口语评测（英文）」服务（绑定现有应用 8535993573），M1 真机验证需要
2. 真机验收时完整练一次并提供对报告质量的主观反馈（评分是否合理、反馈是否有用）
