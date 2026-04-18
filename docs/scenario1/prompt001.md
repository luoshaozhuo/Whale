你现在在 Whale 仓库中工作。请一次性实现“场景一：风机实时数据接入与分层存储”的**完整最小闭环**，并严格遵守项目现有约束。不要拆成多个阶段，不要做额外平台化重构，不要越界实现与本场景无关的能力。

# 一、必须先读的约束文件

在开始任何修改前，先读取并遵守：

1. `/CODEBUDDY.md`
2. `/.codebuddy/rules/general.md`
3. `/.codebuddy/rules/python-style.md`
4. `/.codebuddy/rules/python-typing.md`
5. `/.codebuddy/rules/python-docstrings.md`
6. `/.codebuddy/rules/testing-policy.md`

如果仓库中还有其他 testing 相关规则文件，也一并读取并遵守。

---

# 二、本次任务类型

本次任务类型是：

`feature-new-scene`

因此你必须遵守：

- 使用 `pytest`
- 严格遵守测试目录结构
- 至少补齐 `unit + smoke + integration + e2e`
- 更新 E2E 场景头与 Main-Flow 状态
- 不做无关回归扩张
- 不做无关重构
- 不得把“代码存在”当作“功能实现”
- 无 integration 证据的步骤，不得在 E2E 中标记为 `implemented`

---

# 三、本次任务目标

一次性实现“场景一”的完整最小闭环：

$$
\text{SCL初始化} \rightarrow \text{点位注册表} \rightarrow \text{OPC UA原始采集} \rightarrow \text{ODS} \rightarrow \text{标准化} \rightarrow \text{清洗} \rightarrow \text{DWD} \rightarrow \text{DWS实时/定期聚合} \rightarrow \text{ADS业务聚合}
$$

场景目标是：

1. 能从最小 SCL 子集生成点位注册表
2. 能消费 mock OPC UA 原始数据
3. 能把原始批次写入 ODS
4. 能把关键帧写入 ODS
5. 能把原始数据标准化为统一测点对象
6. 能执行最小清洗规则链
7. 能把清洗后明细写入 DWD
8. 能从 DWD 生成 DWS 实时聚合结果
9. 能从 DWD 生成 DWS 定期聚合结果
10. 能从 DWD/DWS 生成 ADS 业务结果
11. 能通过 unit / smoke / integration / e2e 测试稳定验证

---

# 四、本次明确不做

以下内容一律不要实现：

- Kafka
- HA / 分布式
- 动态采样率
- 复杂迟到数据处理 / watermark
- 平台总架构重构
- 多场景统一调度框架
- 多协议通用接入框架
- 权限、监控、告警
- 大规模性能压测
- 复杂 migration 系统
- 提前抽象成通用平台 core/domain/app/adapters 大框架

如果需要为未来预留扩展点，只允许做**极薄占位**或 TODO 注释，不要实现复杂逻辑。

---

# 五、最小 SCL 子集（强制约束）

仅支持以下字段：

- `turbine_id`（必填）
- `point_code`（必填）
- `opcua_node_id`（必填）
- `value_type`（必填）
- `unit`（必填）
- `min_value`（可选）
- `max_value`（可选）
- `deadband`（可选）
- `max_rate_of_change`（可选）
- `aggregate_group`（可选）

约束：

- 缺失任一必填字段，必须明确报错
- 多余字段忽略
- 不支持复杂 IEC 61850 深层语义
- 只要能解析出最小可用注册表即可

---

# 六、关键测点范围（场景一最小集）

本场景只实现最典型、最容易验证的关键测点：

- `active_power_kw`
- `wind_speed_ms`
- `rotor_speed_rpm`
- `pitch_angle_deg`
- `generator_bearing_temp_c`
- `run_state`
- `fault_code`（可选）

不要扩成全量点表，不要做 600 点级别复杂实现。

---

# 七、时间语义（必须统一）

至少区分并使用以下时间字段：

- `event_time`：源数据时间
- `ingest_time`：平台接收时间
- `process_time`：处理时间（如需要）

规则：

- ODS 原始批次保留 `ingest_time`
- DWD/DWS/ADS 计算与聚合以 `event_time` 为主
- 本场景不处理复杂乱序，只记录，不纠偏

---

# 八、枚举（必须统一）

请使用稳定枚举或稳定常量，不要混用魔法字符串和布尔值。

## `run_state`

最小集合：

- `STOPPED`
- `STARTING`
- `RUNNING`
- `DERATED`
- `FAULT`
- `UNKNOWN`

## `quality_code`

最小集合：

- `GOOD`
- `BAD`
- `CORRECTED`
- `SUSPECT`

## `clean_action`

最小集合：

- `KEEP`
- `CLAMP`
- `DROP`
- `HOLD_LAST`

---

# 九、建议源码目录

请尽量按以下结构实现；如果仓库已有更合适位置，可在不违背现有结构的前提下小幅适配，但不要大范围重构。

```text
src/whale/
├── shared/
│   ├── enums/
│   │   └── quality.py
│   ├── types/
│   │   └── common.py
│   └── utils/
│       └── time.py
└── scenario1/
    ├── models.py
    ├── scl_registry.py
    ├── collector.py
    ├── normalizer.py
    ├── cleaner.py
    ├── realtime_aggregator.py
    ├── periodic_aggregator.py
    ├── ads_aggregator.py
    ├── repositories.py
    └── pipeline.py
```

## 目录原则

- `shared/` 只放明确稳定复用的小内容：
  - 枚举
  - 通用时间工具
  - 极薄公共类型
- 场景强语义逻辑全部放在 `scenario1/`
- 不要为了未来可能复用而过度抽象

---

# 十、数据对象定义

请在 `src/whale/scenario1/models.py` 中定义或补齐最小数据对象。

## 1）PointMeta

建议字段：

- `turbine_id`
- `point_code`
- `opcua_node_id`
- `value_type`
- `unit`
- `min_value`
- `max_value`
- `deadband`
- `max_rate_of_change`
- `aggregate_group`

## 2）RawBatch

建议字段：

- `batch_id`
- `recv_time`
- `turbine_id`
- `raw_payload`

## 3）NormalizedPoint

建议字段：

- `event_time`
- `ingest_time`
- `turbine_id`
- `point_code`
- `value`
- `value_type`
- `unit`
- `source_status`
- `source_node_id`

## 4）CleanResult

建议字段：

- `normalized_point`
- `quality_code`
- `clean_action`
- `clean_reason`

## 5）DWS 实时聚合结果

建议字段：

- `window_end_time`
- `turbine_id`
- `avg_active_power_kw`
- `avg_wind_speed_ms`
- `max_generator_bearing_temp_c`
- `run_state_last`
- `bad_quality_ratio`

## 6）DWS 定期聚合结果

建议字段：

- `bucket_time`
- `turbine_id`
- `energy_increment_kwh`
- `avg_active_power_kw`
- `avg_pitch_angle_deg`

## 7）ADS 功率曲线偏差结果

建议字段：

- `bucket_time`
- `turbine_id`
- `wind_speed_bin`
- `actual_power_kw`
- `theoretical_power_kw`
- `deviation_kw`

## 8）ADS 可利用率结果

建议字段：

- `bucket_time`
- `turbine_id`
- `availability_ratio`
- `run_time_sec`
- `bad_quality_ratio`

要求：

- 使用清晰、稳定、可测试的字段命名
- 尽量使用 `dataclass` 或简洁 typed model
- 不要把数据库行结构和领域对象死耦合

---

# 十一、存储设计

## 1）ODS

使用 SQLite。

至少实现两张表：

### `raw_batches`

最小字段建议：

- `batch_id`
- `recv_time`
- `turbine_id`
- `raw_payload`

### `keyframes`

最小字段建议：

- `frame_time`
- `turbine_id`
- `payload`

要求：

- 由代码自动初始化
- 支持本地测试直接落库
- 不要求复杂 migration

## 2）DWD

目标是“清洗后标准明细”。

实现要求：

- 设计一个最小 `DwdRepository`
- 优先保证测试稳定、可断言
- 允许使用 fake / in-memory / sqlite-backed 测试实现
- 不依赖脆弱外部环境
- 但不要把核心业务路径全 mock 掉

DWD 明细最小字段建议：

- `ts`
- `turbine_id`
- `point_code`
- `value`
- `quality_code`

说明：

- 本次重点不是接入真实 TDengine 集群
- 而是把“清洗后明细写出”打通
- 为后续聚合提供稳定输入

## 3）DWS

实现最小 repository 支持：

- 写入实时聚合结果
- 写入定期聚合结果
- 查询结果供测试断言

## 4）ADS

实现最小 repository 支持：

- 写入功率曲线偏差结果
- 写入可利用率结果
- 查询结果供测试断言

---

# 十二、SCL 解析要求

实现：

`src/whale/scenario1/scl_registry.py`

职责：

- 读取最小 SCL 文件
- 解析为点位注册表
- 对缺失必填字段报错

要求：

- 本场景只支持最小子集，不做复杂 IEC 61850 语义树处理
- 输出必须可直接供 `normalizer` 与 `cleaner` 使用
- 解析结果必须可单测

---

# 十三、采集要求

实现：

`src/whale/scenario1/collector.py`

职责：

- 接收 mock/占位 OPC UA 原始数据输入
- 组装为 `RawBatch`

说明：

- 本次不要求真实 OPC UA 网络订阅
- 只要支持测试夹具中的稳定 mock 原始格式即可
- 请控制原始 payload 结构简单、清晰、稳定

---

# 十四、标准化逻辑要求

实现：

`src/whale/scenario1/normalizer.py`

职责：

- 输入：`RawBatch + PointMeta 注册表`
- 输出：`list[NormalizedPoint]`

要求：

1. 从 `raw_payload` 中抽取单点值
2. 根据 `point_code / opcua_node_id` 映射注册表
3. 正确填充：
   - `turbine_id`
   - `point_code`
   - `value`
   - `value_type`
   - `unit`
   - `event_time`
   - `ingest_time`
4. 对无法映射或结构非法的数据：
   - 明确失败
   - 或产出可测试的错误行为
   - 禁止静默吞掉

---

# 十五、清洗逻辑要求

实现：

`src/whale/scenario1/cleaner.py`

职责：

- 输入：`NormalizedPoint`
- 输出：`CleanResult`

只做以下 4 条固定规则，顺序执行：

## 1）空值 / 类型校验
- 空值 → `BAD`
- 类型不匹配 → `BAD`

## 2）工程范围校验
依据 `min_value / max_value`：
- 超范围时可：
  - `CLAMP`
  - 或 `DROP`
- 但必须记录 `clean_reason`

## 3）死区处理
依据 `deadband`：
- 变化量小于阈值时可保持前值
- 若实现 `HOLD_LAST`，必须可测试
- 若本次不维护完整缓存，也必须给出稳定、可测试的最小行为

## 4）变化率约束
依据 `max_rate_of_change`：
- 超阈值时标记为 `SUSPECT` 或 `BAD`
- 规则必须可测试

输出必须包含：

- `quality_code`
- `clean_action`
- `clean_reason`

禁止只改值不留原因。

---

# 十六、实时聚合要求

实现：

`src/whale/scenario1/realtime_aggregator.py`

窗口定义：

- 窗口长度：5 秒
- 步长：1 秒

至少实现以下单机指标：

- `avg_active_power_kw`
- `avg_wind_speed_ms`
- `max_generator_bearing_temp_c`
- `run_state_last`
- `bad_quality_ratio`

要求：

- 使用 `event_time`
- 本场景不处理复杂乱序
- 逻辑应尽量纯函数化、便于单测

---

# 十七、定期聚合要求

实现：

`src/whale/scenario1/periodic_aggregator.py`

窗口定义：

- 1 分钟桶

至少实现：

- `energy_increment_kwh`
- `avg_active_power_kw`
- `avg_pitch_angle_deg`

发电量增量允许按最小近似：

$$
E \approx \sum P_i \cdot \Delta t
$$

要求：

- 实现简单、清晰、可测试
- 不要引入复杂积分或补点算法

---

# 十八、ADS 聚合要求

实现：

`src/whale/scenario1/ads_aggregator.py`

至少实现两个结果：

## 1）风速分箱功率偏差

要求：

- 按固定风速分箱，例如每 0.5 m/s 一档
- 计算实际功率
- 使用测试夹具中的简化理论功率曲线表得到理论功率
- 输出偏差值

## 2）机组可利用率

最小定义：

$$
Availability = \frac{\text{运行时长}}{\text{统计周期总时长}}
$$

要求：

- 根据 `run_state` 推导运行时长
- 输出值满足：

$$
0 \le Availability \le 1
$$

---

# 十九、pipeline 要推进到的程度

在 `src/whale/scenario1/pipeline.py` 中实现一个**最小、串行、可测**的主流程，打通：

$$
\text{SCL} \rightarrow \text{RawBatch} \rightarrow \text{ODS} \rightarrow \text{NormalizedPoint} \rightarrow \text{CleanResult} \rightarrow \text{DWD} \rightarrow \text{DWS} \rightarrow \text{ADS}
$$

要求：

- 可以用测试夹具直接驱动
- 不引入复杂并发、调度器、消息系统
- 允许保留极薄的分发逻辑
- 但不要做复杂多线程 dispatch / job orchestration

---

# 二十、关键帧规则

对同一 `turbine_id`：

- 每隔固定时间窗口写 1 次关键帧
- 默认可按“每 10 秒最多 1 条”实现

要求：

- 可配置或可注入
- 可单测
- 不要写成难以测试的全局状态

---

# 二十一、测试目录（必须遵守）

必须满足：

```text
tests/
├── unit/
│   └── scenario1/
├── smoke/
│   └── scenario1/
├── integration/
│   └── scenario1/
├── e2e/
│   └── scenario1/
├── fixtures/
│   └── scenario1/
└── conftest.py
```

并在 pytest 配置中注册 markers：

- `unit`
- `smoke`
- `integration`
- `e2e`

如果仓库尚未注册，请补齐。

---

# 二十二、测试夹具

请新增或完善：

```text
tests/fixtures/scenario1/
├── sample_scl.xml
├── sample_raw_batches.json
├── sample_points.json
└── sample_power_curve.csv
```

要求：

- 数据尽量小而稳定
- 不依赖真实网络服务
- 至少覆盖：
  - 正常功率点
  - 正常风速点
  - 正常温度点
  - 一个越界值
  - 一个空值/非法值
  - 不同 `run_state`
  - 简化理论功率曲线表

---

# 二十三、本次必须新增或补齐的测试

## 1）unit

至少新增或补齐：

### `tests/unit/scenario1/test_scl_registry.py`
验证：

- 最小 SCL 成功解析
- 缺失必填字段时报错
- 输出注册表字段正确

### `tests/unit/scenario1/test_normalizer.py`
验证：

- `RawBatch` 能转换为 `NormalizedPoint`
- 映射正确
- 缺失映射时行为明确

### `tests/unit/scenario1/test_cleaner.py`
验证：

- 空值/类型校验
- 范围校验
- 死区规则
- 变化率规则
- 输出 `quality_code / clean_action / clean_reason`

### `tests/unit/scenario1/test_pipeline_keyframe.py`
验证：

- 原始批次写入 ODS
- 关键帧规则生效
- 时间窗口内不会重复插入关键帧

### `tests/unit/scenario1/test_dwd_repository.py`
验证：

- DWD repository 能保存并查询清洗后明细

### `tests/unit/scenario1/test_realtime_aggregator.py`
验证：

- 5 秒窗口、1 秒步长切窗正确
- `avg_active_power_kw` 正确
- `avg_wind_speed_ms` 正确
- `max_generator_bearing_temp_c` 正确
- `bad_quality_ratio` 正确

### `tests/unit/scenario1/test_periodic_aggregator.py`
验证：

- 1 分钟聚合桶正确
- `energy_increment_kwh >= 0`
- `avg_active_power_kw` 正确
- `avg_pitch_angle_deg` 正确

### `tests/unit/scenario1/test_ads_aggregator.py`
验证：

- 风速分箱正确
- 理论功率查表正确
- `deviation_kw` 正确
- `availability_ratio` 在合法区间

### `tests/unit/scenario1/test_dws_ads_repositories.py`
验证：

- DWS repository 可保存并查询结果
- ADS repository 可保存并查询结果

---

## 2）smoke

至少新增或完善：

### `tests/smoke/scenario1/test_pipeline_smoke.py`

目标：

- 验证最小流程可启动且不崩

建议配置：

- 1 台风机
- 6 个关键测点
- 运行一个很小的数据集，不做长时间等待

至少断言：

- ODS `raw_batches` 有数据
- ODS `keyframes` 有数据
- DWD 有数据
- 主流程无异常退出

---

## 3）integration

至少新增或完善：

### `tests/integration/scenario1/test_pipeline_ingest_to_dwd.py`

验证子链路：

$$
\text{SCL注册表} \rightarrow \text{RawBatch} \rightarrow \text{normalize} \rightarrow \text{clean} \rightarrow \text{DWD}
$$

至少断言：

- DWD 写入记录数 > 0
- `active_power_kw` 与 `wind_speed_ms` 写入成功
- 异常值清洗后质量码符合预期

### `tests/integration/scenario1/test_pipeline_dwd_to_dws.py`

验证子链路：

$$
\text{DWD} \rightarrow \text{DWS实时/定期聚合}
$$

至少断言：

- 实时聚合记录数 > 0
- 定期聚合记录数 > 0
- 至少一个关键指标符合预期

### `tests/integration/scenario1/test_pipeline_dws_to_ads.py`

验证子链路：

$$
\text{DWD/DWS} \rightarrow \text{ADS}
$$

至少断言：

- 功率曲线偏差结果数 > 0
- 可利用率结果数 > 0
- `availability_ratio` 落在 `[0,1]`

要求：

- 每个 integration 文件只验证一个子链路
- 必须包含输入 / 执行 / 断言
- 不得只验证“不报错”

---

## 4）e2e（核心）

必须新增或完善：

### `tests/e2e/scenario1/test_scenario1_e2e.py`

文件头必须包含：

```python
"""
Scenario-Name: scenario1
Scenario-Goal: 风机实时数据接入与分层存储最小闭环
Main-Flow:
1. load SCL registry [implemented]
2. ingest raw OPC UA batches [implemented]
3. persist ODS raw batches/keyframes [implemented]
4. normalize raw points [implemented]
5. clean normalized points [implemented]
6. persist DWD records [implemented]
7. aggregate DWS realtime/periodic [implemented]
8. aggregate ADS business results [implemented]
Verification:
- full scenario1 pipeline is stable
"""
```

但注意：

- 只有在存在对应 integration 证据时，步骤才能标 `implemented`
- 如果某步证据不足，必须标 `partial` 或 `not-implemented`

E2E 至少断言：

- `raw_batches` 有数据
- `keyframes` 有数据
- DWD 有数据
- DWS 实时结果有数据
- DWS 定期结果有数据
- ADS 功率曲线偏差结果有数据
- ADS 可利用率结果有数据
- `energy_increment_kwh >= 0`
- `0 <= availability_ratio <= 1`

要求：

- E2E 必须是真实主流程测试
- 可以用稳定 fixture 和 fake repository
- 但主流程逻辑必须真实跑通
- 不要只拼 mock

---

# 二十四、实现要求

## 必须做到

- Python 3.10+ 类型提示完整
- docstring 遵守仓库规范
- 命名清晰
- 逻辑尽量纯函数化、便于单测
- 变更局部、边界清楚
- 优先保持现有行为稳定
- 完成后运行本任务直接受影响的测试
- 完成后运行项目内质量检查流程；若有对应 quality skill，按仓库要求执行

## 明确禁止

- 不要引入复杂设计模式
- 不要做平台总架构重构
- 不要做与本场景无关的清理
- 不要为了未来复用做过度抽象
- 不要用全 mock 伪造 integration/e2e
- 不要修改业务语义只为让测试通过

---

# 二十五、建议执行顺序

按以下顺序实施：

1. 读取约束文件
2. 检查现有目录和 pytest 配置
3. 补齐模型与枚举
4. 实现 SCL 解析
5. 实现 RawBatch 采集输入适配
6. 实现 ODS repository
7. 实现 normalizer
8. 实现 cleaner
9. 实现 DWD repository
10. 实现 realtime aggregator
11. 实现 periodic aggregator
12. 实现 ads aggregator
13. 实现 DWS / ADS repository
14. 串起 pipeline
15. 补 fixtures
16. 补 unit 测试
17. 补 smoke 测试
18. 补 integration 测试
19. 补/更新 e2e
20. 运行相关测试
21. 运行质量检查
22. 汇报结果

---

# 二十六、交付要求

完成后请输出：

## 1）变更清单
按文件列出新增/修改内容。

## 2）测试执行清单
列出本次实际运行的命令，例如：

- `pytest tests/unit/scenario1 -q`
- `pytest tests/smoke/scenario1 -q`
- `pytest tests/integration/scenario1 -q`
- `pytest tests/e2e/scenario1 -q`

以及实际运行的质量检查命令。

## 3）验收结果
明确说明是否已经满足：

- SCL 注册表可生成
- ODS 原始批次与关键帧落盘成功
- 标准化可运行
- 清洗规则可运行
- DWD 明细写入成功
- DWS 实时聚合可运行
- DWS 定期聚合可运行
- ADS 业务聚合可运行
- E2E 通过
- 质量检查通过

## 4）刻意未做项
简述哪些内容被明确留到未来平台化阶段：

- Kafka
- HA / 分布式
- 调度框架
- 复杂迟到数据处理
- 多场景公共抽象

---

# 二十七、最终边界提醒

你这次是在实现“场景一”的**完整最小闭环**，目标是：

- 把功能做完整
- 把测试做完整
- 让主场景状态真实、可证实、可运行

不要擅自扩展到：

- 场景二/场景三
- 平台总架构
- 多协议抽象框架
- 分布式消息系统
- 大规模性能能力

以“刚好满足场景一完整闭环”为准。