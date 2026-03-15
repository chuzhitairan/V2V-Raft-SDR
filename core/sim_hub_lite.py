"""
Lightweight Simulation Hub
--------------------------------
Purpose: Pure UDP forwarding to simulate a wireless broadcast channel for testing RAFT logic.
Fast startup without GNU Radio, suitable for development and debugging.

Architecture:
    Node 1 (TX:50000, RX:50001)  ──┐
    Node 2 (TX:50000, RX:50002)  ──┼──► Hub (Listen 50000) ──► Broadcast to 50001-50005
    Node 3 (TX:50000, RX:50003)  ──┘
    ...

Usage:
    python3 core/sim_hub_lite.py [--nodes 5] [--port 50000]
"""

import socket
import argparse
import time
from datetime import datetime

def main():
    parser = argparse.ArgumentParser(description="Lightweight Sim HubLite")
    parser.add_argument("--nodes", type=int, default=5, help="Nodecount (default 5)")
    parser.add_argument("--port", type=int, default=50000, help="Listenport (default 50000)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show verbose logs")
    args = parser.parse_args()
    
    # Calculate forwarding target port list
    rx_ports = [args.port + i for i in range(1, args.nodes + 1)]
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('127.0.0.1', args.port))
    
    print("=" * 60)
    print(" Lightweight Simulation Hub")
    print("=" * 60)
    print(f" Listen port: {args.port}")
    print(f" Broadcast targets: {rx_ports}")
    print(f" Supported nodes: {args.nodes} ")
    print("=" * 60)
    print("Waiting for messages...\n")
    
    msg_count = 0
    start_time = time.time()
    
    try:
        while True:
            data, addr = sock.recvfrom(4096)
            msg_count += 1
            
            # Broadcast to all nodes
            for port in rx_ports:
                sock.sendto(data, ('127.0.0.1', port))
            
            if args.verbose:
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                # Attempt to parse message type
                try:
                    import json
                    msg = json.loads(data.decode('utf-8'))
                    msg_type = msg.get('type', 'Unknown')
                    sender_id = msg.get('sender_id', '?')
                    term = msg.get('term', '?')
                    print(f"[{timestamp}] #{msg_count} | {msg_type:20} | Node {sender_id} | Term {term}")
                except:
                    print(f"[{timestamp}] #{msg_count} | RAW: {data[:50]}...")
            else:
                # Concise mode: print statistics every 100 messages
                if msg_count % 100 == 0:
                    elapsed = time.time() - start_time
                    rate = msg_count / elapsed
                    print(f" Forwarded {msg_count} messages ({rate:.1f} msg/s)")
                    
    except KeyboardInterrupt:
        elapsed = time.time() - start_time
        print(f"\n\n Stopped running")
        print(f" Stats: {msg_count} messages, Running for {elapsed:.1f} seconds, Average {msg_count/elapsed:.1f} msg/s")


if __name__ == "__main__":
    main()
