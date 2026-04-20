# Ingest 模块决策

## 模块目标

`whale.ingest` 只保留接入侧职责，不承载数据库建模细节，也不负责运行时 OPC UA 采集。

当前阶段，ingest 只承担两件事：

1. 定义 ingest 输出的数据消息管道
2. 作为“配置初始化能力”的业务归属方，调用下层数据库能力

配置库初始化的具体实现已经收拢到 `whale.ingest.infrastructure`。

## 当前架构分层

围绕 OPC UA 配置初始化，当前采用如下结构：

```text
whale/
└── ingest/
    ├── infrastructure/
    │   ├── base.py
    │   ├── models.py
    │   ├── init_db.py
    │   ├── opcua_config_repository.py
    │   ├── opcua_config_import_service.py
    │   ├── opcua_config_query_service.py
    │   ├── opcua_config_api.py
    │   └── opcua_config_dto.py
    ├── message_pipeline.py
    └── INGEST_MODULE_DECISIONS.md
```

这个结构的意思是：

- `ingest`
  是接入侧能力边界
- `ingest.infrastructure`
  是接入侧配置存储的技术实现收纳点
- `base.py / models.py / init_db.py`
  分别负责 SQLAlchemy 基础设施、ORM 模型、数据库初始化入口
- `opcua_config_repository.py`
  负责简单数据访问和复杂查询仓储
- `opcua_config_import_service.py`
  负责配置文件解析与写入编排
- `opcua_config_query_service.py`
  负责复杂只读查询编排
- `opcua_config_api.py`
  负责对外暴露稳定读取入口
- `opcua_config_dto.py`
  负责在各层之间共享 DTO，避免 repository 反向依赖 service

## 表结构决策

数据库使用 SQLite，ORM 使用 SQLAlchemy。

表结构按 `OPCUANodeSet.xml` 的核心构成拆分，当前包括：

- `namespace_uris`
  对应 `NamespaceUris`
- `aliases`
  对应 `Aliases`
- `ua_object_types`
  对应 `UAObjectType`
  虽然你的重点提示里没有单列它，但模板文件中存在，保留它可以更完整兼容 NodeSet
- `ua_objects`
  对应 `UAObject`
- `ua_variables`
  对应 `UAVariable`
- `ua_references`
  对应各类节点之间的 `References`
- `opcua_client_connections`
  对应 `OPCUA_client_connections.yaml`

这里的核心设计原则是：

- NodeSet 的结构信息优先按“元素类型 + 关系表”拆开保存
- `UAObject`、`UAVariable` 与 `UAObjectType` 的关系，不用硬编码在业务逻辑里，而是通过 `ua_references` 保留原始拓扑
- `parent_node_id`、`type_definition` 等常用字段做适度冗余，方便后续查询和运行时装配

## 外层访问数据库的约束

这部分是当前版本最重要的边界约束。

### 写操作

写操作必须走 `service`。

当前落地方式是：

- `OpcUaConfigImportService` 负责读取 YAML / NodeSet
- service 调用 write repository 完成替换写入
- `whale.ingest.infrastructure.init_db` 只作为初始化入口，不直接承载写库细节

外层不要直接调用 repository 去做插入、更新、删除。

### 读操作

读操作分为两类：

- 简单查询：直接走 `read repository`
- 复杂查询：必须走 `query service`

为了减少 session 管理泄漏，对外还提供了 `api` 作为稳定入口：

- `OpcUaConfigReadApi`
  适合简单只读访问
- `OpcUaConfigQueryApi`
  适合聚合、联表、视图型查询

## 当前边界

### 属于 ingest 相关能力的内容

- 从 `OPCUANodeSet.xml` 和 `OPCUA_client_connections.yaml` 初始化 SQLite 配置数据库
- 支持默认模板路径
- 保留用户传入两个配置文件路径的能力
- 通过 ORM 管理表结构和写入
- 定义 ingest 输出消息管道抽象

### 不属于 ingest 的内容

- OPC UA 运行时 client 生命周期管理
- OPC UA 周期轮询采集
- 下游业务存储
- 聚合逻辑
- 指标计算
- 场景编排

其中 OPC UA server 仿真继续由 `tools/opcua_sim` 提供。

## 稳定使用方式

当前推荐调用方式：

1. 准备 SQLite 文件路径
2. 使用默认模板，或显式传入自定义的 YAML / NodeSet 路径
3. 执行 `python -m whale.ingest.infrastructure.init_db --db-path ...`
4. 读侧通过 `read repository / query service / api` 访问数据库

命令行示例：

```bash
python -m whale.ingest.infrastructure.init_db --db-path ./opcua_config.sqlite
```

如果需要指定输入文件：

```bash
python -m whale.ingest.infrastructure.init_db \
  --db-path ./opcua_config.sqlite \
  --connection-config-path ./custom/OPCUA_client_connections.yaml \
  --nodeset-path ./custom/OPCUANodeSet.xml
```

## 修改规则

后续修改时保持以下约束：

- 不要再把这些数据库相关实现拆散回 `whale/` 顶层目录
- 不要让 repository 承担业务决策
- 不要让 service 直接暴露底层 session 细节给外层
- 不要把复杂查询散落到调用方，统一收敛到 query service
- 不要把 OPC UA 运行时轮询逻辑重新放回当前这组初始化模块
