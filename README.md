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
* **真实硬件组网**: 支持多台 **MicroPhase ANTSDR E200 (AD9361)** 硬件接入，通过千兆以太网连接，彻底解决 USB 传输带宽瓶颈，实现稳定的双车/多车通信。
* **Raft 状态机**: 实现了基于 UDP 的完整 Raft 逻辑（Leader 选举、心跳、日志复制、自动容灾）。

---

## 📂 项目结构 (File Structure)

代码按功能分层管理：

```text
V2V-Raft-SDR/
├── README.md               # 项目说明书
├── grc/                    # GNU Radio 流图源文件
│   ├── v2v_sim_hub.grc     # 仿真基站流图
│   └── v2v_hw_phy.grc      # 硬件基站流图 (适配 E200)
└── scripts/                # 核心代码目录
    ├── core/               # [物理层] 负责信号处理与收发
    │   ├── wifi_phy_hier.py      # 物理层逻辑封装 (OFDM调制/解调/同步)
    │   ├── v2v_sim_hub.py        # [仿真基站] 模拟“空气”，将收到的包广播给所有端口
    │   └── v2v_hw_phy.py         # [硬件基站] 调用 UHD 驱动连接 SDR (E200)，实现真实收发
    │
    └── app/                # [应用层] 负责业务逻辑
        ├── raft_node.py          # Raft 节点主程序 (车辆终端)
        └── simple_test.py        # 简单的 Ping/Loopback 测试工具

```

## 🚀 运行指南 (Quick Start)

### 模式一：多节点软件仿真 (5节点集群)

无需硬件，在单机上模拟 5 辆车的共识过程。

#### 1. 启动虚拟信道 (The Air)

打开终端 1，运行仿真集线器：

```bash
python3 scripts/core/v2v_sim_hub.py

```

此程序监听 UDP 50000 端口，并将收到的信号广播给 50001-50005 端口。

#### 2. 启动 Raft 节点 (The Cars)

打开 5 个新的终端窗口，分别运行：

```bash
# 终端 2 (节点 1)
python3 scripts/app/raft_node.py --id 1 --tx 50000 --rx 50001

# 终端 3 (节点 2)
python3 scripts/app/raft_node.py --id 2 --tx 50000 --rx 50002

# ... 依次启动到节点 5 (--rx 50005)

```

#### 3. 验证功能

* **选举**: 观察终端，节点会自动发起投票并选出 Leader。
* **变道指令**: 在 Leader 节点的终端窗口按 **回车键**，触发“变道指令”。观察所有 Follower 是否同步打印 `[执行] 共识达成! 执行操作: 向左变道`。

### 模式二：硬件双机实战 (Hardware Demo)

使用两台 **ANTSDR E200** 进行真实通信。

#### 前提条件:

1. **物理连接**: 确保 E200 已通过网线连接至电脑（或交换机）。
2. **IP 配置**:
* 电脑端网卡需设置静态 IP（如 `192.168.1.100`）。
* 若使用双机，需提前修改其中一台 E200 的 IP 地址（例如一台为 `192.168.1.10`，另一台为 `192.168.1.11`），避免 IP 冲突。


3. **环境检查**: 使用 `ping 192.168.1.10` 确保网络连通。

#### 1. 启动硬件基站 (需 sudo)

* **终端 1 (SDR A - IP .10):**
```bash
# 注意：serial-num 参数传入设备 IP 地址
sudo python3 scripts/core/v2v_hw_phy.py --serial-num "addr=192.168.1.10" --udp-recv-port 10000 --udp-send-port 20000

```


* **终端 2 (SDR B - IP .11):**
```bash
sudo python3 scripts/core/v2v_hw_phy.py --serial-num "addr=192.168.1.11" --udp-recv-port 10001 --udp-send-port 20001

```



#### 2. 启动 Raft 节点

* **终端 3 (车 A):**
```bash
python3 scripts/app/raft_node.py --id 1 --tx 10000 --rx 20000

```


* **终端 4 (车 B):**
```bash
python3 scripts/app/raft_node.py --id 2 --tx 10001 --rx 20001

```



#### 3. 容灾测试

* 在 Leader 对应的终端按 `Ctrl+C` 停止程序，模拟车辆驶离或故障。
* 观察另一台节点是否在几秒内检测到超时，并发起选举成为新 Leader。

## ⚙️ 环境依赖

* **OS**: Ubuntu 24.04 LTS (推荐) / 22.04 LTS
* **Python**: 3.12 (适配 Ubuntu 24.04)
* **SDR Driver**: `antsdr_uhd` (适配 E200 固件)
* **GNU Radio**: 3.10
* **依赖模块**: `gr-ieee802-11`, `gr-foo`

## 🗓️ 开发计划 (Roadmap)

* [x] **P0**: 环境搭建与 gr-ieee802-11 依赖编译
* [x] **P0**: 实现 UDP 接口解耦，摆脱 TAP 网卡依赖
* [x] **P1**: 完成软件回环与多节点仿真架构 (v2v_sim_hub)
* [x] **P1**: **硬件架构升级**: 从 U200 (USB) 迁移至 E200 (Ethernet)，解决 USB 带宽瓶颈与稳定性问题
* [x] **P2**: 实现 Raft 核心逻辑 (选举、心跳、日志复制)
* [ ] **P3**: (进行中) **Raft 算法优化研究**: 重点研究在车联网应用场景下（高动态拓扑、非可靠信道），如何对 Raft 基础框架进行适配与改进（如基于信道质量/RSSI 的加权选举机制）。
