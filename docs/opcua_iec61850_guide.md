# OPC UA × IEC 61850 通信与建模指南（扩展版）

## 1. 文档目的

本文面向风电场、变电站、储能系统、工业网关和数据平台场景，系统说明 **IEC 61850** 与 **OPC UA** 的分工、关系、建模机制、地址空间结构，以及其底层常见传输方式，包括 **TCP socket、WebSocket、`opc.tcp`、`opc.wss`、`opc.https`**。文档重点不是孤立解释几个术语，而是建立一套从“行业语义层”到“运行时传输层”的完整认识框架，帮助在设计模拟器、采集链路、网关映射、平台接入和测试环境时避免概念混淆。

---

## 2. 全局视角：从行业模型到传输承载

在工程上，相关概念可以分成三层理解：

```text
行业语义与对象模型层
└── IEC 61850
    ├── 信息模型：LN / DO / DA
    ├── 工程配置：SCL（ICD / SSD / SCD / CID / IID / SED）
    └── 通信映射
         ├── MMS（Client / Server）
         │    ├── Read / Write
         │    └── Report
         ├── GOOSE
         └── SV

统一工业访问与平台集成层
└── OPC UA
    ├── 信息模型：Node / Object / Variable / Type / Reference / Namespace
    ├── 地址空间：Address Space
    ├── 访问机制：Browse / Read / Write / Subscription / Method
    ├── 类型系统：ObjectType / VariableType / DataType / ReferenceType
    └── 安全机制：证书 / 认证 / 签名 / 加密

运行时传输承载层
├── TCP socket
├── WebSocket
├── HTTP / HTTPS
└── OPC UA 传输映射
     ├── opc.tcp
     ├── opc.wss
     └── opc.https
```

这张结构图说明：

1. **IEC 61850 解决“对象语义”和“工程配置”的问题。**
2. **OPC UA 解决“统一建模”和“统一访问”的问题。**
3. **TCP / WebSocket / HTTPS 解决“数据具体如何在网络上传输”的问题。**

因此，不应把 IEC 61850、MMS、OPC UA、TCP、WebSocket 放在同一个层面直接比较。它们各自解决的是不同层的问题。

---

## 3. IEC 61850：先统一“对象是什么”

### 3.1 标准定位

IEC 61850 是电力自动化领域的标准体系，核心价值在于建立跨厂商统一的信息模型与语义规则。它首先回答：

- 设备功能如何抽象
- 数据对象如何组织
- 工程配置如何交换
- 不同通信方式如何映射这些对象

换句话说，IEC 61850 首先定义的是“对象是什么”，再定义“对象怎么传”。

---

### 3.2 信息模型：LN / DO / DA

IEC 61850 最关键的模型层次是：

```text
LN（Logical Node，逻辑节点）
 └── DO（Data Object，数据对象）
      └── DA（Data Attribute，数据属性）
```

可以理解为：

- **LN**：功能单元
- **DO**：某个功能下的一类业务数据
- **DA**：该业务数据的具体属性和值

例如：

```text
WT01 / LD0 / WTUR1 / WindSpd / mag.f
```

这表示某台风机中某个逻辑节点下风速对象的最终浮点值。系统拿到的不只是“12.5”，而是一个带有标准语义来源的数据点。

---

### 3.3 通信映射：MMS / GOOSE / SV

IEC 61850 不绑定单一传输机制，而是根据场景定义不同映射：

- **MMS**：面向监控系统的客户端 / 服务端访问
  - Read / Write
  - Report（设备主动推送）
- **GOOSE**：面向快速事件联动
- **SV**：面向高速采样值流

这里要特别注意：**MMS / GOOSE / SV 是 IEC 61850 的通信映射，不是与 IEC 61850 并列的独立“行业模型标准”。**

---

### 3.4 SCL：工程配置语言

SCL 是 IEC 61850 的 XML 工程配置语言，常见文件类型包括：

- ICD
- SSD
- SCD
- CID
- IID
- SED

SCL 的职责是描述：

- IED 能力
- 系统结构
- 通信关系
- 模型模板与实例

SCL 属于**工程期 / 配置期**，不是运行时传输协议。

---

## 4. OPC UA：统一工业访问架构

### 4.1 标准定位

OPC UA 的核心不是“一个报文协议”，而是一套完整的工业访问架构。它同时提供：

- 统一地址空间
- 面向对象的信息模型
- 标准化访问接口
- 类型系统
- 安全机制
- 多种传输承载方式

在工程上，可以把它理解为：

> **把工业对象以统一语义和统一访问方式暴露给客户端。**

---

### 4.2 Address Space：图模型而非树模型

OPC UA 地址空间的本质不是 XML 树，而是**带类型的图（typed graph）**：

- **Node**：节点
- **Reference**：节点之间的边
- **ReferenceType**：边的类型
- **TypeDefinition**：节点的语义类型

可以用类比帮助理解：

#### 数据库类比

- Node = 一条记录
- NodeId = 主键
- Reference = 外键关系
- ReferenceType = 外键类型

#### 面向对象类比

- Node = 对象
- ObjectType = 类
- HasComponent = 成员变量
- HasTypeDefinition = 类型声明

---

## 5. Node、NodeId、BrowseName：节点如何被识别

### 5.1 NodeId：唯一标识

NodeId 用于唯一标识节点，格式为：

```text
NodeId = (namespaceIndex, identifier)
```

常见形式：

- `ns=2;i=1`
- `ns=2;s=WTG_01.WS`

identifier 的类型可为：

- `i`：numeric
- `s`：string
- `g`：GUID
- `b`：ByteString

在工程上：

- **NodeId 是全局唯一主键**
- 客户端最终应依赖 NodeId 访问节点

---

### 5.2 BrowseName：导航名称

BrowseName 用于导航和路径表达，例如：

```text
2:WS
```

它的特点是：

- 通常只要求在同一父节点下唯一
- 用于 Browse / Path 导航
- 不保证全局唯一

因此：

- **NodeId = 唯一地址**
- **BrowseName = 局部路径名**

---

### 5.3 为什么两者都需要

NodeId 解决“如何稳定访问”，BrowseName 解决“如何发现和导航”。

这很像文件系统：

- NodeId ≈ inode
- BrowseName / Path ≈ 文件路径

即使 NodeId 采用可读的 string，例如 `ns=2;s=WTG_01.WS`，它也仍然只是一个键，不自动表达结构关系。结构仍然来自 Reference。

---

## 6. Namespace：稳定标识与运行时编号

### 6.1 Namespace URI vs NamespaceIndex

必须区分两个概念：

- **Namespace URI**：稳定标识
- **NamespaceIndex**：运行时编号

例如：

```text
urn:windfarm:2wtg  → 运行时可能映射为 ns=2
```

关键原则是：

> **不要依赖 ns=2 这种数字；要依赖 URI。**

因为不同 server、不同启动顺序、不同 import 过程下，运行时 index 可能变化，但 URI 应保持稳定。

---

### 6.2 URI、URL、URN 的关系

- **URI** 是总概念
- **URL** 是可定位资源的 URI
- **URN** 是只用于唯一命名的 URI

在 OPC UA 中：

- endpoint 常用 URL，例如：
  - `opc.tcp://127.0.0.1:4840`
- namespace URI、application URI 常适合用 URN，例如：
  - `urn:windfarm:2wtg`
  - `urn:whale:opcua-server`

URN 更适合 namespace，因为它表示“是谁”，而不暗示“在哪里”。

---

## 7. Reference 与 ReferenceType：结构不是写出来的，而是连出来的

### 7.1 Reference：节点之间的关系

OPC UA 结构不是靠 XML 嵌套表达，而是靠 Reference 表达。例如：

```text
Objects --Organizes--> WindFarm
WTG_01 --HasComponent--> TotW
```

在 NodeSet 中，很多“父子层级”其实都是 Reference。

---

### 7.2 ReferenceType 也是 Node

这是 OPC UA 的元模型关键点：

- `Organizes`
- `HasComponent`
- `HasTypeDefinition`

它们不是语法关键字，而是**ReferenceType 节点**，也有自己的 NodeId，例如：

- `Organizes = i=35`
- `HasComponent = i=47`
- `HasTypeDefinition = i=40`

因此在 OPC UA 中：

- Node 是对象
- Reference 是连接
- ReferenceType 是连接类型

---

### 7.3 正向与反向：IsForward 的意义

Reference 有方向。例如：

```text
Objects --Organizes--> WindFarm
```

如果在 `WindFarm` 节点里写这条关系，就需要反向写法：

```xml
<Reference ReferenceType="Organizes" IsForward="false">ObjectsFolder</Reference>
```

它的含义不是“WindFarm 组织 Objects”，而是：

> “WindFarm 被 ObjectsFolder 以 Organizes 关系组织起来。”

所以：

- 写正向引用时，`IsForward` 可省略
- 写反向引用时，必须 `IsForward="false"`

---

## 8. Organizes 与 HasComponent：什么时候用哪个

这是建模里最容易混淆的点。

### 8.1 Organizes

适合：

- 分组
- 目录结构
- 松散组织关系

例如：

```text
Objects → WindFarm → WTG_01
```

这里更偏“目录组织”。

---

### 8.2 HasComponent

适合：

- 真正属于父对象的组成部分
- 强语义成员关系

例如：

```text
WTG_01 → TotW / Spd / WS
```

这些变量是风机的一部分。

---

### 8.3 简单判定法

如果去掉子节点会让父对象“缺一块”，那更适合 `HasComponent`；如果只是为了分组方便浏览，则更适合 `Organizes`。

---

## 9. HasTypeDefinition：节点“是什么”

### 9.1 作用

`HasTypeDefinition` 用于声明节点属于哪种类型。例如：

```xml
<Reference ReferenceType="HasTypeDefinition">BaseDataVariableType</Reference>
```

表示：

> 这个节点是一个标准数据变量。

它和 `Organizes / HasComponent` 不同：

- `Organizes / HasComponent` 决定“挂在哪”
- `HasTypeDefinition` 决定“它是什么”

---

### 9.2 工程意义

有了类型定义后，客户端可以知道：

- 这是变量还是对象
- 它应该具备哪些标准属性
- 应该如何解释它的语义

没有类型定义，节点仍可能存在，但语义不完整。

---

## 10. FolderType：容器节点类型

`FolderType` 是标准定义的对象类型：

```text
FolderType = i=61
```

它表示：

> 这是一个容器节点，用于组织其他节点。

它适合：

- `WindFarm`
- `Measurements`
- `Alarms`

它不适合：

- 风机设备本体
- 业务对象实体

所以更合理的做法通常是：

- `WindFarm` → `FolderType`
- `WTG_01` → `BaseObjectType` 或自定义 `WindTurbineType`

---

## 11. Alias：可读性机制

在 NodeSet 里，经常看到：

```xml
<Alias Alias="ObjectsFolder">i=85</Alias>
<Alias Alias="Double">i=11</Alias>
```

Alias 的作用是给标准 NodeId 起可读名字，便于编写：

- `ObjectsFolder` 代替 `i=85`
- `Double` 代替 `i=11`

这些 `i=xx` 不是随便写的，而是 OPC UA 标准命名空间里的固定 NodeId。

---

## 12. NodeSet：不是树形缩进文件，而是节点清单 + 关系图

### 12.1 为什么 XML 看起来“平铺”

在 NodeSet 中，经常会看到：

```xml
<UAObject .../>
<UAVariable .../>
```

看起来像平级，没有包含关系。

这并不表示没有结构。真正的结构关系写在 `<References>` 中。

所以：

> **NodeSet 的 XML 外观不是层级；层级来自 Reference。**

---

### 12.2 文件内 namespace vs 运行时 namespace

NodeSet 里的：

- `ns=0`
- `ns=1`
- `BrowseName="1:WindFarm"`

指的是**NodeSet 文件内部根据 `<NamespaceUris>` 列表形成的局部索引**。

加载到 server 时，真正使用的是：

```text
NodeSet index → URI → runtime namespaceIndex
```

所以：

- 文件内 `ns=1` 不必等于运行时 `ns=1`
- 真正稳定的是 URI

---

## 13. Type Reuse：如何复用，不要复用实例

### 13.1 错误理解：复用变量实例

例如试图让：

- `WTG_01.WS`
- `WTG_02.WS`

共用同一个变量节点

这是错误的，因为它们是两个不同实例，有不同值、不同父对象、不同 NodeId。

---

### 13.2 正确复用方式

应复用：

- **ObjectType**
- **VariableType**
- **建模模板**
- **生成规则**

例如定义：

- `WindTurbineType`
- 其中包含：
  - `TotW`
  - `Spd`
  - `WS`

然后实例化：

- `WTG_01`
- `WTG_02`

这样复用的是结构定义，不是实例本身。

---

### 13.3 大规模风机场景的现实做法

如果每台风机有几百变量，几十台风机：

- 手写全量 XML 不现实
- 手写 `add_variable()` 也不现实

真正可维护的办法是：

```text
SCD / 点表 / 配置
   ↓
模型解析
   ↓
自动生成 NodeSet 或 asyncua runtime nodes
```

---

## 14. asyncua：NodeSet 导入与工程建议

`asyncua` / `opcua-asyncio` 提供了：

- `await server.import_xml(...)`
- `XmlImporter.import_xml(...)`

可将 XML / NodeSet 导入到 server address space。

但需要注意：

1. NodeSet 本身必须定义完整
   - 不能只有节点，没有 Reference
2. 不能假设 importer 会替你补齐所有结构语义
3. 对复杂 NodeSet，导入前最好自己控制生成逻辑

因此，在工程上更稳妥的方式通常是：

- 用 NodeSet 表达静态模型
- 用代码或生成器表达大量实例

---

## 15. TCP socket、WebSocket 与 OPC UA 传输方式

这一部分是前面建模知识之外，必须补齐的“运行时网络承载”知识。

### 15.1 TCP socket 是什么

TCP 是传输层协议，提供：

- 面向连接
- 可靠传输
- 有序字节流
- 重传与流控

socket 是应用程序使用 TCP 的编程接口。可以把它理解为：

> **程序在操作系统里打开的一个“网络端口通信端点”。**

例如：

- server 监听 `0.0.0.0:4840`
- client 连接 `192.168.1.10:4840`

这背后本质就是 TCP socket。

---

### 15.2 WebSocket 是什么

WebSocket 是建立在 HTTP/HTTPS 之上的长连接机制。

典型过程是：

1. 先以标准 HTTP/HTTPS 请求建立连接
2. 然后升级为 WebSocket
3. 建立双向长连接

它的优势在于：

- 能穿常见企业网络策略
- 适合浏览器环境
- 保留长连接能力

---

### 15.3 TCP socket vs WebSocket

两者不是同一层的替代关系，而是：

- TCP socket：更底层、更原生
- WebSocket：基于 HTTP/HTTPS 的上层双向通道

可以类比为：

- TCP socket = 原生工业接线
- WebSocket = 穿着 HTTP 外衣的双向隧道

---

## 16. OPC UA 的三种常见传输承载

### 16.1 `opc.tcp`

这是 OPC UA 最典型、最原生的传输方式。它本质上是：

```text
OPC UA Binary + UA TCP + TCP
```

特点：

- 原生
- 长连接
- 二进制
- 性能最好
- 工业现场最常见

适合：

- SCADA
- 采集网关
- 边缘系统
- 本地模拟器 / 测试服务器

对于你当前的风机模拟与 E2E 测试，`opc.tcp` 是默认首选。

---

### 16.2 `opc.wss`

这是 OPC UA over WebSocket，通常运行在 HTTPS / WSS 上。

特点：

- 通过 WebSocket 承载 OPC UA
- 更适合浏览器
- 更容易穿企业网络策略
- 可走 443 端口
- 长连接能力仍然存在

但要精确理解：

> 它之所以更容易穿企业防火墙，不只是因为“用了 443 端口”，而是因为“流量形态看起来像 HTTPS / WebSocket”。

所以，**443 是门，HTTPS / WSS 才是通行证。**

---

### 16.3 `opc.https`

这是基于 HTTP/HTTPS 请求响应方式的 OPC UA 映射。

特点：

- 更像 request/response
- 一般不适合高频 Subscription
- 现实工业场景使用较少

工程上通常不作为风机实时采集的优先方案。

---

## 17. 为什么 `server.set_endpoint("opc.tcp://0.0.0.0:4840/...")` 不是 WebSocket

当你写：

```python
server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")
```

其含义是：

- 协议：`opc.tcp`
- 监听地址：`0.0.0.0`
- 端口：`4840`
- endpoint path：`/freeopcua/server/`

这里：

- `0.0.0.0` 表示绑定所有网卡
- 不是客户端访问地址
- 客户端通常连接实际地址，如：
  - `opc.tcp://127.0.0.1:4840/freeopcua/server/`

这使用的是 OPC UA over TCP，不是 WebSocket。

---

## 18. `opc.tcp`、`opc.wss`、`opc.https` 的工程选择

### 18.1 工业现场 / SCADA / 本地模拟器

优先：

- `opc.tcp`

原因：

- 简单
- 原生
- 高性能
- 工业兼容性好

---

### 18.2 浏览器 / 云平台 / 穿企业网络

优先考虑：

- `opc.wss`

原因：

- WebSocket 更适合浏览器
- 可利用 HTTPS 通道穿越企业网络策略

---

### 18.3 特殊 IT 集成场景

可能才考虑：

- `opc.https`

但对风机数据连续采集而言，通常不是首选。

---

## 19. IEC 61850 × OPC UA：最终关系梳理

最准确的理解不是“谁替代谁”，而是：

- **IEC 61850**：行业语义与工程配置基础
- **OPC UA**：统一访问与平台集成机制
- **TCP / WebSocket / HTTPS**：运行时传输承载

一个典型工程链路可以是：

```text
底层设备 / IED / 风机控制器
   └── 内部或对外遵循 IEC 61850 模型
            ↓
     原生通过 MMS / Report 提供访问
            ↓
     由网关或服务映射为 OPC UA Address Space
            ↓
     上层平台通过 opc.tcp / opc.wss 接入
```

---

## 20. 针对风机模拟与数据平台的建议

对你当前这类场景，建议如下：

### 20.1 小规模验证

- 可直接用 NodeSet
- 可直接用 `asyncua import_xml()`
- endpoint 用 `opc.tcp`

### 20.2 中到大规模建模

必须采用：

- 类型复用
- 生成器
- SCD / 点表驱动
- 代码或模板生成地址空间

### 20.3 传输方案

优先：

- `opc.tcp`

不要在当前阶段引入 `opc.wss`，除非明确需要浏览器直连或穿企业网络。

---

## 21. 最终总结

本文的核心结论可以压缩为以下几点：

1. **IEC 61850 定义行业对象语义，OPC UA 定义统一对象访问。**
2. **OPC UA 的本质是“带类型语义的图模型”，不是树形 XML。**
3. **NodeId 是唯一主键，BrowseName 是导航名称，结构来自 Reference。**
4. **Organizes 用于分组，HasComponent 用于组成，HasTypeDefinition 用于声明语义类型。**
5. **FolderType 只是容器类型，不应滥用于业务对象。**
6. **实例不能复用，复用的是类型和生成规则。**
7. **NodeSet 的 namespace 编号只是文件内部局部索引，真正稳定的是 URI。**
8. **TCP socket 和 WebSocket 是网络承载；`opc.tcp`、`opc.wss`、`opc.https` 是 OPC UA 在这些承载上的映射。**
9. **对风机模拟、采集网关和 E2E 测试，`opc.tcp` 是最自然、最稳妥的起点。**
10. **当模型规模扩大时，必须从“手写 XML”转向“类型复用 + 自动生成”。**
