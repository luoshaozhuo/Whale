---
name: 重构 Python 代码质量检查 Skill
overview: 创建一个简洁的 Python 代码质量检查 Skill，完全依赖 LLM 能力，删除外部脚本和多余文档
todos:
  - id: cleanup-files
    content: 删除 scripts、references 目录和所有测试文件
    status: completed
  - id: rewrite-skill-md
    content: 按照官网 YAML 格式重写 SKILL.md，完全依赖 LLM 能力
    status: completed
    dependencies:
      - cleanup-files
  - id: update-codebuddy-md
    content: 更新 CODEBUDDY.md 目录结构说明，移除 scripts 和 references 引用
    status: completed
    dependencies:
      - rewrite-skill-md
  - id: verify-skill
    content: 验证重构后的 Skill 能正确触发和工作
    status: completed
    dependencies:
      - update-codebuddy-md
---

## 用户需求

重构 Python 代码质量检查 Skill，创建一个完全依赖 LLM 能力的简洁版本。

## 核心要求

1. 删除所有多余的说明文档（scripts、references、测试文件等）
2. 重写 SKILL.md，完全依赖 LLM 能力，不依赖外部脚本
3. 按照官网 YAML 格式编写，内容编排简洁明了
4. 在 Skill 流程中直接描述检查步骤，不依赖外部工具
5. 完全交给 LLM 修复故障，不保留"自动修复范围"等外部依赖描述

## 技术方案

### 重构策略

1. **删除冗余文件**：移除所有 scripts、references、测试文件等外部依赖
2. **简化 Skill 定义**：按照官网 YAML 格式重写，完全依赖 LLM 能力
3. **LLM 驱动检查**：在 Skill 流程中直接描述检查步骤，由 LLM 执行检查和修复
4. **项目配置集成**：读取项目配置文件（pyproject.toml、.flake8）指导检查

### 实现要点

1. **简洁的 YAML 头部**：符合官网格式，包含 name、description、context、agent、user-invocable、allowed-tools
2. **LLM 检查流程**：在 Skill 中直接描述 Black、isort、Flake8、mypy 检查步骤
3. **智能修复能力**：由 LLM 分析问题并提供修复方案，不依赖外部脚本
4. **项目配置感知**：读取项目配置文件，确保检查符合项目标准

### 目录结构调整

```
Whale/.codebuddy/skills/python-code-quality-checker/
├── SKILL.md              # [MODIFY] 重写为简洁的 LLM 驱动版本
└── (删除所有其他文件和目录)
```

### 关键修改

1. **SKILL.md 重写**：按照官网格式，完全依赖 LLM 能力
2. **删除 scripts/**：移除 run_checks.py、auto_fix.py 等外部脚本
3. **删除 references/**：移除错误代码和最佳实践参考文档
4. **删除测试文件**：移除 test_skill.py
5. **更新 CODEBUDDY.md**：更新目录结构说明，移除 scripts 和 references 引用