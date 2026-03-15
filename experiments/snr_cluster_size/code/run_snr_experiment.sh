#!/bin/bash
# ============================================
# SNR- - 1 (4 E200)
# Node 1 = Leader ( + SNR Broadcast )
# Node 2-4 = Follower (Gain Adjust )
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# SDR Config (4 E200)
SDR_ARGS=(
 "addr=192.168.1.10" # Node 1 (Leader)
 "addr=192.168.1.11" # Node 2
 "addr=192.168.1.12" # Node 3
 "addr=192.168.1.13" # Node 4
)

NODE_IDS=(1 2 3 4)

# Config 
# : ./run_snr_experiment.sh [LEADER_TX] [LEADER_RX] [FOLLOWER_TX] [FOLLOWER_RX] [START_SNR] [STATUS_INTERVAL]
# : ./run_snr_experiment.sh 0.8 0.9 0.7 0.9 20.0 2.0
LEADER_TX_GAIN=${1:-0.8}
LEADER_RX_GAIN=${2:-0.9}
FOLLOWER_TX_GAIN=${3:-0.7}
FOLLOWER_RX_GAIN=${4:-0.9}
START_SNR=${5:-20.0}
STATUS_INTERVAL=${6:-2.0}

# Port Config 
APP_TX_PORTS=(10001 10002 10003 10004)
APP_RX_PORTS=(20001 20002 20003 20004)
CTRL_PORTS=(9001 9002 9003 9004)

# Config 
TOTAL_NODES=6
LEADER_ID=1

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
 pkill -f "raft_leader_snr_experiment.py" 2>/dev/null
 pkill -f "raft_follower_snr_experiment.py" 2>/dev/null
 sleep 2
 echo " "
}

trap cleanup EXIT INT TERM

echo "============================================"
echo "SNR- - E200 Node "
echo "============================================"
echo "Leader: Node 1 (TX=$LEADER_TX_GAIN, RX=$LEADER_RX_GAIN)"
echo "Follower: Node 2-4 (TX=$FOLLOWER_TX_GAIN, RX=$FOLLOWER_RX_GAIN)"
echo " SNR: $START_SNR dB"
echo ""
echo ":"
echo " 1. SNR "
echo " 2. SNR 100 "
echo " 3. SNR 2 dB"
echo " 4. Avg 1 End "
echo "============================================"
echo ""

# 
pkill -f "v2v_hw_phy.py" 2>/dev/null
pkill -f "raft_leader_snr_experiment.py" 2>/dev/null
pkill -f "raft_follower_snr_experiment.py" 2>/dev/null
pkill -f "raft_leader_snr_broadcast.py" 2>/dev/null
pkill -f "raft_follower_gain_adjust.py" 2>/dev/null
sleep 2

# ============================================
# : Start PHY 
# ============================================
echo " : Start PHY "
echo "--------------------------------------------"

PHY_PIDS=()

for i in "${!NODE_IDS[@]}"; do
 node_id=${NODE_IDS[$i]}
 sdr_args=${SDR_ARGS[$i]}
 tx_port=${APP_TX_PORTS[$i]}
 rx_port=${APP_RX_PORTS[$i]}
 ctrl_port=${CTRL_PORTS[$i]}
 
 # Leader Gain Follower Gain 
 if [ $node_id -eq $LEADER_ID ]; then
 tx_gain=$LEADER_TX_GAIN
 rx_gain=$LEADER_RX_GAIN
 else
 tx_gain=$FOLLOWER_TX_GAIN
 rx_gain=$FOLLOWER_RX_GAIN
 fi
 
 echo " Start Node $node_id PHY (Gain : TX=$tx_gain, RX=$rx_gain)..."
 
 python3 $PROJECT_DIR/core/v2v_hw_phy.py \
 --sdr-args "$sdr_args" \
 --tx-gain $tx_gain \
 --rx-gain $rx_gain \
 --udp-recv-port $tx_port \
 --udp-send-port $rx_port \
 --ctrl-port $ctrl_port \
 --no-gui &
 
 PHY_PIDS+=($!)
 
 echo " Waiting Node $node_id PHY ..."
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
 # Leader Node - 
 title="Node $node_id [LEADER] "
 color="yellow"
 
 echo " Start $title"
 
 xterm -bg black -fg $color -title "$title" \
 -fa 'Monospace' -fs 14 \
 -geometry ${WIN_COLS}x${WIN_ROWS}+${x}+${y} \
 -e bash -c "
 echo '=== $title ==='
 echo 'PHY Start Leader...'
 python3 $PROJECT_DIR/experiments/snr_cluster_size/code/raft_leader_snr_experiment.py \
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
 --min-peers 1
 echo 'Stop ...'
 read
 " &
 else
 # Follower Node - 
 title="Node $node_id [Follower] Gain Adjust "
 color="white"
 
 echo " Start $title"
 
 xterm -bg black -fg $color -title "$title" \
 -fa 'Monospace' -fs 14 \
 -geometry ${WIN_COLS}x${WIN_ROWS}+${x}+${y} \
 -e bash -c "
 echo '=== $title ==='
 echo 'PHY Start Follower...'
 python3 $PROJECT_DIR/experiments/snr_cluster_size/code/raft_follower_snr_experiment.py \
 --id $node_id \
 --total $TOTAL_NODES \
 --tx $tx_port \
 --rx $rx_port \
 --ctrl $ctrl_port \
 --target-snr $START_SNR \
 --init-gain $FOLLOWER_TX_GAIN \
 --status-interval $STATUS_INTERVAL
 echo 'Stop ...'
 read
 " &
 fi
 
 win_idx=$((win_idx + 1))
 sleep 0.5
done

echo ""
echo "============================================"
echo "SNR-Node Start "
echo ""
echo " Leader Node SNR"
echo " Follower Target SNR Adjust TX Gain "
echo " SNR "
echo ""
echo " Ctrl+C Stop Node "
echo "============================================"

wait
