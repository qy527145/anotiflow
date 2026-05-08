# anotiflow

可扩展的任务调度通知框架：**触发器 + 行为插件 + 事件总线 + Web 控制台 + 远程动作 SDK**，TOML 配置驱动，基于 UV 管理。

```
触发器（定时 / 事件 / API）──▶ 任务 ──▶ 多个行为按序执行（飞书 / 钉钉 / 自定义本地 / 自定义远程 / 广播事件）
                                                   │
                                                   ├─ bus.publish(...) ──▶ 事件触发其他任务
                                                   └─ WebSocket ──▶ 远端 SDK handler 执行
```

一个任务可以绑定 **N 个触发器 + N 个行为**，任意触发器命中即按顺序执行全部行为。通过 `publish_event` 行为或用户自定义函数向 `EventBus` 广播事件，实现任务之间的链式联动。

## 特性

- **插件式设计** — 顶层 `Action` / `Trigger` 抽象基类，装饰器 `@register_action("xxx")` 即可注册新类型，TOML 自动识别
- **三种触发器** — 定时（基于 `schedule`，完整保留其原生灵活性）+ 事件（进程内 EventBus 订阅）+ **API webhook**（自动签发 token，`POST /trigger/<token>` 携带 payload 即触发）
- **内置通知渠道** — 飞书 / 钉钉（基于 `ipush`）
- **本地 + 远程自定义动作** — 本地走 dotted-path Python 函数；远程通过 WebSocket SDK，**业务依赖跑在客户端 venv 里**，与宿主完全解耦
- **Web 控制台** — 单文件 HTML，可视化管理任务/触发器/动作；改动落盘 TOML，文件改动实时生效，两路等价
- **配置即代码 + 实时同步** — TOML 是事实源，watchdog 监听文件变化自动 rebind；UI 与文件双向同步、hash 抑制回环
- **链式联动** — `EventBus.publish(event, payload)` 与 `EventTrigger` 配对；远程动作回包成功还可经 `publish_on_success` 串入事件总线
- **统一令牌系统** — admin / action / trigger 三类 scope，全部内联存放在 `config.toml` 中；缺失时自动签发，把整个配置发给同事即可完整复刻服务
- **工程细节** — loguru 日志、任务启用/禁用、行为级异常捕获、SIGINT/SIGTERM 优雅关闭、UI 改动原子落盘、远程客户端断线指数回退重连

## 安装

需要 [UV](https://docs.astral.sh/uv/) 与 Python ≥ 3.9。

```bash
git clone <this-repo>
cd anotiflow
uv sync
```

## 快速开始

```bash
# 任意空目录启动；不存在 config.toml 时会自动生成空模板与 admin token
mkdir my-anotiflow && cd my-anotiflow
uv run --project /path/to/anotiflow anotiflow

# 控制台输出会包含：
#   auto-issued admin token: adm_xxxxxxxxxxxxxxxxxx
#   web server starting at http://127.0.0.1:8765
```

打开浏览器访问 `http://127.0.0.1:8765`，登录页填入 admin token，即可可视化管理任务、触发器、动作。

也可以照旧用现成示例：

```bash
uv run anotiflow --config examples/config.toml
# 可选：--log-level DEBUG / --port 9000 / --no-web（仅引擎，不起 Web）
```

## 核心概念

### Task

```
Task = name + enabled + [Trigger, ...] + [Action, ...]
```

任意一个触发器命中 → 按顺序执行所有行为。任一行为抛异常会被记录日志但不影响后续行为 / 其他任务。

### Trigger（触发器）

| 类型 | 作用 | 关键字段 |
|---|---|---|
| `interval` | 定时，基于 `schedule` | `unit` 必填；`every` / `to` / `at` / `until` 可选 |
| `event` | 订阅 EventBus 事件 | `event` 事件名 |
| `api` | webhook 接入，外部 POST 触发 | `token`（缺失时自动签发） |

`interval` 的 `unit` 取值覆盖 `schedule` 的全部灵活性：

- `seconds` / `second`、`minutes` / `minute`、`hours` / `hour`、`days` / `day`、`weeks` / `week`
- 星期名：`monday` / `tuesday` / `wednesday` / `thursday` / `friday` / `saturday` / `sunday`

常见组合：

| 需求 | TOML |
|---|---|
| 每 5 秒 | `unit="seconds", every=5` |
| 每 5~10 秒随机 | `unit="seconds", every=5, to=10` |
| 每分钟的第 23 秒 | `unit="minute", at=":23"` |
| 每天 09:30 | `unit="day", at="09:30"` |
| 每周一 13:15 | `unit="monday", at="13:15"` |
| 每小时执行直到 18:30 | `unit="hour", until="18:30"` |

### Action（行为）

抽象层次：`Action`（顶层）→ `NotifyAction`（通知基类）→ `FeishuNotify` / `DingtalkNotify` / `RemoteActionProxy` / ...

内置类型：

| type | 说明 | 关键字段 |
|---|---|---|
| `feishu` | 飞书群机器人 | `token`, `secret`, `message_template` |
| `dingtalk` | 钉钉群机器人 | `token`, `secret`, `title`, `message_template` |
| `publish_event` | 向 EventBus 广播事件（用于串联任务） | `event`, `[tasks.actions.payload]` |
| `custom` (本地) | 调用宿主 venv 内的 Python 函数 | `path = "module.func"` |
| `custom` (远程) | WebSocket 派发到远端 SDK 客户端 | `remote = true`, `token`, `wait`, `timeout_seconds`, `offline_policy`, `publish_on_success` |

### Context（行为执行时的上下文）

行为模板可访问的命名空间（在 `message_template` / `publish_event.payload` 中用 `{...}` 引用）：

| 字段 | 含义 |
|---|---|
| `{task.name}` | 任务名 |
| `{task.config[xxx]}` | 当前任务任意字段 |
| `{trigger.config[xxx]}` | 命中触发器任意字段 |
| `{trigger.kind}` | `interval` / `event` / `api` |
| `{trigger.fired_at}` | 命中时刻 `YYYY-MM-DD HH:MM:SS` |
| `{trigger.payload[xxx]}` | 业务载荷字段（API/事件触发时来自 body/发布者；定时触发为 `{}`） |

## Web 控制台

启动后默认监听 `http://127.0.0.1:8765`（可在 `[server]` 段或 `--host/--port` 覆盖）。

- **首次访问**：日志中找到 `auto-issued admin token: adm_xxx`，登录页粘贴。
- **左栏**：任务列表，点击 + 新建，圆点表示 enabled。
- **中栏**：当前任务的触发器 / 动作表单编辑；动作类型选 `custom` + `remote=true` 时会自动展示客户端 SDK 代码片段。
- **右栏**：实时只读 TOML 预览。
- **顶部 Tokens**：列出全部令牌、可吊销。

UI 改动通过 `PUT /api/config` 落盘；外部直接编辑 `config.toml` 也会被 watchdog 捕获并实时 rebind。两路等价。

> ⚠️ TOML 写回不保留注释（这是 `tomli_w` 的限制）。如果你严重依赖配置文件里的注释，建议把它们拆到一个独立的 `README` 或保持只用 UI 编辑。

## API 触发（webhook）

```toml
[[tasks.triggers]]
name = "incoming"
type = "api"
# token 不写时会在首次启动时自动签发并回写到本文件
```

外部触发：

```bash
curl -X POST http://127.0.0.1:8765/trigger/<token> \
     -H 'Content-Type: application/json' \
     -d '{"symbol":"AAPL","price":107.6}'
```

body 即 `trigger.payload`；模板 `{trigger.payload[symbol]}` 直接可用。

## 自定义动作

### 本地（与原版一致）

```python
# user_actions.py
from anotiflow.core.event_bus import bus
def check_stock_price(context):
    task, trigger = context["task"], context["trigger"]
    ...
    bus.publish("stock.high", {...})
```

```toml
[[tasks.actions]]
type = "custom"
path = "user_actions.check_stock_price"
```

模块解析路径：CWD 与 config 文件所在目录都自动加入 `sys.path`。

### 远程（推荐：业务依赖跑在客户端进程）

宿主侧配置（token 不写就自动签发）：

```toml
[[tasks.actions]]
type = "custom"
remote = true
wait = true                  # 阻塞等待客户端回包；false 即 fire-and-forget
timeout_seconds = 30
offline_policy = "queue"     # queue 堆积 / drop 丢弃 / error 抛错
publish_on_success = "task.done"   # 可选：回包 ok=true 时把 value 串入事件总线
```

客户端（任意机器、任意 venv，只需 `pip install anotiflow`）：

```python
from anotiflow import RemoteAction

action = RemoteAction("ws://anotiflow-host:8765", token="<上面 UI 复制的 token>")

@action.handler
def handle(ctx):
    # ctx.task.name / ctx.task.config
    # ctx.trigger.name / ctx.trigger.kind / ctx.trigger.config
    # ctx.trigger.fired_at / ctx.trigger.payload
    return {"ok": True}        # 任意 JSON-friendly 值；通过 publish_on_success 流回事件总线

action.run()                   # 阻塞；自动断线指数回退重连
```

完整示例：[examples/remote_client.py](examples/remote_client.py)。

## EventBus

进程内线程安全的发布/订阅单例：

```python
from anotiflow.core.event_bus import bus
bus.publish("stock.high", {"symbol": "AAPL", "price": 107.6})
```

## 配置示例

完整示例见 [examples/config.toml](examples/config.toml) 与 [examples/config.example.toml](examples/config.example.toml)。

## 扩展新渠道 / 新触发器

新增企业微信通知：

```python
# src/anotiflow/actions/wecom.py
from ipush import WeCom
from anotiflow.actions.notify_base import NotifyAction
from anotiflow.core.registry import register_action

@register_action("wecom")
class WeComNotify(NotifyAction):
    def __init__(self, token: str, message_template: str = "") -> None:
        super().__init__(message_template=message_template)
        self.name = "wecom"
        self._client = WeCom(token=token)

    def _send(self, message: str) -> None:
        self._client.send(message)
```

在 [src/anotiflow/actions/__init__.py](src/anotiflow/actions/__init__.py) 里 `import` 该模块触发 `@register_action` 装饰器副作用。

新增触发器同理：继承 `Trigger` + `@register_trigger("your_type")`，在 [src/anotiflow/triggers/__init__.py](src/anotiflow/triggers/__init__.py) 里 `import`。

## 项目结构

```
anotiflow/
├── pyproject.toml
├── src/anotiflow/
│   ├── cli.py                     # uv run anotiflow 入口
│   ├── task.py                    # Task 数据类
│   ├── core/
│   │   ├── event_bus.py           # EventBus 单例
│   │   ├── registry.py            # 类型注册表
│   │   ├── loader.py              # parse_raw + build_tasks（TOML → Task[]）
│   │   ├── scheduler.py           # 旧版主循环（已被 Engine 取代，文件保留）
│   │   ├── engine.py              # 运行时核心：装配/绑定/热重载
│   │   ├── config_store.py        # 配置单一事实源 + 文件 watcher + 原子落盘
│   │   ├── token_index.py         # 从 config 派生的内存令牌索引（仅校验，不落盘）
│   │   ├── api_trigger_hub.py     # API 触发器注册中心
│   │   └── remote_broker.py       # 远程动作分发（WS 通道 + 派发表）
│   ├── triggers/
│   │   ├── base.py / interval.py / event.py
│   │   └── api.py                 # APITrigger
│   ├── actions/
│   │   ├── base.py / notify_base.py / feishu.py / dingtalk.py / publish_event.py
│   │   └── remote.py              # RemoteActionProxy
│   ├── server/
│   │   ├── app.py                 # FastAPI 装配
│   │   ├── auth.py                # admin token 中间件
│   │   ├── routes_config.py       # GET/PUT 配置；细粒度 task CRUD
│   │   ├── routes_tokens.py       # GET/POST/DELETE token
│   │   ├── routes_trigger_api.py  # POST /trigger/{token}
│   │   ├── ws_remote_action.py    # WS /ws/{scope}/{token}
│   │   └── ui/
│   │       ├── login.html         # 极简登录页
│   │       └── index.html         # 控制台单文件 UI
│   └── sdk/
│       ├── __init__.py            # re-export RemoteAction
│       └── remote_action.py       # 客户端 SDK
└── examples/
    ├── config.toml                # 配置示例
    ├── user_actions.py            # 本地自定义动作示例
    └── remote_client.py           # 远程自定义动作客户端示例
```

## 运行

```bash
uv run anotiflow                                  # 当前目录 ./config.toml；不存在自动生成
uv run anotiflow --config /path/to/your.toml     # 指定配置文件
uv run anotiflow --no-web                         # 仅引擎模式（兼容 0.2.x 老用法）
uv run anotiflow --host 0.0.0.0 --port 9000       # 覆盖 [server].host/port
uv run anotiflow --log-level DEBUG
# 等价写法
uv run python -m anotiflow
```

`Ctrl-C` 或 `SIGTERM` 会触发引擎解绑所有触发器、停掉 Web、并优雅退出。

## 依赖

- [schedule](https://pypi.org/project/schedule/) — 定时调度
- [ipush](https://pypi.org/project/ipush/) — 飞书 / 钉钉等推送渠道封装
- [loguru](https://pypi.org/project/loguru/) — 日志
- [fastapi](https://pypi.org/project/fastapi/) + [uvicorn](https://pypi.org/project/uvicorn/) — Web 服务
- [websockets](https://pypi.org/project/websockets/) — 远程动作传输
- [watchdog](https://pypi.org/project/watchdog/) — 配置文件 watcher
- [tomli_w](https://pypi.org/project/tomli-w/) — TOML 写回

## 升级 0.2 → 0.3 注意事项

- **Python 下限**：从 3.8 抬到 3.9（FastAPI 要求）。
- **配置兼容**：旧的 `interval` / `event` 触发器、`feishu` / `dingtalk` / `publish_event` / `custom (path)` 动作配置完全兼容，**无需改动**即可升级。
- **新增**：`[server]` 段（自动生成）、`[[tasks.triggers]] type="api"`、`[[tasks.actions]] type="custom" remote=true`。
- **令牌**：admin / action / trigger token 全部直接内联在 `config.toml` 里。轮换/吊销 = 在 UI 或 TOML 中清空对应字段，下次保存时会自动签发新值。把 `config.toml` 发给别人就能完整复刻服务，不再有副本文件需要管理。
- **TOML 注释**：UI 改动会通过 `tomli_w` 写回，注释会丢失。建议把长注释放到 README 或者只通过 UI 编辑配置。
