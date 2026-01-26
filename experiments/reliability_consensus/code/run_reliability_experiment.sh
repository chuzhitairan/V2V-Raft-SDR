#!/bin/bash
# ============================================
# 可靠性共识实验 - 启动脚本
# ============================================
# Node 1 = Leader (实验控制)
# Node 2-6 = Follower (可信度模拟)
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 项目根目录 (脚本在 experiments/reliability_consensus/code/ 下)
PROJECT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
# 实验代码目录
EXPERIMENT_DIR="$SCRIPT_DIR"

# SDR 配置 (根据实际硬件调整)
# PC1: 4 台 E200
SDR_ARGS=(
    "addr=192.168.1.10"   # Node 1 (Leader)
    "addr=192.168.1.11"   # Node 2
    "addr=192.168.1.12"   # Node 3
    "addr=192.168.1.13"   # Node 4
)

NODE_IDS=(1 2 3 4)

# 增益配置
LEADER_TX_GAIN=${1:-0.8}
LEADER_RX_GAIN=${2:-0.95}
FOLLOWER_TX_GAIN=${3:-0.5}
FOLLOWER_RX_GAIN=${4:-0.95}

# 端口配置
APP_TX_PORTS=(10001 10002 10003 10004)
APP_RX_PORTS=(20001 20002 20003 20004)
CTRL_PORTS=(9001 9002 9003 9004)

# 全局配置
TOTAL_NODES=6    # 包括 PC2 上的两个节点
LEADER_ID=1

# 实验参数 (可通过命令行覆盖)
SNR_LEVELS=${5:-"16.0,6.0"}
P_NODE_LEVELS=${6:-"0.6,0.7,0.8,0.9"}
N_LEVELS=${7:-"1,2,3,4,5,6"}
ROUNDS=${8:-50}
VOTE_DEADLINE=${9:-0.5}
STABILIZE_TIME=${10:-10.0}

# 窗口布局 (2x2)
get_screen_size() {
    if command -v xdpyinfo &> /dev/null; then
        xdpyinfo | grep dimensions | awk '{print $2}'
    else
        echo "1920x1080"
    fi
}

SCREEN_SIZE=$(get_screen_size)
SCREEN_W=$(echo $SCREEN_SIZE | cut -d'x' -f1)
SCREEN_H=$(echo $SCREEN_SIZE | cut -d'x' -f2)
COLS=2
ROWS=2

WIN_W_PX=$((SCREEN_W / COLS))
WIN_H_PX=$((SCREEN_H / ROWS))
WIN_COLS=80
WIN_ROWS=24

check_phy_ready() {
    local port=$1
    local timeout=30
    local count=0
    
    while [ $count -lt $timeout ]; do
        response=$(echo '{"cmd":"ping"}' | timeout 1 nc -u -w1 127.0.0.1 $port 2>/dev/null)
        if [[ "$response" == *"pong"* ]]; then
            return 0
        fi
        sleep 1
        count=$((count + 1))
    done
    return 1
}

cleanup() {
    echo ""
    echo "🛑 停止所有进程..."
    pkill -f "v2v_hw_phy.py" 2>/dev/null
    pkill -f "raft_leader_reliability.py" 2>/dev/null
    pkill -f "raft_follower_reliability.py" 2>/dev/null
    sleep 2
    echo "✅ 清理完成"
}

trap cleanup EXIT INT TERM

echo "============================================"
echo "可靠性共识实验 - E200 节点"
echo "============================================"
echo "Leader: Node 1"
echo "Follower: Node 2-4 (PC1) + Node 5-6 (PC2 手动)"
echo ""
echo "实验参数:"
echo "  SNR 等级: $SNR_LEVELS"
echo "  p_node 等级: $P_NODE_LEVELS"
echo "  系统规模 n: $N_LEVELS"
echo "  每组测试轮数: $ROUNDS"
echo "  投票截止时间: ${VOTE_DEADLINE}s"
echo "============================================"
echo ""

# ============================================
# 第一阶段: 启动 PHY 层
# ============================================
echo "🚀 第一阶段: 启动 PHY 层"
echo "--------------------------------------------"

for i in "${!NODE_IDS[@]}"; do
    node_id="${NODE_IDS[$i]}"
    sdr_arg="${SDR_ARGS[$i]}"
    tx_port="${APP_TX_PORTS[$i]}"
    rx_port="${APP_RX_PORTS[$i]}"
    ctrl_port="${CTRL_PORTS[$i]}"
    
    if [ $node_id -eq $LEADER_ID ]; then
        tx_gain=$LEADER_TX_GAIN
        rx_gain=$LEADER_RX_GAIN
        role="LEADER"
    else
        tx_gain=$FOLLOWER_TX_GAIN
        rx_gain=$FOLLOWER_RX_GAIN
        role="FOLLOWER"
    fi
    
    echo "   启动 Node $node_id PHY ($role)"
    
    python3 $PROJECT_DIR/scripts/core/v2v_hw_phy.py \
        --sdr-args "$sdr_arg" \
        --udp-recv-port $tx_port \
        --udp-send-port $rx_port \
        --ctrl-port $ctrl_port \
        --tx-gain $tx_gain \
        --rx-gain $rx_gain \
        --no-gui \
        &
    
    sleep 2
done

echo ""
echo "⏳ 等待 PHY 层就绪..."
sleep 5

for i in "${!NODE_IDS[@]}"; do
    node_id="${NODE_IDS[$i]}"
    ctrl_port="${CTRL_PORTS[$i]}"
    
    if check_phy_ready $ctrl_port; then
        echo "   ✅ Node $node_id PHY 就绪"
    else
        echo "   ❌ Node $node_id PHY 启动超时"
        cleanup
        exit 1
    fi
    
    sleep 1
done

echo ""
echo "✅ 所有 PHY 层已就绪"
echo ""

# ============================================
# 第二阶段: 启动应用层
# ============================================
echo "🚀 第二阶段: 启动应用层"
echo "--------------------------------------------"

win_idx=0

for node_id in "${NODE_IDS[@]}"; do
    idx=-1
    for i in "${!NODE_IDS[@]}"; do
        if [ ${NODE_IDS[$i]} -eq $node_id ]; then
            idx=$i
            break
        fi
    done
    
    tx_port="${APP_TX_PORTS[$idx]}"
    rx_port="${APP_RX_PORTS[$idx]}"
    ctrl_port="${CTRL_PORTS[$idx]}"
    
    col=$((win_idx % COLS))
    row=$((win_idx / COLS))
    x=$((col * WIN_W_PX))
    y=$((row * WIN_H_PX))
    
    if [ $node_id -eq $LEADER_ID ]; then
        # Leader 节点
        title="Node $node_id [LEADER] 可靠性实验"
        color="yellow"
        
        echo "   启动 $title"
        
        xterm -bg black -fg $color -title "$title" \
            -fa 'Monospace' -fs 14 \
            -geometry ${WIN_COLS}x${WIN_ROWS}+${x}+${y} \
            -e bash -c "
                echo '=== $title ==='
                echo 'PHY 已就绪，启动实验 Leader...'
                python3 $EXPERIMENT_DIR/raft_leader_reliability.py \
                    --id $node_id \
                    --total $TOTAL_NODES \
                    --tx $tx_port \
                    --rx $rx_port \
                    --snr-levels '$SNR_LEVELS' \
                    --p-node-levels '$P_NODE_LEVELS' \
                    --n-levels '$N_LEVELS' \
                    --rounds $ROUNDS \
                    --vote-deadline $VOTE_DEADLINE \
                    --stabilize-time $STABILIZE_TIME
                echo '实验已结束，按回车关闭窗口...'
                read
            " &
    else
        # Follower 节点
        title="Node $node_id [Follower] 可靠性模拟"
        color="white"
        
        echo "   启动 $title"
        
        xterm -bg black -fg $color -title "$title" \
            -fa 'Monospace' -fs 14 \
            -geometry ${WIN_COLS}x${WIN_ROWS}+${x}+${y} \
            -e bash -c "
                echo '=== $title ==='
                echo 'PHY 已就绪，启动 Follower...'
                python3 $EXPERIMENT_DIR/raft_follower_reliability.py \
                    --id $node_id \
                    --total $TOTAL_NODES \
                    --tx $tx_port \
                    --rx $rx_port \
                    --ctrl $ctrl_port \
                    --target-snr 16.0 \
                    --init-gain $FOLLOWER_TX_GAIN \
                    --p-node 1.0 \
                    --status-interval 5.0
                echo '应用层已停止，按回车关闭窗口...'
                read
            " &
    fi
    
    win_idx=$((win_idx + 1))
    sleep 0.5
done

echo ""
echo "============================================"
echo "可靠性共识实验节点已启动！"
echo ""
echo "📋 PC2 手动启动说明 (Node 5, 6):"
echo "   1. 启动 PHY:"
echo "      python3 scripts/core/v2v_hw_phy.py --sdr-args 'addr=...' \\"
echo "          --tx-port 20005 --rx-port 10005 --ctrl-port 9005 \\"
echo "          --tx-gain 0.5 --rx-gain 0.9"
echo ""
echo "   2. 启动 Follower:"
echo "      python3 experiments/reliability_consensus/code/raft_follower_reliability.py \\"
echo "          --id 5 --total 6 --tx 10005 --rx 20005 --ctrl 9005"
echo ""
echo "⌨️  在 Leader 窗口按 Enter 开始实验"
echo "按 Ctrl+C 停止所有节点"
echo "============================================"

wait
