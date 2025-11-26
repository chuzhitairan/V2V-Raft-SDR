# V2V-Raft-SDR: 基于 SDR 的车联网 Raft 共识算法实现

## 📖 项目简介
本项目旨在验证 **Wireless Distributed Consensus (无线分布式共识)** 理论在车联网 (V2V) 场景下的可行性。

项目基于 **GNU Radio** 和 **ANTSDR U200 (AD9361)** 硬件平台，实现了 IEEE 802.11p (V2V) 通信协议栈。我们构建了一套“双模”开发环境，既支持纯软件层面的快速算法验证，也支持基于真实无线电信道的硬件实战。

核心创新在于通过 SDR 底层接口提取信号质量 (RSSI/CSI) 信息，用于优化 Raft 共识算法的 Leader 选举机制。

---

## 📂 项目结构 (Project Structure)

本项目精简了冗余依赖，核心代码位于 `scripts/` 目录下：

```text
scripts/
├── wifi_phy_hier.py         # [核心] 物理层逻辑封装 (OFDM调制/解调/同步)，所有版本共用
├── wifi_transceiver_hw.py   # [硬件版] 基站主程序，调用 UHD 驱动连接 SDR 硬件
├── wifi_transceiver_sim.py  # [仿真版] 基站主程序，使用 Channel Model 模拟软件回环
└── test.py                  # [应用层] 模拟车载终端，负责发送指令和运行 Raft 逻辑
````

### 端口映射 (UDP Port Map)

系统通过 UDP Socket 实现 Python 应用层与 GNU Radio 物理层的解耦：

  * **上行 (Tx)**: Python -\> `UDP 12345` -\> GNU Radio (发射)
  * **下行 (Rx)**: GNU Radio (接收) -\> `UDP 54321` -\> Python

-----

## 🛠️ 硬件环境 (Hardware Setup)

如果要运行硬件版 (`_hw.py`)，需要以下配置：

  * **SDR 开发板**: MicroPhase ANTSDR U200
      * **固件要求**: 需刷入适配 **UHD (USRP B205mini)** 的固件。
      * **接口连接**: 使用 **USB 3.0** 接口（必须连接蓝色/红色 USB 口，否则带宽不足会报错）。
  * **天线**:
      * **TRX 接口**: 连接 5.8GHz 天线（负责发射/接收）。
      * **RX 接口**: 连接 5.8GHz 天线（负责分集接收）。

-----

## 🚀 快速开始 (Quick Start)

### 模式一：纯软件仿真 (Simulation Mode)

*适用场景：无硬件环境、调试 Raft 算法逻辑、开发阶段。*

1.  **启动虚拟基站**：

    ```bash
    python3 scripts/wifi_transceiver_sim.py
    ```

    *注：此模式下信号通过软件模拟的信道回环，无物理信号发射。*

2.  **运行节点**：
    新开一个终端运行：

    ```bash
    python3 scripts/test.py
    ```

### 模式二：硬件实战 (Hardware Mode)

*适用场景：实验室环境、验证真实信道性能、演示阶段。*

1.  **检查设备**：
    确保 SDR 已连接且识别为 USB 3.0 设备：

    ```bash
    lsusb -t  # 确认速度为 5000M
    uhd_find_devices
    ```

2.  **启动 SDR 基站**：

    ```bash
    # 必须使用 sudo 以获取 USB 权限
    sudo python3 scripts/wifi_transceiver_hw.py
    ```

    *等待终端显示 `Operating over USB 3` 且无报错退出。*

3.  **运行节点**：
    新开一个终端运行：

    ```bash
    python3 scripts/test.py
    ```

    *预期现象：SDR 板载 TX/RX 指示灯闪烁，Python 终端收到回显数据。*

-----

## ⚠️ 常见问题 (Troubleshooting)

### 1\. 硬件相关

  * **报错 `Overflow (O)` 或 `Underflow (U)`**
      * **原因**: USB 2.0 带宽不足 (480Mbps) 无法支撑 10MHz 采样率的全双工通信。
      * **解决**: 务必使用 USB 3.0 数据线并连接电脑的 USB 3.0 接口。如果条件限制，可尝试减小 `samp_rate` 。
  * **报错 `RuntimeError: No devices found`**
      * **原因**: 缺少 UHD 固件或权限不足。
      * **解决**: 运行 `sudo uhd_images_downloader` 下载固件，并确保使用 `sudo` 运行 Python。

### 2\. 信号相关

  * **拔掉天线反而能收到数据？**
      * **原因**: 自发自收时信号过强导致接收端饱和 (Saturation)。
      * **解决**: 在代码中降低 `tx_gain` (建议 \< 0.5) 或拉开天线距离。

-----

## 🗓️ 开发计划 (Roadmap)

  - [x] **P0**: 环境搭建与 `gr-ieee802-11` 依赖编译
  - [x] **P0**: 实现 UDP 接口替代 TAP 网卡，解耦网络栈
  - [x] **P1**: 软件回环仿真 (Loopback) 跑通
  - [x] **P1**: 硬件接入 (ANTSDR U200) 与带宽优化
  - [ ] **P2**: 移植 Raft 算法 (将 TCP 通信重构为 UDP)
  - [ ] **P3**: 实现 RSSI 信号强度提取与 Raft 权重整合

<!-- end list -->