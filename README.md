# Ncode — 本地 AI Agent 系统

## 快速开始

```bash
# 安装依赖
uv sync

# 配置 API Key
echo "DEEPSEEK_API_KEY=sk-xxx" >> .env

# 运行测试（启动 daemon + 客户端 + 发送 agent.run）
PYTHONPATH=src uv run python -m main
```

## 核心设计

### 1. Agent 推理闭环引擎

基于 **ReAct（Reasoning + Acting）** 模式。与传统的 Plan-Execute 不同，Agent 每一步基于上一步的工具执行结果动态决定下一步动作，更适合编码、调试等探索性任务。

```
while not done:
    step += 1
    [plan]   LLM.chat(messages, tools)     → 让 LLM 决定下一步
    [observe] 记录 LLM 输出 (thinking/text/tool_use)
    [act]    invoke_tool() × N             → 执行工具
    [check]  end_turn → success / step≥max → failed / 异常 → failed
```

**三层容错机制**：LLM 调用失败立即终止（Provider 内部已做 3 次重试）→ 工具执行失败转为 ToolResult(is_error=True) 传给 LLM 自行纠错 → 步数上限（默认 20）防止无限循环。`end_turn` 优先级高于 `max_steps`，第 20 步恰好完成算成功。

每步事件流：`StepStarted → LlmModelSelected → LlmToken×N → LlmUsage → ToolCallStarted → ToolCallFinished → StepFinished`，客户端订阅即可实时渲染。

### 2. 工具调用安全链路

LLM 返回的 `tool_use` 请求到实际工具执行之间经过 **5 道安全关卡**：

| 关卡 | 说明 | 失败处理 |
|------|------|----------|
| ① 存在性检查 | `registry.get(name)` 查找工具 | 返回 unknown tool |
| ② Schema 校验 | `params_model.model_validate(input)` | 返回 schema_error |
| ③ 权限审批 | `PermissionManager.check_and_wait()` | 返回 permission_denied |
| ④ 超时 + 重试 | `asyncio.wait_for(invoke, 120s)` × 3 | 见下表 |
| ⑤ 结果返回 | 永不抛异常，返回 ToolResult | LLM 自行决策 |

重试分类：`runtime_error` / `rate_limited` → 重试（指数退避 2s/4s）；`timeout` / `schema_error` / `permission_denied` → 不重试。

内置 7 个工具：

| 工具 | 功能 | 安全限制 |
|------|------|----------|
| `read_file` | 读取文件 | 512KB，禁止 `..` 路径穿越 |
| `write_file` | 写入文件 | 1MB，自动创建父目录 |
| `bash` | Shell 命令 | OUTSIDE_CWD 检测 |
| `list_dir` | 目录树 | 最大深度 4，最多 200 条 |
| `get_time` | 时间查询 | 无风险，自动放行 |
| `spawn_agent` | 派生子 Agent | 最大深度 2 |
| `agent_result` | 查询子 Agent 结果 | 仅后台任务 |

### 3. 本地 Agent 权限控制

**4 种决策 × 6 层缓存**，平衡自动化能力与安全边界：

```
决策:
  allow_once     ← 仅本次放行
  always_allow   ← 永远放行 → 写入 ~/.wuwu/policy.toml
  deny_once      ← 仅本次拒绝
  always_deny    ← 永远拒绝 → 写入 ~/.wuwu/policy.toml

6 层优先级（命中即返回，不再检查后续层）:
  Tier 1: deny_patterns    ← 黑名单正则（直接拒绝，不可绕过）
  Tier 2: OUTSIDE_CWD      ← 路径穿越检测（强制 ASK，不可绕过）
  Tier 3: Session Always   ← 内存缓存 (session_id, tool_name)
  Tier 4: Persistent       ← 磁盘缓存 ~/.wuwu/policy.toml
  Tier 5: allow_patterns   ← 白名单正则（自动放行）
  Tier 6: Tool Default     ← 工具默认策略 (read→ALLOW, bash→ASK)
```

ASK 路径使用 **Future 异步审批**模式：创建 Future 存入 pending 表 → 发 `PermissionRequestedEvent` → `await Future`（60s 超时）→ 客户端通过 `permission.respond` RPC 返回决策 → resolve Future。客户端断连时自动拒绝所有待审批请求，防止 Agent 永久挂起。

### 4. 长任务上下文管理

Agent 执行长任务时，对话历史线性增长（每步 +2 条消息），导致 LLM 调用越来越贵、越来越慢。上下文使用率超过 80% 时自动触发压缩：

```
压缩前: 60 条消息 ≈ 50,000 token
  ↓ 调用 LLM（不带工具）按 6 段结构化格式总结
压缩后: 2 条消息 ≈ 500-800 token
  [user: 摘要文本]
  [assistant: "Understood, I'll continue from this summary."]
```

压缩时机选择在工具调用后（`stop_reason == "tool_use"`），保证压缩后的 `[user, assistant]` 序列对下一次 LLM 调用合法。摘要同时写入 `summary_<ts>.md` 文件，支持人工审查。

### 5. 多 Agent 协作编排

父 Agent 通过 `spawn_agent` 工具派生子 Agent 执行独立子任务。支持两种模式：

- **前台模式**：父 Agent `await` 子 Agent 完成，拿到结果后继续推理
- **后台模式**：父 Agent 立即拿到 `run_id`，继续执行其他任务，稍后通过 `agent_result(run_id)` 轮询结果（支持并行）

子 Agent 隔离保证：独立 `ExecutionContext`（不继承父对话）、独立 `EventBus`（通过 bridge 函数转发到父 Bus）、独立 `events.jsonl`、独立 `AgentLoop` 实例。最大嵌套深度 2 层，防止无限递归。

---

## 技术栈

| 层 | 选型 |
|----|------|
| 语言 | Python 3.12 |
| 异步框架 | asyncio |
| 数据校验 | pydantic v2（Discriminator 联合类型） |
| LLM SDK | Anthropic SDK（DeepSeek 兼容端点 `api.deepseek.com/anthropic`） |
| 通信协议 | JSON-RPC 2.0 NDJSON（自研，换行分隔，单帧最大 64MB） |
| 进程模型 | 双进程 C/S（daemon + 客户端通过 TCP loopback 通信） |

## 项目结构

```
src/
├── core/
│   ├── bus/                ← 通信协议定义
│   │   ├── envelope.py     ← JSON-RPC 消息模型
│   │   ├── commands.py     ← RPC 命令
│   │   └── events.py       ← 事件类型
│   ├── transport/          ← TCP 传输层
│   │   ├── socket_server.py   ← TCP 服务端 (daemon 端)
│   │   ├── socket_client.py   ← TCP 客户端
│   │   └── ipc_broadcaster.py ← EventBus → TCP 事件广播
│   ├── events/             ← 事件系统
│   │   ├── bus.py          ← EventBus（发布-订阅）
│   │   └── writer.py       ← EventWriter（事件落盘）
│   ├── llm/                ← LLM Provider
│   │   ├── base.py         ← LLMProvider 接口
│   │   ├── types.py        ← LlmResponse / ToolCallBlock / UsageStats
│   │   └── provider.py     ← DeepSeekProvider（流式 + 重试）
│   ├── tools/              ← 工具系统
│   │   ├── base.py         ← BaseTool 抽象 + ToolResult
│   │   ├── registry.py     ← ToolRegistry（注册/查找/生成 schema）
│   │   ├── invocation.py   ← invoke_tool() 安全包装
│   │   └── builtin/        ← 7 个内置工具
│   ├── permissions/        ← 权限控制
│   │   ├── policy.py       ← ToolPolicy / PermissionDecision / 策略评估
│   │   ├── manager.py      ← PermissionManager（6 层缓存 + Future 审批）
│   │   └── storage.py      ← policy.toml 持久化
│   ├── compact/            ← 上下文压缩
│   │   ├── compactor.py    ← Compactor（LLM 驱动摘要生成）
│   │   └── budget.py       ← tool_result 截断
│   ├── subagent/           ← 子 Agent 编排
│   │   ├── registry.py     ← BackgroundTaskRegistry
│   │   └── tool.py         ← SpawnAgentTool + AgentResultTool
│   ├── trace/              ← 全链路追踪
│   │   ├── record.py       ← TraceRecord
│   │   ├── writer.py       ← TraceWriter（异步队列写入）
│   │   └── provider.py     ← TracingProvider（LLM 装饰器）
│   ├── memory/             ← 上下文文件加载
│   │   └── loader.py       ← load_context_file()
│   ├── config.py           ← 4 层优先级配置系统
│   ├── context.py          ← ExecutionContext（消息管理/状态跟踪）
│   ├── loop.py             ← AgentLoop（ReAct 循环引擎）
│   ├── runner.py           ← AgentRunner（Run 编排/生命周期）
│   ├── runs.py             ← run ID 生成与目录管理
│   └── app.py              ← CoreApp（Daemon 入口/模块组装）
├── cli/                    ← CLI 客户端
│   ├── main.py
│   └── commands/
└── tui/                    ← TUI 前端（规划中）
    └── app.py

main.py                     ← 测试入口（启动 daemon + 客户端 + 验证）
```

## 开发

```bash
# 安装依赖
uv sync

# 配置 DeepSeek API Key
echo "DEEPSEEK_API_KEY=sk-xxx" >> .env

# 运行完整测试（启动 daemon → 连接 → ping → agent.run → 事件推送）
PYTHONPATH=src uv run python -m main

# 查看 trace 日志
cat ~/.wuwu/traces/daemon.jsonl | jq .
```
