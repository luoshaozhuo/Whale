# Tests Guide

本文档说明本仓库测试的常用运行方式、`pytest` 常见参数，以及 [tests/conftest.py](/home/luosh/Whale/tests/conftest.py:1) 的作用。

## Run Tests

运行默认测试发现范围：

```bash
pytest
```

只运行 `tests/unit/tools`：

```bash
pytest tests/unit/tools
```

只运行当前文件：

```bash
pytest tests/unit/tools/test_opcua_sim_loader.py
```

只运行名称匹配的测试：

```bash
pytest tests/unit/tools/test_opcua_sim_loader.py -k load_server_config
```

只运行 `unit` marker 对应的测试：

```bash
pytest -m unit
```

`tests/unit/tools` 里的测试属于单元测试，一般不需要先手动启动 OPC UA 服务器。

## Output Flags

`pytest` 默认输出适中，适合日常直接运行。

`-q` 表示更简洁：

- 适合只看通过数、失败数和总耗时
- 常见输出类似 `3 passed in 0.02s`

`-v` 表示更详细：

- 会显示更多测试名称和执行信息

`-vv` 表示比 `-v` 更详细：

- 适合调试单个文件或排查失败

常见组合：

```bash
pytest
pytest -q
pytest tests/unit/tools -q
pytest tests/unit/tools -vv
```

## Filter Flags

`-m` 和 `-k` 很容易混淆，但作用不同。

`-m <expr>`：按 `marker` 过滤，也就是按 `@pytest.mark.xxx` 过滤。

例如：

```bash
pytest -m unit
pytest -m integration
```

`-k <expr>`：按名称过滤，匹配文件名、类名、函数名中的文本。

例如：

```bash
pytest -k load_server_config
pytest -k loader
```

可以这样记：

- `-m` = marker
- `-k` = keyword / name match

## Other Useful Flags

`-s`：不捕获 `print` 输出，调试时常用。

`-x`：遇到第一个失败就停止。

`--maxfail=1`：最多失败一个测试后停止。

一个常见调试命令：

```bash
pytest tests/unit/tools/test_opcua_sim_loader.py -vv -s
```

这表示只运行当前文件、使用详细输出，并直接显示 `print` 内容。

## About `conftest.py`

[tests/conftest.py](/home/luosh/Whale/tests/conftest.py:1) 会被 `pytest` 自动加载。

这意味着：

- 里面定义的 fixture 不需要手动注册
- 测试函数只要把 fixture 名写进参数列表，pytest 就会自动准备依赖

这个文件主要负责三类事情：

- 提供场景测试数据路径
- 提供 OPC UA 模板文件路径
- 为集成测试准备本地 OPC UA 运行环境

### Fixture Groups

场景数据相关：

- `scenario1_fixture_dir`
- `sample_scl_path`
- `sample_power_curve_path`
- `sample_raw_payloads`
- `scenario1_registry`
- `scenario1_registry_maps`

OPC UA 模板相关：

- `sample_nodeset_path`
  指向 [tools/opcua_sim/templates/OPCUANodeSet.xml](/home/luosh/Whale/tools/opcua_sim/templates/OPCUANodeSet.xml:1)
- `sample_opcua_connections_path`
  指向 [tools/opcua_sim/templates/OPCUA_client_connections.yaml](/home/luosh/Whale/tools/opcua_sim/templates/OPCUA_client_connections.yaml:1)

OPC UA 集成测试运行环境相关：

- `free_ports`
  分配两个本地空闲端口
- `local_opcua_connections_path`
  基于模板 YAML 生成当前测试专用的 localhost 配置
- `opcua_server_runtime`
  启动单个 OPC UA 模拟服务
- `opcua_sim_fleet`
  启动一组 OPC UA 模拟服务

### Typical Dependency Chain

一个典型例子是 `opcua_sim_fleet`：

- 测试函数依赖 `opcua_sim_fleet`
- `opcua_sim_fleet` 依赖 `sample_nodeset_path` 和 `local_opcua_connections_path`
- `local_opcua_connections_path` 依赖 `sample_opcua_connections_path` 和 `free_ports`

所以测试代码本身可以写得比较短，而服务启动、端口分配、临时配置生成、资源清理这些细节都收敛在 `conftest.py` 中。
