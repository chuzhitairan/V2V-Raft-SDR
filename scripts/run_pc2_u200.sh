#!/bin/bash
# ============================================
# 电脑 2: 2 台 U200 (Node 5-6)
# 都是 Follower
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 本机 SDR 配置 (2 台 U200)
SDR_ARGS=(
    "serial=U200100"      # Node 5
    "serial=U200101"      # Node 6
)

NODE_IDS=(5 6)

# 配置参数 (可通过命令行参数覆盖)
# 用法: ./run_pc2_u200.sh [TX_GAIN] [RX_GAIN] [STATUS_INTERVAL]
# 示例: ./run_pc2_u200.sh 0.8 0.6 2.0
TX_GAIN=${1:-0.7}
RX_GAIN=${2:-0.7}
STATUS_INTERVAL=${3:-2.0}

# 端口配置 (与全局配置一致)
APP_TX_PORTS=(10005 10006)
APP_RX_PORTS=(20005 20006)
CTRL_PORTS=(9005 9006)

# 总节点数 (全局)
TOTAL_NODES=6
LEADER_ID=1

# 窗口布局 (2x1)
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
ROWS=1

# 窗口像素尺寸
WIN_W_PX=$((SCREEN_W / COLS))
WIN_H_PX=$((SCREEN_H / ROWS))

# 窗口字符尺寸 (固定值，适合 14pt 字体)
WIN_COLS=80
WIN_ROWS=40

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
    pkill -f "raft_fixed_leader.py" 2>/dev/null
    sleep 2
    echo "✅ 清理完成"
}

trap cleanup EXIT INT TERM

echo "============================================"
echo "电脑 2: U200 节点 (Node 5-6)"
echo "============================================"
echo "Follower: Node 5, 6"
echo "Leader 在电脑 1 (Node 1)"
echo "TX/RX 增益: $TX_GAIN / $RX_GAIN"
echo ""
echo "⚠️  请确保电脑 1 也已启动 (Node 1-4)"
echo "============================================"
echo ""

# 清理旧进程
pkill -f "v2v_hw_phy.py" 2>/dev/null
pkill -f "raft_fixed_leader.py" 2>/dev/null
sleep 2

# ============================================
# 第一阶段: 逐个启动 PHY 层
# ============================================
echo "📡 第一阶段: 启动 PHY 层"
echo "--------------------------------------------"

PHY_PIDS=()
READY_NODES=()

for i in ${!NODE_IDS[@]}; do
    node_id=${NODE_IDS[$i]}
    sdr_args="${SDR_ARGS[$i]}"
    tx_port="${APP_TX_PORTS[$i]}"
    rx_port="${APP_RX_PORTS[$i]}"
    ctrl_port="${CTRL_PORTS[$i]}"
    
    echo -n "   Node $node_id ($sdr_args): "
    
    python3 "$PROJECT_DIR/scripts/core/v2v_hw_phy.py" \
        --sdr-args "$sdr_args" \
        --tx-gain $TX_GAIN \
        --rx-gain $RX_GAIN \
        --udp-recv-port $tx_port \
        --udp-send-port $rx_port \
        --ctrl-port $ctrl_port \
        --no-gui &
    PHY_PID=$!
    PHY_PIDS+=($PHY_PID)
    
    # U200 需要更长的初始化时间
    sleep 8
    
    if check_phy_ready $ctrl_port; then
        echo "✓ (PID: $PHY_PID)"
        READY_NODES+=($node_id)
    else
        echo "❌ (超时)"
    fi
    
    sleep 2
done

echo ""
echo "   就绪节点: ${READY_NODES[*]}"
echo ""

if [ ${#READY_NODES[@]} -lt 1 ]; then
    echo "❌ 没有就绪的节点"
    exit 1
fi

# ============================================
# 第二阶段: 启动应用层
# ============================================
echo "🚀 第二阶段: 启动应用层"
echo "--------------------------------------------"

win_idx=0
for node_id in "${READY_NODES[@]}"; do
    # 找到对应的索引
    for i in ${!NODE_IDS[@]}; do
        if [ ${NODE_IDS[$i]} -eq $node_id ]; then
            idx=$i
            break
        fi
    done
    
    tx_port="${APP_TX_PORTS[$idx]}"
    rx_port="${APP_RX_PORTS[$idx]}"
    
    # U200 节点都是 Follower
    role="follower"
    title="Node $node_id [Follower]"
    color="cyan"
    
    col=$((win_idx % COLS))
    row=$((win_idx / COLS))
    x=$((col * WIN_W_PX))
    y=$((row * WIN_H_PX))
    
    echo "   启动 $title"
    
    xterm -bg black -fg $color -title "$title" \
        -fa 'Monospace' -fs 14 \
        -geometry ${WIN_COLS}x${WIN_ROWS}+${x}+${y} \
        -e bash -c "
            echo '=== $title ==='
            echo 'PHY 已就绪，启动应用层...'
            python3 $PROJECT_DIR/scripts/app/raft_fixed_leader.py \
                --id $node_id \
                --role $role \
                --total $TOTAL_NODES \
                --tx $tx_port \
                --rx $rx_port \
                --leader-id $LEADER_ID \
                --status-interval $STATUS_INTERVAL
            echo '应用层已停止，按回车关闭窗口...'
            read
        " &
    
    win_idx=$((win_idx + 1))
    sleep 0.5
done

echo ""
echo "============================================"
echo "电脑 2 节点已启动！"
echo ""
echo "操作说明:"
echo "  - 这台电脑的节点都是 Follower"
echo "  - Leader 在电脑 1 (Node 1)"
echo "  - 等待电脑 1 发起共识请求"
echo "  - 按 Ctrl+C 停止所有节点"
echo "============================================"
echo ""

wait
