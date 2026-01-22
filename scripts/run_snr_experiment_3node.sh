#!/bin/bash
# ============================================
# SNR-集群规模关系实验 - 3 节点测试版
# Node 1 = Leader
# Node 2-3 = Follower
# 用于验证通信是否正常
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# SDR 配置 (3 台 E200)
SDR_ARGS=(
    "addr=192.168.1.10"   # Node 1 (Leader)
    "addr=192.168.1.11"   # Node 2
    "addr=192.168.1.12"   # Node 3
)

NODE_IDS=(1 2 3)

# 配置参数
LEADER_GAIN=${1:-0.8}
FOLLOWER_INIT_GAIN=${2:-0.7}
START_SNR=${3:-20.0}
STATUS_INTERVAL=${4:-2.0}
DEBUG_MODE=${5:-0}  # 默认关闭调试模式（0=正常模式，1=无限等待）

# 端口配置
APP_TX_PORTS=(10001 10002 10003)
APP_RX_PORTS=(20001 20002 20003)
CTRL_PORTS=(9001 9002 9003)

# 全局配置
TOTAL_NODES=3
LEADER_ID=1

# 窗口布局
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
WIN_COLS=100
WIN_ROWS=30

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
echo "SNR-集群规模实验 - 3节点测试版"
echo "============================================"
echo "Leader: Node 1 (增益: $LEADER_GAIN)"
echo "Follower: Node 2-3 (初始增益: $FOLLOWER_INIT_GAIN)"
echo "起始 SNR: $START_SNR dB"
if [ "$DEBUG_MODE" == "1" ]; then
    echo "🔧 调试模式: 启用 (无限等待SNR稳定)"
fi
echo ""
echo "用法: ./run_snr_experiment_3node.sh [LEADER_GAIN] [FOLLOWER_GAIN] [START_SNR] [STATUS_INTERVAL] [DEBUG_MODE]"
echo "示例: ./run_snr_experiment_3node.sh 0.8 0.7 20.0 2.0 1"
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
    
    if [ $node_id -eq $LEADER_ID ]; then
        tx_gain=$LEADER_GAIN
        rx_gain=$LEADER_GAIN
    else
        tx_gain=$FOLLOWER_INIT_GAIN
        rx_gain=$FOLLOWER_INIT_GAIN
    fi
    
    echo "   启动 Node $node_id PHY ($sdr_args, 增益: TX=$tx_gain, RX=$rx_gain)..."
    
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
        echo "   ❌ Node $node_id PHY 启动超时，跳过..."
        # 不退出，继续尝试其他节点
    fi
    
    sleep 1
done

echo ""
echo "✅ PHY 层启动完成"
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
        title="Node $node_id [LEADER] 实验控制"
        color="yellow"
        
        # 构建 debug-wait 参数
        DEBUG_ARG=""
        if [ "$DEBUG_MODE" == "1" ]; then
            DEBUG_ARG="--debug-wait"
        fi
        
        echo "   启动 $title"
        
        xterm -bg black -fg $color -title "$title" \
            -fa 'Monospace' -fs 12 \
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
                    --stabilize-time 60.0 \
                    --snr-tolerance 3.0 \
                    --stable-count 3 \
                    --min-peers 1 \
                    $DEBUG_ARG
                echo '应用层已停止，按回车关闭窗口...'
                read
            " &
    else
        title="Node $node_id [Follower] 增益调整"
        color="white"
        
        echo "   启动 $title"
        
        xterm -bg black -fg $color -title "$title" \
            -fa 'Monospace' -fs 12 \
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
echo "3节点测试已启动！"
echo ""
echo "📊 Leader 窗口会显示各节点 SNR"
echo "🔧 Follower 会根据目标 SNR 自动调整 TX 增益"
if [ "$DEBUG_MODE" == "1" ]; then
    echo "💡 调试模式: Leader 会无限等待，观察节点是否连上"
fi
echo ""
echo "按 Ctrl+C 停止所有节点"
echo "============================================"

wait
