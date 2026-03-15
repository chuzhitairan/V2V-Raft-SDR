#!/usr/bin/env python3
"""
RTT (Round-Trip Time) 

 SDR PHY  Raft 


:
    python3 core/v2v_hw_phy.py --sdr-args "addr=192.168.1.10"
    
    python3 experiments/pre_test/rtt_benchmark.py --packets 100
"""

import socket
import time
import json
import argparse
import threading
import statistics
from dataclasses import dataclass, asdict
from typing import List, Optional
from datetime import datetime

DEFAULT_TX_PORT = 10000
DEFAULT_RX_PORT = 20000


@dataclass
class PingMessage:
    """Ping """
    type: str = "ping"
    seq: int = 0
    timestamp: float = 0.0
    payload: str = ""
    
    def to_json(self) -> str:
        return json.dumps(asdict(self))
    
    @staticmethod
    def from_json(data: str) -> Optional['PingMessage']:
        try:
            d = json.loads(data)
            return PingMessage(**d)
        except:
            return None


class RTTBenchmark:
    def __init__(self, tx_port: int, rx_port: int, timeout: float = 2.0):
        self.tx_port = tx_port
        self.rx_port = rx_port
        self.timeout = timeout
        
        # Send  socket
        self.tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Receive  socket
        self.rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.rx_sock.bind(("0.0.0.0", rx_port))
        self.rx_sock.settimeout(timeout)
        
        self.pending = {}  # seq -> send_time
        self.rtts: List[float] = []
        self.lost = 0
        self.received = 0
        
        self.running = True
        self.lock = threading.Lock()
    
    def recv_loop(self):
        """Receive """
        while self.running:
            try:
                data, _ = self.rx_sock.recvfrom(4096)
                recv_time = time.time()
                
                msg = PingMessage.from_json(data.decode('utf-8'))
                if msg and msg.type == "ping":
                    with self.lock:
                        if msg.seq in self.pending:
                            send_time = self.pending.pop(msg.seq)
                            rtt = (recv_time - send_time) * 1000
                            self.rtts.append(rtt)
                            self.received += 1
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"Receive Error: {e}")
    
    def run(self, num_packets: int, interval: float, payload_size: int):
        """RunTest """
        print("=" * 60)
        print(" SDR RTT ")
        print("=" * 60)
        print(f"Send Port : {self.tx_port}")
        print(f"Receive Port : {self.rx_port}")
        print(f": {num_packets}")
        print(f": {interval * 1000:.0f} ms")
        print(f": ~{payload_size + 50} bytes")
        print(f"Timeout Time : {self.timeout} s")
        print("=" * 60)
        print()
        
        recv_thread = threading.Thread(target=self.recv_loop, daemon=True)
        recv_thread.start()
        
        payload = "X" * payload_size
        
        print(" StartSend ...")
        start_time = time.time()
        
        for seq in range(num_packets):
            msg = PingMessage(
                type="ping",
                seq=seq,
                timestamp=time.time(),
                payload=payload
            )
            
            with self.lock:
                self.pending[seq] = time.time()
            
            data = msg.to_json().encode('utf-8')
            self.tx_sock.sendto(data, ("127.0.0.1", self.tx_port))
            
            if (seq + 1) % 10 == 0 or seq == num_packets - 1:
                print(f"  Send : {seq + 1}/{num_packets}, Received : {self.received}", end='\r')
            
            time.sleep(interval)
        
        print(f"\n\n Waiting  ({self.timeout}s)...")
        time.sleep(self.timeout)
        
        self.running = False
        total_time = time.time() - start_time
        
        with self.lock:
            self.lost = len(self.pending)
        
        self.print_results(num_packets, total_time)
        
        return self.rtts
    
    def print_results(self, num_packets: int, total_time: float):
        """Stats Result """
        print()
        print("=" * 60)
        print(" Result ")
        print("=" * 60)
        
        loss_rate = self.lost / num_packets * 100
        
        print(f"Send : {num_packets} ")
        print(f"Receive : {self.received} ")
        print(f": {self.lost}  ({loss_rate:.1f}%)")
        print(f"Time : {total_time:.2f} s")
        print()
        
        if self.rtts:
            rtt_min = min(self.rtts)
            rtt_max = max(self.rtts)
            rtt_avg = statistics.mean(self.rtts)
            rtt_std = statistics.stdev(self.rtts) if len(self.rtts) > 1 else 0
            rtt_median = statistics.median(self.rtts)
            
            sorted_rtts = sorted(self.rtts)
            p95_idx = int(len(sorted_rtts) * 0.95)
            p99_idx = int(len(sorted_rtts) * 0.99)
            rtt_p95 = sorted_rtts[p95_idx] if p95_idx < len(sorted_rtts) else rtt_max
            rtt_p99 = sorted_rtts[p99_idx] if p99_idx < len(sorted_rtts) else rtt_max
            
            print("RTT Stats  ():")
            print(f"  : {rtt_min:.2f} ms")
            print(f"  : {rtt_max:.2f} ms")
            print(f"  Avg : {rtt_avg:.2f} ms")
            print(f"  : {rtt_std:.2f} ms")
            print(f"  : {rtt_median:.2f} ms")
            print(f"  P95:    {rtt_p95:.2f} ms")
            print(f"  P99:    {rtt_p99:.2f} ms")
            print()
            
            print("=" * 60)
            print(" Raft ")
            print("=" * 60)
            
            suggested_heartbeat = rtt_p95 * 4 / 1000
            suggested_heartbeat = max(suggested_heartbeat, 0.1)
            
            suggested_timeout_min = suggested_heartbeat * 10
            suggested_timeout_max = suggested_heartbeat * 20
            
            print(f" P95 RTT ({rtt_p95:.1f} ms) :")
            print()
            print(f"  heartbeat_interval = {suggested_heartbeat:.2f} s")
            print(f"  T_base = {suggested_timeout_min:.2f} ~ {suggested_timeout_max:.2f} s")
            print()
            print(":")
            print("   heartbeat_interval > 2~3  RTT (Heartbeat Timeout )")
            print("   T_base > 10  heartbeat_interval (Election )")
            print("    T_base")
            
            print()
            print("=" * 60)
            print(" RTT ")
            print("=" * 60)
            self.print_histogram()
        else:
            print(" Received !")
            print()
            print(":")
            print("  1. SDR PHY Start ")
            print("  2. TX/RX Port ")
            print("  3. Connect ")
    
    def print_histogram(self, bins: int = 10):
        """ ASCII """
        if not self.rtts:
            return
        
        rtt_min = min(self.rtts)
        rtt_max = max(self.rtts)
        bin_width = (rtt_max - rtt_min) / bins if rtt_max > rtt_min else 1
        
        counts = [0] * bins
        for rtt in self.rtts:
            idx = min(int((rtt - rtt_min) / bin_width), bins - 1)
            counts[idx] += 1
        
        max_count = max(counts)
        bar_max_width = 40
        
        for i in range(bins):
            bin_start = rtt_min + i * bin_width
            bin_end = bin_start + bin_width
            count = counts[i]
            bar_width = int(count / max_count * bar_max_width) if max_count > 0 else 0
            bar = "" * bar_width
            print(f"  {bin_start:6.1f}-{bin_end:6.1f} ms | {bar} ({count})")


def main():
    parser = argparse.ArgumentParser(
        description="SDR RTT ",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
:
    python3 experiments/pre_test/rtt_benchmark.py
    
    python3 experiments/pre_test/rtt_benchmark.py --packets 200
    
    python3 experiments/pre_test/rtt_benchmark.py --interval 10
    
    python3 experiments/pre_test/rtt_benchmark.py --payload 500
        """
    )
    
    parser.add_argument("--packets", "-n", type=int, default=100,
                        help="Send  (: 100)")
    parser.add_argument("--interval", "-i", type=float, default=50,
                        help=" (, : 50)")
    parser.add_argument("--payload", "-s", type=int, default=100,
                        help=" (, : 100)")
    parser.add_argument("--timeout", "-t", type=float, default=2.0,
                        help="Receive Timeout  (, : 2.0)")
    parser.add_argument("--tx-port", type=int, default=DEFAULT_TX_PORT,
                        help=f"Send Port  (: {DEFAULT_TX_PORT})")
    parser.add_argument("--rx-port", type=int, default=DEFAULT_RX_PORT,
                        help=f"Receive Port  (: {DEFAULT_RX_PORT})")
    
    args = parser.parse_args()
    
    benchmark = RTTBenchmark(
        tx_port=args.tx_port,
        rx_port=args.rx_port,
        timeout=args.timeout
    )
    
    try:
        benchmark.run(
            num_packets=args.packets,
            interval=args.interval / 1000,
            payload_size=args.payload
        )
    except KeyboardInterrupt:
        print("\n Test ")


if __name__ == "__main__":
    main()
