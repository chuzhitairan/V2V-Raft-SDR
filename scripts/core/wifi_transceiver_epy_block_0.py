"""
Embedded Python Block: SNR Injector
====================================

从 gr-ieee802-11 解码后的消息 metadata 中提取 SNR 值，
注入到 JSON payload 的 phy_state.snr 字段中。

消息流:
    decode_mac (mac_out) --> [SNR Injector] --> UDP Sink

输入: PMT pair (metadata, payload)
    - metadata: 包含 'snr' 字段 (由 frame_equalizer 计算)
    - payload:  JSON 格式的应用层数据

输出: PMT pair (metadata, modified_payload)
    - payload 中的 phy_state.snr 被更新为实际 SNR 值
"""

import numpy as np
from gnuradio import gr
import pmt
import json


class blk(gr.basic_block):
    """
    SNR 注入器
    
    从 802.11 帧的 metadata 中提取 SNR，注入到 JSON payload。
    非 JSON 数据直接透传。
    """
    
    def __init__(self):
        gr.basic_block.__init__(
            self,
            name='SNR Injector',
            in_sig=None,
            out_sig=None
        )
        
        # 注册消息端口
        self.message_port_register_in(pmt.intern('in'))
        self.message_port_register_out(pmt.intern('out'))
        self.set_msg_handler(pmt.intern('in'), self.handle_msg)

    def handle_msg(self, msg):
        """
        处理接收到的消息
        
        Args:
            msg: PMT pair (metadata, payload)
        """
        # 解构消息
        meta = pmt.car(msg)
        payload = pmt.cdr(msg)
        
        # Step 1: 从 metadata 提取 SNR
        # gr-ieee802-11 的 frame_equalizer 会计算并存储 SNR
        snr = self._extract_snr(meta)
        
        # Step 2: 尝试注入 SNR 到 JSON payload
        try:
            # 将 u8vector 转为 bytes
            payload_bytes = bytes(pmt.u8vector_elements(payload))
            json_str = payload_bytes.decode('utf-8')
            
            # 解析并修改 JSON
            data = json.loads(json_str)
            if 'phy_state' in data:
                data['phy_state']['snr'] = snr
            
            # 重新打包
            new_json = json.dumps(data, separators=(',', ':'))  # 紧凑格式
            new_bytes = new_json.encode('utf-8')
            new_payload = pmt.init_u8vector(len(new_bytes), list(new_bytes))
            
            # 发送修改后的消息
            self.message_port_pub(pmt.intern('out'), pmt.cons(meta, new_payload))
            
        except (json.JSONDecodeError, UnicodeDecodeError):
            # 非 JSON 数据，直接透传
            self.message_port_pub(pmt.intern('out'), msg)
        except Exception as e:
            # 其他错误，透传并记录
            print(f"[SNR Injector] Error: {e}")
            self.message_port_pub(pmt.intern('out'), msg)

    def _extract_snr(self, meta) -> float:
        """
        从 metadata 中提取 SNR 值
        
        Args:
            meta: PMT dict 格式的 metadata
            
        Returns:
            SNR 值 (dB)，提取失败返回 0.0
        """
        try:
            if pmt.dict_has_key(meta, pmt.intern("snr")):
                return pmt.to_double(
                    pmt.dict_ref(meta, pmt.intern("snr"), pmt.from_double(0.0))
                )
        except (RuntimeError, TypeError):
            # PMT 类型转换失败
            pass
        return 0.0

