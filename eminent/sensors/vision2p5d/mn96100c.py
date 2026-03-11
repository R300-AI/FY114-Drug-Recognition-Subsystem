#--------------------------------------------------------------------
# Project  : MN98100C
# Author   : Charlie Wang
# Date     : 2025.9.10
# Versuion : 1.0.20250910
# 
# Eminent Electronic Technology, All right reserved 
#--------------------------------------------------------------------


import cv2
import numpy as np
import threading
import time
import os 
import queue

import usb.core
import usb.util
import usb.backend.libusb1


#--------------------------------------------------------------------
# class USBDeviceComm
#--------------------------------------------------------------------
class USBDeviceComm:
    def __init__(self, vid=0x04F3, pid=0x0C7E, ep_out_addr=0x01, ep_in_addr=0x83):
        self.vid = vid
        self.pid = pid
        self.ep_out_addr = ep_out_addr
        self.ep_in_addr = ep_in_addr
        self.device = None
        self.endpoint_out = None
        self.endpoint_in = None

    def connect(self):
        # 使用 libusb1 後端（依賴系統已安裝/可找到 libusb-1.0）
        backend = usb.backend.libusb1.get_backend()

        # 尋找 USB 設備
        self.device = usb.core.find(idVendor=self.vid, idProduct=self.pid, backend=backend)
        
        if self.device is None:
            raise ValueError(f"Device with VID:PID {self.vid:04X}:{self.pid:04X} not found")

        # 設置活動配置
        self.device.set_configuration()
        
        # 獲取端點
        cfg = self.device.get_active_configuration()
        interface = cfg[(0, 0)]

        # 指定端點地址
        self.endpoint_out = usb.util.find_descriptor(interface, bEndpointAddress=self.ep_out_addr)
        self.endpoint_in = usb.util.find_descriptor(interface, bEndpointAddress=self.ep_in_addr)

        if not self.endpoint_out or not self.endpoint_in:
            raise ValueError("Endpoints not found on the device")

        print("MN96100C connected")

    def disconnect(self):
        if self.device:
            usb.util.dispose_resources(self.device)
            print("MN96100C disconnected")

    def send_command(self, data):
        """Send USB command to EP1 (OUT). Accepts bytes, bytearray or list of ints."""
        if isinstance(data, list):
            data = bytearray(data)
        elif isinstance(data, str):
            data = data.encode()
        elif not isinstance(data, (bytes, bytearray)):
            raise ValueError("Command must be bytes, bytearray, or list[int]")
        self.endpoint_out.write(data)
        time.sleep(0.01)  # small delay

    def receive_data(self, size=25602, timeout=1000):
        try:
            raw_25602 = self.endpoint_in.read(size, timeout=timeout)
            
            if len(raw_25602) != 25602:
                print(f"Error: Incomplete data received. Length: {len(raw_25602)}")
                return None
            
            # Change to byte
            raw_byte_25602 = bytes(raw_25602)
            
            last_2byte = raw_byte_25602[-2:]
            
            if (last_2byte == b'\xFF\x23'):
                context = "None"
            else :
                context ='Error'
            
            #print(f"HPD Status : {last_2byte.hex()} => {context}")
            
            modified_data = raw_byte_25602[0:-2]
            modified_string = modified_data.hex()
            return modified_string, context                
                
        except usb.core.USBError as e:
            print(f"USB receive error: {e}")            
            return None

    def get_image(self):
        # Fetch frame image command 
        self.send_command([0x44, 0xFF, 0x01])
        time.sleep(0.1)
        # Receive frame data (160x160)
        self.send_command([0x44, 0xF3, 0x00])
             
        data, context = self.receive_data(25602)
        
        if data:
            return data, context
        else:
            print("Failed to get image data.")
            return None