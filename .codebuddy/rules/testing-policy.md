---
alwaysApply: false
paths: "{src,tests}/**/*.py"
---

# Testing Policy（渐进式迭代测试约束）

---

## 1. 目标与适用范围

本规则用于约束项目在**渐进式迭代开发**中的测试设计、测试执行与实现状态表达，确保：

- 每次迭代都有**可验证结果**
- 主场景与子链路有**明确测试承载**
- “已实现 / 部分实现 / 未实现”有**统一判定标准**
- 当前实现状态可被测试稳定表达，而不是依赖人工解释

本规则属于**开发过程约束**，不定义仓库总结逻辑。

---

## 2. 术语定义

### 主场景（E2E）
当前系统正在推进的端到端流程，由 `tests/e2e/` 承载。

### 子链路（Integration）
主场景中的一个局部处理闭环，由 `tests/integration/` 承载。

### 最小闭环
在当前阶段可以独立运行并被验证的一段流程。

### 有效断言
能够验证行为结果或关键状态的断言，不允许仅“执行不报错”。

### 受影响测试
受当前改动直接或间接影响，需要重新执行的测试集合。

---

## 3. 总体原则

- 测试必须服务当前迭代目标，禁止过度设计。
- 每次迭代必须留下测试证据。
- 测试优先覆盖行为，而非实现细节。
- 不得通过修改业务语义来让测试通过。
- 不得将“代码存在”视为“功能已实现”。
- 优先最小闭环，再逐步扩展。

---

## 4. 测试框架与执行约束（pytest）

### 4.1 必须使用 pytest

- 所有测试必须基于 pytest
- 禁止混用 unittest / nose

---

### 4.2 目录结构（必须）

```text
tests/
├── unit/
├── smoke/
├── integration/
└── e2e/
```

---

### 4.3 标记（必须注册）

```python
@pytest.mark.unit
@pytest.mark.smoke
@pytest.mark.integration
@pytest.mark.e2e
```

必须在 pytest 配置中注册。

---

### 4.4 执行规则

```bash
pytest
pytest -m unit
pytest -m integration
pytest -m e2e
```

---

### 4.5 Fixture 约束

- 公共 fixture 必须放在 `conftest.py`
- 禁止重复初始化逻辑

---

### 4.6 Mock 约束

- 允许 mock 非核心依赖
- 不得 mock 核心业务路径

---

### 4.7 失败策略（强制）

- 任一必测失败，本次迭代不得视为完成
- 禁止弱断言

---

## 5. 测试分层模型

| 层级 | 作用 |
|------|------|
| 单元测试 | 最小逻辑验证 |
| 冒烟测试 | 最小流程不崩 |
| Integration | 子链路闭环 |
| E2E | 主场景 |
| 回归测试 | 全量执行 |

---

## 6. 场景承载规则

### 6.1 主场景必须落在 E2E（强制）

路径：

```text
tests/e2e/
```

---

### 6.2 E2E 场景头（必须）

```python
"""
Scenario-Name: xxx
Scenario-Goal: xxx

Main-Flow:
1. step [implemented]
2. step [partial]
3. step [not-implemented]

Verification:
- xxx
"""
```

---

### 6.3 Main-Flow 规则（强制）

每一步必须：

- 对应真实处理阶段
- 可映射到代码或测试
- 标注状态：

```text
[implemented | partial | not-implemented]
```

---

### 6.4 子链路必须落在 Integration

- 每个文件只验证一个子链路
- 必须包含输入 / 执行 / 断言

---

## 7. E2E 与 Integration 映射（强制）

\[
implemented\ step \Rightarrow 至少一个\ integration\ 测试
\]

否则不得标记为 implemented。

---

## 8. 实现状态判定（强制）

\[
implemented = 实现 + 测试 + 有效断言 + 可稳定执行
\]

| 条件 | 状态 |
|------|------|
| 完整支撑 | implemented |
| 支撑不完整 | partial |
| 无测试 | not-implemented |

---

### 保守规则（必须）

- 无法确认 → `partial`
- 无测试 → `not-implemented`
- 无断言 → 不得标 implemented

---

## 9. 改动类型定义

| 类型 | 含义 |
|------|------|
| amend | 小改 |
| debug | 排查 |
| fix | 修复 |
| feature-step | 完成步骤 |
| feature-scene-update | 改场景 |
| feature-new-scene | 新场景 |

---

## 10. 改动类型 → 最小测试要求（强制）

| 类型 | 最小必测 | 更新E2E | 回归 |
|------|----------|--------|------|
| amend | 单元 / integration | 否 | 否 |
| debug | 复现测试 | 否 | 否 |
| fix | 复现 + 单元 + integration | 视情况 | 是 |
| feature-step | integration + 单元 | 是（如影响主流程） | 否 |
| feature-scene-update | E2E + integration | 是 | 视情况 |
| feature-new-scene | E2E + integration | 是 | 否 |

---

## 11. 测试升级条件

### 升级到冒烟
- 修改入口 / 调度 / 主循环

### 升级到 E2E
- 修改主流程
- 完成步骤
- 修复主场景问题

### 升级到回归
- 多模块变更
- 公共接口变化
- 发版前

---

## 12. 默认执行策略

### 每次修改后（必须）
- 单元
- 受影响 integration
- 必要时冒烟

---

### 子链路完成后（必须）
- integration
- 更新 E2E 状态

---

### 主场景推进后（必须）
- E2E + integration

---

### 发版前（必须）
- 全量回归

---

## 13. 契约测试

适用于：

- 接口
- schema
- 数据格式

---

## 14. 禁止事项

- 不补测试直接改代码
- 无 integration 标 implemented
- E2E 写未来能力
- 用代码存在当实现
- 修改语义让测试通过

---

## 15. 最低完成标准（强制）

一次迭代必须满足：

- 明确改动类型
- 有对应测试
- 更新 E2E（如影响）
- 测试通过

否则视为未完成。

---