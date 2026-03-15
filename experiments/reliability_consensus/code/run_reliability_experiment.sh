#!/bin/bash
# ============================================
# - Start 
# ============================================
# Node 1 = Leader ()
# Node 2-6 = Follower (Simulate )
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# ( experiments/reliability_consensus/code/ )
PROJECT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
# 
EXPERIMENT_DIR="$SCRIPT_DIR"

# SDR Config (Adjust )
# PC1: 4 E200
SDR_ARGS=(
 "addr=192.168.1.10" # Node 1 (Leader)
 "addr=192.168.1.11" # Node 2
 "addr=192.168.1.12" # Node 3
 "addr=192.168.1.13" # Node 4
)

NODE_IDS=(1 2 3 4)

# Gain Config 
LEADER_TX_GAIN=${1:-0.8}
LEADER_RX_GAIN=${2:-0.95}
FOLLOWER_TX_GAIN=${3:-0.5}
FOLLOWER_RX_GAIN=${4:-0.95}

# Port Config 
APP_TX_PORTS=(10001 10002 10003 10004)
APP_RX_PORTS=(20001 20002 20003 20004)
CTRL_PORTS=(9001 9002 9003 9004)

# Config 
TOTAL_NODES=6 # PC2 Node 
LEADER_ID=1

# ()
SNR_LEVELS=${5:-"16.0,6.0"}
P_NODE_LEVELS=${6:-"0.6,0.7,0.8,0.9"}
N_LEVELS=${7:-"1,2,3,4,5,6"}
ROUNDS=${8:-50}
VOTE_DEADLINE=${9:-0.5}
STABILIZE_TIME=${10:-10.0}

# (2x2)
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
 echo " Stop ..."
 pkill -f "v2v_hw_phy.py" 2>/dev/null
 pkill -f "raft_leader_reliability.py" 2>/dev/null
 pkill -f "raft_follower_reliability.py" 2>/dev/null
 sleep 2
 echo " "
}

trap cleanup EXIT INT TERM

echo "============================================"
echo " - E200 Node "
echo "============================================"
echo "Leader: Node 1"
echo "Follower: Node 2-4 (PC1) + Node 5-6 (PC2 )"
echo ""
echo ":"
echo " SNR : $SNR_LEVELS"
echo " p_node : $P_NODE_LEVELS"
echo " n: $N_LEVELS"
echo " Test : $ROUNDS"
echo " Vote : ${VOTE_DEADLINE}s"
echo "============================================"
echo ""

# ============================================
# : Start PHY 
# ============================================
echo " : Start PHY "
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
 
 echo " Start Node $node_id PHY ($role)"
 
 python3 $PROJECT_DIR/core/v2v_hw_phy.py \
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
echo " Waiting PHY ..."
sleep 5

for i in "${!NODE_IDS[@]}"; do
 node_id="${NODE_IDS[$i]}"
 ctrl_port="${CTRL_PORTS[$i]}"
 
 if check_phy_ready $ctrl_port; then
 echo " Node $node_id PHY "
 else
 echo " Node $node_id PHY Start Timeout "
 cleanup
 exit 1
 fi
 
 sleep 1
done

echo ""
echo " PHY "
echo ""

# ============================================
# : Start 
# ============================================
echo " : Start "
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
 # Leader Node 
 title="Node $node_id [LEADER] "
 color="yellow"
 
 echo " Start $title"
 
 xterm -bg black -fg $color -title "$title" \
 -fa 'Monospace' -fs 14 \
 -geometry ${WIN_COLS}x${WIN_ROWS}+${x}+${y} \
 -e bash -c "
 echo '=== $title ==='
 echo 'PHY Start Leader...'
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
 echo 'End ...'
 read
 " &
 else
 # Follower Node 
 title="Node $node_id [Follower] Simulate "
 color="white"
 
 echo " Start $title"
 
 xterm -bg black -fg $color -title "$title" \
 -fa 'Monospace' -fs 14 \
 -geometry ${WIN_COLS}x${WIN_ROWS}+${x}+${y} \
 -e bash -c "
 echo '=== $title ==='
 echo 'PHY Start Follower...'
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
 echo 'Stop ...'
 read
 " &
 fi
 
 win_idx=$((win_idx + 1))
 sleep 0.5
done

echo ""
echo "============================================"
echo "Node Start "
echo ""
echo " PC2 Start (Node 5, 6):"
echo " 1. Start PHY:"
echo " python3 core/v2v_hw_phy.py --sdr-args 'addr=...' \\"
echo " --udp-recv-port 10005 --udp-send-port 20005 --ctrl-port 9005 \\"
echo " --tx-gain 0.5 --rx-gain 0.9"
echo ""
echo " 2. Start Follower:"
echo " python3 experiments/reliability_consensus/code/raft_follower_reliability.py \\"
echo " --id 5 --total 6 --tx 10005 --rx 20005 --ctrl 9005"
echo ""
echo " Leader Enter "
echo " Ctrl+C Stop Node "
echo "============================================"

wait
