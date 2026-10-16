/************************************************************************************************
Copyright (C) 2023 Hesai Technology Co., Ltd.
Copyright (C) 2023 Original Authors
All rights reserved.

All code in this repository is released under the terms of the following Modified BSD License. 
Redistribution and use in source and binary forms, with or without modification, are permitted 
provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this list of conditions and 
  the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice, this list of conditions and 
  the following disclaimer in the documentation and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its contributors may be used to endorse or 
  promote products derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED 
WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A 
PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR 
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT 
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS 
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR 
TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF 
ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
************************************************************************************************/

/*
 * File:   serial_parser.h
 * Author: chang xingshuo<changxingshuo@hesaitech.com>
 *
 * Created on Jan 13, 2025, 19:56 PM  
 */
#pragma once
#include <iostream>
#include <stdint.h>
#include <stdio.h>
#include <string>
#include <random>
#include <string.h>
#include <algorithm>
#include "../Common/include/inner_com.h"

namespace hesai {
namespace lidar {

enum SerialCmdType {
  kCmd = 1,
  kOta = 2,
};

#pragma pack(push, 1)
struct SerialHeader {
  uint8_t start_flag_[7];    
  
  SerialHeader() {
    start_flag_[0] = 0;
    start_flag_[1] = 0;
    start_flag_[2] = 0;
    start_flag_[3] = 0;
    start_flag_[4] = 0;
    start_flag_[5] = 0;
    start_flag_[6] = 0;
  }
  void InitCmd() {
    start_flag_[0] = 0x24;
    start_flag_[1] = 0x4C;
    start_flag_[2] = 0x44;
    start_flag_[3] = 0x43;
    start_flag_[4] = 0x4D;
    start_flag_[5] = 0x44;
    start_flag_[6] = 0x2C;
  }
  void InitOta() {
    start_flag_[0] = 0x24;
    start_flag_[1] = 0x4C;
    start_flag_[2] = 0x44;
    start_flag_[3] = 0x4F;
    start_flag_[4] = 0x54;
    start_flag_[5] = 0x41;
    start_flag_[6] = 0x2C;
  }
};
#pragma pack(pop)

enum ErrorCode {
  kInvalidEquipment  = -1,
  kInvalidData       = -2,
  kReadTimeout       = -3,
  kInvalidDataHeader = -4,
  kSerialOpenError   = -5,
  kInPblNotUpgrade   = -6,
  kFailedCalibration = -7,
};

class SerialParser { 
public:
  static const int kSerialReturnMinLen = 19;
  static void SerialStreamEncode(const SerialCmdType type, const uint8_t cmd, const u8Array_t &payload, u8Array_t &sendCommand) {
    sendCommand.resize(sizeof(SerialHeader));
    sendCommand.push_back(static_cast<uint8_t>(payload.size() + 1));
    sendCommand.push_back(cmd);
    sendCommand.resize(payload.size() + sizeof(SerialHeader) + 2);
    memcpy(sendCommand.data() + sizeof(SerialHeader) + 2, payload.data(), payload.size());
    SerialStreamEncode(type, sendCommand);
  }
  static void SerialStreamEncode(const SerialCmdType type, u8Array_t &byteStream) {
    SerialHeader *pHeader = (SerialHeader *)byteStream.data();
    if (type == kCmd)
      pHeader->InitCmd();
    else if (type == kOta)
      pHeader->InitOta();
    AddEndStreamEncode(byteStream, type);
  }
  static bool SerialStreamDecode(const SerialCmdType type, const u8Array_t &byteStreamIn, u8Array_t &byteStreamOut) {
    int len = static_cast<int>(byteStreamIn.size());
    if (len < kSerialReturnMinLen) return false;
    if (byteStreamIn[len - 2] != 0xEE || byteStreamIn.back() != 0xFF) {
      return false;
    }
    int crc_in_len = static_cast<int>(len) - 13;
    int crc_in_len_true = 0;
    u8Array_t crc_in;
    if (crc_in_len % 4 != 0 && crc_in_len == 30) {
      crc_in_len_true = 32;
    } else if (crc_in_len % 4 != 0 && crc_in_len != 30) {
      crc_in_len_true = 4 * (crc_in_len / 4 + 1);
    } else {
      crc_in_len_true = crc_in_len;
    }
    uint8_t *ptr = (uint8_t *)byteStreamIn.data();
    ptr += len - 6;
    uint32_t crc = 0;
    if (type == kCmd)
      crc = *((uint32_t *)ptr);
    else if (type == kOta)
      crc = *(ptr) * 0x1000000 + *(ptr + 1) * 0x10000 + *(ptr + 2) * 0x100 + *(ptr + 3);
    uint32_t check_crc = Crc32::CRCCalc(byteStreamIn.data() + kCrcBegin, crc_in_len, crc_in_len_true - crc_in_len);
    if(crc != check_crc) {
      return false;
    }
    byteStreamOut.resize(len - 17);
    std::copy_n(byteStreamIn.begin() + kCrcBegin, len - 17, byteStreamOut.begin());
    if (static_cast<size_t>(byteStreamOut[0] + 2) != byteStreamOut.size()) {  // 2为 该位本身 + error_code位
      return false;
    }
    return true;
  }

private:
  static uint32_t GetRandom() {
    std::random_device rd;
    std::mt19937 generator(rd());
    std::uniform_int_distribution<uint32_t> distribution;
    return distribution(generator);
  }
  static void AddEndStreamEncode(u8Array_t &byteStreamOut, const SerialCmdType type) {
    uint32_t rand = 0;
    if (type == kCmd) {
      rand = GetRandom();
      byteStreamOut.push_back(static_cast<uint8_t>(rand));
      byteStreamOut.push_back(static_cast<uint8_t>(rand >> 8));
      byteStreamOut.push_back(static_cast<uint8_t>(rand >> 16));
      byteStreamOut.push_back(static_cast<uint8_t>(rand >> 24));
    }
    uint32_t crc_in_len = byteStreamOut.size() - kCrcBegin;
    uint32_t crc_in_len_true = 0;
    if (crc_in_len % 4 != 0 && crc_in_len == 30) {
      crc_in_len_true = 32;
    } else if (crc_in_len % 4 != 0 && crc_in_len != 30) {
      crc_in_len_true = 4 * (crc_in_len / 4 + 1);
    } else {
      crc_in_len_true = crc_in_len;
    }
    rand = Crc32::CRCCalc(byteStreamOut.data() + kCrcBegin, crc_in_len, crc_in_len_true - crc_in_len);
    if (type == kCmd) {
      byteStreamOut.push_back(static_cast<uint8_t>(rand));
      byteStreamOut.push_back(static_cast<uint8_t>(rand >> 8));
      byteStreamOut.push_back(static_cast<uint8_t>(rand >> 16));
      byteStreamOut.push_back(static_cast<uint8_t>(rand >> 24));
    } else if (type == kOta) {
      byteStreamOut.push_back(static_cast<uint8_t>(rand >> 24));
      byteStreamOut.push_back(static_cast<uint8_t>(rand >> 16));
      byteStreamOut.push_back(static_cast<uint8_t>(rand >> 8));
      byteStreamOut.push_back(static_cast<uint8_t>(rand >> 0));
    }
    byteStreamOut.push_back(0xEE);
    byteStreamOut.push_back(0xFF);
  }
  static const uint16_t kCrcBegin = 7;
};

} // lidar
} // hesai