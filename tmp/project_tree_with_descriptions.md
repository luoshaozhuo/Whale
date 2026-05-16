# 当前项目完整目录树（含每个条目说明）

说明：已排除 .git、.conda、__pycache__、.pytest_cache、.mypy_cache、.ruff_cache、node_modules。

Whale/
├── .claude/  - 目录：Claude 工具配置与项目记忆
│   ├── project-memory.md  - 文件：Markdown 文档
│   ├── settings.json  - 文件：JSON 配置
│   └── settings.local.json  - 文件：JSON 配置
├── .codex/  - 目录：Codex 代理与策略配置
│   ├── agents/  - 目录：agents 相关内容
│   │   └── python_worker.toml  - 文件：TOML 配置
│   └── policies/  - 目录：policies 相关内容
│       ├── README.md  - 文件：项目总览与使用说明
│       ├── engineering-general.md  - 文件：Markdown 文档
│       ├── python-docstrings.md  - 文件：Markdown 文档
│       ├── python-style.md  - 文件：Markdown 文档
│       ├── python-typing.md  - 文件：Markdown 文档
│       └── testing-policy.md  - 文件：Markdown 文档
├── .data/  - 目录：本地运行期数据（隐藏目录）
│   └── ingest/  - 目录：ingest 相关内容
│       └── whale.ingest.db  - 文件：SQLite 数据库
├── .env.ingest.example  - 文件：ingest 环境变量示例
├── .flake8  - 文件：flake8 代码检查配置
├── .gitignore  - 文件：Git 忽略规则
├── .vscode/  - 目录：VS Code 工作区配置
│   └── settings.json  - 文件：JSON 配置
├── AGENTS.md  - 文件：仓库级代理工作规范
├── CLAUDE.md  - 文件：Claude 代理入口说明
├── GIT.md  - 文件：Git 工作流或协作规范
├── README.md  - 文件：项目总览与使用说明
├── config/  - 目录：项目配置文件与模板
├── data/  - 目录：共享或示例数据
│   └── shared/  - 目录：shared 相关内容
├── docker-compose.ingest-dev.yaml  - 文件：ingest 开发环境编排配置
├── docs/  - 目录：项目文档
│   ├── opcua_iec61850_guide.md  - 文件：Markdown 文档
│   ├── performance/  - 目录：性能测试或性能文档
│   │   └── opcua_profiling.md  - 文件：Markdown 文档
│   └── scenario1/  - 目录：scenario1 相关内容
│       ├── prompt001.md  - 文件：Markdown 文档
│       ├── prompt002.md  - 文件：Markdown 文档
│       └── 方案001.md  - 文件：Markdown 文档
├── project_tree.txt  - 文件：项目路径清单（自动生成）
├── pyproject.toml  - 文件：Python 项目构建与工具配置
├── requirements.txt  - 文件：Python 依赖清单
├── scripts/  - 目录：运维/启动脚本
│   └── run_ingest_dev.sh  - 文件：Shell 脚本
├── src/  - 目录：项目源码
│   ├── whale/  - 目录：whale 相关内容
│   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   ├── aggregation/  - 目录：aggregation 相关内容
│   │   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   │   ├── ads.py  - 文件：Python 模块
│   │   │   ├── periodic.py  - 文件：Python 模块
│   │   │   └── realtime.py  - 文件：Python 模块
│   │   ├── ingest/  - 目录：ingest 相关内容
│   │   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   │   ├── adapters/  - 目录：适配器实现（对接外部系统）
│   │   │   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   │   │   ├── config/  - 目录：项目配置文件与模板
│   │   │   │   ├── message/  - 目录：适配器实现（对接外部系统）
│   │   │   │   ├── source/  - 目录：适配器实现（对接外部系统）
│   │   │   │   └── state/  - 目录：适配器实现（对接外部系统）
│   │   │   ├── config.py  - 文件：Python 模块
│   │   │   ├── docs/  - 目录：项目文档
│   │   │   │   ├── DECISIONS.md  - 文件：Markdown 文档
│   │   │   │   └── 设计说明书.md  - 文件：Markdown 文档
│   │   │   ├── entities/  - 目录：领域实体与核心数据模型
│   │   │   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   │   │   ├── node_state.py  - 文件：Python 模块
│   │   │   │   └── source_health_state.py  - 文件：Python 模块
│   │   │   ├── framework/  - 目录：基础设施与框架集成
│   │   │   │   └── persistence/  - 目录：基础设施与框架集成
│   │   │   ├── message_pipeline.py  - 文件：Python 模块
│   │   │   ├── ports/  - 目录：端口接口定义（架构边界）
│   │   │   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   │   │   ├── diagnostics.py  - 文件：Python 模块
│   │   │   │   ├── message/  - 目录：端口接口定义（架构边界）
│   │   │   │   ├── runtime/  - 目录：端口接口定义（架构边界）
│   │   │   │   ├── source/  - 目录：端口接口定义（架构边界）
│   │   │   │   └── state/  - 目录：端口接口定义（架构边界）
│   │   │   ├── runtime/  - 目录：运行期组件与启动逻辑
│   │   │   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   │   │   ├── acquisition_mode.py  - 文件：Python 模块
│   │   │   │   ├── job_status.py  - 文件：Python 模块
│   │   │   │   ├── message_pipeline_settings.py  - 文件：Python 模块
│   │   │   │   ├── scheduler.py  - 文件：Python 模块
│   │   │   │   ├── scheduler_factory.py  - 文件：Python 模块
│   │   │   │   ├── scheduler_job.py  - 文件：Python 模块
│   │   │   │   └── scheduler_settings.py  - 文件：Python 模块
│   │   │   ├── usecases/  - 目录：用例编排与业务流程
│   │   │   │   ├── SourceAcquisitionUseCase .py  - 文件：Python 模块
│   │   │   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   │   │   ├── dtos/  - 目录：用例编排与业务流程
│   │   │   │   └── roles/  - 目录：用例编排与业务流程
│   │   │   └── whale.db  - 文件：SQLite 数据库
│   │   ├── processing/  - 目录：processing 相关内容
│   │   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   │   ├── cleaner.py  - 文件：Python 模块
│   │   │   └── normalizer.py  - 文件：Python 模块
│   │   ├── shared/  - 目录：shared 相关内容
│   │   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   │   ├── enums/  - 目录：enums 相关内容
│   │   │   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   │   │   └── quality.py  - 文件：Python 模块
│   │   │   ├── persistence/  - 目录：persistence 相关内容
│   │   │   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   │   │   ├── base.py  - 文件：Python 模块
│   │   │   │   ├── init_db.py  - 文件：Python 模块
│   │   │   │   ├── orm/  - 目录：orm 相关内容
│   │   │   │   ├── session.py  - 文件：Python 模块
│   │   │   │   └── template/  - 目录：template 相关内容
│   │   │   ├── source/  - 目录：source 相关内容
│   │   │   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   │   │   ├── models.py  - 文件：Python 模块
│   │   │   │   ├── opcua/  - 目录：opcua 相关内容
│   │   │   │   ├── ports.py  - 文件：Python 模块
│   │   │   │   └── scheduling/  - 目录：scheduling 相关内容
│   │   │   └── utils/  - 目录：utils 相关内容
│   │   │       └── time.py  - 文件：Python 模块
│   │   └── storage/  - 目录：storage 相关内容
│   │       └── __init__.py  - 文件：Python 包初始化文件
│   └── whale.egg-info/  - 目录：whale.egg-info 相关内容
│       ├── PKG-INFO  - 文件：PKG-INFO 资源文件
│       ├── SOURCES.txt  - 文件：文本文件
│       ├── dependency_links.txt  - 文件：文本文件
│       ├── requires.txt  - 文件：文本文件
│       └── top_level.txt  - 文件：文本文件
├── tests/  - 目录：测试代码
│   ├── TESTING.md  - 文件：Markdown 文档
│   ├── __init__.py  - 文件：Python 包初始化文件
│   ├── conftest.py  - 文件：pytest 共享夹具与测试配置
│   ├── e2e/  - 目录：e2e 相关内容
│   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   ├── conftest.py  - 文件：pytest 共享夹具与测试配置
│   │   └── helpers.py  - 文件：Python 模块
│   ├── integration/  - 目录：集成测试相关内容
│   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   ├── ingest/  - 目录：集成测试相关内容
│   │   ├── test_fleet_from_repository.py  - 文件：pytest 测试用例
│   │   ├── test_fleet_process_runtime.py  - 文件：pytest 测试用例
│   │   ├── test_framework_db_init.py  - 文件：pytest 测试用例
│   │   └── test_sqlite_config_init.py  - 文件：pytest 测试用例
│   ├── performance/  - 目录：性能测试或性能文档
│   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   ├── endurance/  - 目录：性能测试或性能文档
│   │   │   └── __init__.py  - 文件：Python 包初始化文件
│   │   ├── load/  - 目录：性能测试或性能文档
│   │   │   ├── __init__.py  - 文件：Python 包初始化文件
│   │   │   ├── conftest.py  - 文件：pytest 共享夹具与测试配置
│   │   │   └── test_source_simulation_load.py  - 文件：pytest 测试用例
│   │   └── stress/  - 目录：性能测试或性能文档
│   │       ├── __init__.py  - 文件：Python 包初始化文件
│   │       └── test_acquisition_pipeline_stress.py  - 文件：pytest 测试用例
│   ├── smoke/  - 目录：冒烟测试相关内容
│   │   └── scenario1/  - 目录：冒烟测试相关内容
│   ├── tmp/  - 目录：临时输出、报告与分析产物
│   │   ├── acquisition_pipeline_stress_polling.md  - 文件：Markdown 文档
│   │   ├── acquisition_stress_polling.md  - 文件：Markdown 文档
│   │   ├── analyze_profile.py  - 文件：Python 模块
│   │   ├── charts/  - 目录：charts 相关内容
│   │   │   ├── continuity.png  - 文件：图片资源
│   │   │   ├── continuity_scaling.png  - 文件：图片资源
│   │   │   ├── interval_distribution.png  - 文件：图片资源
│   │   │   ├── intervals_Gather_1t.png  - 文件：图片资源
│   │   │   ├── intervals_Gather_3t.png  - 文件：图片资源
│   │   │   ├── intervals_Gather_5t.png  - 文件：图片资源
│   │   │   ├── intervals_Single_baseline.png  - 文件：图片资源
│   │   │   ├── latency_boxplot.png  - 文件：图片资源
│   │   │   ├── latency_breakdown.png  - 文件：图片资源
│   │   │   ├── latency_cdf.png  - 文件：图片资源
│   │   │   ├── scaling.png  - 文件：图片资源
│   │   │   ├── scaling_latency.png  - 文件：图片资源
│   │   │   ├── source_interval_hist.png  - 文件：图片资源
│   │   │   ├── timeline_single.png  - 文件：图片资源
│   │   │   └── timestamp_timeline.png  - 文件：图片资源
│   │   ├── ingest/  - 目录：ingest 相关内容
│   │   │   ├── polling-results.csv  - 文件：CSV 数据
│   │   │   ├── read-results.csv  - 文件：CSV 数据
│   │   │   └── subscription-results.csv  - 文件：CSV 数据
│   │   ├── load_report_polling.md  - 文件：Markdown 文档
│   │   ├── source_simulation_load_multi_server_report.md  - 文件：Markdown 文档
│   │   ├── source_simulation_load_report.md  - 文件：Markdown 文档
│   │   └── source_simulation_load_single_server_report.md  - 文件：Markdown 文档
│   └── unit/  - 目录：单元测试相关内容
│       ├── __init__.py  - 文件：Python 包初始化文件
│       ├── shared/  - 目录：单元测试相关内容
│       │   └── source/  - 目录：单元测试相关内容
│       │       └── opcua/  - 目录：单元测试相关内容
│       ├── test_config.py  - 文件：pytest 测试用例
│       ├── test_fleet_update_selection.py  - 文件：pytest 测试用例
│       ├── test_kafka_message_publisher.py  - 文件：pytest 测试用例
│       ├── test_opcua_adapter_resolution.py  - 文件：pytest 测试用例
│       ├── test_redis_streams_message_publisher.py  - 文件：pytest 测试用例
│       ├── test_relational_outbox_message_publisher.py  - 文件：pytest 测试用例
│       ├── test_source_acquisition_use_case.py  - 文件：pytest 测试用例
│       ├── test_source_reader.py  - 文件：pytest 测试用例
│       ├── test_source_runtime_config_repository.py  - 文件：pytest 测试用例
│       ├── test_source_scheduling.py  - 文件：pytest 测试用例
│       ├── test_source_simulation_support_sources.py  - 文件：pytest 测试用例
│       └── test_source_subscription.py  - 文件：pytest 测试用例
├── third_party/  - 目录：third_party 相关内容
│   └── open62541/  - 目录：open62541 相关内容
│       ├── .clang-format  - 文件：.clang-format 资源文件
│       ├── .clang-tidy  - 文件：.clang-tidy 资源文件
│       ├── .cquery  - 文件：.cquery 资源文件
│       ├── .dockerignore  - 文件：.dockerignore 资源文件
│       ├── .github/  - 目录：.github 相关内容
│       │   ├── ISSUE_TEMPLATE/  - 目录：ISSUE_TEMPLATE 相关内容
│       │   │   └── bug_report.md  - 文件：Markdown 文档
│       │   ├── dependabot.yml  - 文件：YAML 配置
│       │   ├── lock.yml  - 文件：YAML 配置
│       │   ├── reaction.yml  - 文件：YAML 配置
│       │   ├── semantic.yml  - 文件：YAML 配置
│       │   └── workflows/  - 目录：workflows 相关内容
│       │       ├── build_linux.yml  - 文件：YAML 配置
│       │       ├── build_macos.yml  - 文件：YAML 配置
│       │       ├── build_windows.yml  - 文件：YAML 配置
│       │       ├── build_zephyr.yml  - 文件：YAML 配置
│       │       ├── cifuzz.yml  - 文件：YAML 配置
│       │       ├── codeql.yml  - 文件：YAML 配置
│       │       ├── coverity.yml  - 文件：YAML 配置
│       │       ├── dependent-issues.yml  - 文件：YAML 配置
│       │       ├── doc_upload.yml  - 文件：YAML 配置
│       │       ├── interop_tests.yml  - 文件：YAML 配置
│       │       ├── rebase.yml  - 文件：YAML 配置
│       │       └── release.yml  - 文件：YAML 配置
│       ├── .gitignore  - 文件：Git 忽略规则
│       ├── .gitmodules  - 文件：.gitmodules 资源文件
│       ├── CHANGES.md  - 文件：Markdown 文档
│       ├── CMakeLists.txt  - 文件：文本文件
│       ├── CODE_OF_CONDUCT.md  - 文件：Markdown 文档
│       ├── CONTRIBUTING.md  - 文件：Markdown 文档
│       ├── FEATURES.md  - 文件：Markdown 文档
│       ├── LICENSE  - 文件：LICENSE 资源文件
│       ├── LICENSE-CC0  - 文件：LICENSE-CC0 资源文件
│       ├── README.md  - 文件：项目总览与使用说明
│       ├── SECURITY.md  - 文件：Markdown 文档
│       ├── arch/  - 目录：arch 相关内容
│       │   ├── README.md  - 文件：项目总览与使用说明
│       │   ├── common/  - 目录：common 相关内容
│       │   │   ├── eventloop_common.c  - 文件：eventloop_common.c 资源文件
│       │   │   ├── eventloop_common.h  - 文件：eventloop_common.h 资源文件
│       │   │   ├── eventloop_mqtt.c  - 文件：eventloop_mqtt.c 资源文件
│       │   │   ├── timer.c  - 文件：timer.c 资源文件
│       │   │   └── timer.h  - 文件：timer.h 资源文件
│       │   ├── freertos/  - 目录：freertos 相关内容
│       │   │   ├── clock_freertos.c  - 文件：clock_freertos.c 资源文件
│       │   │   └── freertos.cmake  - 文件：freertos.cmake 资源文件
│       │   ├── lwip/  - 目录：lwip 相关内容
│       │   │   ├── eventloop_lwip.c  - 文件：eventloop_lwip.c 资源文件
│       │   │   ├── eventloop_lwip.h  - 文件：eventloop_lwip.h 资源文件
│       │   │   ├── eventloop_lwip_tcp.c  - 文件：eventloop_lwip_tcp.c 资源文件
│       │   │   └── eventloop_lwip_udp.c  - 文件：eventloop_lwip_udp.c 资源文件
│       │   ├── posix/  - 目录：posix 相关内容
│       │   │   ├── clock_posix.c  - 文件：clock_posix.c 资源文件
│       │   │   ├── eventloop_posix.c  - 文件：eventloop_posix.c 资源文件
│       │   │   ├── eventloop_posix.h  - 文件：eventloop_posix.h 资源文件
│       │   │   ├── eventloop_posix_eth.c  - 文件：eventloop_posix_eth.c 资源文件
│       │   │   ├── eventloop_posix_interrupt.c  - 文件：eventloop_posix_interrupt.c 资源文件
│       │   │   ├── eventloop_posix_tcp.c  - 文件：eventloop_posix_tcp.c 资源文件
│       │   │   └── eventloop_posix_udp.c  - 文件：eventloop_posix_udp.c 资源文件
│       │   └── zephyr/  - 目录：zephyr 相关内容
│       │       ├── Kconfig  - 文件：Kconfig 资源文件
│       │       ├── clock_zephyr.c  - 文件：clock_zephyr.c 资源文件
│       │       ├── eventloop_zephyr.c  - 文件：eventloop_zephyr.c 资源文件
│       │       ├── eventloop_zephyr.h  - 文件：eventloop_zephyr.h 资源文件
│       │       ├── eventloop_zephyr_tcp.c  - 文件：eventloop_zephyr_tcp.c 资源文件
│       │       ├── module.yml  - 文件：YAML 配置
│       │       └── zephyr.cmake  - 文件：zephyr.cmake 资源文件
│       ├── build/  - 目录：build 相关内容
│       │   ├── CMakeCache.txt  - 文件：文本文件
│       │   ├── CMakeFiles/  - 目录：CMakeFiles 相关内容
│       │   │   ├── 3.28.3/  - 目录：3.28.3 相关内容
│       │   │   ├── CMakeConfigureLog.yaml  - 文件：YAML 配置
│       │   │   ├── CMakeDirectoryInformation.cmake  - 文件：CMakeDirectoryInformation.cmake 资源文件
│       │   │   ├── CMakeRuleHashes.txt  - 文件：文本文件
│       │   │   ├── CMakeScratch/  - 目录：CMakeScratch 相关内容
│       │   │   ├── Export/  - 目录：Export 相关内容
│       │   │   ├── Makefile.cmake  - 文件：Makefile.cmake 资源文件
│       │   │   ├── Makefile2  - 文件：Makefile2 资源文件
│       │   │   ├── TargetDirectories.txt  - 文件：文本文件
│       │   │   ├── _CMakeLTOTest-C/  - 目录：_CMakeLTOTest-C 相关内容
│       │   │   ├── cmake.check_cache  - 文件：cmake.check_cache 资源文件
│       │   │   ├── open62541-code-generation.dir/  - 目录：open62541-code-generation.dir 相关内容
│       │   │   ├── open62541-generator-ids-ns0.dir/  - 目录：open62541-generator-ids-ns0.dir 相关内容
│       │   │   ├── open62541-generator-namespace.dir/  - 目录：open62541-generator-namespace.dir 相关内容
│       │   │   ├── open62541-generator-statuscode.dir/  - 目录：open62541-generator-statuscode.dir 相关内容
│       │   │   ├── open62541-generator-transport.dir/  - 目录：open62541-generator-transport.dir 相关内容
│       │   │   ├── open62541-generator-types.dir/  - 目录：open62541-generator-types.dir 相关内容
│       │   │   ├── open62541-object.dir/  - 目录：open62541-object.dir 相关内容
│       │   │   ├── open62541-plugins.dir/  - 目录：open62541-plugins.dir 相关内容
│       │   │   ├── open62541.dir/  - 目录：open62541.dir 相关内容
│       │   │   ├── pkgRedirects/  - 目录：pkgRedirects 相关内容
│       │   │   └── progress.marks  - 文件：progress.marks 资源文件
│       │   ├── Makefile  - 文件：Makefile 资源文件
│       │   ├── bin/  - 目录：bin 相关内容
│       │   │   ├── libopen62541.so  - 文件：libopen62541.so 资源文件
│       │   │   ├── libopen62541.so.1.5  - 文件：libopen62541.so.1.5 资源文件
│       │   │   └── libopen62541.so.1.5.4  - 文件：libopen62541.so.1.5.4 资源文件
│       │   ├── cmake_install.cmake  - 文件：cmake_install.cmake 资源文件
│       │   ├── doc/  - 目录：doc 相关内容
│       │   │   ├── CMakeFiles/  - 目录：CMakeFiles 相关内容
│       │   │   ├── Makefile  - 文件：Makefile 资源文件
│       │   │   └── cmake_install.cmake  - 文件：cmake_install.cmake 资源文件
│       │   ├── doc_src/  - 目录：doc_src 相关内容
│       │   │   ├── building.rst  - 文件：building.rst 资源文件
│       │   │   ├── conf.py  - 文件：Python 模块
│       │   │   ├── core_concepts.rst  - 文件：core_concepts.rst 资源文件
│       │   │   ├── ecc_security.rst  - 文件：ecc_security.rst 资源文件
│       │   │   ├── eventfilter_query/  - 目录：eventfilter_query 相关内容
│       │   │   ├── index.rst  - 文件：index.rst 资源文件
│       │   │   ├── nodeset_compiler.rst  - 文件：nodeset_compiler.rst 资源文件
│       │   │   ├── nodeset_compiler_pump.png  - 文件：图片资源
│       │   │   ├── open62541.png  - 文件：图片资源
│       │   │   ├── open62541_html.png  - 文件：图片资源
│       │   │   ├── plugin.rst  - 文件：plugin.rst 资源文件
│       │   │   ├── requirements.txt  - 文件：Python 依赖清单
│       │   │   ├── toc.rst  - 文件：toc.rst 资源文件
│       │   │   ├── tutorials.rst  - 文件：tutorials.rst 资源文件
│       │   │   ├── ua-wireshark-pubsub.png  - 文件：图片资源
│       │   │   └── ua-wireshark.png  - 文件：图片资源
│       │   ├── install_manifest.txt  - 文件：文本文件
│       │   ├── open62541Config.cmake  - 文件：open62541Config.cmake 资源文件
│       │   ├── open62541ConfigVersion.cmake  - 文件：open62541ConfigVersion.cmake 资源文件
│       │   ├── open62541Targets.cmake  - 文件：open62541Targets.cmake 资源文件
│       │   └── src_generated/  - 目录：src_generated 相关内容
│       │       ├── open62541/  - 目录：open62541 相关内容
│       │       └── open62541.pc  - 文件：open62541.pc 资源文件
│       ├── codecov.yml  - 文件：YAML 配置
│       ├── deps/  - 目录：deps 相关内容
│       │   ├── README.md  - 文件：项目总览与使用说明
│       │   ├── base64.c  - 文件：base64.c 资源文件
│       │   ├── base64.h  - 文件：base64.h 资源文件
│       │   ├── cj5.c  - 文件：cj5.c 资源文件
│       │   ├── cj5.h  - 文件：cj5.h 资源文件
│       │   ├── dtoa.c  - 文件：dtoa.c 资源文件
│       │   ├── dtoa.h  - 文件：dtoa.h 资源文件
│       │   ├── itoa.c  - 文件：itoa.c 资源文件
│       │   ├── itoa.h  - 文件：itoa.h 资源文件
│       │   ├── libc_time.c  - 文件：libc_time.c 资源文件
│       │   ├── libc_time.h  - 文件：libc_time.h 资源文件
│       │   ├── mdnsd/  - 目录：mdnsd 相关内容
│       │   │   ├── .github/  - 目录：.github 相关内容
│       │   │   ├── .gitignore  - 文件：Git 忽略规则
│       │   │   ├── API.md  - 文件：Markdown 文档
│       │   │   ├── ChangeLog.md  - 文件：Markdown 文档
│       │   │   ├── LICENSE  - 文件：LICENSE 资源文件
│       │   │   ├── Makefile.am  - 文件：Makefile.am 资源文件
│       │   │   ├── README.md  - 文件：项目总览与使用说明
│       │   │   ├── autogen.sh  - 文件：Shell 脚本
│       │   │   ├── configure.ac  - 文件：configure.ac 资源文件
│       │   │   ├── examples/  - 目录：examples 相关内容
│       │   │   ├── lib/  - 目录：lib 相关内容
│       │   │   ├── libmdnsd/  - 目录：libmdnsd 相关内容
│       │   │   ├── m4/  - 目录：m4 相关内容
│       │   │   ├── man/  - 目录：man 相关内容
│       │   │   ├── mdnsd.service.in  - 文件：mdnsd.service.in 资源文件
│       │   │   ├── src/  - 目录：项目源码
│       │   │   └── test/  - 目录：test 相关内容
│       │   ├── mp_printf.c  - 文件：mp_printf.c 资源文件
│       │   ├── mp_printf.h  - 文件：mp_printf.h 资源文件
│       │   ├── mqtt-c/  - 目录：mqtt-c 相关内容
│       │   │   ├── .github/  - 目录：.github 相关内容
│       │   │   ├── .gitignore  - 文件：Git 忽略规则
│       │   │   ├── CMakeLists.txt  - 文件：文本文件
│       │   │   ├── Doxyfile  - 文件：Doxyfile 资源文件
│       │   │   ├── LICENSE  - 文件：LICENSE 资源文件
│       │   │   ├── README.md  - 文件：项目总览与使用说明
│       │   │   ├── build.zig  - 文件：build.zig 资源文件
│       │   │   ├── cmake/  - 目录：cmake 相关内容
│       │   │   ├── docs/  - 目录：项目文档
│       │   │   ├── examples/  - 目录：examples 相关内容
│       │   │   ├── include/  - 目录：include 相关内容
│       │   │   ├── makefile  - 文件：makefile 资源文件
│       │   │   ├── src/  - 目录：项目源码
│       │   │   └── tests.c  - 文件：tests.c 资源文件
│       │   ├── musl_inet_pton.c  - 文件：musl_inet_pton.c 资源文件
│       │   ├── musl_inet_pton.h  - 文件：musl_inet_pton.h 资源文件
│       │   ├── nodesetLoader/  - 目录：nodesetLoader 相关内容
│       │   │   ├── .clang-format  - 文件：.clang-format 资源文件
│       │   │   ├── .github/  - 目录：.github 相关内容
│       │   │   ├── .gitignore  - 文件：Git 忽略规则
│       │   │   ├── .gitmodules  - 文件：.gitmodules 资源文件
│       │   │   ├── CMakeLists.txt  - 文件：文本文件
│       │   │   ├── LICENSE  - 文件：LICENSE 资源文件
│       │   │   ├── README.md  - 文件：项目总览与使用说明
│       │   │   ├── backends/  - 目录：backends 相关内容
│       │   │   ├── cmake/  - 目录：cmake 相关内容
│       │   │   ├── conanfile.txt  - 文件：文本文件
│       │   │   ├── coverage/  - 目录：coverage 相关内容
│       │   │   ├── include/  - 目录：include 相关内容
│       │   │   ├── nodesetloader-config.cmake  - 文件：nodesetloader-config.cmake 资源文件
│       │   │   ├── nodesets/  - 目录：nodesets 相关内容
│       │   │   ├── runCppcheck.sh  - 文件：Shell 脚本
│       │   │   ├── runLcov.sh  - 文件：Shell 脚本
│       │   │   ├── src/  - 目录：项目源码
│       │   │   └── tests/  - 目录：测试代码
│       │   ├── open62541_queue.h  - 文件：open62541_queue.h 资源文件
│       │   ├── parse_num.c  - 文件：parse_num.c 资源文件
│       │   ├── parse_num.h  - 文件：parse_num.h 资源文件
│       │   ├── pcg_basic.c  - 文件：pcg_basic.c 资源文件
│       │   ├── pcg_basic.h  - 文件：pcg_basic.h 资源文件
│       │   ├── tr_dirent.h  - 文件：tr_dirent.h 资源文件
│       │   ├── ua-nodeset/  - 目录：ua-nodeset 相关内容
│       │   │   ├── .github/  - 目录：.github 相关内容
│       │   │   ├── ADI/  - 目录：ADI 相关内容
│       │   │   ├── AMB/  - 目录：AMB 相关内容
│       │   │   ├── AML/  - 目录：AML 相关内容
│       │   │   ├── AdditiveManufacturing/  - 目录：AdditiveManufacturing 相关内容
│       │   │   ├── AnsiC/  - 目录：AnsiC 相关内容
│       │   │   ├── AutoID/  - 目录：AutoID 相关内容
│       │   │   ├── BACnet/  - 目录：BACnet 相关内容
│       │   │   ├── CAS/  - 目录：CAS 相关内容
│       │   │   ├── CNC/  - 目录：CNC 相关内容
│       │   │   ├── CSPPlusForMachine/  - 目录：CSPPlusForMachine 相关内容
│       │   │   ├── CommercialKitchenEquipment/  - 目录：CommercialKitchenEquipment 相关内容
│       │   │   ├── CranesHoists/  - 目录：CranesHoists 相关内容
│       │   │   ├── CuttingTool/  - 目录：CuttingTool 相关内容
│       │   │   ├── DEXPI/  - 目录：DEXPI 相关内容
│       │   │   ├── DI/  - 目录：DI 相关内容
│       │   │   ├── DotNet/  - 目录：DotNet 相关内容
│       │   │   ├── ECM/  - 目录：ECM 相关内容
│       │   │   ├── FDI/  - 目录：FDI 相关内容
│       │   │   ├── FDT/  - 目录：FDT 相关内容
│       │   │   ├── GDS/  - 目录：GDS 相关内容
│       │   │   ├── GMS/  - 目录：GMS 相关内容
│       │   │   ├── GPOS/  - 目录：GPOS 相关内容
│       │   │   ├── Glass/  - 目录：Glass 相关内容
│       │   │   ├── I4AAS/  - 目录：I4AAS 相关内容
│       │   │   ├── IA/  - 目录：IA 相关内容
│       │   │   ├── IEC61850/  - 目录：IEC61850 相关内容
│       │   │   ├── IJT/  - 目录：IJT 相关内容
│       │   │   ├── IOLink/  - 目录：IOLink 相关内容
│       │   │   ├── IREDES/  - 目录：IREDES 相关内容
│       │   │   ├── ISA-95/  - 目录：ISA-95 相关内容
│       │   │   ├── ISA95-JOBCONTROL/  - 目录：ISA95-JOBCONTROL 相关内容
│       │   │   ├── LADS/  - 目录：LADS 相关内容
│       │   │   ├── LaserSystems/  - 目录：LaserSystems 相关内容
│       │   │   ├── MDIS/  - 目录：MDIS 相关内容
│       │   │   ├── MTConnect/  - 目录：MTConnect 相关内容
│       │   │   ├── MachineTool/  - 目录：MachineTool 相关内容
│       │   │   ├── MachineVision/  - 目录：MachineVision 相关内容
│       │   │   ├── Machinery/  - 目录：Machinery 相关内容
│       │   │   ├── MetalForming/  - 目录：MetalForming 相关内容
│       │   │   ├── Mining/  - 目录：Mining 相关内容
│       │   │   ├── Onboarding/  - 目录：Onboarding 相关内容
│       │   │   ├── OpenApi/  - 目录：OpenApi 相关内容
│       │   │   ├── OpenSCS/  - 目录：OpenSCS 相关内容
│       │   │   ├── PADIM/  - 目录：PADIM 相关内容
│       │   │   ├── PAEFS/  - 目录：PAEFS 相关内容
│       │   │   ├── PLCopen/  - 目录：PLCopen 相关内容
│       │   │   ├── PNDRV/  - 目录：PNDRV 相关内容
│       │   │   ├── PNEM/  - 目录：PNEM 相关内容
│       │   │   ├── PNENC/  - 目录：PNENC 相关内容
│       │   │   ├── PNGSDGM/  - 目录：PNGSDGM 相关内容
│       │   │   ├── PNRIO/  - 目录：PNRIO 相关内容
│       │   │   ├── POWERLINK/  - 目录：POWERLINK 相关内容
│       │   │   ├── PROFINET/  - 目录：PROFINET 相关内容
│       │   │   ├── PackML/  - 目录：PackML 相关内容
│       │   │   ├── PlasticsRubber/  - 目录：PlasticsRubber 相关内容
│       │   │   ├── Powertrain/  - 目录：Powertrain 相关内容
│       │   │   ├── Pumps/  - 目录：Pumps 相关内容
│       │   │   ├── RSL/  - 目录：RSL 相关内容
│       │   │   ├── Robotics/  - 目录：Robotics 相关内容
│       │   │   ├── Safety/  - 目录：Safety 相关内容
│       │   │   ├── Scales/  - 目录：Scales 相关内容
│       │   │   ├── Scheduler/  - 目录：Scheduler 相关内容
│       │   │   ├── Schema/  - 目录：Schema 相关内容
│       │   │   ├── Sercos/  - 目录：Sercos 相关内容
│       │   │   ├── Shotblasting/  - 目录：Shotblasting 相关内容
│       │   │   ├── SurfaceTechnology/  - 目录：SurfaceTechnology 相关内容
│       │   │   ├── TMC/  - 目录：TMC 相关内容
│       │   │   ├── TTD/  - 目录：TTD 相关内容
│       │   │   ├── UAFX/  - 目录：UAFX 相关内容
│       │   │   ├── WMTP/  - 目录：WMTP 相关内容
│       │   │   ├── Weihenstephan/  - 目录：Weihenstephan 相关内容
│       │   │   ├── WireHarness/  - 目录：WireHarness 相关内容
│       │   │   ├── WoT/  - 目录：WoT 相关内容
│       │   │   ├── Woodworking/  - 目录：Woodworking 相关内容
│       │   │   ├── XML/  - 目录：XML 相关内容
│       │   │   └── readme.md  - 文件：Markdown 文档
│       │   ├── utf8.c  - 文件：utf8.c 资源文件
│       │   ├── utf8.h  - 文件：utf8.h 资源文件
│       │   ├── yxml.c  - 文件：yxml.c 资源文件
│       │   ├── yxml.h  - 文件：yxml.h 资源文件
│       │   ├── ziptree.c  - 文件：ziptree.c 资源文件
│       │   └── ziptree.h  - 文件：ziptree.h 资源文件
│       ├── doc/  - 目录：doc 相关内容
│       │   ├── CMakeLists.txt  - 文件：文本文件
│       │   ├── building.rst  - 文件：building.rst 资源文件
│       │   ├── conf.py  - 文件：Python 模块
│       │   ├── core_concepts.rst  - 文件：core_concepts.rst 资源文件
│       │   ├── ecc_security.rst  - 文件：ecc_security.rst 资源文件
│       │   ├── eventfilter_query/  - 目录：eventfilter_query 相关内容
│       │   │   ├── ETFA2024 - A Query Language for OPC UA Event Filters.pdf  - 文件：ETFA2024 - A Query Language for OPC UA Event Filters.pdf 资源文件
│       │   │   ├── ETFA2024 Slides - A Query Language for OPC UA Event Filters.pdf  - 文件：ETFA2024 Slides - A Query Language for OPC UA Event Filters.pdf 资源文件
│       │   │   ├── case_0.rst  - 文件：case_0.rst 资源文件
│       │   │   ├── case_1.rst  - 文件：case_1.rst 资源文件
│       │   │   ├── case_2.rst  - 文件：case_2.rst 资源文件
│       │   │   ├── case_3.rst  - 文件：case_3.rst 资源文件
│       │   │   ├── case_4.rst  - 文件：case_4.rst 资源文件
│       │   │   ├── eventFilter.svg  - 文件：矢量图资源
│       │   │   ├── generate_query_language_ebnf.py  - 文件：Python 模块
│       │   │   ├── literal.svg  - 文件：矢量图资源
│       │   │   ├── nodeId.svg  - 文件：矢量图资源
│       │   │   ├── operand.svg  - 文件：矢量图资源
│       │   │   ├── operator.svg  - 文件：矢量图资源
│       │   │   └── simpleAttributeOperand.svg  - 文件：矢量图资源
│       │   ├── index.rst  - 文件：index.rst 资源文件
│       │   ├── nodeset_compiler.rst  - 文件：nodeset_compiler.rst 资源文件
│       │   ├── nodeset_compiler_pump.png  - 文件：图片资源
│       │   ├── open62541.png  - 文件：图片资源
│       │   ├── open62541_html.png  - 文件：图片资源
│       │   ├── plugin.rst  - 文件：plugin.rst 资源文件
│       │   ├── requirements.txt  - 文件：Python 依赖清单
│       │   ├── toc.rst  - 文件：toc.rst 资源文件
│       │   ├── tutorials.rst  - 文件：tutorials.rst 资源文件
│       │   ├── ua-wireshark-pubsub.png  - 文件：图片资源
│       │   └── ua-wireshark.png  - 文件：图片资源
│       ├── examples/  - 目录：examples 相关内容
│       │   ├── CMakeLists.txt  - 文件：文本文件
│       │   ├── access_control/  - 目录：access_control 相关内容
│       │   │   ├── client_access_control.c  - 文件：client_access_control.c 资源文件
│       │   │   ├── client_access_control_encrypt.c  - 文件：client_access_control_encrypt.c 资源文件
│       │   │   ├── server_access_control.c  - 文件：server_access_control.c 资源文件
│       │   │   └── server_rbac.c  - 文件：server_rbac.c 资源文件
│       │   ├── ci_server.c  - 文件：ci_server.c 资源文件
│       │   ├── client.c  - 文件：client.c 资源文件
│       │   ├── client_async.c  - 文件：client_async.c 资源文件
│       │   ├── client_connect.c  - 文件：client_connect.c 资源文件
│       │   ├── client_connect_loop.c  - 文件：client_connect_loop.c 资源文件
│       │   ├── client_historical.c  - 文件：client_historical.c 资源文件
│       │   ├── client_json_config.c  - 文件：client_json_config.c 资源文件
│       │   ├── client_method_async.c  - 文件：client_method_async.c 资源文件
│       │   ├── client_subscription_loop.c  - 文件：client_subscription_loop.c 资源文件
│       │   ├── common.h  - 文件：common.h 资源文件
│       │   ├── custom_datatype/  - 目录：custom_datatype 相关内容
│       │   │   ├── client_types_custom.c  - 文件：client_types_custom.c 资源文件
│       │   │   ├── custom_datatype.h  - 文件：custom_datatype.h 资源文件
│       │   │   └── server_types_custom.c  - 文件：server_types_custom.c 资源文件
│       │   ├── discovery/  - 目录：discovery 相关内容
│       │   │   ├── client_find_servers.c  - 文件：client_find_servers.c 资源文件
│       │   │   ├── server_lds.c  - 文件：server_lds.c 资源文件
│       │   │   ├── server_multicast.c  - 文件：server_multicast.c 资源文件
│       │   │   └── server_register.c  - 文件：server_register.c 资源文件
│       │   ├── encryption/  - 目录：encryption 相关内容
│       │   │   ├── README_client_server_tpm_keystore.txt  - 文件：文本文件
│       │   │   ├── client_encryption.c  - 文件：client_encryption.c 资源文件
│       │   │   ├── client_encryption_tpm_keystore.c  - 文件：client_encryption_tpm_keystore.c 资源文件
│       │   │   ├── server_encryption.c  - 文件：server_encryption.c 资源文件
│       │   │   ├── server_encryption_filestore.c  - 文件：server_encryption_filestore.c 资源文件
│       │   │   └── server_encryption_tpm_keystore.c  - 文件：server_encryption_tpm_keystore.c 资源文件
│       │   ├── events/  - 目录：events 相关内容
│       │   │   ├── client_filter_queries.c  - 文件：client_filter_queries.c 资源文件
│       │   │   └── server_random_events.c  - 文件：server_random_events.c 资源文件
│       │   ├── json_config/  - 目录：json_config 相关内容
│       │   │   ├── client_json_config.json5  - 文件：client_json_config.json5 资源文件
│       │   │   ├── client_json_config_minimal.json5  - 文件：client_json_config_minimal.json5 资源文件
│       │   │   └── server_json_config.json5  - 文件：server_json_config.json5 资源文件
│       │   ├── nodeset/  - 目录：nodeset 相关内容
│       │   │   ├── CMakeLists.txt  - 文件：文本文件
│       │   │   ├── Opc.Ua.POWERLINK.NodeSet2.bsd  - 文件：Opc.Ua.POWERLINK.NodeSet2.bsd 资源文件
│       │   │   ├── server_nodeset.c  - 文件：server_nodeset.c 资源文件
│       │   │   ├── server_nodeset.csv  - 文件：CSV 数据
│       │   │   ├── server_nodeset.xml  - 文件：server_nodeset.xml 资源文件
│       │   │   ├── server_nodeset_plcopen.c  - 文件：server_nodeset_plcopen.c 资源文件
│       │   │   ├── server_nodeset_powerlink.c  - 文件：server_nodeset_powerlink.c 资源文件
│       │   │   ├── server_testnodeset.c  - 文件：server_testnodeset.c 资源文件
│       │   │   ├── testnodeset.csv  - 文件：CSV 数据
│       │   │   ├── testnodeset.xml  - 文件：testnodeset.xml 资源文件
│       │   │   └── testtypes.bsd  - 文件：testtypes.bsd 资源文件
│       │   ├── nodeset_loader/  - 目录：nodeset_loader 相关内容
│       │   │   ├── CMakeLists.txt  - 文件：文本文件
│       │   │   ├── nodeset_loader.c  - 文件：nodeset_loader.c 资源文件
│       │   │   └── server_nodeset_loader.c  - 文件：server_nodeset_loader.c 资源文件
│       │   ├── pubsub/  - 目录：pubsub 相关内容
│       │   │   ├── README_pubsub_tpm2_pkcs11.txt  - 文件：文本文件
│       │   │   ├── README_pubsub_tpm_keystore.txt  - 文件：文本文件
│       │   │   ├── example_publisher.bin  - 文件：example_publisher.bin 资源文件
│       │   │   ├── pubsub_publish_encrypted.c  - 文件：pubsub_publish_encrypted.c 资源文件
│       │   │   ├── pubsub_publish_encrypted_tpm.c  - 文件：pubsub_publish_encrypted_tpm.c 资源文件
│       │   │   ├── pubsub_publish_encrypted_tpm_keystore.c  - 文件：pubsub_publish_encrypted_tpm_keystore.c 资源文件
│       │   │   ├── pubsub_subscribe_encrypted.c  - 文件：pubsub_subscribe_encrypted.c 资源文件
│       │   │   ├── pubsub_subscribe_encrypted_tpm.c  - 文件：pubsub_subscribe_encrypted_tpm.c 资源文件
│       │   │   ├── pubsub_subscribe_encrypted_tpm_keystore.c  - 文件：pubsub_subscribe_encrypted_tpm_keystore.c 资源文件
│       │   │   ├── pubsub_subscribe_standalone_dataset.c  - 文件：pubsub_subscribe_standalone_dataset.c 资源文件
│       │   │   ├── server_pubsub_file_configuration.c  - 文件：server_pubsub_file_configuration.c 资源文件
│       │   │   ├── server_pubsub_publisher_iop.c  - 文件：server_pubsub_publisher_iop.c 资源文件
│       │   │   ├── server_pubsub_publisher_on_demand.c  - 文件：server_pubsub_publisher_on_demand.c 资源文件
│       │   │   ├── server_pubsub_subscribe_custom_monitoring.c  - 文件：server_pubsub_subscribe_custom_monitoring.c 资源文件
│       │   │   ├── sks/  - 目录：sks 相关内容
│       │   │   ├── tutorial_pubsub_connection.c  - 文件：tutorial_pubsub_connection.c 资源文件
│       │   │   ├── tutorial_pubsub_mqtt_publish.c  - 文件：tutorial_pubsub_mqtt_publish.c 资源文件
│       │   │   ├── tutorial_pubsub_mqtt_subscribe.c  - 文件：tutorial_pubsub_mqtt_subscribe.c 资源文件
│       │   │   ├── tutorial_pubsub_publish.c  - 文件：tutorial_pubsub_publish.c 资源文件
│       │   │   └── tutorial_pubsub_subscribe.c  - 文件：tutorial_pubsub_subscribe.c 资源文件
│       │   ├── pubsub_realtime/  - 目录：pubsub_realtime 相关内容
│       │   │   ├── README.md  - 文件：项目总览与使用说明
│       │   │   ├── etfa18-pfrommer-tsn-pubsub.pdf  - 文件：etfa18-pfrommer-tsn-pubsub.pdf 资源文件
│       │   │   ├── opc-ua-tsn-wrs.pdf  - 文件：opc-ua-tsn-wrs.pdf 资源文件
│       │   │   ├── server_pubsub_publish_rt_offsets.c  - 文件：server_pubsub_publish_rt_offsets.c 资源文件
│       │   │   ├── server_pubsub_publish_rt_state_machine.c  - 文件：server_pubsub_publish_rt_state_machine.c 资源文件
│       │   │   ├── server_pubsub_subscribe_rt_offsets.c  - 文件：server_pubsub_subscribe_rt_offsets.c 资源文件
│       │   │   └── server_pubsub_subscribe_rt_state_machine.c  - 文件：server_pubsub_subscribe_rt_state_machine.c 资源文件
│       │   ├── server.cpp  - 文件：server.cpp 资源文件
│       │   ├── server_inheritance.c  - 文件：server_inheritance.c 资源文件
│       │   ├── server_instantiation.c  - 文件：server_instantiation.c 资源文件
│       │   ├── server_json_config.c  - 文件：server_json_config.c 资源文件
│       │   ├── server_loglevel.c  - 文件：server_loglevel.c 资源文件
│       │   ├── server_mainloop.c  - 文件：server_mainloop.c 资源文件
│       │   ├── server_repeated_job.c  - 文件：server_repeated_job.c 资源文件
│       │   ├── server_settimestamp.c  - 文件：server_settimestamp.c 资源文件
│       │   ├── tutorial_client_events.c  - 文件：tutorial_client_events.c 资源文件
│       │   ├── tutorial_client_firststeps.c  - 文件：tutorial_client_firststeps.c 资源文件
│       │   ├── tutorial_datatypes.c  - 文件：tutorial_datatypes.c 资源文件
│       │   ├── tutorial_server_alarms_conditions.c  - 文件：tutorial_server_alarms_conditions.c 资源文件
│       │   ├── tutorial_server_datasource.c  - 文件：tutorial_server_datasource.c 资源文件
│       │   ├── tutorial_server_events.c  - 文件：tutorial_server_events.c 资源文件
│       │   ├── tutorial_server_firststeps.c  - 文件：tutorial_server_firststeps.c 资源文件
│       │   ├── tutorial_server_historicaldata.c  - 文件：tutorial_server_historicaldata.c 资源文件
│       │   ├── tutorial_server_historicaldata_circular.c  - 文件：tutorial_server_historicaldata_circular.c 资源文件
│       │   ├── tutorial_server_method.c  - 文件：tutorial_server_method.c 资源文件
│       │   ├── tutorial_server_method_async.c  - 文件：tutorial_server_method_async.c 资源文件
│       │   ├── tutorial_server_monitoreditems.c  - 文件：tutorial_server_monitoreditems.c 资源文件
│       │   ├── tutorial_server_object.c  - 文件：tutorial_server_object.c 资源文件
│       │   ├── tutorial_server_reverseconnect.c  - 文件：tutorial_server_reverseconnect.c 资源文件
│       │   ├── tutorial_server_variable.c  - 文件：tutorial_server_variable.c 资源文件
│       │   ├── tutorial_server_variabletype.c  - 文件：tutorial_server_variabletype.c 资源文件
│       │   └── zephyr/  - 目录：zephyr 相关内容
│       │       └── server/  - 目录：server 相关内容
│       ├── include/  - 目录：include 相关内容
│       │   └── open62541/  - 目录：open62541 相关内容
│       │       ├── client.h  - 文件：client.h 资源文件
│       │       ├── client_highlevel.h  - 文件：client_highlevel.h 资源文件
│       │       ├── client_highlevel_async.h  - 文件：client_highlevel_async.h 资源文件
│       │       ├── client_subscriptions.h  - 文件：client_subscriptions.h 资源文件
│       │       ├── common.h  - 文件：common.h 资源文件
│       │       ├── config.h.in  - 文件：config.h.in 资源文件
│       │       ├── plugin/  - 目录：plugin 相关内容
│       │       ├── pubsub.h  - 文件：pubsub.h 资源文件
│       │       ├── server.h  - 文件：server.h 资源文件
│       │       ├── server_pubsub.h  - 文件：server_pubsub.h 资源文件
│       │       ├── types.h  - 文件：types.h 资源文件
│       │       └── util.h  - 文件：util.h 资源文件
│       ├── plugins/  - 目录：plugins 相关内容
│       │   ├── README.md  - 文件：项目总览与使用说明
│       │   ├── crypto/  - 目录：crypto 相关内容
│       │   │   ├── mbedtls/  - 目录：mbedtls 相关内容
│       │   │   ├── openssl/  - 目录：openssl 相关内容
│       │   │   ├── pkcs11/  - 目录：pkcs11 相关内容
│       │   │   ├── ua_certificategroup_filestore.c  - 文件：ua_certificategroup_filestore.c 资源文件
│       │   │   ├── ua_certificategroup_none.c  - 文件：ua_certificategroup_none.c 资源文件
│       │   │   ├── ua_filestore_common.c  - 文件：ua_filestore_common.c 资源文件
│       │   │   ├── ua_filestore_common.h  - 文件：ua_filestore_common.h 资源文件
│       │   │   ├── ua_securitypolicy_filestore.c  - 文件：ua_securitypolicy_filestore.c 资源文件
│       │   │   └── ua_securitypolicy_none.c  - 文件：ua_securitypolicy_none.c 资源文件
│       │   ├── historydata/  - 目录：historydata 相关内容
│       │   │   ├── ua_history_data_backend_memory.c  - 文件：ua_history_data_backend_memory.c 资源文件
│       │   │   ├── ua_history_data_gathering_default.c  - 文件：ua_history_data_gathering_default.c 资源文件
│       │   │   └── ua_history_database_default.c  - 文件：ua_history_database_default.c 资源文件
│       │   ├── include/  - 目录：include 相关内容
│       │   │   └── open62541/  - 目录：open62541 相关内容
│       │   ├── ua_accesscontrol_default.c  - 文件：ua_accesscontrol_default.c 资源文件
│       │   ├── ua_config_default.c  - 文件：ua_config_default.c 资源文件
│       │   ├── ua_config_json.c  - 文件：ua_config_json.c 资源文件
│       │   ├── ua_debug_dump_pkgs.c  - 文件：ua_debug_dump_pkgs.c 资源文件
│       │   ├── ua_log_stdout.c  - 文件：ua_log_stdout.c 资源文件
│       │   ├── ua_log_syslog.c  - 文件：ua_log_syslog.c 资源文件
│       │   ├── ua_nodesetloader.c  - 文件：ua_nodesetloader.c 资源文件
│       │   └── ua_nodestore_ziptree.c  - 文件：ua_nodestore_ziptree.c 资源文件
│       ├── src/  - 目录：项目源码
│       │   ├── client/  - 目录：client 相关内容
│       │   │   ├── ua_client.c  - 文件：ua_client.c 资源文件
│       │   │   ├── ua_client_connect.c  - 文件：ua_client_connect.c 资源文件
│       │   │   ├── ua_client_discovery.c  - 文件：ua_client_discovery.c 资源文件
│       │   │   ├── ua_client_highlevel.c  - 文件：ua_client_highlevel.c 资源文件
│       │   │   ├── ua_client_internal.h  - 文件：ua_client_internal.h 资源文件
│       │   │   ├── ua_client_subscriptions.c  - 文件：ua_client_subscriptions.c 资源文件
│       │   │   └── ua_client_util.c  - 文件：ua_client_util.c 资源文件
│       │   ├── pubsub/  - 目录：pubsub 相关内容
│       │   │   ├── ua_pubsub_config.c  - 文件：ua_pubsub_config.c 资源文件
│       │   │   ├── ua_pubsub_connection.c  - 文件：ua_pubsub_connection.c 资源文件
│       │   │   ├── ua_pubsub_dataset.c  - 文件：ua_pubsub_dataset.c 资源文件
│       │   │   ├── ua_pubsub_internal.h  - 文件：ua_pubsub_internal.h 资源文件
│       │   │   ├── ua_pubsub_keystorage.c  - 文件：ua_pubsub_keystorage.c 资源文件
│       │   │   ├── ua_pubsub_keystorage.h  - 文件：ua_pubsub_keystorage.h 资源文件
│       │   │   ├── ua_pubsub_manager.c  - 文件：ua_pubsub_manager.c 资源文件
│       │   │   ├── ua_pubsub_networkmessage.h  - 文件：ua_pubsub_networkmessage.h 资源文件
│       │   │   ├── ua_pubsub_networkmessage_binary.c  - 文件：ua_pubsub_networkmessage_binary.c 资源文件
│       │   │   ├── ua_pubsub_networkmessage_json.c  - 文件：ua_pubsub_networkmessage_json.c 资源文件
│       │   │   ├── ua_pubsub_ns0.c  - 文件：ua_pubsub_ns0.c 资源文件
│       │   │   ├── ua_pubsub_ns0_sks.c  - 文件：ua_pubsub_ns0_sks.c 资源文件
│       │   │   ├── ua_pubsub_reader.c  - 文件：ua_pubsub_reader.c 资源文件
│       │   │   ├── ua_pubsub_readergroup.c  - 文件：ua_pubsub_readergroup.c 资源文件
│       │   │   ├── ua_pubsub_securitygroup.c  - 文件：ua_pubsub_securitygroup.c 资源文件
│       │   │   ├── ua_pubsub_writer.c  - 文件：ua_pubsub_writer.c 资源文件
│       │   │   └── ua_pubsub_writergroup.c  - 文件：ua_pubsub_writergroup.c 资源文件
│       │   ├── server/  - 目录：server 相关内容
│       │   │   ├── ua_discovery.c  - 文件：ua_discovery.c 资源文件
│       │   │   ├── ua_discovery.h  - 文件：ua_discovery.h 资源文件
│       │   │   ├── ua_discovery_mdns.c  - 文件：ua_discovery_mdns.c 资源文件
│       │   │   ├── ua_discovery_mdns_avahi.c  - 文件：ua_discovery_mdns_avahi.c 资源文件
│       │   │   ├── ua_nodes.c  - 文件：ua_nodes.c 资源文件
│       │   │   ├── ua_server.c  - 文件：ua_server.c 资源文件
│       │   │   ├── ua_server_async.c  - 文件：ua_server_async.c 资源文件
│       │   │   ├── ua_server_async.h  - 文件：ua_server_async.h 资源文件
│       │   │   ├── ua_server_auditing.c  - 文件：ua_server_auditing.c 资源文件
│       │   │   ├── ua_server_binary.c  - 文件：ua_server_binary.c 资源文件
│       │   │   ├── ua_server_config.c  - 文件：ua_server_config.c 资源文件
│       │   │   ├── ua_server_internal.h  - 文件：ua_server_internal.h 资源文件
│       │   │   ├── ua_server_ns0.c  - 文件：ua_server_ns0.c 资源文件
│       │   │   ├── ua_server_ns0_diagnostics.c  - 文件：ua_server_ns0_diagnostics.c 资源文件
│       │   │   ├── ua_server_ns0_gds.c  - 文件：ua_server_ns0_gds.c 资源文件
│       │   │   ├── ua_server_ns0_rbac.c  - 文件：ua_server_ns0_rbac.c 资源文件
│       │   │   ├── ua_server_rbac.c  - 文件：ua_server_rbac.c 资源文件
│       │   │   ├── ua_server_rbac.h  - 文件：ua_server_rbac.h 资源文件
│       │   │   ├── ua_server_utils.c  - 文件：ua_server_utils.c 资源文件
│       │   │   ├── ua_services.c  - 文件：ua_services.c 资源文件
│       │   │   ├── ua_services.h  - 文件：ua_services.h 资源文件
│       │   │   ├── ua_services_attribute.c  - 文件：ua_services_attribute.c 资源文件
│       │   │   ├── ua_services_discovery.c  - 文件：ua_services_discovery.c 资源文件
│       │   │   ├── ua_services_method.c  - 文件：ua_services_method.c 资源文件
│       │   │   ├── ua_services_monitoreditem.c  - 文件：ua_services_monitoreditem.c 资源文件
│       │   │   ├── ua_services_nodemanagement.c  - 文件：ua_services_nodemanagement.c 资源文件
│       │   │   ├── ua_services_securechannel.c  - 文件：ua_services_securechannel.c 资源文件
│       │   │   ├── ua_services_session.c  - 文件：ua_services_session.c 资源文件
│       │   │   ├── ua_services_subscription.c  - 文件：ua_services_subscription.c 资源文件
│       │   │   ├── ua_services_view.c  - 文件：ua_services_view.c 资源文件
│       │   │   ├── ua_session.c  - 文件：ua_session.c 资源文件
│       │   │   ├── ua_session.h  - 文件：ua_session.h 资源文件
│       │   │   ├── ua_subscription.c  - 文件：ua_subscription.c 资源文件
│       │   │   ├── ua_subscription.h  - 文件：ua_subscription.h 资源文件
│       │   │   ├── ua_subscription_alarms_conditions.c  - 文件：ua_subscription_alarms_conditions.c 资源文件
│       │   │   ├── ua_subscription_datachange.c  - 文件：ua_subscription_datachange.c 资源文件
│       │   │   └── ua_subscription_event.c  - 文件：ua_subscription_event.c 资源文件
│       │   ├── ua_securechannel.c  - 文件：ua_securechannel.c 资源文件
│       │   ├── ua_securechannel.h  - 文件：ua_securechannel.h 资源文件
│       │   ├── ua_securechannel_crypto.c  - 文件：ua_securechannel_crypto.c 资源文件
│       │   ├── ua_types.c  - 文件：ua_types.c 资源文件
│       │   ├── ua_types_definition.c  - 文件：ua_types_definition.c 资源文件
│       │   ├── ua_types_encoding_binary.c  - 文件：ua_types_encoding_binary.c 资源文件
│       │   ├── ua_types_encoding_binary.h  - 文件：ua_types_encoding_binary.h 资源文件
│       │   ├── ua_types_encoding_json.c  - 文件：ua_types_encoding_json.c 资源文件
│       │   ├── ua_types_encoding_json.h  - 文件：ua_types_encoding_json.h 资源文件
│       │   ├── ua_types_encoding_xml.c  - 文件：ua_types_encoding_xml.c 资源文件
│       │   ├── ua_types_encoding_xml.h  - 文件：ua_types_encoding_xml.h 资源文件
│       │   └── util/  - 目录：util 相关内容
│       │       ├── ua_encryptedsecret.c  - 文件：ua_encryptedsecret.c 资源文件
│       │       ├── ua_eventfilter_grammar.c  - 文件：ua_eventfilter_grammar.c 资源文件
│       │       ├── ua_eventfilter_grammar.y  - 文件：ua_eventfilter_grammar.y 资源文件
│       │       ├── ua_eventfilter_lex.c  - 文件：ua_eventfilter_lex.c 资源文件
│       │       ├── ua_eventfilter_lex.re  - 文件：ua_eventfilter_lex.re 资源文件
│       │       ├── ua_eventfilter_parser.c  - 文件：ua_eventfilter_parser.c 资源文件
│       │       ├── ua_eventfilter_parser.h  - 文件：ua_eventfilter_parser.h 资源文件
│       │       ├── ua_types_lex.c  - 文件：ua_types_lex.c 资源文件
│       │       ├── ua_types_lex.re  - 文件：ua_types_lex.re 资源文件
│       │       ├── ua_util.c  - 文件：ua_util.c 资源文件
│       │       └── ua_util_internal.h  - 文件：ua_util_internal.h 资源文件
│       ├── tests/  - 目录：测试代码
│       │   ├── CMakeLists.txt  - 文件：文本文件
│       │   ├── check_base64.c  - 文件：check_base64.c 资源文件
│       │   ├── check_chunking.c  - 文件：check_chunking.c 资源文件
│       │   ├── check_cj5.c  - 文件：check_cj5.c 资源文件
│       │   ├── check_client_highlevel_read.c  - 文件：check_client_highlevel_read.c 资源文件
│       │   ├── check_client_highlevel_write.c  - 文件：check_client_highlevel_write.c 资源文件
│       │   ├── check_dtoa.c  - 文件：check_dtoa.c 资源文件
│       │   ├── check_encoding_roundtrip.c  - 文件：check_encoding_roundtrip.c 资源文件
│       │   ├── check_eventloop.c  - 文件：check_eventloop.c 资源文件
│       │   ├── check_eventloop_eth.c  - 文件：check_eventloop_eth.c 资源文件
│       │   ├── check_eventloop_interrupt.c  - 文件：check_eventloop_interrupt.c 资源文件
│       │   ├── check_eventloop_mqtt.c  - 文件：check_eventloop_mqtt.c 资源文件
│       │   ├── check_eventloop_tcp.c  - 文件：check_eventloop_tcp.c 资源文件
│       │   ├── check_eventloop_udp.c  - 文件：check_eventloop_udp.c 资源文件
│       │   ├── check_itoa.c  - 文件：check_itoa.c 资源文件
│       │   ├── check_kvm_utils.c  - 文件：check_kvm_utils.c 资源文件
│       │   ├── check_libc_time.c  - 文件：check_libc_time.c 资源文件
│       │   ├── check_mp_printf.c  - 文件：check_mp_printf.c 资源文件
│       │   ├── check_musl_inet_pton.c  - 文件：check_musl_inet_pton.c 资源文件
│       │   ├── check_parse_num.c  - 文件：check_parse_num.c 资源文件
│       │   ├── check_pcg_basic.c  - 文件：check_pcg_basic.c 资源文件
│       │   ├── check_securechannel.c  - 文件：check_securechannel.c 资源文件
│       │   ├── check_timer.c  - 文件：check_timer.c 资源文件
│       │   ├── check_types_builtin.c  - 文件：check_types_builtin.c 资源文件
│       │   ├── check_types_builtin_binary.c  - 文件：check_types_builtin_binary.c 资源文件
│       │   ├── check_types_builtin_json.c  - 文件：check_types_builtin_json.c 资源文件
│       │   ├── check_types_builtin_variant.c  - 文件：check_types_builtin_variant.c 资源文件
│       │   ├── check_types_builtin_xml.c  - 文件：check_types_builtin_xml.c 资源文件
│       │   ├── check_types_copy_complex.c  - 文件：check_types_copy_complex.c 资源文件
│       │   ├── check_types_custom.c  - 文件：check_types_custom.c 资源文件
│       │   ├── check_types_json_decode.c  - 文件：check_types_json_decode.c 资源文件
│       │   ├── check_types_json_encode.c  - 文件：check_types_json_encode.c 资源文件
│       │   ├── check_types_memory.c  - 文件：check_types_memory.c 资源文件
│       │   ├── check_types_nodeid_copy.c  - 文件：check_types_nodeid_copy.c 资源文件
│       │   ├── check_types_order.c  - 文件：check_types_order.c 资源文件
│       │   ├── check_types_order_struct.c  - 文件：check_types_order_struct.c 资源文件
│       │   ├── check_types_parse.c  - 文件：check_types_parse.c 资源文件
│       │   ├── check_types_print.c  - 文件：check_types_print.c 资源文件
│       │   ├── check_types_range.c  - 文件：check_types_range.c 资源文件
│       │   ├── check_types_range_lookup.c  - 文件：check_types_range_lookup.c 资源文件
│       │   ├── check_utf8.c  - 文件：check_utf8.c 资源文件
│       │   ├── check_util_functions.c  - 文件：check_util_functions.c 资源文件
│       │   ├── check_utils.c  - 文件：check_utils.c 资源文件
│       │   ├── check_utils_trustlist_path.c  - 文件：check_utils_trustlist_path.c 资源文件
│       │   ├── check_utils_url_kvm.c  - 文件：check_utils_url_kvm.c 资源文件
│       │   ├── check_xml_encoding_roundtrip.c  - 文件：check_xml_encoding_roundtrip.c 资源文件
│       │   ├── check_yxml.c  - 文件：check_yxml.c 资源文件
│       │   ├── check_ziptree.c  - 文件：check_ziptree.c 资源文件
│       │   ├── client/  - 目录：client 相关内容
│       │   │   ├── certificates.h  - 文件：certificates.h 资源文件
│       │   │   ├── check_activateSession.c  - 文件：check_activateSession.c 资源文件
│       │   │   ├── check_activateSessionAsync.c  - 文件：check_activateSessionAsync.c 资源文件
│       │   │   ├── check_client.c  - 文件：check_client.c 资源文件
│       │   │   ├── check_client_async.c  - 文件：check_client_async.c 资源文件
│       │   │   ├── check_client_async_connect.c  - 文件：check_client_async_connect.c 资源文件
│       │   │   ├── check_client_async_read.c  - 文件：check_client_async_read.c 资源文件
│       │   │   ├── check_client_authentication.c  - 文件：check_client_authentication.c 资源文件
│       │   │   ├── check_client_discovery.c  - 文件：check_client_discovery.c 资源文件
│       │   │   ├── check_client_encryption.c  - 文件：check_client_encryption.c 资源文件
│       │   │   ├── check_client_highlevel.c  - 文件：check_client_highlevel.c 资源文件
│       │   │   ├── check_client_highlevel_readwrite.c  - 文件：check_client_highlevel_readwrite.c 资源文件
│       │   │   ├── check_client_historical_data.c  - 文件：check_client_historical_data.c 资源文件
│       │   │   ├── check_client_json_config.c  - 文件：check_client_json_config.c 资源文件
│       │   │   ├── check_client_securechannel.c  - 文件：check_client_securechannel.c 资源文件
│       │   │   ├── check_client_subscriptions.c  - 文件：check_client_subscriptions.c 资源文件
│       │   │   ├── check_client_subscriptions_datachange.c  - 文件：check_client_subscriptions_datachange.c 资源文件
│       │   │   ├── check_subscriptionWithactivateSession.c  - 文件：check_subscriptionWithactivateSession.c 资源文件
│       │   │   ├── client_json/  - 目录：client_json 相关内容
│       │   │   └── historical_read_test_data.h  - 文件：historical_read_test_data.h 资源文件
│       │   ├── common.h  - 文件：common.h 资源文件
│       │   ├── encryption/  - 目录：encryption 相关内容
│       │   │   ├── certificates.h  - 文件：certificates.h 资源文件
│       │   │   ├── certificates_ca.h  - 文件：certificates_ca.h 资源文件
│       │   │   ├── check_ca_chain.c  - 文件：check_ca_chain.c 资源文件
│       │   │   ├── check_cert_generation.c  - 文件：check_cert_generation.c 资源文件
│       │   │   ├── check_cert_validation_client_response.c  - 文件：check_cert_validation_client_response.c 资源文件
│       │   │   ├── check_certificategroup.c  - 文件：check_certificategroup.c 资源文件
│       │   │   ├── check_crl_validation.c  - 文件：check_crl_validation.c 资源文件
│       │   │   ├── check_csr_generation.c  - 文件：check_csr_generation.c 资源文件
│       │   │   ├── check_ecc_config.c  - 文件：check_ecc_config.c 资源文件
│       │   │   ├── check_encryption_aes128sha256rsaoaep.c  - 文件：check_encryption_aes128sha256rsaoaep.c 资源文件
│       │   │   ├── check_encryption_aes256sha256rsapss.c  - 文件：check_encryption_aes256sha256rsapss.c 资源文件
│       │   │   ├── check_encryption_basic128rsa15.c  - 文件：check_encryption_basic128rsa15.c 资源文件
│       │   │   ├── check_encryption_basic256.c  - 文件：check_encryption_basic256.c 资源文件
│       │   │   ├── check_encryption_basic256sha256.c  - 文件：check_encryption_basic256sha256.c 资源文件
│       │   │   ├── check_encryption_ecc.c  - 文件：check_encryption_ecc.c 资源文件
│       │   │   ├── check_encryption_eccnistp256.c  - 文件：check_encryption_eccnistp256.c 资源文件
│       │   │   ├── check_encryption_key_password.c  - 文件：check_encryption_key_password.c 资源文件
│       │   │   ├── check_gds_informationmodel.c  - 文件：check_gds_informationmodel.c 资源文件
│       │   │   ├── check_update_certificate.c  - 文件：check_update_certificate.c 资源文件
│       │   │   ├── check_update_trustlist.c  - 文件：check_update_trustlist.c 资源文件
│       │   │   ├── check_username_connect_none.c  - 文件：check_username_connect_none.c 资源文件
│       │   │   └── ecc_certificates.h  - 文件：ecc_certificates.h 资源文件
│       │   ├── fuzz/  - 目录：fuzz 相关内容
│       │   │   ├── CMakeLists.txt  - 文件：文本文件
│       │   │   ├── README.md  - 文件：项目总览与使用说明
│       │   │   ├── check_build.sh  - 文件：Shell 脚本
│       │   │   ├── corpus_generator.c  - 文件：corpus_generator.c 资源文件
│       │   │   ├── custom_memory_manager.c  - 文件：custom_memory_manager.c 资源文件
│       │   │   ├── custom_memory_manager.h  - 文件：custom_memory_manager.h 资源文件
│       │   │   ├── fuzz_attributeoperand.cc  - 文件：fuzz_attributeoperand.cc 资源文件
│       │   │   ├── fuzz_base64_decode.cc  - 文件：fuzz_base64_decode.cc 资源文件
│       │   │   ├── fuzz_base64_encode.cc  - 文件：fuzz_base64_encode.cc 资源文件
│       │   │   ├── fuzz_binary_decode.cc  - 文件：fuzz_binary_decode.cc 资源文件
│       │   │   ├── fuzz_binary_message.cc  - 文件：fuzz_binary_message.cc 资源文件
│       │   │   ├── fuzz_binary_message.options  - 文件：fuzz_binary_message.options 资源文件
│       │   │   ├── fuzz_binary_message_corpus/  - 目录：fuzz_binary_message_corpus 相关内容
│       │   │   ├── fuzz_binary_message_header.dict  - 文件：fuzz_binary_message_header.dict 资源文件
│       │   │   ├── fuzz_certificate_parse.cc  - 文件：fuzz_certificate_parse.cc 资源文件
│       │   │   ├── fuzz_client.cc  - 文件：fuzz_client.cc 资源文件
│       │   │   ├── fuzz_config_json.cc  - 文件：fuzz_config_json.cc 资源文件
│       │   │   ├── fuzz_eventfilter_parse.cc  - 文件：fuzz_eventfilter_parse.cc 资源文件
│       │   │   ├── fuzz_json/  - 目录：fuzz_json 相关内容
│       │   │   ├── fuzz_json_decode.cc  - 文件：fuzz_json_decode.cc 资源文件
│       │   │   ├── fuzz_json_decode_encode.cc  - 文件：fuzz_json_decode_encode.cc 资源文件
│       │   │   ├── fuzz_mdns_message.cc  - 文件：fuzz_mdns_message.cc 资源文件
│       │   │   ├── fuzz_mdns_xht.cc  - 文件：fuzz_mdns_xht.cc 资源文件
│       │   │   ├── fuzz_parse_string.cc  - 文件：fuzz_parse_string.cc 资源文件
│       │   │   ├── fuzz_pubsub_binary.cc  - 文件：fuzz_pubsub_binary.cc 资源文件
│       │   │   ├── fuzz_pubsub_connection_config.cc  - 文件：fuzz_pubsub_connection_config.cc 资源文件
│       │   │   ├── fuzz_pubsub_json.cc  - 文件：fuzz_pubsub_json.cc 资源文件
│       │   │   ├── fuzz_server_services.cc  - 文件：fuzz_server_services.cc 资源文件
│       │   │   ├── fuzz_src_ua_util.cc  - 文件：fuzz_src_ua_util.cc 资源文件
│       │   │   ├── fuzz_src_ua_util.options  - 文件：fuzz_src_ua_util.options 资源文件
│       │   │   ├── fuzz_src_ua_util_endpoints.dict  - 文件：fuzz_src_ua_util_endpoints.dict 资源文件
│       │   │   ├── fuzz_tcp_message.cc  - 文件：fuzz_tcp_message.cc 资源文件
│       │   │   ├── fuzz_xml_decode_encode.cc  - 文件：fuzz_xml_decode_encode.cc 资源文件
│       │   │   ├── fuzz_xml_decode_encode.dict  - 文件：fuzz_xml_decode_encode.dict 资源文件
│       │   │   ├── generate_corpus.sh  - 文件：Shell 脚本
│       │   │   ├── oss-fuzz-copy.sh  - 文件：Shell 脚本
│       │   │   └── ua_debug_dump_pkgs_file.c  - 文件：ua_debug_dump_pkgs_file.c 资源文件
│       │   ├── interop/  - 目录：interop 相关内容
│       │   │   ├── README.md  - 文件：项目总览与使用说明
│       │   │   ├── check_interop_client.c  - 文件：check_interop_client.c 资源文件
│       │   │   ├── dotnet/  - 目录：dotnet 相关内容
│       │   │   ├── interop_server.c  - 文件：interop_server.c 资源文件
│       │   │   └── node-opcua/  - 目录：node-opcua 相关内容
│       │   ├── invalid_bit_types.bsd  - 文件：invalid_bit_types.bsd 资源文件
│       │   ├── invalid_bit_types.csv  - 文件：CSV 数据
│       │   ├── multithreading/  - 目录：multithreading 相关内容
│       │   │   ├── check_mt_addDeleteObject.c  - 文件：check_mt_addDeleteObject.c 资源文件
│       │   │   ├── check_mt_addObjectNode.c  - 文件：check_mt_addObjectNode.c 资源文件
│       │   │   ├── check_mt_addVariableNode.c  - 文件：check_mt_addVariableNode.c 资源文件
│       │   │   ├── check_mt_addVariableTypeNode.c  - 文件：check_mt_addVariableTypeNode.c 资源文件
│       │   │   ├── check_mt_readValueAttribute.c  - 文件：check_mt_readValueAttribute.c 资源文件
│       │   │   ├── check_mt_readWriteDelete.c  - 文件：check_mt_readWriteDelete.c 资源文件
│       │   │   ├── check_mt_readWriteDeleteCallback.c  - 文件：check_mt_readWriteDeleteCallback.c 资源文件
│       │   │   ├── check_mt_writeValueAttribute.c  - 文件：check_mt_writeValueAttribute.c 资源文件
│       │   │   ├── deviceObjectType.h  - 文件：deviceObjectType.h 资源文件
│       │   │   └── mt_testing.h  - 文件：mt_testing.h 资源文件
│       │   ├── network_replay/  - 目录：network_replay 相关内容
│       │   │   ├── check_network_replay.c  - 文件：check_network_replay.c 资源文件
│       │   │   ├── prosys_basic256sha256.pcap  - 文件：prosys_basic256sha256.pcap 资源文件
│       │   │   ├── unified_cpp_basic256sha256.pcap  - 文件：unified_cpp_basic256sha256.pcap 资源文件
│       │   │   └── unified_cpp_none.pcap  - 文件：unified_cpp_none.pcap 资源文件
│       │   ├── nodeset-compiler/  - 目录：nodeset-compiler 相关内容
│       │   │   ├── CMakeLists.txt  - 文件：文本文件
│       │   │   ├── Opc.Ua.AutoID.NodeIds.csv  - 文件：CSV 数据
│       │   │   ├── Opc.Ua.AutoID.Types.bsd  - 文件：Opc.Ua.AutoID.Types.bsd 资源文件
│       │   │   ├── check_client_get_remote_datatypes.c  - 文件：check_client_get_remote_datatypes.c 资源文件
│       │   │   ├── check_client_nsMapping.c  - 文件：check_client_nsMapping.c 资源文件
│       │   │   ├── check_nodeset_compiler_adi.c  - 文件：check_nodeset_compiler_adi.c 资源文件
│       │   │   ├── check_nodeset_compiler_autoid.c  - 文件：check_nodeset_compiler_autoid.c 资源文件
│       │   │   ├── check_nodeset_compiler_plc.c  - 文件：check_nodeset_compiler_plc.c 资源文件
│       │   │   ├── check_nodeset_compiler_testnodeset.c  - 文件：check_nodeset_compiler_testnodeset.c 资源文件
│       │   │   ├── cross_ns_base.bsd  - 文件：cross_ns_base.bsd 资源文件
│       │   │   ├── cross_ns_base.csv  - 文件：CSV 数据
│       │   │   ├── cross_ns_diff.bsd  - 文件：cross_ns_diff.bsd 资源文件
│       │   │   ├── cross_ns_diff.csv  - 文件：CSV 数据
│       │   │   ├── cross_ns_same.bsd  - 文件：cross_ns_same.bsd 资源文件
│       │   │   ├── cross_ns_same.csv  - 文件：CSV 数据
│       │   │   ├── test_cross_ns_types.py  - 文件：pytest 测试用例
│       │   │   ├── test_splitNodeidNs.py  - 文件：pytest 测试用例
│       │   │   ├── testnodeset.csv  - 文件：CSV 数据
│       │   │   ├── testnodeset.xml  - 文件：testnodeset.xml 资源文件
│       │   │   └── testtypes.bsd  - 文件：testtypes.bsd 资源文件
│       │   ├── nodeset-loader/  - 目录：nodeset-loader 相关内容
│       │   │   ├── CMakeLists.txt  - 文件：文本文件
│       │   │   ├── check_memory.sh  - 文件：Shell 脚本
│       │   │   ├── check_nodeset_loader_adi.c  - 文件：check_nodeset_loader_adi.c 资源文件
│       │   │   ├── check_nodeset_loader_autoid.c  - 文件：check_nodeset_loader_autoid.c 资源文件
│       │   │   ├── check_nodeset_loader_compare_di.c  - 文件：check_nodeset_loader_compare_di.c 资源文件
│       │   │   ├── check_nodeset_loader_di.c  - 文件：check_nodeset_loader_di.c 资源文件
│       │   │   ├── check_nodeset_loader_input.c  - 文件：check_nodeset_loader_input.c 资源文件
│       │   │   ├── check_nodeset_loader_ordering_di.c  - 文件：check_nodeset_loader_ordering_di.c 资源文件
│       │   │   ├── check_nodeset_loader_plc.c  - 文件：check_nodeset_loader_plc.c 资源文件
│       │   │   ├── check_nodeset_loader_testnodeset.c  - 文件：check_nodeset_loader_testnodeset.c 资源文件
│       │   │   ├── check_nodeset_loader_ua_nodeset.c  - 文件：check_nodeset_loader_ua_nodeset.c 资源文件
│       │   │   ├── client.c  - 文件：client.c 资源文件
│       │   │   ├── run_test.sh  - 文件：Shell 脚本
│       │   │   ├── run_test_ordering.sh  - 文件：Shell 脚本
│       │   │   └── server.c  - 文件：server.c 资源文件
│       │   ├── pubsub/  - 目录：pubsub 相关内容
│       │   │   ├── check_publisher_configuration.bin  - 文件：check_publisher_configuration.bin 资源文件
│       │   │   ├── check_pubsub_configuration.c  - 文件：check_pubsub_configuration.c 资源文件
│       │   │   ├── check_pubsub_connection_ethernet.c  - 文件：check_pubsub_connection_ethernet.c 资源文件
│       │   │   ├── check_pubsub_connection_mqtt.c  - 文件：check_pubsub_connection_mqtt.c 资源文件
│       │   │   ├── check_pubsub_connection_udp.c  - 文件：check_pubsub_connection_udp.c 资源文件
│       │   │   ├── check_pubsub_custom_state_machine.c  - 文件：check_pubsub_custom_state_machine.c 资源文件
│       │   │   ├── check_pubsub_decryption.c  - 文件：check_pubsub_decryption.c 资源文件
│       │   │   ├── check_pubsub_encoding.c  - 文件：check_pubsub_encoding.c 资源文件
│       │   │   ├── check_pubsub_encoding_custom.c  - 文件：check_pubsub_encoding_custom.c 资源文件
│       │   │   ├── check_pubsub_encoding_json.c  - 文件：check_pubsub_encoding_json.c 资源文件
│       │   │   ├── check_pubsub_encryption.c  - 文件：check_pubsub_encryption.c 资源文件
│       │   │   ├── check_pubsub_encryption_aes256.c  - 文件：check_pubsub_encryption_aes256.c 资源文件
│       │   │   ├── check_pubsub_get_state.c  - 文件：check_pubsub_get_state.c 资源文件
│       │   │   ├── check_pubsub_informationmodel.c  - 文件：check_pubsub_informationmodel.c 资源文件
│       │   │   ├── check_pubsub_informationmodel_methods.c  - 文件：check_pubsub_informationmodel_methods.c 资源文件
│       │   │   ├── check_pubsub_mqtt.c  - 文件：check_pubsub_mqtt.c 资源文件
│       │   │   ├── check_pubsub_offset.c  - 文件：check_pubsub_offset.c 资源文件
│       │   │   ├── check_pubsub_pds.c  - 文件：check_pubsub_pds.c 资源文件
│       │   │   ├── check_pubsub_publish.c  - 文件：check_pubsub_publish.c 资源文件
│       │   │   ├── check_pubsub_publish_ethernet.c  - 文件：check_pubsub_publish_ethernet.c 资源文件
│       │   │   ├── check_pubsub_publish_json.c  - 文件：check_pubsub_publish_json.c 资源文件
│       │   │   ├── check_pubsub_publisherid.c  - 文件：check_pubsub_publisherid.c 资源文件
│       │   │   ├── check_pubsub_publishspeed.c  - 文件：check_pubsub_publishspeed.c 资源文件
│       │   │   ├── check_pubsub_sks_client.c  - 文件：check_pubsub_sks_client.c 资源文件
│       │   │   ├── check_pubsub_sks_keystorage.c  - 文件：check_pubsub_sks_keystorage.c 资源文件
│       │   │   ├── check_pubsub_sks_pull.c  - 文件：check_pubsub_sks_pull.c 资源文件
│       │   │   ├── check_pubsub_sks_push.c  - 文件：check_pubsub_sks_push.c 资源文件
│       │   │   ├── check_pubsub_sks_securitygroups.c  - 文件：check_pubsub_sks_securitygroups.c 资源文件
│       │   │   ├── check_pubsub_subscribe.c  - 文件：check_pubsub_subscribe.c 资源文件
│       │   │   ├── check_pubsub_subscribe_encrypted.c  - 文件：check_pubsub_subscribe_encrypted.c 资源文件
│       │   │   ├── check_pubsub_subscribe_msgrcvtimeout.c  - 文件：check_pubsub_subscribe_msgrcvtimeout.c 资源文件
│       │   │   ├── check_pubsub_udp_unicast.c  - 文件：check_pubsub_udp_unicast.c 资源文件
│       │   │   ├── check_subscriber_configuration.bin  - 文件：check_subscriber_configuration.bin 资源文件
│       │   │   └── ethernet_config.h  - 文件：ethernet_config.h 资源文件
│       │   ├── server/  - 目录：server 相关内容
│       │   │   ├── check_accesscontrol.c  - 文件：check_accesscontrol.c 资源文件
│       │   │   ├── check_discovery.c  - 文件：check_discovery.c 资源文件
│       │   │   ├── check_eventfilter_parser.c  - 文件：check_eventfilter_parser.c 资源文件
│       │   │   ├── check_interfaces.c  - 文件：check_interfaces.c 资源文件
│       │   │   ├── check_local_monitored_item.c  - 文件：check_local_monitored_item.c 资源文件
│       │   │   ├── check_monitoreditem_filter.c  - 文件：check_monitoreditem_filter.c 资源文件
│       │   │   ├── check_node_inheritance.c  - 文件：check_node_inheritance.c 资源文件
│       │   │   ├── check_nodes.c  - 文件：check_nodes.c 资源文件
│       │   │   ├── check_nodestore.c  - 文件：check_nodestore.c 资源文件
│       │   │   ├── check_server.c  - 文件：check_server.c 资源文件
│       │   │   ├── check_server_alarmsconditions.c  - 文件：check_server_alarmsconditions.c 资源文件
│       │   │   ├── check_server_asyncop.c  - 文件：check_server_asyncop.c 资源文件
│       │   │   ├── check_server_attr_wrappers.c  - 文件：check_server_attr_wrappers.c 资源文件
│       │   │   ├── check_server_callbacks.c  - 文件：check_server_callbacks.c 资源文件
│       │   │   ├── check_server_client_readwrite.c  - 文件：check_server_client_readwrite.c 资源文件
│       │   │   ├── check_server_diagnostics.c  - 文件：check_server_diagnostics.c 资源文件
│       │   │   ├── check_server_getendpoints.c  - 文件：check_server_getendpoints.c 资源文件
│       │   │   ├── check_server_historical_data.c  - 文件：check_server_historical_data.c 资源文件
│       │   │   ├── check_server_historical_data_circular.c  - 文件：check_server_historical_data_circular.c 资源文件
│       │   │   ├── check_server_jobs.c  - 文件：check_server_jobs.c 资源文件
│       │   │   ├── check_server_json_config.c  - 文件：check_server_json_config.c 资源文件
│       │   │   ├── check_server_monitoringspeed.c  - 文件：check_server_monitoringspeed.c 资源文件
│       │   │   ├── check_server_node_services.c  - 文件：check_server_node_services.c 资源文件
│       │   │   ├── check_server_ns0_diagnostics.c  - 文件：check_server_ns0_diagnostics.c 资源文件
│       │   │   ├── check_server_password.c  - 文件：check_server_password.c 资源文件
│       │   │   ├── check_server_rbac.c  - 文件：check_server_rbac.c 资源文件
│       │   │   ├── check_server_rbac_client.c  - 文件：check_server_rbac_client.c 资源文件
│       │   │   ├── check_server_rbac_interlocked.c  - 文件：check_server_rbac_interlocked.c 资源文件
│       │   │   ├── check_server_rbac_permissions.c  - 文件：check_server_rbac_permissions.c 资源文件
│       │   │   ├── check_server_readspeed.c  - 文件：check_server_readspeed.c 资源文件
│       │   │   ├── check_server_readwrite.c  - 文件：check_server_readwrite.c 资源文件
│       │   │   ├── check_server_reverseconnect.c  - 文件：check_server_reverseconnect.c 资源文件
│       │   │   ├── check_server_speed_addnodes.c  - 文件：check_server_speed_addnodes.c 资源文件
│       │   │   ├── check_server_userspace.c  - 文件：check_server_userspace.c 资源文件
│       │   │   ├── check_server_utils.c  - 文件：check_server_utils.c 资源文件
│       │   │   ├── check_services_attributes.c  - 文件：check_services_attributes.c 资源文件
│       │   │   ├── check_services_attributes_all.c  - 文件：check_services_attributes_all.c 资源文件
│       │   │   ├── check_services_call.c  - 文件：check_services_call.c 资源文件
│       │   │   ├── check_services_nodemanagement.c  - 文件：check_services_nodemanagement.c 资源文件
│       │   │   ├── check_services_nodemanagement_callbacks.c  - 文件：check_services_nodemanagement_callbacks.c 资源文件
│       │   │   ├── check_services_subscriptions.c  - 文件：check_services_subscriptions.c 资源文件
│       │   │   ├── check_services_subscriptions_modify.c  - 文件：check_services_subscriptions_modify.c 资源文件
│       │   │   ├── check_services_view.c  - 文件：check_services_view.c 资源文件
│       │   │   ├── check_session.c  - 文件：check_session.c 资源文件
│       │   │   ├── check_subscription_event_filter.c  - 文件：check_subscription_event_filter.c 资源文件
│       │   │   ├── check_subscription_events.c  - 文件：check_subscription_events.c 资源文件
│       │   │   ├── check_subscription_events_local.c  - 文件：check_subscription_events_local.c 资源文件
│       │   │   ├── historical_read_test_data.h  - 文件：historical_read_test_data.h 资源文件
│       │   │   ├── interface-testmodel.xml  - 文件：interface-testmodel.xml 资源文件
│       │   │   ├── randomindextest_backend.h  - 文件：randomindextest_backend.h 资源文件
│       │   │   └── server_json_config.json5  - 文件：server_json_config.json5 资源文件
│       │   ├── testing-plugins/  - 目录：testing-plugins 相关内容
│       │   │   ├── test_helpers.c  - 文件：test_helpers.c 资源文件
│       │   │   ├── test_helpers.h  - 文件：test_helpers.h 资源文件
│       │   │   ├── testing_clock.c  - 文件：testing_clock.c 资源文件
│       │   │   ├── testing_clock.h  - 文件：testing_clock.h 资源文件
│       │   │   ├── testing_networklayers.c  - 文件：testing_networklayers.c 资源文件
│       │   │   ├── testing_networklayers.h  - 文件：testing_networklayers.h 资源文件
│       │   │   ├── testing_networklayers_pcap.c  - 文件：testing_networklayers_pcap.c 资源文件
│       │   │   ├── testing_policy.c  - 文件：testing_policy.c 资源文件
│       │   │   ├── testing_policy.h  - 文件：testing_policy.h 资源文件
│       │   │   └── thread_wrapper.h  - 文件：thread_wrapper.h 资源文件
│       │   ├── valgrind_check_error.py  - 文件：Python 模块
│       │   └── valgrind_suppressions.supp  - 文件：valgrind_suppressions.supp 资源文件
│       └── tools/  - 目录：辅助工具与模拟器代码
│           ├── amalgamate.py  - 文件：Python 模块
│           ├── c2rst.py  - 文件：Python 模块
│           ├── certs/  - 目录：certs 相关内容
│           │   ├── create_self-signed.py  - 文件：Python 模块
│           │   ├── localhost.cnf  - 文件：localhost.cnf 资源文件
│           │   └── localhost_ecc.cnf  - 文件：localhost_ecc.cnf 资源文件
│           ├── ci/  - 目录：ci 相关内容
│           │   ├── cross-sdk/  - 目录：cross-sdk 相关内容
│           │   ├── linux/  - 目录：linux 相关内容
│           │   └── win/  - 目录：win 相关内容
│           ├── client_config_schema.json  - 文件：JSON 配置
│           ├── cmake/  - 目录：cmake 相关内容
│           │   ├── AssignSourceGroup.cmake  - 文件：AssignSourceGroup.cmake 资源文件
│           │   ├── FindCheck.cmake  - 文件：FindCheck.cmake 资源文件
│           │   ├── FindGcov.cmake  - 文件：FindGcov.cmake 资源文件
│           │   ├── FindLWIP.cmake  - 文件：FindLWIP.cmake 资源文件
│           │   ├── FindLibreSSL.cmake  - 文件：FindLibreSSL.cmake 资源文件
│           │   ├── FindMbedTLS.cmake  - 文件：FindMbedTLS.cmake 资源文件
│           │   ├── FindSphinx.cmake  - 文件：FindSphinx.cmake 资源文件
│           │   ├── FindValgrind.cmake  - 文件：FindValgrind.cmake 资源文件
│           │   ├── Findcodecov.cmake  - 文件：Findcodecov.cmake 资源文件
│           │   ├── Findlibwebsockets.cmake  - 文件：Findlibwebsockets.cmake 资源文件
│           │   ├── SetGitBasedVersion.cmake  - 文件：SetGitBasedVersion.cmake 资源文件
│           │   ├── open62541Config.cmake.in  - 文件：open62541Config.cmake.in 资源文件
│           │   └── open62541Macros.cmake  - 文件：open62541Macros.cmake 资源文件
│           ├── docker/  - 目录：docker 相关内容
│           │   ├── Dockerfile  - 文件：Dockerfile 资源文件
│           │   ├── README.md  - 文件：项目总览与使用说明
│           │   └── TinyDockerfile  - 文件：TinyDockerfile 资源文件
│           ├── gdb-prettyprint.py  - 文件：Python 模块
│           ├── generate_bsd.py  - 文件：Python 模块
│           ├── generate_datatypes.py  - 文件：Python 模块
│           ├── generate_nodeid_header.py  - 文件：Python 模块
│           ├── generate_statuscode_descriptions.py  - 文件：Python 模块
│           ├── nodeset_compiler/  - 目录：nodeset_compiler 相关内容
│           │   ├── NodeID_NS0_Base.txt  - 文件：文本文件
│           │   ├── README.md  - 文件：项目总览与使用说明
│           │   ├── __init__.py  - 文件：Python 包初始化文件
│           │   ├── backend_graphviz.py  - 文件：Python 模块
│           │   ├── backend_open62541.py  - 文件：Python 模块
│           │   ├── datatypes.py  - 文件：Python 模块
│           │   ├── nodes.py  - 文件：Python 模块
│           │   ├── nodeset.py  - 文件：Python 模块
│           │   ├── nodeset_compiler.py  - 文件：Python 模块
│           │   ├── opaque_type_mapping.py  - 文件：Python 模块
│           │   └── type_parser.py  - 文件：Python 模块
│           ├── nodeset_injector/  - 目录：nodeset_injector 相关内容
│           │   ├── CMakeLists.txt  - 文件：文本文件
│           │   ├── empty.bsd.template  - 文件：empty.bsd.template 资源文件
│           │   ├── generate_nodesetinjector.py  - 文件：Python 模块
│           │   └── schema/  - 目录：schema 相关内容
│           ├── open62541.pc.in  - 文件：open62541.pc.in 资源文件
│           ├── schema/  - 目录：schema 相关内容
│           │   ├── Custom.Opc.Ua.Transport.bsd  - 文件：Custom.Opc.Ua.Transport.bsd 资源文件
│           │   ├── NodeIds.csv  - 文件：CSV 数据
│           │   ├── Opc.Ua.NodeSet2.DiagnosticsMinimal.xml  - 文件：Opc.Ua.NodeSet2.DiagnosticsMinimal.xml 资源文件
│           │   ├── Opc.Ua.NodeSet2.EventsMinimal.xml  - 文件：Opc.Ua.NodeSet2.EventsMinimal.xml 资源文件
│           │   ├── Opc.Ua.NodeSet2.HistorizingMinimal.xml  - 文件：Opc.Ua.NodeSet2.HistorizingMinimal.xml 资源文件
│           │   ├── Opc.Ua.NodeSet2.Part8_Subset.xml  - 文件：Opc.Ua.NodeSet2.Part8_Subset.xml 资源文件
│           │   ├── Opc.Ua.NodeSet2.PubSubMinimal.xml  - 文件：Opc.Ua.NodeSet2.PubSubMinimal.xml 资源文件
│           │   ├── Opc.Ua.NodeSet2.Reduced.xml  - 文件：Opc.Ua.NodeSet2.Reduced.xml 资源文件
│           │   ├── Opc.Ua.Types.bsd  - 文件：Opc.Ua.Types.bsd 资源文件
│           │   ├── StatusCode.csv  - 文件：CSV 数据
│           │   ├── datatypes_dataaccess.txt  - 文件：文本文件
│           │   ├── datatypes_diagnostics.txt  - 文件：文本文件
│           │   ├── datatypes_discovery.txt  - 文件：文本文件
│           │   ├── datatypes_historizing.txt  - 文件：文本文件
│           │   ├── datatypes_method.txt  - 文件：文本文件
│           │   ├── datatypes_minimal.txt  - 文件：文本文件
│           │   ├── datatypes_pubsub.txt  - 文件：文本文件
│           │   ├── datatypes_query.txt  - 文件：文本文件
│           │   ├── datatypes_subscriptions.txt  - 文件：文本文件
│           │   ├── datatypes_transport.txt  - 文件：文本文件
│           │   └── datatypes_typedescription.txt  - 文件：文本文件
│           ├── server_config_schema.json  - 文件：JSON 配置
│           ├── tpm_keystore/  - 目录：tpm_keystore 相关内容
│           │   ├── CMakeLists.txt  - 文件：文本文件
│           │   └── cert_encrypt_tpm.c  - 文件：cert_encrypt_tpm.c 资源文件
│           ├── ua-cli/  - 目录：ua-cli 相关内容
│           │   ├── CMakeLists.txt  - 文件：文本文件
│           │   └── ua.c  - 文件：ua.c 资源文件
│           └── ua2json/  - 目录：ua2json 相关内容
│               ├── CMakeLists.txt  - 文件：文本文件
│               ├── README.md  - 文件：项目总览与使用说明
│               ├── examples/  - 目录：examples 相关内容
│               └── ua2json.c  - 文件：ua2json.c 资源文件
├── tools/  - 目录：辅助工具与模拟器代码
│   ├── __init__.py  - 文件：Python 包初始化文件
│   └── source_simulation/  - 目录：source_simulation 相关内容
│       ├── __init__.py  - 文件：Python 包初始化文件
│       ├── adapters/  - 目录：适配器实现（对接外部系统）
│       │   ├── opcua/  - 目录：适配器实现（对接外部系统）
│       │   │   ├── __init__.py  - 文件：Python 包初始化文件
│       │   │   ├── address_space.py  - 文件：Python 模块
│       │   │   ├── asyncua_source_simulator.py  - 文件：Python 模块
│       │   │   ├── docs/  - 目录：项目文档
│       │   │   ├── open62541_source_simulator.py  - 文件：Python 模块
│       │   │   └── templates/  - 目录：适配器实现（对接外部系统）
│       │   └── registry.py  - 文件：Python 模块
│       ├── domain.py  - 文件：Python 模块
│       ├── fleet.py  - 文件：Python 模块
│       ├── open62541_runner/  - 目录：open62541_runner 相关内容
│       │   ├── CMakeLists.txt  - 文件：文本文件
│       │   ├── README.md  - 文件：项目总览与使用说明
│       │   ├── build/  - 目录：build 相关内容
│       │   │   ├── CMakeCache.txt  - 文件：文本文件
│       │   │   ├── CMakeFiles/  - 目录：CMakeFiles 相关内容
│       │   │   ├── Makefile  - 文件：Makefile 资源文件
│       │   │   ├── cmake_install.cmake  - 文件：cmake_install.cmake 资源文件
│       │   │   ├── open62541_client_reader  - 文件：open62541_client_reader 资源文件
│       │   │   └── open62541_source_simulator  - 文件：open62541_source_simulator 资源文件
│       │   ├── open62541_client_reader.c  - 文件：open62541_client_reader.c 资源文件
│       │   └── open62541_source_simulator.c  - 文件：open62541_source_simulator.c 资源文件
│       ├── ports.py  - 文件：Python 模块
│       └── tests/  - 目录：测试代码
│           ├── README.md  - 文件：项目总览与使用说明
│           ├── __init__.py  - 文件：Python 包初始化文件
│           ├── conftest.py  - 文件：pytest 共享夹具与测试配置
│           ├── support/  - 目录：support 相关内容
│           │   ├── __init__.py  - 文件：Python 包初始化文件
│           │   ├── cpu.py  - 文件：Python 模块
│           │   ├── metrics.py  - 文件：Python 模块
│           │   ├── report.py  - 文件：Python 模块
│           │   └── sources.py  - 文件：Python 模块
│           ├── test_open62541_source_simulation_single_server_smoke.py  - 文件：pytest 测试用例
│           ├── test_registry.py  - 文件：pytest 测试用例
│           ├── test_source_simulation_multi_server_capacity.py  - 文件：pytest 测试用例
│           ├── test_source_simulation_multi_server_profile.py  - 文件：pytest 测试用例
│           └── tmp/  - 目录：临时输出、报告与分析产物
│               └── source_polling_scheduler_experiments.md  - 文件：测试说明文档
├── 代码质量与注释.md  - 文件：Markdown 文档
├── 工程管理.md  - 文件：Markdown 文档
└── 测试策略.md  - 文件：Markdown 文档
