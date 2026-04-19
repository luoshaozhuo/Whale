你现在在 Whale 仓库上做一次增量开发。请直接修改代码并补充测试，不要只给方案。

# 任务目标

在不破坏现有 scenario1 主链路的前提下，新增一个放在 `tools/` 下的 OPC UA 仿真工具集，用于：

1. 读取 scenario1 的 SCD 文件作为元数据输入；
2. 基于 SCD 解析结果启动两台风机 OPC UA 仿真服务器；
3. 每台风机对应一个独立 OPC UA server 实例和独立 endpoint；
4. 服务器周期性刷新点位值；
5. pytest 可通过 fixture 启停这些 server；
6. 设计上为后续扩展激光雷达、测风塔等设备预留插件机制；
7. 暂不要求把现有 pipeline 全量切换到 OPC UA collector；
8. 在 `tools/` 下预留 `SCD -> OPC` 转换入口骨架，但本轮不实现完整 NodeSet 编译。

# 现有基线

请先阅读并遵守以下现状：

- 当前仓库是 scenario1 单场景最小闭环，不是通用平台。
- 当前主链路是：
  `SCL 注册表 -> mock OPC UA 原始批次 -> ODS -> 标准化 -> 清洗 -> DWD -> DWS -> ADS`
- 本轮目标只是先把“真实模拟 OPC UA server”建起来，为后续 E2E 切换做准备。
- 不做平台化扩张：不引入 Kafka、HA、分布式、watermark、监控告警、多场景调度等。
- 代码与测试组织必须服从仓库现有 testing policy、pyproject、pytest 结构。

# 开始前必须先阅读的文件

请先阅读这些文件，再开始实现：

- `docs/scenario1/方案001.md`
- `docs/scenario1/prompt001`
- 当前 scenario1 使用的 SCD 文件
- `src/whale/scenario1/scl_registry.py`
- `src/whale/scenario1/pipeline.py`
- `src/whale/scenario1/collector.py`（如果存在）
- `tests/e2e/scenario1/test_scenario1_e2e.py`
- 仓库中的 testing policy / rules 文件
- `pyproject.toml`
- `tests/fixtures/` 现有结构

# 本轮必须完成的实现

## 1. 在 `tools/` 下新增 OPC UA 仿真工具

允许你根据仓库风格微调命名，但职责必须等价，建议结构如下：

tools/
└── opcua_sim/
    ├── __init__.py
    ├── models.py
    ├── scd_loader.py
    ├── address_space_builder.py
    ├── value_generators.py
    ├── server_runtime.py
    ├── fleet_runtime.py
    ├── cli.py
    ├── device_plugins/
    │   ├── __init__.py
    │   ├── base.py
    │   └── wind_turbine.py

要求：
- `models.py`：定义仿真内部模型，不污染业务模型
- `scd_loader.py`：从 SCD 解析设备与信号定义
- `address_space_builder.py`：把设备定义映射成 OPC UA 地址空间
- `value_generators.py`：生成模拟值
- `server_runtime.py`：单台 server 生命周期
- `fleet_runtime.py`：同时管理两台及以上 server
- `device_plugins/base.py`：设备插件基类或协议
- `device_plugins/wind_turbine.py`：风机插件
- `cli.py`：本地手工启动入口

## 2. SCD 解析要求

实现最小可用的 SCD 解析能力，输出内部元模型，至少支持：

- 识别两台风机设备
- 识别每台设备的 host / port / device_id / device_type
- 识别最小信号子集并转成可用于建 OPC UA 节点的定义
- 当前先支持风机，后续设备类型可扩展
- 如果现有 `src/whale/scenario1/scl_registry.py` 可复用，请优先复用；如不适合，可包装或少量抽取公共能力，但不要为此大规模重构业务代码

## 3. OPC UA server 要求

必须实现：
- 两台风机 -> 两台独立 OPC UA server
- 每台 server 独立 endpoint / port
- 默认能在 localhost 启动
- 点位以清晰分层 browse path 暴露，不要全部扁平化
- server 启动后，变量值会周期性刷新
- stop 后能正确释放端口，测试不会残留僵尸进程

## 4. 扩展机制要求

必须有设备插件机制，不允许把实现写死成只支持风机。

至少做到：
- 有 `DevicePlugin` 基类/协议
- 当前实现 `WindTurbineDevicePlugin`
- 地址空间构建逻辑依赖设备定义和插件，而不是风机硬编码
- 后续可扩展激光雷达、测风塔，而不需要重写整个仿真框架

## 5. CLI 要求

提供本地启动入口，至少支持：
- 指定 SCD 路径
- 按 SCD 启动全部设备
- 可指定 host/port 起始值
- 可指定刷新周期
- 启动后打印每台 server 的 endpoint

目标效果类似：
- `python -m tools.opcua_sim.cli --scd <path>`
- 输出：
  - `WTG_01 -> opc.tcp://127.0.0.1:4840/...`
  - `WTG_02 -> opc.tcp://127.0.0.1:4841/...`

## 6. 测试要求

请新增或修改测试，至少覆盖：

### unit
- SCD 可解析出两台风机
- 信号定义可转为内部元模型
- value generator 在 deterministic 模式下可预测
- 风机插件可正常工作

### integration
- 可启动单台 OPC UA server 并读到节点
- 可同时启动两台 server 并分别读到节点

### fixture
- 提供 pytest fixture 用于启动/停止 server 集群
- 后续 E2E 测试可直接复用这个 fixture

本轮不强制把现有完整 pipeline E2E 切到 OPC UA 输入，但至少要把“测试前启动真实模拟 server”这层基础设施做完整。

# 依赖要求

- 选择合适的 Python OPC UA 库来实现 server/client 测试
- 依赖尽量少
- 按仓库现有方式更新 `pyproject.toml`
- 不引入需要额外系统服务的组件

# 实现顺序（必须按此顺序执行）

1. 先阅读指定文件，理解现有 scenario1 与测试组织方式
2. 设计并实现 `tools/opcua_sim` 的内部模型与 SCD 解析
3. 实现风机插件和地址空间构建
4. 实现单机 server 与多机 fleet runtime
5. 实现 CLI
6. 补 unit / integration / fixture 测试
7. 运行相关测试并修复
8. 最后输出修改摘要、测试结果、后续接入 pipeline 的建议

# 验收标准

任务完成时必须同时满足：

1. `tools/` 下存在完整的 OPC UA 仿真工具结构
2. 能从 SCD 中识别并生成两台风机仿真定义
3. pytest 可启动两台独立 OPC UA server
4. 测试能读到两台 server 的节点值
5. 代码结构已预留设备插件扩展点
6. 没有破坏现有 scenario1 主链路与现有测试体系
7. 已提供本地手工启动方式
8. `SCD -> OPC` 转换入口骨架已放到 `tools/` 下

# 输出要求

完成后请给出：

1. 修改了哪些文件
2. 每个新增模块的职责
3. 运行了哪些测试，结果如何
4. 当前实现的边界
5. 下一步如何把 pipeline collector 切到 OPC UA
