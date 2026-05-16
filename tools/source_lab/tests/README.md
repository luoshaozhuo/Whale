# source_lab 测试运行说明

本目录存放 tools/source_lab 的验证与压测测试，覆盖 backend 选择、open62541 smoke、单 server 读路径、多 server 读路径。

## 1. 测试文件说明

```text
tools/source_lab/tests/
├── test_factory.py
│   └── 验证 factory.py 是否能根据 SOURCE_SIM_OPCUA_BACKEND 选择 asyncua/open62541 后端。
├── test_open62541_source_simulation_single_server_smoke.py
│   └── 验证 open62541 后端能否启动、读取节点、执行 writes、内部自动更新。
├── test_source_simulation_multi_server_capacity.py
│   └── 多 server capacity 分级测试，重点检查可达频率与稳定性。
└── test_source_simulation_multi_server_profile.py
  └── 多 server profile 测试，含 open62541_runner_poll 的诊断与验收指标。
```

说明：

- multi server capacity/profile 当前测试的是 `PreparedReadPlan + read_prepared_raw()` raw path。
- `open62541_runner_poll` 由 C runner 内部 fixed-rate polling 驱动，作为已验证高频模式保留。

## 2. 运行前准备

进入仓库根目录：

```bash
cd ~/Whale
```

如果使用 `open62541` 后端，必须先编译 C runner：

```bash
cmake -S tools/source_lab/opcua/native \
  -B tools/source_lab/opcua/native/build \
  -DCMAKE_PREFIX_PATH=$HOME/.local/open62541

cmake --build tools/source_lab/opcua/native/build
```

确认 runner 已生成：

```bash
ls -lh tools/source_lab/opcua/native/build/open62541_source_simulator
```

## 3. factory 测试

```bash
python -m pytest tools/source_lab/tests/test_factory.py -s -v
```

## 4. open62541 单 server smoke 测试

```bash
SOURCE_SIM_OPCUA_BACKEND=open62541 \
python -m pytest tools/source_lab/tests/test_open62541_source_simulation_single_server_smoke.py -s -v
```

如果 runner 不存在，测试会 skip。

## 5. multi-server capacity 测试

```bash
SOURCE_SIM_OPCUA_BACKEND=asyncua \
python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_capacity.py -q
```

## 6. multi-server profile 测试

```bash
SOURCE_SIM_OPCUA_BACKEND=open62541 \
SOURCE_SIM_OPCUA_CLIENT_BACKEND=open62541 \
SOURCE_SIM_PROFILE_SCHEDULER_MODE=open62541_runner_poll \
SOURCE_SIM_LOAD_PROCESS_COUNT=1 \
SOURCE_SIM_LOAD_COROUTINES_PER_PROCESS=0 \
SOURCE_SIM_LOAD_SERVER_COUNT=2 \
SOURCE_SIM_LOAD_TARGET_HZ=5 \
SOURCE_SIM_LOAD_LEVEL_DURATION_S=5 \
SOURCE_SIM_LOAD_WARMUP_S=2 \
SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false \
SOURCE_SIM_LOAD_MAX_CONCURRENT_READS=16 \
SOURCE_SIM_LOAD_TOP_GAP_COUNT=5 \
SOURCE_SIM_PROFILE_SHOW_ALL=false \
SOURCE_SIM_PROFILE_MAX_LINES=80 \
SOURCE_SIM_FLEET_STARTUP_TIMEOUT_S=30 \
SOURCE_SIM_PORT_START=52000 \
SOURCE_SIM_PORT_END=65000 \
python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_profile.py -s -v
```

## 7. 多 server worker 模型

`test_source_simulation_multi_server_bottleneck.py` 现在只支持一套统一 worker 模型：

- `SOURCE_SIM_LOAD_WORKER_COUNT=1`
  单进程 coroutine。一个 event loop、一个 `SourcePollingScheduler`、一个 `ReadConcurrencyLimiter`、多个 `OpcUaSourceReader`。
- `SOURCE_SIM_LOAD_WORKER_COUNT>1`
  多进程 worker。主进程负责启动 simulator fleet、构造 source 列表、全局计算 stagger offset，并按 round-robin 分片给 worker；每个 worker 进程内部再用 coroutine + scheduler + limiter 执行自己的 sources。
- `read_schedule` 固定为 `global_stagger`。
- 每个 worker 都有自己的 `ReadConcurrencyLimiter`。
- `SourcePollingScheduler` 是否维护内部 stats 由环境变量控制。

重要语义：

- 全局 stagger offset 必须先在主进程按全量 source 计算，再分片给 worker。
- worker 内不得重新按本地 index 从 0ms 开始计算 offset，否则会重新形成 burst。
- worker 只在结束时回传聚合统计，不逐 tick 做跨进程通信。

## 7. 多 server 环境变量

当前 multi server 测试重点变量如下：

- `SOURCE_SIM_LOAD_WORKER_COUNT`
  默认 `1`。`1` 表示单进程 coroutine；`>1` 表示多进程 worker。
- `SOURCE_SIM_LOAD_MAX_CONCURRENT_READS_PER_WORKER`
  默认 `16`。每个 worker 内 `ReadConcurrencyLimiter.max_concurrent`。
- `SOURCE_SIM_LOAD_MAX_CONCURRENT_READS`
  旧兼容变量。只有当 `SOURCE_SIM_LOAD_MAX_CONCURRENT_READS_PER_WORKER` 未设置时才读取它。
- `SOURCE_SIM_LOAD_SCHEDULER_DIAGNOSTICS_ENABLED`
  默认 `false`。传给 `SourcePollingScheduler(diagnostics_enabled=...)`。
- `SOURCE_SIM_LOAD_LEVEL_DURATION_S`
- `SOURCE_SIM_LOAD_WARMUP_S`
- `SOURCE_SIM_LOAD_HZ_START`
- `SOURCE_SIM_LOAD_HZ_STEP`
- `SOURCE_SIM_LOAD_HZ_MAX`
- `SOURCE_SIM_LOAD_SERVER_COUNT_START`
- `SOURCE_SIM_LOAD_SERVER_COUNT_STEP`
- `SOURCE_SIM_LOAD_SERVER_COUNT_MAX`
- `SOURCE_SIM_LOAD_READ_TIMEOUT_S`
- `SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED`
- `SOURCE_SIM_LOAD_SOURCE_UPDATE_HZ`
- `SOURCE_SIM_LOAD_PERIOD_TOLERANCE_RATIO`
- `SOURCE_SIM_LOAD_PERIOD_PASS_RATIO`
- `SOURCE_SIM_LOAD_MIN_POINTS`
- `SOURCE_SIM_LOAD_MAX_POINTS`

不再使用的旧 multi server 变量：

- `SOURCE_SIM_LOAD_READER_MODE`
- `SOURCE_SIM_LOAD_READ_SCHEDULE`
- 旧的 process/coroutine 切换开关
- burst 调度模式

## 8. 多 server 示例命令

单进程 coroutine：

```bash
SOURCE_SIM_OPCUA_BACKEND=open62541 \
SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false \
SOURCE_SIM_LOAD_WORKER_COUNT=1 \
SOURCE_SIM_LOAD_MAX_CONCURRENT_READS_PER_WORKER=16 \
SOURCE_SIM_LOAD_SCHEDULER_DIAGNOSTICS_ENABLED=false \
SOURCE_SIM_LOAD_SERVER_COUNT_START=20 \
SOURCE_SIM_LOAD_SERVER_COUNT_STEP=1 \
SOURCE_SIM_LOAD_SERVER_COUNT_MAX=20 \
SOURCE_SIM_LOAD_HZ_START=10 \
SOURCE_SIM_LOAD_HZ_STEP=1 \
SOURCE_SIM_LOAD_HZ_MAX=10 \
SOURCE_SIM_LOAD_LEVEL_DURATION_S=30 \
SOURCE_SIM_LOAD_WARMUP_S=5 \
python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_bottleneck.py -s -v
```

多进程 worker：

```bash
SOURCE_SIM_OPCUA_BACKEND=open62541 \
SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false \
SOURCE_SIM_LOAD_WORKER_COUNT=4 \
SOURCE_SIM_LOAD_MAX_CONCURRENT_READS_PER_WORKER=4 \
SOURCE_SIM_LOAD_SCHEDULER_DIAGNOSTICS_ENABLED=false \
SOURCE_SIM_LOAD_SERVER_COUNT_START=20 \
SOURCE_SIM_LOAD_SERVER_COUNT_STEP=1 \
SOURCE_SIM_LOAD_SERVER_COUNT_MAX=20 \
SOURCE_SIM_LOAD_HZ_START=10 \
SOURCE_SIM_LOAD_HZ_STEP=1 \
SOURCE_SIM_LOAD_HZ_MAX=10 \
SOURCE_SIM_LOAD_LEVEL_DURATION_S=30 \
SOURCE_SIM_LOAD_WARMUP_S=5 \
python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_bottleneck.py -s -v
```

近似纯 process：

```bash
SOURCE_SIM_OPCUA_BACKEND=open62541 \
SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false \
SOURCE_SIM_LOAD_WORKER_COUNT=20 \
SOURCE_SIM_LOAD_MAX_CONCURRENT_READS_PER_WORKER=1 \
SOURCE_SIM_LOAD_SCHEDULER_DIAGNOSTICS_ENABLED=false \
SOURCE_SIM_LOAD_SERVER_COUNT_START=20 \
SOURCE_SIM_LOAD_SERVER_COUNT_STEP=1 \
SOURCE_SIM_LOAD_SERVER_COUNT_MAX=20 \
SOURCE_SIM_LOAD_HZ_START=10 \
SOURCE_SIM_LOAD_HZ_STEP=1 \
SOURCE_SIM_LOAD_HZ_MAX=10 \
SOURCE_SIM_LOAD_LEVEL_DURATION_S=30 \
SOURCE_SIM_LOAD_WARMUP_S=5 \
python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_bottleneck.py -s -v
```

## 9. 小规模验证命令

单进程 coroutine：

```bash
SOURCE_SIM_OPCUA_BACKEND=open62541 \
SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false \
SOURCE_SIM_LOAD_WORKER_COUNT=1 \
SOURCE_SIM_LOAD_MAX_CONCURRENT_READS_PER_WORKER=4 \
SOURCE_SIM_LOAD_SCHEDULER_DIAGNOSTICS_ENABLED=false \
SOURCE_SIM_LOAD_SERVER_COUNT_START=2 \
SOURCE_SIM_LOAD_SERVER_COUNT_STEP=1 \
SOURCE_SIM_LOAD_SERVER_COUNT_MAX=2 \
SOURCE_SIM_LOAD_HZ_START=2 \
SOURCE_SIM_LOAD_HZ_STEP=1 \
SOURCE_SIM_LOAD_HZ_MAX=2 \
SOURCE_SIM_LOAD_LEVEL_DURATION_S=5 \
SOURCE_SIM_LOAD_WARMUP_S=2 \
python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_bottleneck.py -s -v
```

多进程 worker：

```bash
SOURCE_SIM_OPCUA_BACKEND=open62541 \
SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false \
SOURCE_SIM_LOAD_WORKER_COUNT=2 \
SOURCE_SIM_LOAD_MAX_CONCURRENT_READS_PER_WORKER=2 \
SOURCE_SIM_LOAD_SCHEDULER_DIAGNOSTICS_ENABLED=false \
SOURCE_SIM_LOAD_SERVER_COUNT_START=2 \
SOURCE_SIM_LOAD_SERVER_COUNT_STEP=1 \
SOURCE_SIM_LOAD_SERVER_COUNT_MAX=2 \
SOURCE_SIM_LOAD_HZ_START=2 \
SOURCE_SIM_LOAD_HZ_STEP=1 \
SOURCE_SIM_LOAD_HZ_MAX=2 \
SOURCE_SIM_LOAD_LEVEL_DURATION_S=5 \
SOURCE_SIM_LOAD_WARMUP_S=2 \
python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_bottleneck.py -s -v
```

## 10. PASS / FAIL 判据

multi server 压测当前仍使用同一套通过标准：

1. `batch_mismatches == 0`
2. `read_errors == 0`
3. `missing_response_timestamps == 0`
4. `response timestamp gap` 样本数 `> 0`
5. `min_reader_pass_ratio >= SOURCE_SIM_LOAD_PERIOD_PASS_RATIO`

多 server 表格当前主要显示这些诊断列：

- `min_p`
  每个 reader 的 response timestamp 周期最低达标率。
- `j95 / jmax`
  response timestamp 周期误差的 p95 / max，单位 ms。
- `raw95 / rawmax`
  `read_prepared_raw()` 外层完整调用耗时。
- `wrap95 / wrapmax`
  raw 返回后，测试 wrapper 构造结果对象的耗时。
- `cb95 / cbmax`
  scheduler callback 中记录测试统计的耗时。
- `t95 / tmax`
  `read_tick()` 完整耗时。

说明：

- 表格不显示 `bad`，不代表不检查 `bad`。`batch_mismatches` 仍然参与 PASS/FAIL。
- `scheduler.job_stats()` 不参与 PASS/FAIL。
- 如果 `cbmax` 很高，说明测试统计回调自身可能造成尾延迟。
- 如果 `rawmax` 很高，说明 `read_prepared_raw/asyncua/ReadResponse` 链路是主要来源。
- 如果 `wrapmax` 很高，说明测试侧对象包装或 Python 分配有尖峰。
- 如果 `tmax` 很高但 `rawmax/wrapmax/cbmax` 都不高，说明 event loop 调度恢复或 scheduler 事件构造可能存在抖动。
