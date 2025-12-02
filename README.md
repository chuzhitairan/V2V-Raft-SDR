# V2V-Raft-SDR: 车联网环境下的 Raft 共识算法 SDR 实现

## 📖 项目简介 (Introduction)
本项目旨在验证 **Wireless Distributed Consensus (无线分布式共识)** 理论在车联网 (V2V) 场景下的可行性。

项目利用 **GNU Radio** 和 **SDR (软件无线电)** 技术构建了 IEEE 802.11p 通信物理层，并在此基础上实现了一个**完全去中心化**的 Raft 共识集群。系统独创了 **“双模架构”**，既支持在单机上进行大规模节点的纯软件仿真，也支持接入多台 SDR 设备进行真实电磁环境下的硬件实战。

目前已成功实现多节点 Leader 选举、心跳维持及**车道变更指令的日志复制与共识**。

---

## 🌟 核心特性 (Key Features)
* **软硬双模架构**: 同一套 Raft 应用层代码，既可以连接虚拟信道进行仿真，也可以无缝切换到真实 SDR 硬件。
* **物理层实现**: 基于 `gr-ieee802-11` 实现完整的 OFDM 物理层与 MAC 层处理。
* **上帝视角信道 (Sim Hub)**: 软件仿真模式下，通过 UDP 广播机制模拟无线电的“广播”特性，实现单机多节点组网。
* **真实硬件组网**: 支持多台 **MicroPhase ANTSDR U200 (AD9361)** 硬件接入，通过命令行参数灵活配置序列号与端口，实现真实的双车/多车通信。
* **Raft 状态机**: 实现了基于 UDP 的完整 Raft 逻辑（Leader 选举、心跳、日志复制、自动容灾）。

---

## 📂 项目结构 (File Structure)

代码按功能分层管理：

```text
V2V-Raft-SDR/
├── README.md               # 项目说明书
├── grc/                    # GNU Radio 流图源文件
│   ├── v2v_sim_hub.grc     # 仿真基站流图
│   └── v2v_hw_phy.grc      # 硬件基站流图
└── scripts/                # 核心代码目录
    ├── core/               # [物理层] 负责信号处理与收发
    │   ├── wifi_phy_hier.py      # 物理层逻辑封装 (OFDM调制/解调/同步)
    │   ├── v2v_sim_hub.py        # [仿真基站] 模拟“空气”，将收到的包广播给所有端口
    │   └── v2v_hw_phy.py         # [硬件基站] 调用 UHD 驱动连接 SDR，实现真实收发
    │
    └── app/                # [应用层] 负责业务逻辑
        ├── raft_node.py          # Raft 节点主程序 (车辆终端)
        └── simple_test.py        # 简单的 Ping/Loopback 测试工具
```

## 🚀 运行指南 (Quick Start)
### 模式一：多节点软件仿真 (5节点集群)

无需硬件，在单机上模拟 5 辆车的共识过程。

#### 1. 启动虚拟信道 (The Air) 打开终端 1，运行仿真集线器：
```bash

python3 scripts/core/v2v_sim_hub.py
```
此程序监听 UDP 50000 端口，并将收到的信号广播给 50001-50005 端口。

#### 2. 启动 Raft 节点 (The Cars) 打开 5 个新的终端窗口，分别运行：
```bash

# 终端 2 (节点 1)
python3 scripts/app/raft_node.py --id 1 --tx 50000 --rx 50001

# 终端 3 (节点 2)
python3 scripts/app/raft_node.py --id 2 --tx 50000 --rx 50002

# ... 依次启动到节点 5 (--rx 50005)
```
#### 3. 验证功能

* 选举: 观察终端，节点会自动发起投票并选出 Leader。

* 变道指令: 在 Leader 节点的终端窗口按 回车键，触发“变道指令”。观察所有 Follower 是否同步打印 [执行] 共识达成! 执行操作: 向左变道。

### 模式二：硬件双机实战 (Hardware Demo)

使用两台 ANTSDR U200 进行真实通信。

前提条件:

* 确保两台 SDR 已连接，且序列号已通过 usrp_burn_mb_eeprom 修改为不同值 (如 U200100 和 U200101)。

* 确保 USB 连接在 3.0 接口上 (lsusb -t 显示 5000M)。

#### 1.启动硬件基站 (需 sudo)

* 终端 1 (SDR A):
```bash

sudo python3 scripts/core/v2v_hw_phy.py --serial U200100 --rx-port 10000 --tx-port 20000
```
* 终端 2 (SDR B):
```bash

sudo python3 scripts/core/v2v_hw_phy.py --serial U200101 --rx-port 10001 --tx-port 20001
```
#### 2. 启动 Raft 节点

* 终端 3 (车 A):
```bash

python3 scripts/app/raft_node.py --id 1 --tx 10000 --rx 20000
```
* 终端 4 (车 B):
```bash

python3 scripts/app/raft_node.py --id 2 --tx 10001 --rx 20001
```
#### 3. 容灾测试

* 在 Leader 对应的终端按 `Ctrl+C` 停止程序， 等待一段时间再重新启动。

* 观察另一台节点是否在几秒内检测到超时，并发起选举成为新 Leader。

## ⚙️ 环境依赖

    OS: Ubuntu 20.04 / 22.04 LTS

    Python: 3.8+

    SDR Driver: UHD 4.x (适配 B205mini 固件)

    GNU Radio: 3.10 (推荐)

    依赖模块: gr-ieee802-11, gr-foo

## 🗓️ 开发计划 (Roadmap)

    [x] P0: 环境搭建与 gr-ieee802-11 依赖编译

    [x] P0: 实现 UDP 接口解耦，摆脱 TAP 网卡依赖

    [x] P1: 完成软件回环与多节点仿真架构 (v2v_sim_hub)

    [x] P1: 解决 USB 2.0 带宽瓶颈，实现双 SDR 硬件互联

    [x] P2: 实现 Raft 核心逻辑 (选举、心跳、日志复制)

    [ ] P3: (进行中) 提取 RSSI 信号强度，实现基于信道质量的加权选举