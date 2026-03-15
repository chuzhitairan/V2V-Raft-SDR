"""
Embedded Python Block: SNR Injector
====================================

Extract SNR value from gr-ieee802-11 decoded message metadata,
And inject it into phy_state.snr field of JSON payload.

Message Flow:
    decode_mac (mac_out) --> [SNR Injector] --> UDP Sink

Input: PMT pair (metadata, payload)
    - metadata: Contains 'snr' field (calculated by frame_equalizer)
    - payload:  JSON format application layer data

Output: PMT pair (metadata, modified_payload)
    - payload phy_state.snr is updated to actual SNR value
"""

import numpy as np
from gnuradio import gr
import pmt
import json


class blk(gr.basic_block):
    """
    SNR Injector
    
    Extract SNR from 802.11 frame metadata and inject it into JSON payload.
    Non-JSON data is passed through directly.
    """
    
    def __init__(self):
        gr.basic_block.__init__(
            self,
            name='SNR Injector',
            in_sig=None,
            out_sig=None
        )
        
        # Register message ports
        self.message_port_register_in(pmt.intern('in'))
        self.message_port_register_out(pmt.intern('out'))
        self.set_msg_handler(pmt.intern('in'), self.handle_msg)
        
        # Debug counter
        self._msg_count = 0
        self._debug_enabled = True  # Enable debug output

    def handle_msg(self, msg):
        """
        Process received message
        
        Args:
            msg: PMT pair (metadata, payload)
        """
        # Destructure message
        meta = pmt.car(msg)
        payload = pmt.cdr(msg)
        
        # Step 1: Extract SNR from metadata
        # gr-ieee802-11 frame_equalizer calculates and stores SNR
        snr = self._extract_snr(meta)
        
        # Debug output
        self._msg_count += 1
        if self._debug_enabled and (self._msg_count <= 5 or self._msg_count % 50 == 0):
            print(f"[SNR Injector] msg#{self._msg_count} snr={snr:.1f}dB")
        
        # Step 2: Attempt to inject SNR into JSON payload
        try:
            # Convert u8vector to bytes
            payload_bytes = bytes(pmt.u8vector_elements(payload))
            json_str = payload_bytes.decode('utf-8')
            
            # Parse and modify JSON
            data = json.loads(json_str)
            if 'phy_state' in data:
                data['phy_state']['snr'] = snr
            
            # Repackage
            new_json = json.dumps(data, separators=(',', ':'))  # Compact format
            new_bytes = new_json.encode('utf-8')
            new_payload = pmt.init_u8vector(len(new_bytes), list(new_bytes))
            
            # Send modified message
            self.message_port_pub(pmt.intern('out'), pmt.cons(meta, new_payload))
            
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Non-JSON data, straight pass-through
            self.message_port_pub(pmt.intern('out'), msg)
        except Exception as e:
            # Other errors, pass-through and log
            print(f"[SNR Injector] Error: {e}")
            self.message_port_pub(pmt.intern('out'), msg)

    def _extract_snr(self, meta) -> float:
        """
        Extract SNR value from metadata
        
        Args:
            meta: PMT dict format metadata
            
        Returns:
            SNR value (dB), returns 0.0 if failed
        """
        try:
            # Try multiple possible key names
            for key_name in ["snr", "SNR", "snr_db", "evm"]:
                if pmt.dict_has_key(meta, pmt.intern(key_name)):
                    val = pmt.dict_ref(meta, pmt.intern(key_name), pmt.from_double(0.0))
                    return pmt.to_double(val)
            
            # Debug: Print all metadata keys
            if self._debug_enabled and self._msg_count <= 3:
                print(f"[SNR Injector] metadata keys: {pmt.to_python(meta)}")
                
        except (RuntimeError, TypeError) as e:
            if self._debug_enabled:
                print(f"[SNR Injector] extract error: {e}")
        return 0.0

