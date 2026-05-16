# open62541 native tools 源码安装与编译

本目录用于编译 source_lab 的 open62541 native tools，而不是单一 runner。

包含两个 executable：

- open62541_source_simulator：用于启动 OPC UA source simulator server。
- open62541_client_reader：用于 high-frequency client read/profile，支持 PREPARE / READ / START_POLL / STOP_POLL 等 stdin 协议。

## 1. 下载 open62541 源码

在 Whale 仓库根目录执行：

```bash
cd ~/Whale
mkdir -p third_party
cd third_party

git clone --depth 1 https://github.com/open62541/open62541.git
cd open62541

git submodule update --init --recursive
```

## 2. 编译并安装 open62541

安装到用户本地目录：

```bash
cmake -S . -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=ON \
  -DUA_ENABLE_AMALGAMATION=OFF \
  -DCMAKE_INSTALL_PREFIX=$HOME/.local/open62541

cmake --build build -j
cmake --install build
```

检查是否安装成功：

```bash
find $HOME/.local/open62541 -name "open62541Config.cmake"
```

正常应看到类似路径：

```text
/home/luosh/.local/open62541/lib/cmake/open62541/open62541Config.cmake
```

## 3. 编译 native tools

回到 Whale 仓库根目录：

```bash
cd ~/Whale
```

执行：

```bash
cmake -S tools/source_lab/opcua/native \
  -B tools/source_lab/opcua/native/build \
  -DCMAKE_PREFIX_PATH=$HOME/.local/open62541

cmake --build tools/source_lab/opcua/native/build
```

编译成功后生成：

```text
tools/source_lab/opcua/native/build/open62541_source_simulator
tools/source_lab/opcua/native/build/open62541_client_reader
```

## 4. 运行 smoke 测试

```bash
cd ~/Whale

SOURCE_SIM_OPCUA_BACKEND=open62541 \
SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false \
python -m pytest tools/source_lab/tests/test_open62541_source_simulation_single_server_smoke.py -s -v
```

## 5. 运行单 server 压测

```bash
cd ~/Whale

SOURCE_SIM_OPCUA_BACKEND=open62541 \
SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false \
SOURCE_SIM_LOAD_HZ_START=1 \
SOURCE_SIM_LOAD_HZ_STEP=2 \
SOURCE_SIM_LOAD_HZ_MAX=200 \
SOURCE_SIM_LOAD_LEVEL_DURATION_S=20 \
SOURCE_SIM_LOAD_WARMUP_S=5 \
python -m pytest tools/source_lab/tests/test_source_simulation_single_server_bottleneck.py -s -v
```

## 6. 常见错误

如果 CMake 报：

```text
Could not find a package configuration file provided by "open62541"
```

说明没有找到：

```text
open62541Config.cmake
```

重新指定路径：

```bash
cmake -S tools/source_lab/opcua/native \
  -B tools/source_lab/opcua/native/build \
  -Dopen62541_DIR=$HOME/.local/open62541/lib/cmake/open62541
```

如果 `git clone` 失败，删除后重试：

```bash
cd ~/Whale/third_party
rm -rf open62541

git clone --depth 1 https://github.com/open62541/open62541.git
```