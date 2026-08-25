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
- [ ] Part C 评分与反馈系统
- [ ] Part D 题库知识库系统
- [ ] Part E 学习路径与 Dashboard
- [ ] Part F 模拟考试模式
- [ ] Part G 测试与上线

> 开发提示：`VOLC_MOCK=1` 启动后端可在没有任何火山凭据的情况下体验完整语音练习流程（Mock 转写/语音）。
> 真实凭据接入验证：`scripts/volc_spike.py`（需语音控制台的 APPID + Access Token）。

## License

MIT
