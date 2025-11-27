# V2V-Raft-SDR: 车联网环境下的 Raft 共识算法 SDR 实现

## 📖 项目简介 (Introduction)
本项目旨在验证 **Wireless Distributed Consensus (无线分布式共识)** 理论在车联网 (V2V) 场景下的可行性。

项目利用 **GNU Radio** 和 **SDR (软件无线电)** 技术构建了 IEEE 802.11p 通信物理层，并在此基础上实现了一个**完全去中心化**的 Raft 共识集群。系统支持“纯软件多节点仿真”和“硬件在环实战”两种模式，能够模拟车辆在真实无线信道中的 Leader 选举与共识过程。

## 🌟 核心特性
* **物理层仿真**: 基于 `gr-ieee802-11` 实现完整的 OFDM 物理层与 MAC 层处理。
* **上帝视角信道**: 软件仿真模式下，通过 UDP 广播机制模拟无线电的“广播”特性，实现多节点组网。
* **Raft 算法移植**: 实现了基于 UDP 的 Raft 状态机（Leader 选举、心跳维持、超时重选）。
* **SDR 硬件接入**: 支持 MicroPhase ANTSDR U200 (AD9361) 硬件接入，在真实电磁环境中验证算法。

---

## 📂 文件说明 (File Structure)

核心代码位于 `scripts/` 目录下：

| 文件名 | 类型 | 说明 |
| :--- | :--- | :--- |
| **`v2v_sim_hub.py`** | 仿真基站 | (修改自 `wifi_transceiver.py`) **软件仿真核心**。它模拟了“空气”，监听 UDP 50000 端口，并将收到的信号广播给 50001-50005 端口的节点。 |
| **`v2v_hw_phy.py`** | 硬件基站 | (修改自`wifi_transceiver.py`) **硬件实战核心**。调用 UHD 驱动连接 SDR 硬件，实现真实的射频收发。 |
| **`raft_node.py`** | 节点逻辑 | Raft 算法实现。每个运行实例代表一辆车，具有独立的 ID、状态和超时计时器。 |
| **`wifi_phy_hier.py`** | 依赖库 | GNU Radio 生成的物理层逻辑层级块，是上述两个基站程序的**硬性依赖**。 |

---

## 🚀 运行指南 (Quick Start)

### 场景一：多节点软件仿真 (5节点集群)
*无需硬件，在单机上模拟 5 辆车的共识过程。*

**1. 启动虚拟信道 (The Air)**
打开终端 1，运行仿真集线器：
```bash
python3 scripts/v2v_sim_hub.py
```

此程序会建立 UDP 桥接，负责将任一节点的消息广播给其他所有节点。

**2. 启动 Raft 节点 (The Cars)** 
请分别打开 5 个新的终端窗口，依次运行：

```bash

# 终端 2 (节点 1)
python3 scripts/raft_node.py --id 1

# 终端 3 (节点 2)
python3 scripts/raft_node.py --id 2

# ... 依次启动到节点 5
python3 scripts/raft_node.py --id 5
```

**3. 预期现象**

* 选举: 所有节点启动后，你会看到日志中出现 [超时] 发起选举!。

* 投票: 其他节点会打印 [投票] 投给了 -> 节点 X。

* 当选: 获得多数票的节点会打印 👑 [当选] 我是 Leader! 并开始发送心跳。

* 容灾: 尝试按 Ctrl+C 杀掉 Leader 进程，观察其他节点是否能在几秒内自动选出新 Leader。

### 场景二：硬件单机回环 (Loopback)

使用 ANTSDR U200 进行自发自收测试。

连接硬件: 确保 SDR 连接至 USB 3.0 接口。

启动硬件基站:

```bash
sudo python3 scripts/v2v_hw_phy.py
```

(等待显示 Operating over USB 3)

运行测试应用:
```bash
python3 scripts/simple_test.py
```

⚙️ 环境依赖

    OS: Ubuntu 20.04 / 22.04 LTS

    Python: 3.8+

    SDR Driver: UHD 4.x (适配 B205mini 固件)

    GNU Radio: 3.10 (推荐) 或 3.8

    依赖模块: gr-ieee802-11, gr-foo

🗓️ 开发计划

    [x] 完成物理层软件回环与硬件接入

    [x] 实现基于 UDP 的多节点软件仿真架构

    [x] 实现基础 Raft 选举逻辑

    [ ] Next: 优化 Raft 逻辑，加入日志复制功能

    [ ] Next: 在 GNU Radio 中提取 RSSI (信号强度)，实现基于信号质量的加权选举