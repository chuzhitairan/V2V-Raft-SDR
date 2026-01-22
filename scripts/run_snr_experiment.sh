#!/bin/bash
# ============================================
# SNR-集群规模关系实验 - 电脑 1 (4 台 E200)
# Node 1 = Leader (实验控制 + SNR 广播)
# Node 2-4 = Follower (增益自动调整)
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# SDR 配置 (4 台 E200)
SDR_ARGS=(
    "addr=192.168.1.10"   # Node 1 (Leader)
    "addr=192.168.1.11"   # Node 2
    "addr=192.168.1.12"   # Node 3
    "addr=192.168.1.13"   # Node 4
)

NODE_IDS=(1 2 3 4)

# 配置参数
# 用法: ./run_snr_experiment.sh [LEADER_GAIN] [FOLLOWER_INIT_GAIN] [START_SNR]
# 示例: ./run_snr_experiment.sh 0.8 0.7 20.0
LEADER_GAIN=${1:-0.8}
FOLLOWER_INIT_GAIN=${2:-0.7}
START_SNR=${3:-20.0}
STATUS_INTERVAL=${4:-2.0}

# 端口配置
APP_TX_PORTS=(10001 10002 10003 10004)
APP_RX_PORTS=(20001 20002 20003 20004)
CTRL_PORTS=(9001 9002 9003 9004)

# 全局配置
TOTAL_NODES=6
LEADER_ID=1

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
    pkill -f "raft_leader_snr_experiment.py" 2>/dev/null
    pkill -f "raft_follower_snr_experiment.py" 2>/dev/null
    sleep 2
    echo "✅ 清理完成"
}

trap cleanup EXIT INT TERM

echo "============================================"
echo "SNR-集群规模关系实验 - E200 节点"
echo "============================================"
echo "Leader: Node 1 (TX/RX 增益: $LEADER_GAIN)"
echo "Follower: Node 2-4 (初始增益: $FOLLOWER_INIT_GAIN)"
echo "起始 SNR: $START_SNR dB"
echo ""
echo "实验流程:"
echo "  1. SNR 稳定后自动开始测量"
echo "  2. 每个 SNR 测量 100 次集群规模"
echo "  3. SNR 每次降低 2 dB"
echo "  4. 平均集群规模≤1 时结束"
echo "============================================"
echo ""

# 清理旧进程
pkill -f "v2v_hw_phy.py" 2>/dev/null
pkill -f "raft_leader_snr_experiment.py" 2>/dev/null
pkill -f "raft_follower_snr_experiment.py" 2>/dev/null
pkill -f "raft_leader_snr_broadcast.py" 2>/dev/null
pkill -f "raft_follower_gain_adjust.py" 2>/dev/null
sleep 2

# ============================================
# 第一阶段: 启动 PHY 层
# ============================================
echo "📡 第一阶段: 启动 PHY 层"
echo "--------------------------------------------"

PHY_PIDS=()

for i in "${!NODE_IDS[@]}"; do
    node_id=${NODE_IDS[$i]}
    sdr_args=${SDR_ARGS[$i]}
    tx_port=${APP_TX_PORTS[$i]}
    rx_port=${APP_RX_PORTS[$i]}
    ctrl_port=${CTRL_PORTS[$i]}
    
    # Leader 使用指定增益，Follower 使用初始增益
    if [ $node_id -eq $LEADER_ID ]; then
        tx_gain=$LEADER_GAIN
        rx_gain=$LEADER_GAIN
    else
        tx_gain=$FOLLOWER_INIT_GAIN
        rx_gain=$FOLLOWER_INIT_GAIN
    fi
    
    echo "   启动 Node $node_id PHY (增益: TX=$tx_gain, RX=$rx_gain)..."
    
    python3 $PROJECT_DIR/scripts/core/v2v_hw_phy.py \
        --sdr-args "$sdr_args" \
        --tx-gain $tx_gain \
        --rx-gain $rx_gain \
        --udp-recv-port $tx_port \
        --udp-send-port $rx_port \
        --ctrl-port $ctrl_port \
        --no-gui &
    
    PHY_PIDS+=($!)
    
    echo "   等待 Node $node_id PHY 就绪..."
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
        # Leader 节点 - 实验版
        title="Node $node_id [LEADER] 实验控制"
        color="yellow"
        
        echo "   启动 $title"
        
        xterm -bg black -fg $color -title "$title" \
            -fa 'Monospace' -fs 14 \
            -geometry ${WIN_COLS}x${WIN_ROWS}+${x}+${y} \
            -e bash -c "
                echo '=== $title ==='
                echo 'PHY 已就绪，启动实验 Leader...'
                python3 $PROJECT_DIR/scripts/app/raft_leader_snr_experiment.py \
                    --id $node_id \
                    --total $TOTAL_NODES \
                    --tx $tx_port \
                    --rx $rx_port \
                    --start-snr $START_SNR \
                    --snr-step 2.0 \
                    --measurements 100 \
                    --stabilize-time 30.0 \
                    --snr-tolerance 3.0 \
                    --stable-count 3 \
                    --min-peers 1
                echo '应用层已停止，按回车关闭窗口...'
                read
            " &
    else
        # Follower 节点 - 实验版
        title="Node $node_id [Follower] 增益调整"
        color="white"
        
        echo "   启动 $title"
        
        xterm -bg black -fg $color -title "$title" \
            -fa 'Monospace' -fs 14 \
            -geometry ${WIN_COLS}x${WIN_ROWS}+${x}+${y} \
            -e bash -c "
                echo '=== $title ==='
                echo 'PHY 已就绪，启动实验 Follower...'
                python3 $PROJECT_DIR/scripts/app/raft_follower_snr_experiment.py \
                    --id $node_id \
                    --total $TOTAL_NODES \
                    --tx $tx_port \
                    --rx $rx_port \
                    --ctrl $ctrl_port \
                    --target-snr $START_SNR \
                    --init-gain $FOLLOWER_INIT_GAIN \
                    --status-interval $STATUS_INTERVAL
                echo '应用层已停止，按回车关闭窗口...'
                read
            " &
    fi
    
    win_idx=$((win_idx + 1))
    sleep 0.5
done

echo ""
echo "============================================"
echo "SNR-集群规模实验节点已启动！"
echo ""
echo "📊 Leader 窗口会显示观测到的各节点 SNR"
echo "🔧 Follower 会根据目标 SNR 自动调整 TX 增益"
echo "🎯 SNR 稳定后自动开始集群规模测量"
echo ""
echo "按 Ctrl+C 停止所有节点"
echo "============================================"

wait
