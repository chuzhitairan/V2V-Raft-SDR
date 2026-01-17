# ANTSDR E200 安装与适配指南

**适用环境**：Ubuntu 24.04 LTS / GCC 13 / Python 3.12

---

## 第一阶段：硬件准备与模式切换 (物理操作)

E200 出厂可能处于 Pluto 模式或 USB 模式，必须通过 SD 卡引导进入 **E200 网络模式**。

1. **准备 SD 卡**：
* 确保 Micro SD 卡中已烧录了 ANTSDR E200 的专用固件镜像（如果还没烧录，需先用读卡器刷入 E200 固件）。
* 将 SD 卡插入板子卡槽。


2. **设置拨码开关 (DIP Switch)**：
* 找到网口下方的三个小开关。
* 将 **中间的开关** (通常标记为 Boot 选择) 拨向 **SD 卡** 一侧（通常是 ON 或标有 SD 字样的一侧）。
* *注：不同批次丝印可能不同，核心目的是让它从 SD 卡启动 Linux。*


3. **连接线缆**：
* **网线**：连接电脑网口和 E200 网口。
* **USB 线**：连接电脑或充电头（**仅作为供电使用**，不需要传数据）。


4. **上电等待**：
* 通电后，观察板上 LED 灯变化。等待约 **40-60 秒**，等待板载系统完全启动。



---

## 第二阶段：电脑网络配置 (静态 IP)

电脑必须和 E200 (默认 192.168.1.10) 在同一网段才能通信。

1. 打开 Ubuntu **设置 (Settings)** -> **网络 (Network)** -> **有线连接** -> ⚙️ 齿轮图标。
2. 选择 **IPv4** 标签，设置为 **手动 (Manual)**。
3. 填写如下信息（**严格按照以下参数**）：
* **地址 (Address)**: `192.168.1.100` (只要不是 .10 且在同一网段即可)
* **子网掩码 (Netmask)**: `255.255.255.0`
* **网关 (Gateway)**: `(留空不填)` —— *关键点，填了可能会导致路由混乱*


4. 点击应用，并关闭再重新打开有线连接开关。
5. **验证连接**：
打开终端输入：
```bash
ping 192.168.1.10

```


如果看到 `ttl=64` 的回复，说明物理链路和系统已经通了。

---

## 第三阶段：环境清理与依赖安装

确保没有旧的 UHD 干扰，并安装 Ubuntu 24.04 所需的依赖。

```bash
# 1. 彻底卸载旧版本 (防止动态库冲突)
sudo apt-get remove --purge "libuhd*" "uhd-host" "uhd-soapysdr"
sudo rm -rf /usr/local/lib/libuhd* sudo rm -rf /usr/local/include/uhd
sudo rm -f /usr/local/bin/uhd_*
sudo ldconfig

# 2. 安装编译依赖 (Ubuntu 24.04 专用列表)
sudo apt-get update
sudo apt-get install -y autoconf automake build-essential ccache cmake cpufrequtils doxygen ethtool g++ git inetutils-tools libboost-all-dev libusb-1.0-0 libusb-1.0-0-dev libusb-dev python3-dev python3-mako python3-numpy python3-requests python3-scipy python3-setuptools python3-ruamel.yaml libncurses-dev

```

---

## 第四阶段：下载源码与编译

### 1. 获取源码

```bash
cd ~
# 如果文件夹已存在，建议先删除重下，保证干净
rm -rf antsdr_uhd 
git clone https://github.com/MicroPhase/antsdr_uhd.git
cd antsdr_uhd

```

### 2. 编译与安装

```bash
cd host
mkdir build
cd build

# 1. 生成 Makefile
cmake -DENABLE_X400=OFF -DENABLE_N320=OFF -DENABLE_X300=OFF -DENABLE_USRP2=OFF -DENABLE_USRP1=OFF -DENABLE_N300=OFF -DENABLE_E320=OFF -DENABLE_E300=OFF ../

# 2. 编译 (使用 4 核加速)
make -j4

# 3. 安装到系统
sudo make install
sudo ldconfig

```

> **注意**：如果在 `cmake` 阶段报错提示 `pybind11` 相关问题，请执行 `cd ../.. && git submodule update --init --recursive` 更新子模块后再重试。

---

## 第五阶段：验证设备与固件加载

1. **搜索设备**：
```bash
uhd_find_devices

```


* **成功标志**：终端应显示 `Product: E200` 或 `ANTSDR-E200`，且 IP 为 `192.168.1.10`。


2. **探针测试 (Probe)**：
```bash
uhd_usrp_probe --args="addr=192.168.1.10"

```


---

## 第六阶段：运行指令

以后启动基站时，使用以下命令（指定 IP）：

```bash
# 启动接收/发送脚本，参数传入 IP 地址
sudo python3 scripts/core/v2v_hw_phy.py --serial-num "addr=192.168.1.10" --udp-recv-port 12345 --udp-send-port 54321

```