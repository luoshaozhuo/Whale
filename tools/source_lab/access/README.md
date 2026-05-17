# source_lab access

`tools/source_lab/access` 是 `source_lab` 下的 **source 接入能力扫描工具**，用于实验、诊断和容量探测，不是生产接入框架。

新的边界如下：

```text
src/whale/shared/source/access
    通用 source 接入抽象，可被 src/whale 复用。

tools/source_lab/access
    接入能力扫描工具，负责 preflight、capacity scan、报告输出和本地/现场 provider 编排。
```

## 1. 分层定位

`src/whale/shared/source/access` 负责可复用基础层：

```text
1. SourceEndpointSpec / SourcePointSpec
2. TickResult
3. SourceAccessAdapter 协议
4. OPC UA adapter 包装
5. prepare_read -> read_prepared_raw 读取链路
```

`tools/source_lab/access` 负责工具层：

```text
1. preflight
2. capacity scan
3. PASS / FLAKY / FAIL / SKIP
4. server_count / hz ramp
5. fail confirm runs
6. reporter
7. simulator / field provider 编排
```

这意味着：

```text
access 不是生产接入框架
tools/source_lab/access 是工具层
src/whale/shared/source/access 才是可复用接入基础层
```

## 2. 当前目录职责

```text
tools/source_lab/access/
├── __init__.py
├── capacity.py
├── config.py
├── metrics.py
├── model.py
├── preflight.py
├── reporter.py
├── scheduling.py
├── utils.py
├── worker.py
└── providers/
    ├── __init__.py
    ├── base.py
    ├── field.py
    └── simulator.py
```

其中：

```text
model.py
    只保留扫描工具专用模型，例如 CapacityScanConfig / CapacityScanResult /
    PreflightResult / CapacityLevelMetrics / ConfirmedLevelResult。

preflight.py
    负责 TCP reachability、adapter connect、prepare_read、read_tick 和结果归一化。

capacity.py
    负责 server_count ramp、hz ramp、失败确认、停止策略和总结果汇总。

worker.py
    负责一个 level 的扫描执行，依赖 shared/source/access 中的通用 adapter。

providers/
    负责 simulator / field 两类 source 来源与生命周期。
```

## 3. 行为边界

本次分层不改变以下行为：

```text
1. preflight 语义
2. capacity scan 语义
3. PASS / FLAKY / FAIL / SKIP 判定
4. stop_hz_ramp_on_first_fail 行为
5. accept_flaky_as_pass 行为
6. OPC UA open62541 client backend 默认路径
7. SourcePollingScheduler 使用路径
8. profile 测试路径
```

额外说明：

```text
capacity/profile 边界不变
open62541_runner_poll 仍只属于 profile 测试，不进入 capacity scan
```

## 4. 依赖方向

允许：

```text
tools/source_lab/access
    -> src/whale/shared/source/access
```

禁止：

```text
src/whale/shared/source/access
    -> tools/source_lab
src/whale/shared/source/access
    -> tools/source_lab/tests
tools/source_lab/access
    -> source_lab test-only helpers
```
