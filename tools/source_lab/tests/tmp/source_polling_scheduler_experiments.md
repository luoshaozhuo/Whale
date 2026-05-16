# SourcePollingScheduler Experiments

This file records the automated experiment matrix for the high-frequency polling scheduler investigation.

## Experiment A

- experiment_id: `A_absolute_direct`
- hypothesis: `SourcePollingScheduler` 的通用执行链路本身引入额外调度抖动，切到 profile-only direct absolute loop 也许能接近已验证 PASS 的 profile absolute scheduler。
- files_changed: `src/whale/shared/source/scheduling/polling.py`, `tools/source_lab/tests/test_source_simulation_multi_server_profile.py`, `tests/unit/test_source_scheduling.py`
- implementation_summary: 在 `SourcePollingScheduler` 内新增 `SOURCE_SIM_PROFILE_SCHEDULER_IMPL=absolute_direct`，为每个 job 走 direct absolute loop，跳过 callback worker 与 stats，仅保留 event sink、必要 event 构造和 disabled callback 短路。
- test_command: `python -m py_compile src/whale/shared/source/scheduling/polling.py tools/source_lab/tests/test_source_simulation_multi_server_profile.py tests/unit/test_source_scheduling.py && python -m pytest tests/unit/test_source_scheduling.py -q && SOURCE_SIM_OPCUA_BACKEND=open62541 SOURCE_SIM_OPCUA_CLIENT_BACKEND=open62541 SOURCE_SIM_PROFILE_SCHEDULER_MODE=source_polling_scheduler SOURCE_SIM_PROFILE_SCHEDULER_IMPL=absolute_direct SOURCE_SIM_PROFILE_SCHEDULER_CALLBACK_MODE=disabled SOURCE_SIM_PROFILE_PRINT_SCHEDULER_STRUCTURE=false SOURCE_SIM_PROFILE_PRINT_TASK_CREATION=false SOURCE_SIM_LOAD_PROCESS_COUNT=1 SOURCE_SIM_LOAD_COROUTINES_PER_PROCESS=0 SOURCE_SIM_LOAD_SERVER_COUNT=10 SOURCE_SIM_LOAD_TARGET_HZ=10 SOURCE_SIM_LOAD_LEVEL_DURATION_S=30 SOURCE_SIM_LOAD_WARMUP_S=10 SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false SOURCE_SIM_LOAD_MAX_CONCURRENT_READS=16 SOURCE_SIM_LOAD_PERIOD_MAX_TOLERANCE_RATIO=0.2 SOURCE_SIM_LOAD_PERIOD_MEAN_ERROR_RATIO=0.05 SOURCE_SIM_LOAD_TOP_GAP_COUNT=10 SOURCE_SIM_PROFILE_SHOW_ALL=false SOURCE_SIM_PROFILE_MAX_LINES=80 SOURCE_SIM_FLEET_STARTUP_TIMEOUT_S=30 SOURCE_SIM_PORT_START=47500 SOURCE_SIM_PORT_END=65000 python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_profile.py -s -v`
- profile_summary: `status=FAIL`; 指标形态与既有失败一致，尖刺集中在 sleep wake lag，而非 operation/runner/pipe。
- period_max_ms: `144.0`
- period_mean_ms: `99.99`
- max_sleep_wake_lag_ms: `43.8`
- operation_ms range: `1.3..3.6`
- runner_read_ms range: `0.8..2.1`
- pipe_back_ms range: `0.2..1.4`
- pass/fail: `FAIL`
- conclusion: 直接去掉 `_run_job/_execute_job/_run_operation` 链路仍未消除 30~40ms 级晚醒尖刺，单纯在 `SourcePollingScheduler` 内塞一个 direct path 不是足够解法。
- whether kept or reverted: `kept temporarily for comparison; not best-so-far`

## Experiment B

- experiment_id: `B_high_frequency_fixed_rate`
- hypothesis: 与其继续改通用 `SourcePollingScheduler`，不如用专用高频 fixed-rate scheduler 直接复现 absolute scheduler 结构。
- files_changed: `src/whale/shared/source/scheduling/fixed_rate.py`, `src/whale/shared/source/scheduling/__init__.py`, `tools/source_lab/tests/test_source_simulation_multi_server_profile.py`, `tests/unit/test_source_scheduling.py`
- implementation_summary: 新增 `HighFrequencyFixedRateScheduler`，profile 模式切到 `SOURCE_SIM_PROFILE_SCHEDULER_MODE=high_frequency_fixed_rate`，每个 reader 一个 direct absolute loop task，事件结构复用 `PollingResultEvent`/`PollingErrorEvent`。
- test_command: `python -m py_compile src/whale/shared/source/scheduling/polling.py src/whale/shared/source/scheduling/fixed_rate.py src/whale/shared/source/scheduling/__init__.py tools/source_lab/tests/test_source_simulation_multi_server_profile.py tests/unit/test_source_scheduling.py && python -m pytest tests/unit/test_source_scheduling.py -q && SOURCE_SIM_OPCUA_BACKEND=open62541 SOURCE_SIM_OPCUA_CLIENT_BACKEND=open62541 SOURCE_SIM_PROFILE_SCHEDULER_MODE=high_frequency_fixed_rate SOURCE_SIM_PROFILE_SCHEDULER_CALLBACK_MODE=disabled SOURCE_SIM_PROFILE_PRINT_SCHEDULER_STRUCTURE=false SOURCE_SIM_PROFILE_PRINT_TASK_CREATION=false SOURCE_SIM_LOAD_PROCESS_COUNT=1 SOURCE_SIM_LOAD_COROUTINES_PER_PROCESS=0 SOURCE_SIM_LOAD_SERVER_COUNT=10 SOURCE_SIM_LOAD_TARGET_HZ=10 SOURCE_SIM_LOAD_LEVEL_DURATION_S=30 SOURCE_SIM_LOAD_WARMUP_S=10 SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false SOURCE_SIM_LOAD_MAX_CONCURRENT_READS=16 SOURCE_SIM_LOAD_PERIOD_MAX_TOLERANCE_RATIO=0.2 SOURCE_SIM_LOAD_PERIOD_MEAN_ERROR_RATIO=0.05 SOURCE_SIM_LOAD_TOP_GAP_COUNT=10 SOURCE_SIM_PROFILE_SHOW_ALL=false SOURCE_SIM_PROFILE_MAX_LINES=80 SOURCE_SIM_FLEET_STARTUP_TIMEOUT_S=30 SOURCE_SIM_PORT_START=47600 SOURCE_SIM_PORT_END=65000 python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_profile.py -s -v`
- profile_summary: `status=FAIL`; 相比 A 有改善，但 30ms 级 sleep wake lag 仍在，说明“专用 scheduler”本身还不够。
- period_max_ms: `136.0`
- period_mean_ms: `99.99`
- max_sleep_wake_lag_ms: `37.9`
- operation_ms range: `1.3..3.6`
- runner_read_ms range: `0.7..1.9`
- pipe_back_ms range: `0.2..0.7`
- pass/fail: `FAIL`
- conclusion: 把通用抽象替换成专用 fixed-rate scheduler 能降低最坏周期，但没有跨过 120ms，说明单纯“一 reader 一 task 的 absolute loop”仍有抖动源。
- whether kept or reverted: `kept as diagnostic profile-only scheduler`

## Experiment C

- experiment_id: `C_high_frequency_central_ticker`
- hypothesis: 10 个独立 `asyncio.sleep()` polling task 存在唤醒公平性问题，改为一个 central ticker 统一按到期顺序发车可能更稳。
- files_changed: `tools/source_lab/tests/test_source_simulation_multi_server_profile.py`
- implementation_summary: 新增 `SOURCE_SIM_PROFILE_SCHEDULER_MODE=high_frequency_central_ticker`，单一 ticker task 维护所有 reader 的下一次 `scheduled_at`，到点后 `create_task` 执行 read，limiter 继续生效。
- test_command: `python -m py_compile src/whale/shared/source/scheduling/polling.py src/whale/shared/source/scheduling/fixed_rate.py src/whale/shared/source/scheduling/__init__.py tools/source_lab/tests/test_source_simulation_multi_server_profile.py tests/unit/test_source_scheduling.py && python -m pytest tests/unit/test_source_scheduling.py -q && SOURCE_SIM_OPCUA_BACKEND=open62541 SOURCE_SIM_OPCUA_CLIENT_BACKEND=open62541 SOURCE_SIM_PROFILE_SCHEDULER_MODE=high_frequency_central_ticker SOURCE_SIM_PROFILE_SCHEDULER_CALLBACK_MODE=disabled SOURCE_SIM_PROFILE_PRINT_SCHEDULER_STRUCTURE=false SOURCE_SIM_PROFILE_PRINT_TASK_CREATION=false SOURCE_SIM_LOAD_PROCESS_COUNT=1 SOURCE_SIM_LOAD_COROUTINES_PER_PROCESS=0 SOURCE_SIM_LOAD_SERVER_COUNT=10 SOURCE_SIM_LOAD_TARGET_HZ=10 SOURCE_SIM_LOAD_LEVEL_DURATION_S=30 SOURCE_SIM_LOAD_WARMUP_S=10 SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false SOURCE_SIM_LOAD_MAX_CONCURRENT_READS=16 SOURCE_SIM_LOAD_PERIOD_MAX_TOLERANCE_RATIO=0.2 SOURCE_SIM_LOAD_PERIOD_MEAN_ERROR_RATIO=0.05 SOURCE_SIM_LOAD_TOP_GAP_COUNT=10 SOURCE_SIM_PROFILE_SHOW_ALL=false SOURCE_SIM_PROFILE_MAX_LINES=80 SOURCE_SIM_FLEET_STARTUP_TIMEOUT_S=30 SOURCE_SIM_PORT_START=47700 SOURCE_SIM_PORT_END=65000 python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_profile.py -s -v`
- profile_summary: `status=FAIL`; 这是当前 `period_max_ms` 最低的正式 profile，但仍有 35ms 级晚醒/晚发车尖刺。
- period_max_ms: `134.0`
- period_mean_ms: `99.85`
- max_sleep_wake_lag_ms: `35.5`
- operation_ms range: `1.4..3.3`
- runner_read_ms range: `1.6..1.9`
- pipe_back_ms range: `0.2..1.0`
- pass/fail: `FAIL`
- conclusion: 多 task 唤醒公平性确实是部分因素，central ticker 比 A/B/F 都更好，但仍无法把尖刺压进 120ms 验收线。
- whether kept or reverted: `best_so_far by period_max_ms; kept`

## Experiment D

- experiment_id: `D_high_frequency_coarse_sleep_spin`
- hypothesis: 默认 `asyncio.sleep()` 在 10ms 粒度会偶发晚醒，先粗睡后 `await asyncio.sleep(0)` 微调可能减少 oversleep。
- files_changed: `tools/source_lab/tests/test_source_simulation_multi_server_profile.py`
- implementation_summary: 新增 `SOURCE_SIM_PROFILE_SCHEDULER_MODE=high_frequency_coarse_sleep_spin`，在 absolute loop 中改成 “`sleep(remaining - 1ms)` + yield-until-target” 等待策略。
- test_command: `python -m py_compile src/whale/shared/source/scheduling/polling.py src/whale/shared/source/scheduling/fixed_rate.py src/whale/shared/source/scheduling/__init__.py tools/source_lab/tests/test_source_simulation_multi_server_profile.py tests/unit/test_source_scheduling.py && python -m pytest tests/unit/test_source_scheduling.py -q && SOURCE_SIM_OPCUA_BACKEND=open62541 SOURCE_SIM_OPCUA_CLIENT_BACKEND=open62541 SOURCE_SIM_PROFILE_SCHEDULER_MODE=high_frequency_coarse_sleep_spin SOURCE_SIM_PROFILE_SCHEDULER_CALLBACK_MODE=disabled SOURCE_SIM_PROFILE_PRINT_SCHEDULER_STRUCTURE=false SOURCE_SIM_PROFILE_PRINT_TASK_CREATION=false SOURCE_SIM_LOAD_PROCESS_COUNT=1 SOURCE_SIM_LOAD_COROUTINES_PER_PROCESS=0 SOURCE_SIM_LOAD_SERVER_COUNT=10 SOURCE_SIM_LOAD_TARGET_HZ=10 SOURCE_SIM_LOAD_LEVEL_DURATION_S=30 SOURCE_SIM_LOAD_WARMUP_S=10 SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false SOURCE_SIM_LOAD_MAX_CONCURRENT_READS=16 SOURCE_SIM_LOAD_PERIOD_MAX_TOLERANCE_RATIO=0.2 SOURCE_SIM_LOAD_PERIOD_MEAN_ERROR_RATIO=0.05 SOURCE_SIM_LOAD_TOP_GAP_COUNT=10 SOURCE_SIM_PROFILE_SHOW_ALL=false SOURCE_SIM_PROFILE_MAX_LINES=80 SOURCE_SIM_FLEET_STARTUP_TIMEOUT_S=30 SOURCE_SIM_PORT_START=47800 SOURCE_SIM_PORT_END=65000 python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_profile.py -s -v`
- profile_summary: `status=FAIL`; sleep wake 尖刺基本被压平，但最坏周期仍是 135ms。
- period_max_ms: `135.0`
- period_mean_ms: `99.96`
- max_sleep_wake_lag_ms: `35.6` for the worst gap row, but most top gaps dropped to `0.0..5.8ms`
- operation_ms range: `1.3..9.1`
- runner_read_ms range: `0.6..3.8`
- pipe_back_ms range: `0.2..1.6`
- pass/fail: `FAIL`
- conclusion: 这轮最关键的定位价值最高。单纯消掉 sleep oversleep 后，最坏周期几乎不降，说明剩余 135ms 尖刺并不主要来自 scheduler sleep 精度。
- whether kept or reverted: `kept as strongest localization evidence`

## Experiment E

- experiment_id: `E_uvloop_diagnostic`
- hypothesis: 默认 asyncio event loop 精度不足，`uvloop` 可能改善 wake lag。
- files_changed: `tools/source_lab/tests/test_source_simulation_multi_server_profile.py`
- implementation_summary: 新增 `SOURCE_SIM_PROFILE_USE_UVLOOP=true` 时的可选 `uvloop.install()`；若未安装则打印跳过信息，不作为失败。
- test_command: `python -m py_compile src/whale/shared/source/scheduling/polling.py src/whale/shared/source/scheduling/fixed_rate.py src/whale/shared/source/scheduling/__init__.py tools/source_lab/tests/test_source_simulation_multi_server_profile.py tests/unit/test_source_scheduling.py && python -m pytest tests/unit/test_source_scheduling.py -q && python - <<'PY'\nimport importlib.util\nprint('installed' if importlib.util.find_spec('uvloop') else 'missing')\nPY`
- profile_summary: `uvloop not installed in current environment`
- period_max_ms: `n/a`
- period_mean_ms: `n/a`
- max_sleep_wake_lag_ms: `n/a`
- operation_ms range: `n/a`
- runner_read_ms range: `n/a`
- pipe_back_ms range: `n/a`
- pass/fail: `SKIPPED`
- conclusion: 当前环境无法完成 uvloop 对照，因此没有证据支持“仅换 event loop 实现即可过线”。
- whether kept or reverted: `kept as optional diagnostic hook`

## Experiment F

- experiment_id: `F_high_frequency_grouped_reader_loop`
- hypothesis: 10 个 reader 分成少量 group task，可能比单 ticker 或每 reader 一个 task 更稳。
- files_changed: `tools/source_lab/tests/test_source_simulation_multi_server_profile.py`
- implementation_summary: 新增 `SOURCE_SIM_PROFILE_SCHEDULER_MODE=high_frequency_grouped_reader_loop` 与 `SOURCE_SIM_PROFILE_SCHEDULER_GROUP_COUNT=2`，每个 group task 内部按到期顺序触发本组 reader 的 read task。
- test_command: `python -m py_compile src/whale/shared/source/scheduling/polling.py src/whale/shared/source/scheduling/fixed_rate.py src/whale/shared/source/scheduling/__init__.py tools/source_lab/tests/test_source_simulation_multi_server_profile.py tests/unit/test_source_scheduling.py && python -m pytest tests/unit/test_source_scheduling.py -q && SOURCE_SIM_OPCUA_BACKEND=open62541 SOURCE_SIM_OPCUA_CLIENT_BACKEND=open62541 SOURCE_SIM_PROFILE_SCHEDULER_MODE=high_frequency_grouped_reader_loop SOURCE_SIM_PROFILE_SCHEDULER_CALLBACK_MODE=disabled SOURCE_SIM_PROFILE_PRINT_SCHEDULER_STRUCTURE=false SOURCE_SIM_PROFILE_PRINT_TASK_CREATION=false SOURCE_SIM_PROFILE_SCHEDULER_GROUP_COUNT=2 SOURCE_SIM_LOAD_PROCESS_COUNT=1 SOURCE_SIM_LOAD_COROUTINES_PER_PROCESS=0 SOURCE_SIM_LOAD_SERVER_COUNT=10 SOURCE_SIM_LOAD_TARGET_HZ=10 SOURCE_SIM_LOAD_LEVEL_DURATION_S=30 SOURCE_SIM_LOAD_WARMUP_S=10 SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false SOURCE_SIM_LOAD_MAX_CONCURRENT_READS=16 SOURCE_SIM_LOAD_PERIOD_MAX_TOLERANCE_RATIO=0.2 SOURCE_SIM_LOAD_PERIOD_MEAN_ERROR_RATIO=0.05 SOURCE_SIM_LOAD_TOP_GAP_COUNT=10 SOURCE_SIM_PROFILE_SHOW_ALL=false SOURCE_SIM_PROFILE_MAX_LINES=80 SOURCE_SIM_FLEET_STARTUP_TIMEOUT_S=30 SOURCE_SIM_PORT_START=47900 SOURCE_SIM_PORT_END=65000 python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_profile.py -s -v`
- profile_summary: `status=FAIL`; grouping 没有优于 central ticker。
- period_max_ms: `137.0`
- period_mean_ms: `99.83`
- max_sleep_wake_lag_ms: `37.2`
- operation_ms range: `1.5..2.6`
- runner_read_ms range: `0.8..1.7`
- pipe_back_ms range: `0.1..0.8`
- pass/fail: `FAIL`
- conclusion: 把 10 个 reader 收敛到 2 个 group task 不能优于单 ticker，说明“减少 task 数”本身不是决定性变量。
- whether kept or reverted: `kept as profile-only diagnostic mode`

## Period decomposition after scheduler matrix

Note:
- 当前仓库正式 profile 的实际入口变量是 `SOURCE_SIM_PROFILE_SCHEDULER_MODE`。
- 因此本轮没有使用示例中的 `SOURCE_SIM_PROFILE_SCHEDULER_IMPL=central_ticker/coarse_sleep_spin`，而是分别使用：
  - `SOURCE_SIM_PROFILE_SCHEDULER_MODE=high_frequency_central_ticker`
  - `SOURCE_SIM_PROFILE_SCHEDULER_MODE=high_frequency_coarse_sleep_spin`

### central_ticker

- command: `SOURCE_SIM_OPCUA_BACKEND=open62541 SOURCE_SIM_OPCUA_CLIENT_BACKEND=open62541 SOURCE_SIM_PROFILE_SCHEDULER_MODE=high_frequency_central_ticker SOURCE_SIM_PROFILE_PRINT_SCHEDULER_STRUCTURE=false SOURCE_SIM_PROFILE_PRINT_TASK_CREATION=false SOURCE_SIM_LOAD_PROCESS_COUNT=1 SOURCE_SIM_LOAD_COROUTINES_PER_PROCESS=0 SOURCE_SIM_LOAD_SERVER_COUNT=10 SOURCE_SIM_LOAD_TARGET_HZ=10 SOURCE_SIM_LOAD_LEVEL_DURATION_S=30 SOURCE_SIM_LOAD_WARMUP_S=10 SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false SOURCE_SIM_LOAD_MAX_CONCURRENT_READS=16 SOURCE_SIM_LOAD_PERIOD_MAX_TOLERANCE_RATIO=0.2 SOURCE_SIM_LOAD_PERIOD_MEAN_ERROR_RATIO=0.05 SOURCE_SIM_LOAD_TOP_GAP_COUNT=10 SOURCE_SIM_PROFILE_SHOW_ALL=false SOURCE_SIM_PROFILE_MAX_LINES=80 SOURCE_SIM_FLEET_STARTUP_TIMEOUT_S=30 SOURCE_SIM_PORT_START=48200 SOURCE_SIM_PORT_END=65000 python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_profile.py -s -v`
- period_max_ms: `135.0`
- max_cmd_period_ms: `134.5`
- max_stdout_period_ms: `134.8`
- max_runner_request_period_ms: `134.5`
- max_runner_response_write_period_ms: `134.4`
- max_finish_period_ms: `134.8`
- max_response_period_ms: `135.0`
- max_response_vs_cmd_delta_ms: `2.1`
- max_response_vs_finish_delta_ms: `0.8`
- gap_classification_summary:
  - `command_schedule_spike=0`
  - `python_receive_spike=0`
  - `runner_request_spike=0`
  - `runner_response_write_spike=0`
  - `response_timestamp_only_spike=0`
  - `mixed_spike=2`
  - `unknown=8`
- conclusion: 最坏 top gaps 不是 response timestamp 单独异常，而是 `cmd/stdout/runner_request/runner_response_write/finish/response` 周期一起落在 `123~135ms`。这属于 `mixed_spike`，说明 central_ticker 下确实发生了真实发起与完成周期一起变长。

### coarse_sleep_spin

- command: `SOURCE_SIM_OPCUA_BACKEND=open62541 SOURCE_SIM_OPCUA_CLIENT_BACKEND=open62541 SOURCE_SIM_PROFILE_SCHEDULER_MODE=high_frequency_coarse_sleep_spin SOURCE_SIM_PROFILE_PRINT_SCHEDULER_STRUCTURE=false SOURCE_SIM_PROFILE_PRINT_TASK_CREATION=false SOURCE_SIM_LOAD_PROCESS_COUNT=1 SOURCE_SIM_LOAD_COROUTINES_PER_PROCESS=0 SOURCE_SIM_LOAD_SERVER_COUNT=10 SOURCE_SIM_LOAD_TARGET_HZ=10 SOURCE_SIM_LOAD_LEVEL_DURATION_S=30 SOURCE_SIM_LOAD_WARMUP_S=10 SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false SOURCE_SIM_LOAD_MAX_CONCURRENT_READS=16 SOURCE_SIM_LOAD_PERIOD_MAX_TOLERANCE_RATIO=0.2 SOURCE_SIM_LOAD_PERIOD_MEAN_ERROR_RATIO=0.05 SOURCE_SIM_LOAD_TOP_GAP_COUNT=10 SOURCE_SIM_PROFILE_SHOW_ALL=false SOURCE_SIM_PROFILE_MAX_LINES=80 SOURCE_SIM_FLEET_STARTUP_TIMEOUT_S=30 SOURCE_SIM_PORT_START=48300 SOURCE_SIM_PORT_END=65000 python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_profile.py -s -v`
- period_max_ms: `102.0`
- max_cmd_period_ms: `100.3`
- max_stdout_period_ms: `103.3`
- max_runner_request_period_ms: `100.3`
- max_runner_response_write_period_ms: `102.5`
- max_finish_period_ms: `103.8`
- max_response_period_ms: `102.0`
- max_response_vs_cmd_delta_ms: `2.0`
- max_response_vs_finish_delta_ms: `0.7`
- gap_classification_summary:
  - `command_schedule_spike=0`
  - `python_receive_spike=0`
  - `runner_request_spike=0`
  - `runner_response_write_spike=0`
  - `response_timestamp_only_spike=0`
  - `mixed_spike=0`
  - `unknown=10`
- conclusion: 在 coarse_sleep_spin 这轮里，没有任何 top gap 触发 `>=120ms` 分类条件；所有周期分层字段都重新回到约 `100~104ms`。这说明 response timestamp 不是单独的虚假坏指标，链路整体确实恢复稳定了。

### Final judgment

- `period_max_ms≈134~135` 的主因不是 `response_timestamp_only_spike`。在 `central_ticker` 失败样本中，真实 `cmd/stdout/runner request/runner response write/finish` 周期和 `response_timestamp` 周期一起变长。
- 因此当前没有证据支持“应该仅因为 response_timestamp period 而调整 PASS 判据”。
- 继续做新的 scheduler 大矩阵没有必要，但继续围绕 wake 精度和 high-frequency wait 策略做小范围验证仍然有价值，因为 `coarse_sleep_spin` 这轮已经在正式 profile 下达到 `PASS`。
- `central_ticker` 仍是上一轮失败矩阵中的 best-so-far 结构候选；但按本轮正式分解结果，`coarse_sleep_spin` 已经成为当前最强结果样本，并且它表明 scheduler 侧相位控制仍然会决定是否出现全链路 `mixed_spike`。

## Final stabilization: high_frequency_coarse_sleep_spin

### Background summary

- `high_frequency_central_ticker` failed with `classification=mixed_spike`.
- The failing top gaps showed `cmd/stdout/runner_request/runner_response_write/finish/response` periods stretching together, so `response_timestamp period` is not a false-positive acceptance signal.
- There is still no evidence supporting a weaker PASS rule that discounts `response_timestamp period`.
- `high_frequency_coarse_sleep_spin` remains the only mode that has demonstrated repeated PASS results in this open62541 high-frequency profile, but the 3-run stabilization replay below shows it is not yet perfectly stable.

### Stability reruns

| run | port_start | scheduler_mode | callback_mode | status | period_max_ms | period_mean_ms | max_cmd_period_ms | max_finish_period_ms | max_response_period_ms | classification_summary |
|---|---:|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 48600 | `high_frequency_coarse_sleep_spin` | `disabled` | `FAIL` | 132.0 | 99.85 | 132.6 | 131.9 | 132.0 | `mixed_spike=2, unknown=8` |
| 2 | 48700 | `high_frequency_coarse_sleep_spin` | `disabled` | `PASS` | 102.0 | 99.99 | 100.5 | 103.0 | 102.0 | `unknown=10` |
| 3 | 48800 | `high_frequency_coarse_sleep_spin` | `disabled` | `PASS` | 102.0 | 99.92 | 100.4 | 101.8 | 102.0 | `unknown=10` |

### Failure sample details

- run: `1`
- status: `FAIL`
- period_max_ms: `132.0`
- cmd_period_ms: `132.6`
- stdout_period_ms: `131.9`
- runner_request_period_ms: `132.6`
- runner_response_write_period_ms: `131.8`
- finish_period_ms: `131.9`
- response_period_ms: `132.0`
- classification: `mixed_spike`
- conclusion: this is still a real synchronized timing expansion rather than `response_timestamp_only_spike`

### Final conclusion

- `high_frequency_coarse_sleep_spin` is the current best scheduler mode for this open62541 high-frequency profile, but it is **not yet stable enough to declare fully validated** under the requested 3-run replay because run 1 failed.
- `high_frequency_coarse_sleep_spin` remains the preferred acceptance candidate for `10 server x 10Hz x 416-point` profile/capacity validation, because the two passing reruns stayed near `100..103ms` across `cmd/finish/response` periods.
- `SourcePollingScheduler` remains the general-purpose baseline but is not suitable for this high-frequency `pmax` target without the coarse sleep plus yield strategy.
- No evidence supports weakening the `response_timestamp period` criterion.

### Risk notes

- `high_frequency_coarse_sleep_spin` uses coarse sleep plus `asyncio.sleep(0)` yield trimming and should still be treated as a high-frequency profile/capacity-specific strategy.
- The 3-run replay shows residual occasional instability: one run still produced a `130ms`-class `mixed_spike`.
- Before promoting this strategy into a production runtime decision, it still needs evaluation across CPU ratio, higher `server_count`, different `Hz`, and different OS/event loop combinations.
- Current evidence only covers `open62541 simulator + open62541 client + 10 server x 10Hz` in this repository environment.

### Retained mode guidance

- acceptance-oriented modes:
  - `source_polling_scheduler`
  - `high_frequency_coarse_sleep_spin`
- diagnostic-only modes. Do not use as acceptance mode:
  - `absolute`
  - `high_frequency_fixed_rate`
  - `high_frequency_central_ticker`
  - `high_frequency_grouped_reader_loop`

## Optional uvloop comparison

- implementation:
  - added `SOURCE_SIM_PROFILE_USE_UVLOOP=true|false`
  - when `true`, `uvloop.install()` runs before any `asyncio.run(...)`
  - when `uvloop` is not installed, the profile test now does `pytest.skip("uvloop is not installed")`
  - metrics output now includes `use_uvloop=True|False`

| run | port_start | use_uvloop | scheduler_mode | callback_mode | status | period_max_ms | period_mean_ms | max_cmd_period_ms | max_finish_period_ms | max_response_period_ms |
|---|---:|---|---|---|---|---:|---:|---:|---:|---:|
| 1 | 50100 | `True` | `high_frequency_coarse_sleep_spin` | `disabled` | `FAIL` | 144.0 | 99.89 | 144.1 | 144.9 | 144.0 |
| 2 | 50200 | `True` | `high_frequency_coarse_sleep_spin` | `disabled` | `PASS` | 102.0 | 99.96 | 101.1 | 104.3 | 102.0 |
| 3 | 50300 | `True` | `high_frequency_coarse_sleep_spin` | `disabled` | `PASS` | 103.0 | 99.94 | 101.1 | 103.1 | 103.0 |

- run 1 classification summary: `mixed_spike=3, unknown=7`
- run 2 classification summary: `unknown=10`
- run 3 classification summary: `unknown=10`

- conclusion:
  - `uvloop` is not a reliable improvement in this profile.
  - It produced one clear regression back to the `130ms+ mixed_spike` failure shape.
  - Because default asyncio already has repeated passing samples for `high_frequency_coarse_sleep_spin`, `uvloop` should remain optional diagnostic tooling only.
  - Recommendation: do not enable `uvloop` by default for this high-frequency profile. Keep default asyncio as the validated baseline.

## C runner internal polling

### Why this was added

- `uvloop` remained unstable in repeated replay and is not suitable as the default answer.
- Python-side scheduler tuning reached diminishing returns; the remaining failures were `mixed_spike` tails rather than pure callback or limiter cost.
- The new runner-internal polling path removes the per-tick Python `READ` command and lets fixed-rate scheduling happen beside the open62541 client read itself.

### Protocol summary

- `START_POLL<TAB>plan_id<TAB>target_hz<TAB>warmup_s<TAB>duration_s`
- `POLL_STARTED<TAB>plan_id<TAB>target_hz<TAB>warmup_s<TAB>duration_s`
- `RESULT_STREAM<TAB>plan_id<TAB>seq<TAB>OK|ERROR<TAB>value_count<TAB>response_timestamp_ms<TAB>detail<TAB>scheduled_ts_ns<TAB>read_start_ts_ns<TAB>read_end_ts_ns<TAB>response_write_ts_ns`
- `POLL_DONE<TAB>plan_id<TAB>total_ticks<TAB>ok_count<TAB>error_count`
- `STOP_POLL<TAB>plan_id` is also supported for cleanup and early stop.

### Three-run profile replay

| run | port_start | mode | status | period_max_ms | period_mean_ms | max_c_scheduled_period_ms | max_c_response_write_period_ms | max_py_stdout_period_ms | max_response_period_ms | classification_summary |
|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 51000 | `open62541_runner_poll` | `PASS` | 107.0 | 100.00 | 100.0 | 107.3 | 108.2 | 107.0 | `unknown=10` |
| 2 | 51100 | `open62541_runner_poll` | `PASS` | 106.0 | 99.99 | 100.0 | 106.7 | 108.2 | 106.0 | `unknown=10` |
| 3 | 51200 | `open62541_runner_poll` | `PASS` | 107.0 | 100.00 | 100.0 | 106.9 | 107.2 | 107.0 | `unknown=10` |

### Final conclusion

- The runner-internal polling mode is better than `high_frequency_coarse_sleep_spin` for validation stability: the Python scheduler path had a better best-case `period_max_ms≈102`, but it failed 1 of 3 replay runs, while `open62541_runner_poll` passed all 3 runs cleanly.
- `open62541_runner_poll` should be treated as the next validated high-frequency profile/capacity mode for `open62541 simulator + open62541 client + 10 server x 10Hz`.
- Process sharding is not required for this specific replay shape yet. `pipe_back_ms` stayed low and the new decomposition shows the C-side schedule is stable at `~100ms`.
- If later higher server counts still fail, the next question is no longer “which Python scheduler mode?” but “how far one process can scale once polling is already inside the runner.”

## Final validated mode: open62541_runner_poll

### Background

- The Python scheduler path has been explored enough for this scenario:
  - `source_polling_scheduler` is the original baseline but not stable enough for the target tail-latency line.
  - `high_frequency_coarse_sleep_spin` is the Python-layer best-effort fallback.
  - `uvloop` remains unstable and is not recommended as a default.
- The C runner internal polling path removes the per-tick Python timer plus stdin `READ` command layer and executes fixed-rate polling beside the open62541 client read itself.

### Protocol

- `START_POLL<TAB>plan_id<TAB>target_hz<TAB>warmup_s<TAB>duration_s`
- `POLL_STARTED<TAB>plan_id<TAB>target_hz<TAB>warmup_s<TAB>duration_s`
- `RESULT_STREAM<TAB>plan_id<TAB>seq<TAB>OK|ERROR<TAB>value_count<TAB>response_timestamp_ms<TAB>detail<TAB>scheduled_ts_ns<TAB>read_start_ts_ns<TAB>read_end_ts_ns<TAB>response_write_ts_ns`
- `STOP_POLL<TAB>plan_id`
- `POLL_STOPPED<TAB>plan_id<TAB>total_ticks<TAB>ok_count<TAB>error_count`
- `POLL_DONE<TAB>plan_id<TAB>total_ticks<TAB>ok_count<TAB>error_count`

### Three formal validation runs

| run | port_start | scheduler_mode | status | period_max_ms | period_mean_abs_error_ms | batch_mismatches | read_errors | missing_response_timestamps | max_c_scheduled_period_ms | max_c_response_write_period_ms | max_py_stdout_period_ms | max_response_period_ms |
|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 51300 | `open62541_runner_poll` | `PASS` | 106.0 | 0.01 | 0 | 0 | 0 | 100.0 | 105.4 | 105.3 | 106.0 |
| 2 | 51400 | `open62541_runner_poll` | `PASS` | 103.0 | 0.01 | 0 | 0 | 0 | 100.0 | 104.0 | 106.2 | 103.0 |
| 3 | 51500 | `open62541_runner_poll` | `PASS` | 102.0 | 0.01 | 0 | 0 | 0 | 100.0 | 103.7 | 104.0 | 102.0 |

### Final conclusion

- `open62541_runner_poll` is the validated high-frequency profile mode for the current `10 server x 10Hz x 416-point` open62541 simulator/client scenario.
- It is more architecturally robust than Python-side scheduler variants because fixed-rate polling is executed inside the C runner.
- `high_frequency_coarse_sleep_spin` remains a Python-layer best-effort fallback, not the final preferred mode.
- `uvloop` remains diagnostic-only and should not be enabled by default.
- No evidence supports weakening the `response_timestamp period` criterion.
- The `STOP_POLL` cancellation path is now covered by unit tests, including early close with `POLL_STOPPED`, natural `POLL_DONE` completion, and early close that receives `POLL_DONE` instead of `POLL_STOPPED`.

### Remaining risks

- This remains a profile/capacity-only mode and is not the production reader default.
- Higher `server_count` or higher `target_hz` still require separate validation.
- Process sharding remains the next scaling direction once one-process limits are reached.
- The open62541 raw polling backend still does not provide full Batch metadata parity.
