# RUBICONe: RAFT-Unified Behaviors for Intervehicular Cooperative Operations and Negotiations

##  Overview
This repository provides the reference implementation for **RUBICONe**, a distributed framework extending the RAFT consensus algorithm tailored for cooperative lane-changing decisions in Vehicular Ad-Hoc Networks (VANETs). 

The project evaluates the feasibility of **Wireless Distributed Consensus** in Vehicle-to-Vehicle (V2V) scenarios. It implements a fully decentralized RAFT consensus cluster on top of an **IEEE 802.11p** physical layer built with **GNU Radio** and **Software Defined Radio (SDR)**. 

### Core Features
* **Dual-Mode Architecture**: The identical RAFT application layer can run seamlessly on both virtual simulated channels (Sim Hub) and real-world SDR hardware environments.
* **Physical Layer**: Full OFDM PHY and MAC layer processing based on `gr-ieee802-11`.
* **Hardware-in-the-Loop Setup**: Supports multi-SDR topology (e.g., MicroPhase ANTSDR E200 / Ettus USRP), mitigating USB bandwidth bottlenecks via Gigabit Ethernet interconnects.
* **RAFT State Machine**: Complete implementation of UDP-based RAFT logic (Leader election, heartbeat, log replication, and automated failover).

---

##  Repository Structure

```text
.
├── core/                      # Core PHY and simulation code
│   ├── v2v_sim_hub.py         # Simulation hub (GNU Radio)
│   ├── v2v_hw_phy.py          # Hardware hub (SDR integration)
│   ├── sim_hub_lite.py        # Lightweight simulation hub (UDP forwarding)
│   └── wifi_phy_hier.py       # WiFi PHY hier block (OFDM modulation/demodulation)
├── experiments/               # Scripts and datasets for paper evaluation
│   ├── pre_test/              # Base benchmark profiling
│   ├── reliability_consensus/ # System Reliability vs. Node Scale Experiment
│   └── snr_cluster_size/      # System Scale vs. SNR Experiment
└── grc/                       # GNU Radio Companion flowgraphs
```

---

##  Prerequisites & Environment Setup

This project is tested and verified on **Ubuntu 24.04 LTS**.
* **Python**: 3.12 
* **SDR Driver**: `UHD` (matching your SDR firmware)
* **GNU Radio**: 3.10+
* **OOT Modules**: `gr-ieee802-11`, `gr-foo`

### Compiling OOT Modules (Ubuntu 24.04 / GCC 13)

When compiling on Ubuntu 24.04, it is critical to address library isolation and GCC 13 compilation standards.

**1. Install `gr-foo`**
```bash
git clone https://github.com/bastibl/gr-foo.git && cd gr-foo
mkdir build && cd build
cmake -DCMAKE_INSTALL_PREFIX=/usr \
      -DCMAKE_CXX_STANDARD=17 \
      -DCMAKE_CXX_FLAGS="-D_GLIBCXX_USE_C99_MATH=1" \
      -DGR_PYTHON_DIR=/usr/lib/python3/dist-packages ..
make -j$(nproc)
sudo make install
sudo ldconfig
```

**2. Install `gr-ieee802-11`**
```bash
git clone https://github.com/bastibl/gr-ieee802-11.git && cd gr-ieee802-11
mkdir build && cd build
cmake -DCMAKE_INSTALL_PREFIX=/usr \
      -DCMAKE_CXX_STANDARD=17 \
      -DCMAKE_CXX_FLAGS="-D_GLIBCXX_USE_C99_MATH=1" \
      -DGR_PYTHON_DIR=/usr/lib/python3/dist-packages ..
make -j$(nproc)
sudo make install
sudo ldconfig
```

---

##  Running the System

### Mode 1: Software Simulation (5-Node Cluster)
Simulates the consensus process of multiple vehicles on a single machine without SDR hardware.

**1. Start the Virtual Channel (Terminal 1)**
```bash
python3 core/sim_hub_lite.py --nodes 5
```

**2. Start RAFT Nodes (Terminals 2-6)**
```bash
# Terminal 2 (Node 1)
python3 experiments/reliability_consensus/code/raft_leader_reliability.py \
    --id 1 --total 5 --tx 50000 --rx 50001

# Terminal 3 (Node 2)
python3 experiments/reliability_consensus/code/raft_follower_reliability.py \
    --id 2 --total 5 --tx 50000 --rx 50002

# Terminals 4-6 (Nodes 3-5)
# Repeat for nodes 3, 4, 5 by incrementing the --rx port (50003, 50004, 50005)
```

**Validation**: Nodes will automatically initiate an election. Press `Enter` in the Leader's terminal to trigger a simulated "lane-changing log replication".

---

### Mode 2: Hardware-in-the-Loop SDR

To interact with real hardware, run the PHY layer script assigning distinct IPs to each device before spawning the RAFT logic.

```bash
# Terminal 1: SDR Device A (e.g., 192.168.1.10)
sudo python3 core/v2v_hw_phy.py --sdr-args "addr=192.168.1.10" \
    --udp-recv-port 10001 --udp-send-port 20001

# Terminal 2: SDR Device B (e.g., 192.168.1.11)
sudo python3 core/v2v_hw_phy.py --sdr-args "addr=192.168.1.11" \
    --udp-recv-port 10002 --udp-send-port 20002

# Terminal 3 & 4: Application Layer Binding
python3 experiments/snr_cluster_size/code/raft_leader_snr_experiment.py \
    --id 1 --total 2 --tx 10001 --rx 20001

python3 experiments/snr_cluster_size/code/raft_follower_snr_experiment.py \
    --id 2 --total 2 --tx 10002 --rx 20002
```

---

##  Reproducing Paper Experiments

### 1. SNR vs. Cluster Size Evaluation
This experiment demonstrates the maximum effective cluster nodes maintained across declining SNR conditions (from 24 dB to 0 dB).

**Runner Setup:**
```bash
# Initialize an automated N-node assessment
./experiments/snr_cluster_size/code/run_snr_experiment.sh \
    [LEADER_TX] [LEADER_RX] [FOLLOWER_TX] [FOLLOWER_RX] [START_SNR] [STATUS_INTERVAL]

# Example execution mapping
./experiments/snr_cluster_size/code/run_snr_experiment.sh 0.8 0.9 0.7 0.9 20.0 2.0
```
**Plot Generation:**
```bash
python3 experiments/snr_cluster_size/code/plot_snr_experiment.py \
    experiments/snr_cluster_size/results/[latest_json_result].json
```

### 2. System Reliability vs. Node Scale
Evaluates collective system reliability (P_sys) against individual node competence (p_node) and channel quality scenarios.

**Runner Setup:**
```bash
cd V2V-Raft-SDR
./experiments/reliability_consensus/code/run_reliability_experiment.sh
```

**Plot Generation:**
```bash
python3 experiments/reliability_consensus/code/plot_reliability.py \
    experiments/reliability_consensus/results/high_reliability/[latest_json_result].json
```
