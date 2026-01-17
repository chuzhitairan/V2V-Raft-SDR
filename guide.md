# ANTSDR E200 安装与适配指南 (Ubuntu 24.04 版)

**适用环境**：Ubuntu 24.04 LTS / GCC 13 / Python 3.12
**硬件设备**：ANTSDR E200 (网口版)
**目标**：安装 UHD 3.15 驱动，修复新系统编译报错，并适配 V2V 项目代码。

---

## 第一阶段：硬件准备与模式切换 (至关重要)

E200 出厂默认是 Pluto 模式（UHD 无法识别），必须切换到 **USRP 模式**。

1. **插入 SD 卡**：取出配件包里的 32GB SD 卡，插入 E200 卡槽。
2. **拨码开关 (DIP Switch)**：
* 找到网口下方的三个小开关。
* 将中间的开关拨向 **SD** 一侧（通常是拨到右边，具体看丝印）。


3. **连接**：
* 网线连接电脑和 E200。
* USB 线连接电脑供电。


4. **等待启动**：通电后等待约 40 秒，让系统从 SD 卡加载。

---

## 第二阶段：电脑网络配置

为了让电脑能通过网线找到 E200，需配置静态 IP。

1. 打开 **设置** -> **网络** -> **有线连接** -> ⚙️ 齿轮图标。
2. 选择 **IPv4** 标签，设置为 **手动 (Manual)**。
3. 填写如下信息（**注意：网关必须留空！**）：
* **地址 (Address)**: `192.168.1.100`
* **子网掩码 (Netmask)**: `255.255.255.0`
* **网关 (Gateway)**: `(留空不填)`


4. 点击应用，并重新插拔网线。
5. **验证**：终端输入 `ping 192.168.1.10`，若能 ping 通则网络正常。

---

## 第三阶段：环境清理与依赖安装

防止旧驱动冲突，并安装编译工具。

```bash
# 1. 卸载系统自带的旧 UHD（如果装过）
sudo apt-get remove --purge "libuhd*" "uhd-host" "uhd-soapysdr"
sudo apt-get autoremove

# 2. 清理 /usr/local 下的残留 (确保环境纯净)
sudo rm -rf /usr/local/lib/libuhd* sudo rm -rf /usr/local/include/uhd
sudo rm -f /usr/local/bin/uhd_*

# 3. 安装依赖工具 (Ubuntu 24.04 专用)
sudo apt-get update
sudo apt-get install -y autoconf automake build-essential ccache cmake cpufrequtils doxygen ethtool g++ git inetutils-tools libboost-all-dev libusb-1.0-0 libusb-1.0-0-dev libusb-dev python3-dev python3-mako python3-numpy python3-requests python3-scipy python3-setuptools python3-ruamel.yaml libncurses-dev

```

---

## 第四阶段：获取源码与补丁修复 (核心步骤)

因为 Ubuntu 24.04 的编译器 (GCC 13) 和 Python (3.12) 太新，直接编译官方源码会报错，必须按以下步骤操作。

### 1. 下载源码并切换分支

```bash
cd ~
git clone https://github.com/MicroPhase/antsdr_uhd.git
cd antsdr_uhd

# 切换到 E200 专用分支 (必须是这个分支！)
git checkout e200_dev

```

### 2. 替换 pybind11 (修复 Python 3.12 兼容性)

```bash
cd host/lib/deps
rm -rf pybind11
git clone https://github.com/pybind/pybind11.git
cd pybind11
# 切换到支持 Python 3.12 的版本
git checkout v2.12.0

```

### 3. 手动修改 6 个源代码文件 (修复 GCC 13 报错)

请使用 `nano` 或文本编辑器打开以下文件，添加缺失的头文件。

* **文件 1**: `host/include/uhd/cal/database.hpp`
* **修改**：在头部 `#include` 列表末尾添加：
```cpp
#include <cstdint>

```




* **文件 2**: `host/include/uhd/rfnoc/defaults.hpp`
* **修改**：在头部 `#include` 列表末尾添加：
```cpp
#include <cstdint>

```




* **文件 3**: `host/lib/utils/serial_number.cpp`
* **修改**：在头部 `#include` 列表末尾添加：
```cpp
#include <cstdint>

```




* **文件 4**: `host/lib/usrp/common/lmx2592.cpp`
* **修改**：在头部 `#include` 列表末尾添加：
```cpp
#include <array>

```




* **文件 5 & 6**:
* `host/lib/usrp/cores/rx_dsp_core_3000.cpp`
* `host/lib/usrp/cores/rx_frontend_core_3000.cpp`
* **修改**：在这两个文件的头部 `#include` 区域，都添加：
```cpp
#include <boost/math/special_functions/sign.hpp>

```




* **文件 7**: `host/lib/usrp/ant/ant_io_impl.cpp`
* **修改**：在头部 `#include` 列表的**下一行**，添加：
```cpp
using namespace boost::placeholders;

```





---

## 第五阶段：编译与安装

```bash
# 1. 进入构建目录
cd ~/antsdr_uhd/host
mkdir build
cd build

# 2. 配置 (禁用不需要的组件加速编译)
cmake -DENABLE_X400=OFF -DENABLE_N320=OFF -DENABLE_X300=OFF -DENABLE_USRP2=OFF -DENABLE_USRP1=OFF -DENABLE_N300=OFF -DENABLE_E320=OFF -DENABLE_E300=OFF ../

# 3. 编译 (利用 4 核)
make -j4

# 4. 安装
sudo make install
sudo ldconfig

```

---

## 第六阶段：验证设备

执行以下命令：

```bash
uhd_usrp_probe --args="addr=192.168.1.10"

```

**成功标志**：

1. 输出版本号包含 **3.15** (例如 `UHD_4.1.0.e200_dev` 或 `3.15`)。
2. 输出信息中包含：`[INFO] [E200] Detected Device: ANTSDR`。

---

## 第七阶段：修改项目代码适配 E200

我们的项目 `V2V-Raft-SDR` 原本只支持 USB 连接，需要修改代码以支持网口 IP 连接。

**修改文件**：`scripts/core/v2v_hw_phy.py`

**1. 找到 `self.uhd_usrp_source_0` (接收部分) 并修改为：**

```python
        # 判断是 IP 还是序列号
        if "addr" in serial_num:
            source_dev_args = ",".join(("type=b200," + serial_num, ""))
        else:
            source_dev_args = ",".join(("type=b200,serial=" + serial_num, ""))

        self.uhd_usrp_source_0 = uhd.usrp_source(
            source_dev_args,  # 使用修改后的变量
            uhd.stream_args(
                cpu_format="fc32",
                args='',
                channels=list(range(0,1)),
            ),
        )

```

**2. 找到 `self.uhd_usrp_sink_0` (发射部分) 并修改为：**

```python
        self.uhd_usrp_sink_0 = uhd.usrp_sink(
            source_dev_args,  # 直接复用上面的变量
            uhd.stream_args(
                cpu_format="fc32",
                args='',
                channels=list(range(0,1)),
            ),
            'packet_len',
        )

```

---

## 如何启动项目 (E200 专用命令)

以后启动基站时，使用以下命令（指定 IP 而不是序列号）：

```bash
sudo python3 scripts/core/v2v_hw_phy.py --serial-num "addr=192.168.1.10" --udp-recv-port 12345 --udp-send-port 54321

```