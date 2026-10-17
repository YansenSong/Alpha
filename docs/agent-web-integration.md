# Pi × RobotPilot 集成

当前交付：SDK 验证、独立 WebSocket Gateway 和 RobotPilot `/agent` 聊天页面（本机开发模式）。

ROS MCP、仿真业务工具与机器人任务验证已在此基础上扩展，安装和运行以 [机器人执行集成文档](agent-robot-execution.md) 为准。下文 Mock 验证记录属于最初 Web 集成阶段；当前 Gateway 默认加载项目 MCP，需先安装 alpha-mcp 依赖。

## 安装与验证

要求 Node.js >=22.19.0。Gateway 单独固定依赖
`@earendil-works/pi-coding-agent@1.3.0`，不引用全局 npm 包或修改 Pi 源码。

```bash
npm ci --prefix third_party/RobotPilot/agent-gateway
bash scripts/verify_pi_sdk.sh --trust-project
```

`--trust-project` 仅授权当前运行加载本仓库 `.pi/` 的代码和配置，不保存全局信任。
未提供此参数时验证必须失败。

离线验证检查项目 APPEND_SYSTEM、扩展集合、活动工具白名单，并直接执行只读
Mock 工具。它不发出模型请求，也不保存聊天历史。

真实模型验证（会使用已有 Pi 认证，产生模型请求）：

```bash
PI_AGENT_PROVIDER=deepseek PI_AGENT_MODEL=deepseek-flash \
  bash scripts/verify_pi_sdk.sh --trust-project --live
```

不指定模型环境变量时，仅从用户 Pi settings.json 读取 defaultProvider/defaultModel；
若没有偏好，选择首个可用模型。显式模型或已保存的默认模型不可用时直接失败。
环境变量应成对提供。验证不打印认证信息。

Live 检查模型文本增量、模型实际选择并成功执行 `get_alpha_info`、
`agent_settled`，随后发起第二轮请求并在生成时中止。总超时 90 秒。

## 资源与权限边界

- Pi cwd 固定为 AckermannRobot 根目录，与启动命令所在目录无关。
- `.pi/settings.json` 禁用默认内置工具；Host 另外指定唯一允许工具 `get_alpha_info`。
- 使用 Gateway `.runtime/agent` 作为独立 agentDir，不加载用户全局扩展或设置。
- ModelRuntime 单独复用 Pi 用户模型注册表与认证；只读取全局模型偏好，不把全局设置传入 ResourceLoader。
- 暂不加载 skills、prompt templates、上下文文件、主题或 MCP。
- 只接受当前项目的 robotpilot-tools.ts 扩展；新增扩展需同步修改 Host 策略。
- 扩展加载失败、项目系统指令缺失或工具列表异常均直接失败。
- 工具白名单不构成扩展代码的操作系统沙箱；本项目扩展是受信任代码。
- SDK 验证会话仅在内存中；Gateway 会话持久化到 `.runtime/sessions/`。运行数据、依赖和环境文件已忽略。

## Gateway 启动

```bash
PI_AGENT_PROVIDER=deepseek PI_AGENT_MODEL=deepseek-flash \
  bash scripts/run_pi_gateway.sh --trust-project
```

默认仅监听 `127.0.0.1:8769`；`PI_GATEWAY_PORT` 可修改端口。
健康检查：`GET /agent-api/health`。WebSocket：`/agent-api/ws`。
当前仅用于本机开发，接受 Origin `http://localhost:3000` 和
`http://127.0.0.1:3000`，拒绝没有 Origin 的连接。不提供 RobotPilot 用户鉴权。
不要通过反向代理将此开发 Gateway 暴露到远程网络。

会话创建响应的 `resume_token` 只返回一次。客户端需和 session_id 一起保存，
它是恢复和访问该会话的凭证，服务端只存储哈希。该机制隔离会话，
不等同于 RobotPilot 用户身份认证。不得将凭证放入 URL 或日志。

## WebSocket 协议

所有命令必须有 1–80 位字母、数字、下划线或短横线的 `request_id`。

| 命令 | 其他字段 | 行为 |
| --- | --- | --- |
| `session.create` | 无 | 创建并绑定；返回 snapshot 和 resume_token |
| `session.resume` | session_id, resume_token | 绑定已有会话并返回完整 snapshot |
| `session.sync` | session_id | 再次获取完整 snapshot |
| `session.delete` | session_id, resume_token | 校验归属后删除会话及历史；运行中拒绝删除 |
| `chat.prompt` | session_id, text | 接受普通文本，返回 request.ack |
| `chat.abort` | session_id | 等待当前运行停止后返回 request.ack |

每个连接只绑定一个会话。运行中再提交新 Prompt 会被拒绝，首版不提供 steer/followUp。
同一会话相同 request_id + 相同文本只接受一次；同 ID 不同文本会被拒绝。
Pi slash 命令和 prompt template 展开未开放给网页。

事件包含 session_id、run_id、递增 seq：`chat.accepted`、
`agent.message_start`、`agent.text_delta`、`agent.message_end`、
`agent.tool_start`、`agent.tool_end`、`agent.error`、`agent.settled`。
请求响应另有 `request.ack` 和 `request.error`，不占事件序号。

`session.snapshot` 包含 seq、status、run_id、items。客户端用快照整体替换
当前状态，只应用 seq 更大的后续事件。Delta 按 message_id 追加；message_end
用完整 item 替换对应消息，避免重复。工具卡片按 item.id 关联。
当前工具只展示受控名称、状态和批准的静态文本结果，不转发原始 SDK 对象。

`agent.settled` 在 SDK prompt Promise 完成后发出，包含自动重试后的最终空闲状态。
SDK 错误详情不直接发到浏览器。浏览器断线不会停止运行；重连重新请求快照，
不自动重发 Prompt。慢客户端会被断开，可通过快照恢复。

Pi JSONL 和 UI 快照持久化到 `.runtime/sessions/`，快照以临时文件加 rename 写入。
进程重启可恢复历史，但不会重放未完成的任务；中断状态显示 interrupted。
这不提供机器断电时跨 Pi JSONL 与 UI 快照的事务一致性。
最多保留 16 个会话，每个会话最多接受 500 个唯一 Prompt，单条文本最多 12000 字符。
已提供会话删除入口；尚未提供自动清理策略。

## Gateway 验证

```bash
npm test --prefix third_party/RobotPilot/agent-gateway
PI_AGENT_PROVIDER=deepseek PI_AGENT_MODEL=deepseek-flash \
  npm run verify:gateway --prefix third_party/RobotPilot/agent-gateway -- --trust-project
```

自动测试使用真实 WebSocket 和模拟模型验证隔离、去重、并发拒绝、重连、
中止、重启恢复与 Origin 检查。Live 验证使用真实模型及临时目录，
检查文本流、工具调用和 Gateway 重启后的第二轮 Pi 对话；结束后清理该临时目录。

## RobotPilot 页面使用

终端一启动 Gateway：

```bash
PI_AGENT_PROVIDER=deepseek PI_AGENT_MODEL=deepseek-flash \
  bash scripts/run_pi_gateway.sh --trust-project
```

终端二使用现有 RobotPilot 启动脚本：

```bash
bash scripts/run_robotpilot.sh
```

打开 `http://localhost:3000/agent`，点击“新建会话”，输入：

> 你好，请调用工具检查一下，目前支持哪些 Alpha 项目能力？

如果只验证 Mock 聊天页面，无需启动 ROS，也可以单独启动前端：

```bash
cd third_party/RobotPilot/web
VITE_AUTH_MODE=open npm run dev -- --host 127.0.0.1
```

该方式其他依赖 Flask / ROS 的页面可能显示离线状态。

页面沿用现有导航、主题和 Dashboard 组件，支持：

- 文本流、最终消息替换、可展开的工具结果卡片；AI 回复使用 Markdown 排版，用户输入按纯文本展示；不执行回复中的 HTML。
- 多个会话与恢复凭证的浏览器本地保存，刷新后恢复当前会话。
- 停止生成；切换页面或断线不会主动中止服务端运行。
- 重连后用完整快照恢复；不自动重发 Prompt。
- Enter 发送、Shift+Enter 换行及输入法组合输入保护。
- 输入在确认接收前保留，提交失败可修改后重试。
- 断线提示与发送禁用，独立于现有 ROS 页面。

浏览器仅保存会话凭证和列表元数据，聊天记录在 Gateway 本地。
清除浏览器存储会丢失恢复入口。删除会话会清理服务端历史和浏览器恢复凭证；正在生成时需先停止。
新建会话响应丢失时不会自动重复创建，应先恢复已有会话或手动新建。

Vite 将 `/agent-api` HTTP 和 WebSocket 代理到 `127.0.0.1:8769`。
若修改 PI_GATEWAY_PORT，也需要同步修改 Vite 代理目标。
当前页面只在本机 Vite + AUTH_MODE=open 启用；生产构建或 local 登录模式
显示说明，不连接未鉴权的开发 Gateway。生产接入仍需用户认证及反向代理。

网络链路验证（需前端 npm 依赖，会发出真实模型请求）：

```bash
PI_AGENT_PROVIDER=deepseek PI_AGENT_MODEL=deepseek-flash \
  npm run verify:web --prefix third_party/RobotPilot/agent-gateway -- --trust-project
```

该命令用临时 Gateway 和 Vite 实例检查 `/agent` HTML、HTTP 代理和
WebSocket 代理后的模型流式输出与工具事件；不代替浏览器视觉验收。

## 后续工作

正式部署前接入 RobotPilot 用户认证及生产代理；真实机器人能力继续保持未接入。

## 本次验证记录（2026-10-17）

- Node v24.18.0；本地 Pi 1.3.0 / 8efd314fa；SDK npm 依赖 1.3.0。
- 离线资源、工具白名单和 Mock 执行通过；从 `/tmp` 启动同样通过。
- 缺少显式信任参数时按预期拒绝。
- 使用 deepseek/deepseek-flash 的真实文本流、工具调用、settled 和生成中止通过。
- 用户当前默认 deepseek/deepseek-v4-flash 不在可用模型列表中，未修改该设置；验证通过环境变量选择可用模型。
- SDK/Gateway 阶段未更改 ROS 链路；页面接入阶段已运行前端完整测试与构建。

Gateway 验证：真实 DeepSeek WebSocket 流式输出、工具事件和进程重启后的 Pi 第二轮对话通过。

页面接入验证：前端 59 项测试通过、生产构建通过；真实 Vite HTTP/WebSocket 代理与模型工具调用验证通过。当前无可连接的浏览器会话，未完成截图和实际浏览器视觉验收。

## 回复渲染

AI 回复支持 Markdown 标题、段落、列表、引用、GFM 表格、任务列表、行内代码和代码块。
常见代码语言（Python、Shell、JavaScript、TypeScript、JSON、YAML、C++、HTML/XML）
进行局部高亮，未知语言与超过 30000 字符的代码块保留纯文本。
代码块和整条回复可以复制，剪贴板失败时显示失败反馈。
尚未闭合的代码围栏在流式输出时继续作为代码展示；历史回复使用 memo 避免随新 token 重复解析。
表格和长代码可以横向滚动，正文限制阅读宽度并适配明暗主题。
图片显示为链接，不自动加载外部图片；链接仅接受 HTTP(S) 和 mailto，外链打开新标签。
不使用 raw HTML 插件；代码高亮只插入 highlight.js 转义后的输出。

## deepseek-harness 渲染参考（2026-10-17）

参考仓库：[deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)，
核对提交 `687f282e8625c6b8d11ff58211a90524be2e4317`。
重点阅读 `ui-chat` 的 AssistantMarkdown、TurnProcessNodeView、use-scroll-follow，
以及 `ui-tool` 的 ToolRow 和 `ui-primitives` 的 CodeBlock。
本项目独立实现对应交互，没有引入该项目运行时或复制其源文件。

本轮应用：

- 工具执行以紧凑状态行呈现，位于唯一的 Agent 作者栏下方，保持工具与回复的事件顺序。
- 工具结果按需展开，失败时默认展开；运行状态改变不覆盖用户手动展开/收起的选择。
- 一轮回复的复制操作只放在末尾，复制该轮所有文字内容。
- 代码提供换行开关，表格可展开至聊天区域可用宽度并取消高度限制。
- 内容与窗口尺寸改变时，根据用户的跟随意图决定是否滚到底部；翻阅历史不被新 token 拉走。
- 所有状态来自 Pi 事件，不展示虚构的推理耗时或未接入的 reasoning 数据。

验证：前端 70 项测试和构建通过。未进行实际浏览器视觉验收。

## 开发服务器空模块故障诊断

曾出现运行中 Vite 缓存空 AgentPage 模块：HTTP 200 仅返回 source map，
没有 default 导出，React.lazy 在输出警告时抛出
`Cannot convert object to primitive value`。重新触发该文件编译后恢复。
后续编辑正在被 Vite 监视的文件应采用原子替换，避免截断写入时被读取为空模块。

```bash
npm run verify:ui --prefix third_party/RobotPilot/agent-gateway
```

此命令不调用模型，直接检查运行中 Vite 返回的七个聊天模块是否具备预期导出。
verify:web 同样检查这些模块，避免仅凭首页 HTTP 200 误判页面可加载。
错误边界显示后需刷新页面重试，无需清除浏览器会话凭证或聊天记录。

会话删除：列表中的删除按钮需二次确认，服务端成功后才移除浏览器凭证。
删除当前会话后切换至剩余会话或空白页；删除会话不会在重启后重新出现。
Pi JSONL 删除前先将会话元数据改名为删除标记，异常退出后继续清理。

输入框默认高度 96px，发送/停止按钮位于框内右下角。
“发送给 Pi”标签仅供读屏识别，不显示快捷键提示或字数统计。
验证：前端 72 项、Gateway 7 项测试和构建通过；已重启本机 Gateway，
并用临时测试会话验证真实服务的创建及删除接口。
