---
name: python-code-quality-checker
description: Use this skill when you create or modify Python files in this project, when the user asks to check or fix Python code quality, or when code needs to pass Black, isort, Flake8, or mypy.
allowed-tools: Read, Write, Bash
context: fork
---

# Python 代码质量检查与最小修复

当当前任务新增或修改了 Python 文件，或用户要求检查/修复 Python 代码质量问题时，使用本 Skill。

## 项目特有约束

- 配置来源只认项目根目录中的 `pyproject.toml` 和 `.flake8`
- 文档字符串规范为 Google 风格
- 默认先做局部检查，必要时再做全量扫描
- 只做最小必要修复
- 不为通过检查而顺带重构无关代码
- 输出只给结果摘要，不粘贴冗长日志

## 先决条件

先确认以下工具在当前 Python 环境中可用：

- `black`
- `isort`
- `flake8`
- `mypy`
- `pydocstyle`
- `flake8-docstrings`

若缺失：

1. 明确指出缺失工具
2. 给出最小安装命令
3. 停止后续流程，不伪造执行结果

推荐安装命令：

```bash
pip install black isort flake8 mypy pydocstyle flake8-docstrings
```

## 检查范围策略

默认优先检查当前任务直接涉及的 Python 文件。

按以下优先级确定检查范围：

1. 若当前任务已明确给出改动文件列表，优先只检查这些文件
2. 否则，若当前目录是 Git 仓库，优先使用 `git diff` 识别本次改动的 Python 文件
3. 若无法可靠识别改动文件，再退回到全量扫描：
   - `src/`
   - `tests/`

当出现以下任一情况时，应直接执行全量扫描：

- 用户明确要求全量检查、全项目扫描或基线体检
- 当前改动涉及公共基础模块、共享库或影响范围不清晰
- 刚完成一轮较大重构或批量修改
- 局部检查通过，但仍怀疑存在跨模块问题

不要扫描无关目录。

## Git 改动识别要求

优先综合以下来源识别改动文件：

- 未暂存改动
- 已暂存改动

只保留 `.py` 文件。

若 `git diff` 结果为空，但与当前任务上下文明显不符，不要盲目认为“无改动”，应退回到全量扫描。

## 执行清单

按以下顺序执行，并在每一步后根据结果决定是否继续：

- [ ] 确定检查范围
- [ ] 运行 Black
- [ ] 运行 isort
- [ ] 运行 Flake8
- [ ] 运行 mypy
- [ ] 修复当前任务直接相关的问题
- [ ] 重新运行受影响的检查
- [ ] 输出结果摘要

## 默认命令

局部检查时，对目标文件集合执行：

```bash
black <targets>
isort <targets>
flake8 <targets>
mypy <targets>
```

全量扫描时，默认执行：

```bash
black src tests
isort src tests
flake8 src tests
mypy src tests
```

若项目实际目录不完整，应只对存在的目标执行，不要因缺少目录而报假错误。

## 处理规则

### Black

- 直接格式化
- 以 `pyproject.toml` 为准
- 不手工制造与 Black 冲突的格式

### isort

- 直接整理导入
- 与 Black 风格保持一致
- 删除当前改动引入的未使用导入

### Flake8

优先处理：

- 未使用 import
- 未使用变量
- 当前改动引入的风格问题
- 当前改动引入的文档字符串问题

处理要求：

- `__init__.py` 按项目配置处理
- 不为了消除告警而改动无关逻辑
- 不无理由加入 `noqa`

### mypy

优先处理：

- 当前改动涉及的公共函数、公共方法类型问题
- 当前改动引入的明显类型不一致
- 当前改动涉及的核心内部函数类型问题

处理要求：

- 不无理由引入 `Any`
- 不滥用 `type: ignore`
- 若必须忽略，范围要最小

## 文档字符串要求

当 Flake8 / docstring 检查报错，按以下规则修复：

- 类、公共函数、公共方法应提供 Google 风格文档字符串
- 文档字符串说明职责、输入、输出和必要异常
- 无参数或无返回值时，不强制补 `Args` 或 `Returns`
- 不机械复述代码表面行为
- 模块级和包级文档字符串按当前 `.flake8` 配置执行

## Gotchas

- `docstring-convention = google` 依赖 `flake8-docstrings`；若未安装，Flake8 不会按预期检查 Google 风格文档字符串
- `pydocstyle` 是配套工具，不替代 Flake8；当前统一以 Flake8 输出为主
- `mypy` 可能因项目导入路径或第三方依赖缺失而报环境相关错误；这类问题要与当前改动引入的问题分开说明
- 若 `context: fork` 下无法直接继承主任务里的改动文件信息，应优先依赖文件列表或 `git diff`，不要主观猜测范围

## 修复边界

可以直接修复：

- Black 格式问题
- isort 导入顺序问题
- 当前改动引入的未使用 import
- 当前改动引入的简单 Flake8 问题
- 当前改动涉及的明显 Google 风格文档字符串问题
- 当前改动涉及的明显类型问题

不要擅自修复：

- 与当前任务无关的历史遗留问题
- 大范围结构重构
- 核心业务逻辑改写
- 仅为消除告警而删除可疑但可能有效的代码

## 验证循环

每次修复后：

1. 只重新运行受影响的检查
2. 若仍失败，继续最小修复
3. 直到：
   - 当前任务范围内通过；或
   - 发现阻塞问题并可明确说明原因

## 输出模板

最终只输出摘要，使用以下结构：

```text
检查范围：
已执行工具：
已自动修复：
剩余问题：
结论：
```

结论只允许两类：

- `当前任务范围内检查通过`
- `未完全通过，阻塞原因已明确说明`

若存在历史遗留问题，单独标注为“既有问题”，不要混入本次改动问题。