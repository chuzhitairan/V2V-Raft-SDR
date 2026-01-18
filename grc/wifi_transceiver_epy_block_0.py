"""
Embedded Python Block: SNR Injector
"""

import numpy as np
from gnuradio import gr
import pmt
import json

class blk(gr.basic_block):  # 类名必须保持为 blk
    def __init__(self):
        gr.basic_block.__init__(self,
            name='SNR Injector',   # 这里是在 GRC 界面上显示的名字
            in_sig=None,
            out_sig=None)
        
        # 注册消息输入和输出端口
        self.message_port_register_in(pmt.intern('in'))
        self.message_port_register_out(pmt.intern('out'))
        self.set_msg_handler(pmt.intern('in'), self.handle_msg)

    def handle_msg(self, msg):
        # msg 是一个 pair: (metadata, payload)
        meta = pmt.car(msg)
        payload = pmt.cdr(msg)
        
        # 1. 尝试从 metadata 中提取 SNR
        # gr-ieee802-11 通常会将 SNR 存储在 'snr' 字段
        current_snr = 0.0
        try:
            if pmt.dict_has_key(meta, pmt.intern("snr")):
                current_snr = pmt.to_double(pmt.dict_ref(meta, pmt.intern("snr"), pmt.from_double(0.0)))
        except:
            pass
            
        # 2. 解析 Payload (假设是 JSON 字符串)
        try:
            # 将 u8vector 转为 bytes 再解码
            payload_bytes = bytes(pmt.u8vector_elements(payload))
            json_str = payload_bytes.decode('utf-8')
            
            # 3. 修改 JSON，注入 SNR
            data = json.loads(json_str)
            if 'phy_state' in data:
                data['phy_state']['snr'] = current_snr
            
            # 4. 重新打包
            new_json_str = json.dumps(data)
            new_payload_bytes = new_json_str.encode('utf-8')
            # 将 bytes 转回 u8vector
            new_payload = pmt.init_u8vector(len(new_payload_bytes), list(new_payload_bytes))
            
            # 生成新消息并发送
            new_msg = pmt.cons(meta, new_payload)
            self.message_port_pub(pmt.intern('out'), new_msg)
            
        except Exception as e:
            # 如果解析失败（非 JSON 数据），直接透传原数据
            self.message_port_pub(pmt.intern('out'), msg)
