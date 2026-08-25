# 部署指南（火山引擎 ECS + Docker + Nginx）

> Part A 交付的部署配置。实际部署在 ECS 购买、域名备案/解析完成后进行。

## 一、架构

```
浏览器 ──► Nginx (80/443)
             ├── /          → 前端静态文件（Vue 构建产物）
             ├── /api/      → FastAPI (uvicorn, 容器 backend:8000)
             └── /ws/       → WebSocket（Part B 语音流式通道，已预留）
                      ├── PostgreSQL 16（容器 db）
                      └── Redis 7（容器 redis）
```

## 二、服务器要求

| 项 | 建议 |
|----|------|
| ECS 规格 | 2 核 4G 起步（eb.c6ae / ecs.g7ie 等），系统盘 40G+ |
| 操作系统 | Ubuntu 22.04 / Alibaba Cloud Linux（装 Docker 方便即可） |
| 带宽 | 固定带宽 5Mbps 或按流量计费 |
| 安全组 | 放行 80、443；22 仅限管理 IP |
| 域名 | 需 ICP 备案（使用国内云 + 绑定域名时）；HTTPS 证书可用免费 DV 证书 |

## 三、环境变量清单（backend/.env）

从 `backend/.env.example` 复制后填写：

| 变量 | 必填 | 说明 |
|------|------|------|
| `ENV` | ✅ | 生产填 `prod`（强制要求密钥显式配置） |
| `DATABASE_URL` | ✅ | 生产编排中已由 compose 注入，无需手填 |
| `REDIS_URL` | ✅ | 同上，compose 注入 |
| `SECRET_KEY` | ✅ | JWT 签名密钥：`python -c "import secrets; print(secrets.token_hex(32))"` |
| `API_KEY_ENCRYPTION_KEY` | ✅ | API Key 加密主密钥（64 位 hex），生成方式同上。**丢失后已存的用户 Key 将无法解密**，请妥善保管 |
| `VOLC_ARK_DEFAULT_API_KEY` | 建议 | 平台默认豆包 Key（火山方舟控制台获取），用户未配置 BYOK 时回退使用 |
| `VOLC_ARK_TEST_MODEL` | 可选 | 连通性测试模型，默认 doubao-1.5-pro-32k-250115 |

`POSTGRES_PASSWORD` 写在 `deploy/.env`（供 compose 使用）。

## 四、部署步骤

```bash
# 1. 服务器上安装 Docker（Ubuntu 示例）
curl -fsSL https://get.docker.com | bash

# 2. 拉取代码
git clone https://github.com/Arreb-01/IELTS-speaking-coach.git
cd IELTS-speaking-coach

# 3. 准备配置
cp backend/.env.example backend/.env
vi backend/.env          # 填写 SECRET_KEY / API_KEY_ENCRYPTION_KEY / VOLC_ARK_DEFAULT_API_KEY
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" > deploy/.env

# 4. 构建前端产物并放入 nginx 挂载目录
cd frontend && npm ci && npm run build && cd ..
rm -rf deploy/dist && cp -r frontend/dist deploy/dist

# 5. 启动（deploy 目录会读取上级 backend 的 Dockerfile）
cd deploy && docker compose -f docker-compose.prod.yml --env-file .env up -d --build

# 6. 执行数据库迁移（首次部署）
docker exec ielts-backend alembic upgrade head
```

## 五、HTTPS 证书

1. 在火山引擎证书中心申请免费 DV 证书（或 Let's Encrypt）
2. 证书文件放 `deploy/certs/fullchain.pem` 与 `privkey.pem`
3. 打开 `deploy/nginx.conf` 中注释的 443 server 块，并启用 80 → 443 跳转
4. `docker exec ielts-nginx nginx -s reload`

## 六、常用运维命令

```bash
docker compose -f docker-compose.prod.yml logs -f backend   # 看后端日志
docker compose -f docker-compose.prod.yml restart backend   # 重启后端
docker exec ielts-backend alembic upgrade head               # 升级后跑迁移
docker exec ielts-db pg_dump -U ielts ielts_coach > backup.sql  # 备份数据库
```

## 七、版本迭代流程

```bash
git pull
cd frontend && npm ci && npm run build && cd ..
rm -rf deploy/dist && cp -r frontend/dist deploy/dist
cd deploy && docker compose -f docker-compose.prod.yml up -d --build backend
docker exec ielts-backend alembic upgrade head
```
