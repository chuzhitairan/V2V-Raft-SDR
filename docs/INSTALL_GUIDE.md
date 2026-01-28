# V2V-Raft-SDR 环境搭建标准指南

本文档提供了在 **Ubuntu 24.04 LTS (GCC 13)** 环境下部署本项目的**标准正确路径**。遵循此流程可避免 ABI 不兼容、Python 路径隔离以及库冲突等常见问题。

## 📋 1. 环境准备 (Prerequisites)

### 1.1 安装基础依赖

```bash
sudo apt update
sudo apt install -y \
    git cmake g++ build-essential libboost-all-dev libgmp-dev swig python3-numpy \
    python3-mako python3-sphinx python3-lxml doxygen libfftw3-dev \
    libsdl1.2-dev libgsl-dev libqwt-qt5-dev libqt5opengl5-dev python3-pyqt5 \
    liblog4cpp5-dev libzmq3-dev python3-yaml python3-click python3-click-plugins \
    python3-zmq python3-scipy python3-gi python3-docutils controlport \
    gnuradio gnuradio-dev gr-osmosdr uhd-host libuhd-dev

```

### 1.2 🧹 环境清理 (至关重要)

**这是最关键的一步。** 许多报错是因为系统同时存在 `apt` 安装的库（在 `/usr/lib`）和手动编译的旧库（在 `/usr/local/lib`）。

在编译新模块前，请务必执行以下命令清理“幽灵”文件：

```bash
# 清除 /usr/local 下残留的 GNU Radio 和 UHD 库
sudo rm -rf /usr/local/lib/libgnuradio*
sudo rm -rf /usr/local/lib/libuhd*
sudo rm -rf /usr/local/include/gnuradio
sudo rm -rf /usr/local/include/uhd
sudo rm -f /usr/local/bin/uhd_*

# 刷新系统库缓存
sudo ldconfig

```

---

## 🛠️ 2. OOT 模块编译安装 (标准流程)

本项目依赖 `gr-foo` 和 `gr-ieee802-11`。在 Ubuntu 24.04 下，必须使用特定的 CMake 参数来确何与系统 GCC 13 编译器及 Python 环境的兼容性。

### ✅ 核心编译参数说明

* `-DCMAKE_INSTALL_PREFIX=/usr`: 覆盖系统路径，避免优先级冲突。
* `-DGR_PYTHON_DIR=/usr/lib/python3/dist-packages`: **解决 Python 路径隔离问题的关键**。强制安装到系统目录，防止 `ImportError`。
* `-DCMAKE_CXX_FLAGS="-D_GLIBCXX_USE_C99_MATH=1"`: **解决 GCC 13 `isnan` 报错的关键**。

### 2.1 安装 gr-foo

```bash
cd ~
git clone https://github.com/bastibl/gr-foo.git
cd gr-foo

# 创建构建目录（如果已有，建议先 rm -rf build 清除）
rm -rf build && mkdir build && cd build

# 黄金配置命令
cmake -DCMAKE_INSTALL_PREFIX=/usr \
      -DCMAKE_CXX_STANDARD=17 \
      -DCMAKE_CXX_FLAGS="-D_GLIBCXX_USE_C99_MATH=1" \
      -DGR_PYTHON_DIR=/usr/lib/python3/dist-packages \
      ..

# 编译与安装
make -j$(nproc)
sudo make install
sudo ldconfig

```

### 2.2 安装 gr-ieee802-11

```bash
cd ~
git clone https://github.com/bastibl/gr-ieee802-11.git
cd gr-ieee802-11

rm -rf build && mkdir build && cd build

# 同样的黄金配置
cmake -DCMAKE_INSTALL_PREFIX=/usr \
      -DCMAKE_CXX_STANDARD=17 \
      -DCMAKE_CXX_FLAGS="-D_GLIBCXX_USE_C99_MATH=1" \
      -DGR_PYTHON_DIR=/usr/lib/python3/dist-packages \
      ..

make -j$(nproc)
sudo make install
sudo ldconfig

```

---

## 🔌 3. 硬件配置

### 3.1 下载 UHD 固件镜像

必须使用系统自带的工具，确保镜像版本与驱动匹配。

```bash
# 这一步需要联网
sudo uhd_images_downloader

```

### 3.2 配置 USB 权限

如果使用 USB 连接 SDR（如 B210/U200），需配置 udev 规则：

```bash
sudo cp /usr/lib/uhd/utils/uhd-usrp.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger

```

---

## ⚠️ 4. 常见问题与避坑指南 (Troubleshooting)

如果严格按照上述步骤操作，通常不会遇到问题。以下是历史错误的复盘：

### Q1: 报错 `ImportError: ... referenced unknown base type "gr::sync_block"`

* **现象**：Python 运行报错，提示找不到基类。
* **原因**：
1. 模块被安装到了 `site-packages`，而 GNU Radio 核心在 `dist-packages`，导致 Python 符号隔离。
2. 或者使用了 GCC 12 编译模块，而系统库是 GCC 13，导致 C++ ABI 不兼容。


* **解决**：使用第 2 节中的 `cmake` 命令重新编译，确保指定了 `-DGR_PYTHON_DIR` 且使用系统默认编译器。

### Q2: 编译报错 `error: 'isnan' was not declared in this scope`

* **原因**：GCC 13 对 C++ 标准库头文件进行了精简。
* **解决**：**不要降级编译器！** 在 cmake 时添加 `-DCMAKE_CXX_FLAGS="-D_GLIBCXX_USE_C99_MATH=1"` 即可完美解决。

### Q3: 运行报错 `ImportError: /lib/x86_64-linux-gnu/libgnuradio-foo.so: undefined symbol`

* **原因**：链接到了旧的库文件。
* **解决**：执行 `1.2` 节中的清理命令，删除 `/usr/local/lib` 下的残留文件，并运行 `sudo ldconfig`。

### Q4: 找不到设备 `No devices found`

* **解决**：
1. 确认已运行 `uhd_find_devices` 能看到设备。
2. 确认已运行 `sudo uhd_images_downloader`。
3. 如果是 USB 设备，尝试拔插并等待 3 秒。
