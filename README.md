# claude-design-mcp

> `claude.ai/design` 网页封装 MCP 连接器
> 用 Playwright 浏览器自动化控制 Claude Design，暴露 5 个 MCP 工具。

## 工具列表

| 工具名 | 说明 |
|--------|------|
| `design_login` | 登录 claude.ai，保存 session |
| `design_create` | 输入 prompt，生成设计稿，可导出 HTML / 截图 |
| `design_refine` | 追加修改指令，更新设计稿 |
| `design_export` | 导出当前设计稿（html / screenshot / pdf） |
| `design_status` | 查看当前浏览器页面状态 |

## 快速部署（VPS）

```bash
# 1. 拉代码
git clone https://github.com/hostingervps1/claude-design-mcp
cd claude-design-mcp

# 2. 填账号（或登录后 session 自动保存）
cp .env.example .env
# 编辑 .env，填入 CLAUDE_EMAIL 和 CLAUDE_PASSWORD

# 3. 启动
docker compose up -d --build

# 4. 验证
curl http://localhost:8090/health
```

## 接入 mcp.xinjiyuan.tech

在 VPS 的 MCP 网关配置中添加：

```json
{
  "name": "claude-design",
  "url": "http://localhost:8090/mcp",
  "transport": "streamable_http"
}
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CLAUDE_EMAIL` | 空 | claude.ai 账号邮箱 |
| `CLAUDE_PASSWORD` | 空 | claude.ai 账号密码 |
| `SESSION_FILE` | `/data/session.json` | session 缓存路径 |
| `PORT` | `8090` | MCP 服务端口 |
| `HEADLESS` | `true` | 无头模式（VPS 必须 true） |
| `BROWSER_TIMEOUT` | `60000` | 浏览器操作超时（ms） |

## 典型调用流程

```
1. design_login（首次使用）
       ↓
2. design_create（输入 prompt）
       ↓
3. design_refine（反复修改）
       ↓
4. design_export（导出最终稿）
```

## 注意事项

- Claude Design 是 token 消耗较大的功能，每次调用会消耗你 claude.ai Pro 订阅的 Design 配额
- `design_create` 的 `wait_seconds` 默认 30s，复杂设计建议设 60-90s
- session 文件保存在 `/data/session.json`，下次启动自动复用，无需重复登录
- VPS 必须设置 `shm_size: 1gb`，否则 Chromium 会崩溃

## 相关仓库

- [disassembly-pipeline](https://github.com/hostingervps1/disassembly-pipeline) — 万能拆迁流水线
- [vast-core](https://github.com/hostingervps1/vast-core) — 后端拆迁产物
- [openhands-adapters](https://github.com/hostingervps1/openhands-adapters) — 拆迁模块接入层
