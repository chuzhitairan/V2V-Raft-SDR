# V2V-Raft-SDR: 车联网环境下的 Raft 共识算法 SDR 实现

## 📖 项目简介

本项目旨在验证 **Wireless Distributed Consensus (无线分布式共识)** 理论在车联网 (V2V) 场景下的可行性。

项目利用 **GNU Radio** 和 **SDR (软件无线电)** 技术构建了 IEEE 802.11p 通信物理层，并在此基础上实现了一个**完全去中心化**的 Raft 共识集群。系统独创了 **"双模架构"**，既支持在单机上进行大规模节点的纯软件仿真，也支持接入多台 SDR 设备进行真实电磁环境下的硬件实战。

目前已成功实现多节点 Leader 选举、心跳维持及**车道变更指令的日志复制与共识**。

---

## 🌟 核心特性

* **软硬双模架构**: 同一套 Raft 应用层代码，既可以连接虚拟信道进行仿真，也可以无缝切换到真实 SDR 硬件。
* **物理层实现**: 基于 `gr-ieee802-11` 实现完整的 OFDM 物理层与 MAC 层处理。
* **上帝视角信道 (Sim Hub)**: 软件仿真模式下，通过 UDP 广播机制模拟无线电的"广播"特性，实现单机多节点组网。
* **真实硬件组网**: 支持多台 **MicroPhase ANTSDR E200 (AD9361)** 硬件接入，通过千兆以太网连接，解决 USB 传输带宽瓶颈。
* **Raft 状态机**: 实现了基于 UDP 的完整 Raft 逻辑（Leader 选举、心跳、日志复制、自动容灾）。

---

## 📂 项目结构

\`\`\`text
V2V-Raft-SDR/
├── README.md                  # 项目说明书 (本文件)
├── docs/                      # 文档目录
│   ├── INSTALL_GUIDE.md       # 环境搭建指南
│   ├── HARDWARE_OPERATION_GUIDE.md  # 硬件操作指南
│   └── PROTOCOL_FEATURES.md   # Raft 协议特性说明
│
├── core/                      # 核心物理层代码
│   ├── wifi_phy_hier.py       # WiFi PHY 层次块 (OFDM 调制/解调/同步)
│   ├── v2v_sim_hub.py         # 仿真基站 (完整 GNU Radio 版)
│   ├── v2v_hw_phy.py          # 硬件基站 (连接 SDR 设备)
│   └── sim_hub_lite.py        # 轻量级仿真 Hub (纯 UDP 转发)
│
├── experiments/               # 实验代码与数据
│   ├── pre_test/              # 预测试 (基准测试)
│   │   ├── full_auto_benchmark.py   # TX Gain-SNR 自动扫描
│   │   ├── plot_csv.py              # 结果绘图
│   │   └── results/                 # 测试数据与报告
│   │
│   ├── snr_cluster_size/      # SNR-集群规模实验
│   │   ├── code/              # 实验脚本
│   │   ├── results/           # 实验数据
│   │   └── README.md          # 实验说明
│   │
│   └── reliability_consensus/ # 可靠性共识实验
│       ├── code/              # 实验脚本
│       ├── results/           # 实验数据
│       └── README.md          # 实验说明
│
└── grc/                       # GNU Radio Companion 流图文件
    ├── v2v_sim_hub.py.grc     # 仿真基站流图
    └── v2v_hw_phy.py.grc      # 硬件基站流图
\`\`\`

---

## 🚀 快速开始

### 模式一：软件仿真 (5 节点集群)

无需硬件，在单机上模拟多辆车的共识过程。

#### 1. 启动虚拟信道

\`\`\`bash
# 使用轻量级 Hub (推荐，启动快)
python3 core/sim_hub_lite.py --nodes 5

# 或使用完整 GNU Radio Hub (需要 GUI)
python3 core/v2v_sim_hub.py
\`\`\`

#### 2. 启动 Raft 节点

\`\`\`bash
# 终端 1 (Leader)
python3 experiments/reliability_consensus/code/raft_leader_reliability.py \
    --id 1 --total 5 --tx 50000 --rx 50001

# 终端 2-5 (Follower)
python3 experiments/reliability_consensus/code/raft_follower_reliability.py \
    --id 2 --total 5 --tx 50000 --rx 50002
# ... 依次启动节点 3-5 (--rx 50003 到 50005)
\`\`\`

#### 3. 验证功能

- **选举**: 观察终端，节点会自动发起投票并选出 Leader。
- **变道指令**: 在 Leader 节点的终端窗口按 **回车键**，触发"变道指令"。

### 模式二：硬件双机实战

使用两台 **ANTSDR E200** 进行真实通信。详见 [硬件操作指南](docs/HARDWARE_OPERATION_GUIDE.md)。

\`\`\`bash
# 终端 1: SDR A (IP .10)
sudo python3 core/v2v_hw_phy.py \
    --sdr-args "addr=192.168.1.10" \
    --udp-recv-port 10001 --udp-send-port 20001

# 终端 2: SDR B (IP .11)
sudo python3 core/v2v_hw_phy.py \
    --sdr-args "addr=192.168.1.11" \
    --udp-recv-port 10002 --udp-send-port 20002

# 终端 3-4: 启动 Raft 应用层
python3 experiments/snr_cluster_size/code/raft_leader_snr_experiment.py \
    --id 1 --total 2 --tx 10001 --rx 20001

python3 experiments/snr_cluster_size/code/raft_follower_snr_experiment.py \
    --id 2 --total 2 --tx 10002 --rx 20002
\`\`\`

---

## 📚 文档索引

| 文档 | 说明 |
|------|------|
| [docs/INSTALL_GUIDE.md](docs/INSTALL_GUIDE.md) | 环境搭建 (Ubuntu 24.04 + GNU Radio + SDR 驱动) |
| [docs/HARDWARE_OPERATION_GUIDE.md](docs/HARDWARE_OPERATION_GUIDE.md) | 硬件操作 (E200/U200 配置与故障排除) |
| [docs/PROTOCOL_FEATURES.md](docs/PROTOCOL_FEATURES.md) | Raft 协议实现细节 |
| [experiments/snr_cluster_size/README.md](experiments/snr_cluster_size/README.md) | SNR-集群规模实验说明 |
| [experiments/reliability_consensus/README.md](experiments/reliability_consensus/README.md) | 可靠性共识实验说明 |

---

## ⚙️ 环境依赖

* **OS**: Ubuntu 24.04 LTS (推荐) / 22.04 LTS
* **Python**: 3.12 (适配 Ubuntu 24.04)
* **SDR Driver**: `antsdr_uhd` (适配 E200 固件)
* **GNU Radio**: 3.10+
* **依赖模块**: `gr-ieee802-11`, `gr-foo`

详细安装步骤见 [安装指南](docs/INSTALL_GUIDE.md)。

---

## 🗓️ 开发计划

* [x] **P0**: 环境搭建与 gr-ieee802-11 依赖编译
* [x] **P0**: 实现 UDP 接口解耦，摆脱 TAP 网卡依赖
* [x] **P1**: 完成软件回环与多节点仿真架构 (v2v_sim_hub)
* [x] **P1**: 硬件架构升级 (从 U200 USB 迁移至 E200 Ethernet)
* [x] **P2**: 实现 Raft 核心逻辑 (选举、心跳、日志复制)
* [x] **P3**: SNR-集群规模实验
* [x] **P3**: 可靠性共识实验
* [ ] **P4**: 基于信道质量的加权选举机制研究
