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
├── frontend/               # 前端项目 (Vue 3 + TypeScript)
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── vite.config.ts
├── backend/                # 后端项目 (Python FastAPI)
│   ├── app/
│   ├── requirements.txt
│   └── alembic/             # 数据库迁移
├── scripts/                # 工具脚本
│   └── parse_pdf.py         # PDF 题库解析脚本
└── docs/                   # 文档
    └── architecture.md      # 架构设计文档
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

```bash
# 克隆仓库
git clone https://github.com/Arreb-01/IELTS-speaking-coach.git
cd IELTS-speaking-coach

# 前端开发
cd frontend
npm install
npm run dev

# 后端开发
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## 相关文档

- [产品需求文档 (PRD)](./PRD.md)

## License

MIT
