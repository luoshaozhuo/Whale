# Whale - 能源数据统一平台

## 项目概述
渐进式开发的能源数据平台，从Level 0数据流开始，逐步构建统一数据底座。

## 开发原则
1. **渐进式**：从最简单用例开始
2. **最简方案**：不过度设计
3. **阶段性重构**：功能稳定后优化架构
4. **测试驱动**：确保迭代可靠性

## 快速开始
```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 安装开发依赖
pip install -e ".[dev]"

# 运行代码检查
flake8 src/
black --check src/
mypy src/

# 运行测试
pytest
```

## 编码规范
- PEP 8标准
- Black格式化（行宽100）
- Google风格文档字符串
- 全面使用类型提示

## 项目结构
```
Whale/
├── src/whale/          # 核心代码
├── tests/              # 测试
├── docs/               # 文档
└── config/             # 配置
```

## 配置说明
- `CODEBUDDY.md`：项目级配置和约束
- `.codebuddy/`：CodeBuddy规则和模板
- `pyproject.toml`：Python工具链配置

## init_db

PYTHONPATH=src python -m whale.ingest.framework.persistence.init_db
