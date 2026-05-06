# anotify

可扩展的任务调度通知框架：**触发器 + 行为插件 + 事件总线**，TOML 配置驱动，基于 UV 管理。

```
触发器（定时 / 事件）──▶ 任务 ──▶ 多个行为按序执行（飞书 / 钉钉 / 自定义 / 广播事件）
                                            │
                                            └─ bus.publish(...) ──▶ 事件触发其他任务
```

一个任务可以绑定 **N 个触发器 + N 个行为**，任意触发器命中即按顺序执行全部行为。通过 `publish_event` 行为或用户自定义函数向 `EventBus` 广播事件，实现任务之间的链式联动。

## 特性

- **插件式设计** — 顶层 `Action` / `Trigger` 抽象基类，派生出通知基类 / 具体渠道；装饰器 `@register_action("xxx")` 即可注册新类型，TOML 自动识别
- **两种触发器** — 定时（基于 `schedule`，**完整保留其原生灵活性**：秒/分/时/天/周、每周一..周日、`at` 精确时刻、`to` 随机区间、`until` 截止时刻）+ 事件（进程内 EventBus 订阅）；预留手动触发扩展点
- **内置通知渠道** — 飞书 / 钉钉（基于 `ipush`），统一继承 `NotifyAction`，一个任务可多渠道同步发送
- **配置即代码** — TOML 管理任务、触发器、行为参数；新增任务零代码
- **自定义业务逻辑** — 用户写普通 Python 函数（`fn(context) -> None`），TOML 以 dotted path 引用；通常用于"定时检查 + 满足条件广播事件"的判断层
- **链式联动** — `EventBus.publish(event, payload)` 与 `EventTrigger` 配对，形成任务间事件链路
- **工程细节** — loguru 日志、任务启用/禁用、行为级异常捕获、SIGINT/SIGTERM 优雅关闭

## 安装

需要 [UV](https://docs.astral.sh/uv/)。

```bash
git clone <this-repo>
cd anotify
uv sync
```

## 快速开始

```bash
uv run anotify --config examples/config.toml
# 可选：--log-level DEBUG
```

默认示例会每 5 秒随机模拟一次"股价检查"，高于阈值即广播 `stock.high` 事件，触发飞书 / 钉钉通知。将 [examples/config.toml](examples/config.toml) 里的 `token` / `secret` 替换为真实值就能收到真通知；占位值会发送失败但不会让进程崩溃。

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

抽象层次：`Action`（顶层）→ `NotifyAction`（通知基类）→ `FeishuNotify` / `DingtalkNotify` / ...

内置类型：

| type | 说明 | 关键字段 |
|---|---|---|
| `feishu` | 飞书群机器人 | `token`, `secret`, `message_template` |
| `dingtalk` | 钉钉群机器人 | `token`, `secret`, `title`, `message_template` |
| `publish_event` | 向 EventBus 广播事件（用于串联任务） | `event`, `[tasks.actions.payload]` |
| `custom` | 调用用户自定义函数 | `path = "module.func"` |

### Context（行为执行时的上下文）

每次任务触发，框架会组装 context 字典传给每个 action。在 `message_template` / `publish_event.payload` 里用 `{xxx}` 引用：

| 字段 | 含义 |
|---|---|
| `{task_name}` | 任务名 |
| `{trigger_name}` | 触发来源描述，如 `interval(every 5 seconds)` / `event(stock.high)` |
| `{trigger_type}` | `interval` / `event` |
| `{fired_at}` | 触发时刻 `YYYY-MM-DD HH:MM:SS` |
| `{trigger_payload}` | 完整业务载荷 dict |
| `{trigger_payload[symbol]}` | 载荷中某字段 |

### EventBus

进程内线程安全的发布/订阅单例：

```python
from anotify.core.event_bus import bus
bus.publish("stock.high", {"symbol": "AAPL", "price": 107.6})
```

## 配置示例

```toml
# 任务 1：每 5 秒跑一次自定义业务检查
[[tasks]]
name = "check_stock_price"
enabled = true

[[tasks.triggers]]
type = "interval"
every = 5
unit = "seconds"

[[tasks.actions]]
type = "custom"
path = "examples.user_actions.check_stock_price"

# 任务 2：多触发器（定时 + 两个事件），按序发飞书 + 钉钉
[[tasks]]
name = "notify_with_multi_triggers"
enabled = true

[[tasks.triggers]]
type = "interval"
every = 12
unit = "seconds"

[[tasks.triggers]]
type = "event"
event = "stock.high"

[[tasks.triggers]]
type = "event"
event = "manual.fire"

[[tasks.actions]]
type = "feishu"
token = "xxxx"
secret = "yyyy"
message_template = """[{task_name}] 触发={trigger_name} @ {fired_at}
载荷={trigger_payload}"""

[[tasks.actions]]
type = "dingtalk"
token = "xxxx"
secret = "yyyy"
title = "anotify 通知"
message_template = "{trigger_payload[symbol]} = {trigger_payload[price]}"

# 任务 3：每天 09:30 广播事件（用 publish_event 串联）
[[tasks]]
name = "daily_morning_fire"
enabled = true

[[tasks.triggers]]
type = "interval"
unit = "day"
at = "09:30"

[[tasks.actions]]
type = "publish_event"
event = "manual.fire"

[tasks.actions.payload]
reason = "morning_cron@{fired_at}"
```

完整示例见 [examples/config.toml](examples/config.toml)。

## 自定义业务行为

写一个普通 Python 函数，签名 `fn(context: dict) -> None`：

```python
# examples/user_actions.py
from anotify.core.event_bus import bus
from loguru import logger

def check_stock_price(context: dict) -> None:
    price = fetch_price("AAPL")
    logger.info(f"[{context['task_name']}] price={price} at {context['fired_at']}")
    if price > 100:
        bus.publish("stock.high", {"symbol": "AAPL", "price": price})
```

TOML 引用：

```toml
[[tasks.actions]]
type = "custom"
path = "examples.user_actions.check_stock_price"
```

模块解析路径：框架会把 CWD 与 config 文件所在目录都加入 `sys.path`，所以 `examples.user_actions.check_stock_price` 在项目根目录执行 `uv run anotify` 时能被正确加载。

## 扩展新渠道 / 新触发器

以新增企业微信通知为例：

```python
# src/anotify/actions/wecom.py
from ipush import WeCom
from anotify.actions.notify_base import NotifyAction
from anotify.core.registry import register_action

@register_action("wecom")
class WeComNotify(NotifyAction):
    def __init__(self, token: str, message_template: str = "") -> None:
        super().__init__(message_template=message_template)
        self.name = "wecom"
        self._client = WeCom(token=token)

    def _send(self, message: str) -> None:
        self._client.send(message)
```

在 [src/anotify/actions/__init__.py](src/anotify/actions/__init__.py) 里 `import` 该模块触发 `@register_action` 装饰器副作用，之后 TOML 里 `type = "wecom"` 即可使用。

新增触发器同理：继承 `Trigger` + `@register_trigger("your_type")`，在 [src/anotify/triggers/__init__.py](src/anotify/triggers/__init__.py) 里 `import`。

## 项目结构

```
anotify/
├── pyproject.toml
├── src/anotify/
│   ├── cli.py                     # uv run anotify 入口
│   ├── __main__.py                # python -m anotify
│   ├── task.py                    # Task 数据类
│   ├── logging_setup.py           # loguru 初始化
│   ├── core/
│   │   ├── event_bus.py           # EventBus 单例
│   │   ├── registry.py            # 类型注册表
│   │   ├── loader.py              # TOML → Task[]
│   │   └── scheduler.py           # 主循环 + 优雅关闭
│   ├── triggers/
│   │   ├── base.py                # Trigger ABC
│   │   ├── interval.py            # 定时触发（schedule）
│   │   └── event.py               # 事件触发（EventBus 订阅）
│   └── actions/
│       ├── base.py                # Action ABC + CallableAction
│       ├── notify_base.py         # NotifyAction
│       ├── feishu.py              # 飞书通知
│       ├── dingtalk.py            # 钉钉通知
│       └── publish_event.py       # 广播事件行为
└── examples/
    ├── config.toml                # 配置示例（含 4 个任务）
    └── user_actions.py            # 自定义业务行为示例
```

## 运行

```bash
uv run anotify --config examples/config.toml
uv run anotify --config /path/to/your.toml --log-level DEBUG
# 等价写法
uv run python -m anotify --config examples/config.toml
```

`Ctrl-C` 或 `SIGTERM` 会触发 Scheduler 解绑所有触发器并优雅退出。

## 依赖

- [schedule](https://pypi.org/project/schedule/) — 定时调度
- [ipush](https://pypi.org/project/ipush/) — 飞书 / 钉钉等推送渠道统一封装
- [loguru](https://pypi.org/project/loguru/) — 日志
