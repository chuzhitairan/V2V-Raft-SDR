#!/bin/bash
# ============================================================================
# 可靠性共识实验 - 软件仿真测试脚本
# ============================================================================
# 使用 sim_hub_lite 进行纯软件仿真，无需硬件
# 
# 架构:
#   Hub (端口 50000) 接收所有消息并广播
#   节点 1 (Leader):   TX=50000, RX=50001
#   节点 2 (Follower): TX=50000, RX=50002
#   ...
# ============================================================================

set -e

NODES=${1:-4}        # 节点数，默认 4
ROUNDS=${2:-20}      # 每组测试轮数，默认 20 (仿真用较少轮数)

echo "=============================================="
echo "🔬 可靠性共识实验 - 软件仿真模式"
echo "=============================================="
echo "节点数: $NODES"
echo "测试轮数: $ROUNDS"
echo "=============================================="

# 清理之前的进程
echo "🧹 清理旧进程..."
pkill -f "sim_hub_lite" 2>/dev/null || true
pkill -f "raft_leader_reliability" 2>/dev/null || true
pkill -f "raft_follower_reliability" 2>/dev/null || true
sleep 1

# 启动仿真 Hub
echo "🌐 启动仿真 Hub..."
python3 scripts/core/sim_hub_lite.py --nodes $NODES --port 50000 &
HUB_PID=$!
sleep 1

# 启动 Follower 节点 (从节点 2 开始)
echo "👥 启动 Follower 节点..."
for ((i=2; i<=NODES; i++)); do
    RX_PORT=$((50000 + i))
    # 仿真模式下不需要真实的 ctrl 端口，用一个假端口
    CTRL_PORT=$((9000 + i))
    
    echo "   节点 $i: RX=$RX_PORT, Ctrl=$CTRL_PORT"
    python3 scripts/app/raft_follower_reliability.py \
        --id $i \
        --total $NODES \
        --tx 50000 \
        --rx $RX_PORT \
        --ctrl $CTRL_PORT \
        --status-interval 5.0 &
    
    sleep 0.3
done

sleep 2

# 生成 n_levels 字符串 (1,2,3,...,NODES)
N_LEVELS=$(seq -s, 1 $NODES)

echo ""
echo "=============================================="
echo "🔧 Leader 参数:"
echo "   SNR 等级: 20.0 (仿真模式固定)"
echo "   p_node 等级: 0.6,0.7,0.8,0.9,1.0"
echo "   系统规模 n: $N_LEVELS"
echo "   测试轮数: $ROUNDS"
echo "=============================================="
echo ""
echo "3 秒后自动启动 Leader..."
sleep 3

# 启动 Leader (使用 yes 自动发送 Enter)
echo "" | python3 scripts/app/raft_leader_reliability.py \
    --id 1 \
    --total $NODES \
    --tx 50000 \
    --rx 50001 \
    --snr-levels "20.0" \
    --p-node-levels "0.6,0.7,0.8,0.9,1.0" \
    --n-levels "$N_LEVELS" \
    --rounds $ROUNDS \
    --vote-deadline 0.3 \
    --stabilize-time 2.0

# 清理
echo ""
echo "🧹 清理进程..."
kill $HUB_PID 2>/dev/null || true
pkill -f "raft_follower_reliability" 2>/dev/null || true

echo "✅ 仿真测试完成"
