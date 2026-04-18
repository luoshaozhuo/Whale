---
name: summarize-repo-current-state
description: 当你需要生成或更新仓库当前状态 4+1 视图，并希望该过程先自动验证当前仓库是否具备可被可信总结的条件、再基于上一版总结做增量更新时，使用此 Skill。它用于维护绑定提交号、可追溯、渐进演化的当前状态基线，而不是从零重写总结。
---

# 增量更新仓库当前状态

## 一、用途

生成仓库“当前状态基线”，用于：

- 后续 AI 协作
- coding agent 输入
- 当前进度判断

---

## 二、执行顺序（强制）

必须严格按顺序执行：

1. 确认工作区干净
2. 执行 `validate-summary-readiness`
3. 若结果为 allow → 执行总结
4. 否则停止

---

## 三、总结文件

路径：

```
docs/current-state/summarize.md
```

---

## 四、元数据（必须）

```yaml
---
summary_commit: <HEAD>
summary_parent_commit: <上一次commit或空>
summary_mode: bootstrap | incremental
summary_range: <old..new> | full
summary_time: <时间>
summary_gate: passed
---
```

---

## 五、模式

### 1. bootstrap

- 无旧总结
- 全量生成

---

### 2. incremental（默认）

- 读取旧总结
- 只更新受影响部分

---

## 六、核心规则

### 1. 只总结真实状态

禁止：

- 写未来架构
- 猜测模块
- 把规则当实现

---

### 2. 必须增量更新（强制）

流程：

1. 读取旧总结
2. 找变化
3. 局部更新

---

### 3. 结构固定（强制）

必须保持：

1. 当前阶段
2. 逻辑视图
3. 开发视图
4. 协作视图
5. 技术约束
6. 用例视图
7. 空白边界

---

### 4. 未受影响内容不得修改（强制）

禁止：

- 全文重写
- 风格优化重写
- 无关修改

---

## 七、更新动作（仅允许）

- append（新增）
- replace-section（替换章节）
- patch-item（局部修改）

---

## 八、用例视图规则（关键）

必须基于：

- tests/e2e
- tests/integration

禁止：

- 从代码猜用例

---

## 九、章节更新规则

### 修改 tests/e2e

→ 更新用例视图

### 修改 tests/integration

→ 更新用例实现深度

### 修改 rules / skills

→ 更新协作视图、约束视图

### 修改 src

→ 更新逻辑视图

---

## 十、本次更新说明（建议）

可附：

- 本次更新了哪些部分

---

## 十一、首次总结

若无 summarize.md：

- 执行 bootstrap
- 写入 HEAD

---

## 十二、最终规则

总结必须：

- 绑定 commit
- 基于已校验状态
- 增量更新
- 不得重写

---

一句话：

当前状态总结 = 已提交 + 已校验 + 可追溯 + 增量更新