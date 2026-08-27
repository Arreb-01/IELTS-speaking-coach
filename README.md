# AI 雅思口语教练 (AI IELTS Speaking Coach)

> 面向中国自学雅思考生的网页端 AI 口语教练，用中文深度反馈 + 自适应学习路径 + 可视化提分体系，帮助考生高效突破口语瓶颈。

## 项目简介

国内雅思考生口语平均分仅 5.4 分，是四项中得分最低的。本产品旨在通过 AI 技术为自学考生提供低成本的口语练习与评分服务，核心差异化在于：

1. **中文深度反馈** — 练习后提供中文解析，告诉用户"为什么失分"和"怎么改进"
2. **自适应学习路径** — 根据评分数据自动推荐每日练习计划
3. **进度可视化** — 雷达图 + 趋势图，提分过程看得见

## 技术栈

### 前端
- Vue 3 + TypeScript + Vite
- Element Plus (UI 组件库)
- ECharts (数据可视化)
- Web Audio API + MediaRecorder (浏览器音频采集)

### 后端
- Python + FastAPI
- PostgreSQL (数据库)
- Redis (缓存)
- Nginx (反向代理 + 静态托管)

### AI 服务 (火山引擎全栈)
- **LLM**: doubao-1.5-pro-32k / doubao-seed-2.1-turbo
- **ASR**: 豆包流式语音识别 2.0
- **TTS**: 豆包语音合成 2.0
- **发音评测**: 火山引擎口语评测 (service_type 81)

### BYOK 架构
系统支持用户自带火山引擎 API Key (Bring Your Own Key)，优先使用用户自带的 Key 调用 AI 服务，未配置时回退到平台默认 Key。

## 项目结构

```
IELTS-speaking-coach/
├── README.md               # 项目说明
├── PRD.md                  # 产品需求文档
├── .gitignore
├── docker-compose.yml      # 本地开发：PostgreSQL 16 + Redis 7
├── frontend/               # 前端项目 (Vue 3 + TypeScript + Element Plus)
│   ├── src/
│   │   ├── api/            # axios 封装 + 接口模块（401 静默刷新）
│   │   ├── layouts/        # 主布局（240px 侧边栏 + 64px 顶栏）
│   │   ├── router/         # 路由与登录守卫
│   │   ├── stores/         # Pinia 状态
│   │   ├── styles/         # 设计 token + Element Plus 主题覆盖
│   │   └── views/          # 页面（登录/注册/API Key 管理/Dashboard 等）
│   └── vite.config.ts      # dev 代理 /api → localhost:8000
├── backend/                # 后端项目 (Python FastAPI)
│   ├── app/
│   │   ├── api/v1/         # 路由：auth / users / api-keys
│   │   ├── core/           # 配置、JWT、AES-256-GCM 加密
│   │   ├── db/             # SQLAlchemy 模型与会话
│   │   ├── schemas/        # Pydantic 模型
│   │   └── services/       # Redis 缓存（内存回退）、火山引擎客户端
│   ├── alembic/            # 数据库迁移
│   ├── tests/              # pytest
│   └── Dockerfile
├── deploy/                 # 生产编排：docker-compose.prod.yml + nginx.conf
├── scripts/                # 工具脚本（PDF 题库解析，Part D）
└── docs/
    ├── deployment.md       # 部署指南
    └── design/             # UI 设计稿（HTML mockups + 设计 token）
```

## 开发规划

开发按模块拆分为独立可交付单元：

| 模块 | 内容 | 依赖 |
|------|------|------|
| Part A | 基础设施与用户系统 (含 API Key 管理) | 无 |
| Part B | 语音对话核心引擎 | Part A |
| Part C | 评分与反馈系统 | Part B |
| Part D | 题库知识库系统 | Part A，可与 B/C 并行 |
| Part E | 学习路径与 Dashboard | Part C + D |
| Part F | 模拟考试模式 | Part B + C + D |
| Part G | 测试与上线 | A-F 全部 |

## 快速开始

### 1. 启动本地数据库（需 Docker Desktop）

```bash
docker compose up -d        # PostgreSQL 16 (5432) + Redis 7 (6379)
```

> 没有 Docker 时后端可降级运行：未配置 `REDIS_URL` 时自动使用进程内缓存，
> 也可用 `DATABASE_URL=sqlite+aiosqlite:///./dev.db` 临时跑起来（仅限本地开发）。

### 2. 后端

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt    # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS/Linux

cp .env.example .env       # 本地开发可不填任何值（有开发默认值）

.venv/Scripts/alembic upgrade head               # 建表
.venv/Scripts/uvicorn app.main:app --reload --port 8000
```

运行测试：`.venv/Scripts/python -m pytest`（无需数据库，SQLite + 内存缓存）

### 3. 前端

```bash
cd frontend
npm install
npm run dev                # http://localhost:5173，/api 自动代理到 8000
```

### 4. 验证

浏览器打开 http://localhost:5173 → 注册账号 → 左侧「API 设置」→
填入火山引擎方舟 API Key → 「测试连接」应返回"连接成功"。
接口文档（Swagger）：http://localhost:8000/docs

## 相关文档

- [产品需求文档 (PRD)](./PRD.md)
- [部署指南](./docs/deployment.md)
- [UI 设计稿](./docs/design/)（设计 token 见 `colors_and_type.css`，页面 mockup 见 `pages/`）

## 当前进度

- [x] **Part A** 基础设施与用户系统（注册登录 / API Key 管理 / 部署配置）✅ 2026-08
- [x] **Part B** 语音对话核心引擎（流式 ASR / TTS / LLM 考官 / Part 1/2/3 练习）✅ 2026-08
- [x] **Part C** 评分与反馈系统（两阶段评分流水线 / 四维 Band + 雷达 / 逐句分析 /
  中文深度反馈 / 高分表达替换 / 历史与趋势）✅ 2026-08
- [x] **Part D** 题库知识库系统（三份 PDF 全量解析入库 / 话题库搜索筛选分页 /
  参考范文 + 跟读 / 高分表达库 / 个人词汇本 / Part 2 串联提示）✅ 2026-08
- [ ] Part E 学习路径与 Dashboard
- [ ] Part F 模拟考试模式
- [ ] Part G 测试与上线

> 开发提示：`VOLC_MOCK=1` 启动后端可在没有任何火山凭据的情况下体验完整语音练习流程（Mock 转写/语音/评测）。
> 真实凭据接入验证：`scripts/volc_spike.py`（需语音控制台的 APPID + Access Token）；
> 口语评测协议探测：`scripts/auc_probe*.py`（见 `backend/app/services/volcengine/evaluation.py` 头注）。

### Part C 评分流水线（架构速览）

练习结束后自动触发，`score_reports` / `turn_analyses` 两表持久化（迁移 0003）：

1. **阶段一（10s 内出分）**：流利度规则引擎（纯本地）∥ 火山口语评测（每轮音频 + 参考文本）
   ∥ LLM 快速四维打分（**禁用深度思考**，实测开启时 >30s、关闭后 ~3s）→
   融合（发音 = 真实评测 0.7 + LLM 0.3，综合 = 四维均值取半档）→ 报告置 completed
2. **阶段二（后台补齐，前端轮询渐进呈现）**：LLM 深度分析一次产出逐句问题标注 +
   中文总评/优点/改进建议/高分表达替换
3. **降级**：LLM 打分失败 → 规则引擎出流利度、其余维度保守 5.0 并标注低置信度；
   空轮次（无有效作答）→ 报告 failed 并给出原因
4. **手动重评**：报告页「重新评分」按钮 → `POST /api/v1/practices/{id}/rescore`（幂等）

> 口语评测（service_type 81）真机校准进展：端点 `POST /api/v1/mdd` 请求形态已实证
> （见 evaluation.py 头注），当前账号返回"无可用实例"——待语音控制台开通「口语评测」后，
> 校准 `VOLC_EVALUATION_CLUSTER` 即可切换真实评测（Mock 全流程可用）。

### Part D 题库知识库（架构速览）

数据来源：三份 PDF 素材（2026年5-8月题季，本地 gitignore 不入库）→ 解析为中间 JSON → 幂等导入。
新考季换 PDF 后重跑两条命令即可：`python scripts/parse_pdf.py` → `python scripts/import_topics.py`。

1. **解析管线**（`backend/scripts/parse_pdf.py`，规则优先 + LLM 兜底）：
   - p1（59 话题/303 题）：22 号字标题定边界；标签从总览页颜色（红=必考 4 / 蓝=新题）+ 标题文字；
     每题范文挂 question 级
   - p2&p3（77 话题）：标题 → Cue Card → 中文概要（CJK 行）→ 英文范文（ASCII 行）→「笔记区」后
     P3 问答（编号+问号识别，跨行问题拼接）；分类（人物/事件/事物/地点）从总览页分组匹配；
     范文挂 topic 级；中文名由 LLM 批量译英文名（upsert 键）
   - 串联版（13 组）：一份范文适配 4-5 个话题，别名经规则+LLM 对到 p2p3 话题 → `topic_links`
   - 校验报告：`scripts/parsed/report.md`（话题数/缺字段清单/未匹配别名）
2. **导入**（`backend/scripts/import_topics.py`，幂等）：按 `name_en` upsert，PDF 别名映射到种子名
   保住练习历史；题目/范文删除重建；表达库对每话题一次 LLM 提取 5-8 条（断点续跑）。
   实测入库：145 话题 / 747 题 / 707 篇范文 / 50 条串联
3. **API**：`GET /topics`（search/category/tag/分页）、`GET /topics/{id}`（题目+范文+表达+串联聚合）、
   `GET /topics/expressions`、`POST /topics/speak`（范文跟读 TTS，PCM→WAV）、词汇本 CRUD `/vocab-words`
4. **前端**：话题库完整版（搜索/分类/标签/分页）、话题详情页（Cue Card/范文折叠+跟读/高分表达收藏/
   串联提示）、词汇本页、错题本占位页（Part C 数据接入后启用）

## License

MIT
