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


#include "serial_client.h"
#include "../../SerialParser/serial_parser.h"
using namespace hesai::lidar;

SerialClient::SerialClient() {
}

SerialClient::~SerialClient() {
}

int SerialClient::QueryCommand(const uint8_t cmd, const u8Array_t &payload, u8Array_t &byteStreamOut, uint32_t timeout) {
  if (source_send_ == nullptr || source_recv_ == nullptr || source_send_->IsOpened() == false || source_recv_->IsOpened() == false) return kInvalidEquipment;
  u8Array_t sendCommand;
  SerialParser::SerialStreamEncode(kCmd, cmd, payload, sendCommand);

  std::string sendMsg = BytePrinter::getInstance().printByteArrayToString(sendCommand);
  ProduceLogMessage("SEND: " + sendMsg);

  source_recv_->SetReceiveStype(SERIAL_CLEAR_RECV_BUF);
  if (source_send_->Send(sendCommand.data(), sendCommand.size(), 0) < 0) {
    return kInvalidEquipment;
  }
  UdpPacket udp_packet;
  int size = source_recv_->Receive(udp_packet, kBufSize, 1, timeout);
  if (size < 0) return kReadTimeout; 
  u8Array_t recvData;
  recvData.resize(size);
  memcpy(recvData.data(), udp_packet.buffer, size);

  std::string recvMsg = BytePrinter::getInstance().printByteArrayToString(recvData);
  ProduceLogMessage("RECV: " + recvMsg);

  bool ret = SerialParser::SerialStreamDecode(kCmd, recvData, byteStreamOut);
  if (ret == false) return kInvalidData;
  return 0;
}

int SerialClient::RecvSpecialAckData(uint8_t &status, uint8_t &ret_code, int timeout) {
  if (source_recv_ == nullptr || source_recv_->IsOpened() == false) return kInvalidEquipment;
  UdpPacket udp_packet;
  int size = source_recv_->Receive(udp_packet, kBufSize, 1, timeout);
  if (size < 0) return kReadTimeout; 
  u8Array_t recvData, byteStreamOut;
  recvData.resize(size);
  memcpy(recvData.data(), udp_packet.buffer, size);

  std::string recvMsg = BytePrinter::getInstance().printByteArrayToString(recvData);
  ProduceLogMessage("RECV: " + recvMsg);

  bool ret = SerialParser::SerialStreamDecode(kOta, recvData, byteStreamOut);
  if (ret == false || byteStreamOut.size() == 0) return kInvalidData;
  status = byteStreamOut[1];
  ret_code = byteStreamOut.back();
  return 0;
}

int SerialClient::ChangeMode(uint8_t mode, uint8_t reserved) {
  u8Array_t payload, byteStreamOut;
  payload.push_back(mode);
  payload.push_back(reserved);
  int ret = QueryCommand(0x03, payload, byteStreamOut, 3000);
  if (ret != 0) {
    return ret;
  }
  if (byteStreamOut.size() != 5 || byteStreamOut[1] != 0x03 || byteStreamOut[2] != mode) {
    return kInvalidData;
  }
  if (byteStreamOut[4] != 0x00) {
    return (byteStreamOut[4]);
  }
  return 0;
}

int SerialClient::ChangeUpgradeMode() {
  u8Array_t payload, byteStreamOut;
  payload.push_back(0x04);
  payload.push_back(0x00);
  int ret = QueryCommand(0x03, payload, byteStreamOut, 20000);
  if (ret != 0) {
    return ret;
  }
  if (byteStreamOut.size() != 5 || byteStreamOut[1] != 0x03 || byteStreamOut[2] != 0x04) {
    return kInvalidData;
  }
  if (byteStreamOut[4] != 0x00) {
    return (byteStreamOut[4]);
  }
  return 0;
}

int SerialClient::GetCorrectionInfo(u8Array_t &dataOut) {
  ChangeMode(0x01);
  u8Array_t payload, byteStreamOut;
  payload.push_back(0x07);
  payload.push_back(0x00);
  int ret = QueryCommand(0x02, payload, byteStreamOut, 5000);
  ChangeMode(now_mode_);
  if (ret != 0) {
    return ret;
  }
  if (byteStreamOut.size() < 6) return kInvalidData;
  if (byteStreamOut[1] != 0x02 || byteStreamOut[2] != 0x07 || byteStreamOut[3] != 0x00 
      || static_cast<size_t>(byteStreamOut[4] + 6) != byteStreamOut.size()) {
    return kInvalidData;
  }
  if (byteStreamOut.back() != 0x00) {
    return static_cast<int>(byteStreamOut.back());
  }
  dataOut.resize(byteStreamOut[4]);
  std::copy_n(byteStreamOut.begin() + 5, byteStreamOut[4], dataOut.begin());
  return 0;
}

int SerialClient::GetSnInfo(u8Array_t &dataOut) {
  ChangeMode(0x01);
  u8Array_t payload, byteStreamOut;
  payload.push_back(0x0A);
  payload.push_back(0x01);
  payload.resize(38);
  int ret = QueryCommand(0x02, payload, byteStreamOut, 5000);
  ChangeMode(now_mode_);
  if (ret != 0) {
    return ret;
  }
  if (byteStreamOut.size() != 41 || byteStreamOut[1] != 0x02 || byteStreamOut[2] != 0x0A || byteStreamOut[3] != 0x01) {
    return kInvalidData;
  }
  if (byteStreamOut.back() != 0x00) {
    return static_cast<int>(byteStreamOut.back());
  }
  dataOut.resize(36);
  std::copy_n(byteStreamOut.begin() + 4, 36, dataOut.begin());
  return 0;
}

int SerialClient::GetLidarVersion(u8Array_t &dataOut, uint8_t type) {
  ChangeMode(0x01);
  u8Array_t payload, byteStreamOut;
  payload.push_back(0x0F);
  payload.push_back(type);
  payload.resize(27);
  int ret = QueryCommand(0x02, payload, byteStreamOut, 1000);
  ChangeMode(now_mode_);
  if (ret != 0) {
    return ret;
  }
  if (byteStreamOut.size() != 30 || byteStreamOut[1] != 0x02 || byteStreamOut[2] != 0x0F) {
    return kInvalidDataHeader;
  }
  if (byteStreamOut.back() != 0x00) {
    return static_cast<int>(byteStreamOut.back());
  }
  dataOut.resize(24);
  std::copy_n(byteStreamOut.begin() + 4, 24, dataOut.begin());
  return 0;
}

int SerialClient::GetLidarFaultState(u8Array_t &dataOut) {
  ChangeMode(0x01);
  u8Array_t payload, byteStreamOut;
  payload.push_back(0x08);
  payload.push_back(0x21);
  int ret = QueryCommand(0x02, payload, byteStreamOut, 5000);
  ChangeMode(now_mode_);
  if (ret != 0) {
    return ret;
  }
  if (byteStreamOut[1] != 0x02 || byteStreamOut[2] != 0x08 || byteStreamOut[3] != 0xA1) {
    return kInvalidDataHeader;
  }
  if (byteStreamOut.back() != 0x00) {
    return static_cast<int>(byteStreamOut.back());
  }
  dataOut.resize(byteStreamOut.size() - 5);
  std::copy_n(byteStreamOut.begin() + 4, byteStreamOut.size() - 5, dataOut.begin());
  return 0;
}

int SerialClient::OtaQueryCommand(const uint32_t all_num, const uint32_t num, const uint32_t len, const uint8_t *payload, uint8_t &status, uint8_t &ret_code, uint8_t type) {
  if (source_recv_ == nullptr || source_recv_->IsOpened() == false) return kInvalidEquipment;
  u8Array_t sendCommand;
  sendCommand.resize(sizeof(SerialHeader));
  sendCommand.push_back(0x00);
  sendCommand.push_back(0x00);
  sendCommand.push_back(0x00);
  sendCommand.push_back(type);
  sendCommand.push_back(static_cast<uint8_t>(all_num >> 24));
  sendCommand.push_back(static_cast<uint8_t>(all_num >> 16));
  sendCommand.push_back(static_cast<uint8_t>(all_num >> 8));
  sendCommand.push_back(static_cast<uint8_t>(all_num >> 0));
  sendCommand.push_back(static_cast<uint8_t>(num >> 24));
  sendCommand.push_back(static_cast<uint8_t>(num >> 16));
  sendCommand.push_back(static_cast<uint8_t>(num >> 8));
  sendCommand.push_back(static_cast<uint8_t>(num >> 0));
  sendCommand.push_back(static_cast<uint8_t>(len >> 24));
  sendCommand.push_back(static_cast<uint8_t>(len >> 16));
  sendCommand.push_back(static_cast<uint8_t>(len >> 8));
  sendCommand.push_back(static_cast<uint8_t>(len >> 0));
  sendCommand.resize(sendCommand.size() + len);
  memcpy(sendCommand.data() + sizeof(SerialHeader) + 16, payload, len);
  SerialParser::SerialStreamEncode(kOta, sendCommand);
  source_recv_->SetReceiveStype(SERIAL_CLEAR_RECV_BUF);
  if (source_recv_->Send(sendCommand.data(), sendCommand.size(), 0) < 0) {
    return kInvalidEquipment;
  }
  int ret = RecvSpecialAckData(status, ret_code, 30000);
  if (ret != 0) {
    return ret;
  }
  return 0;
}

void SerialClient::SetSerial(Source* source_send, Source* source_recv) {
  source_send_ = source_send;
  source_recv_ = source_recv;
}

void SerialClient::ProduceLogMessage(const std::string& message) {
  if (log_message_handler_callback_) {
    log_message_handler_callback_(message);
  }
}

int SerialClient::RequestUpgradeLargePackage(uint8_t type) {
  if (source_send_ == nullptr || source_recv_ == nullptr || source_send_->IsOpened() == false || source_recv_->IsOpened() == false) return kInvalidEquipment;
  u8Array_t payload, byteStreamOut;
  payload.push_back(0x05);
  payload.push_back(type);
  int ret = QueryCommand(0x02, payload, byteStreamOut, 5000);
  if (ret != 0) {
    return ret;
  }
  if (byteStreamOut.size() != 5 || byteStreamOut[1] != 0x02 || byteStreamOut[2] != 0x05 || byteStreamOut[3] != type) {
    return kInvalidData;
  }
  if (byteStreamOut[4] != 0x00) {
    return int(byteStreamOut[4]) * -1;
  }
  source_recv_->Close();
  source_recv_->SetReceiveStype(SERIAL_COMMAND_RECV);
  source_recv_->Open();
  ProduceLogMessage("wait recv ready ack\n");
  uint8_t status, ret_code;
  ret = RecvSpecialAckData(status, ret_code, 4000);
  if (ret != 0) {
    return ret;
  }
  if (status != 0x55) {
    return kFailedCalibration;
  }
  return 0;
}

int SerialClient::GetPblVersionIdInPbl(u8Array_t &byteStreamOut) {
  if (source_recv_ == nullptr || source_recv_->IsOpened() == false) return kInvalidEquipment;
  u8Array_t sendCommand;
  uint32_t all_num = 1, num = 0, len = 1024;
  sendCommand.resize(sizeof(SerialHeader));
  sendCommand.push_back(0x00);
  sendCommand.push_back(0x00);
  sendCommand.push_back(0x00);
  sendCommand.push_back(0x05);
  sendCommand.push_back(static_cast<uint8_t>(all_num >> 24));
  sendCommand.push_back(static_cast<uint8_t>(all_num >> 16));
  sendCommand.push_back(static_cast<uint8_t>(all_num >> 8));
  sendCommand.push_back(static_cast<uint8_t>(all_num >> 0));
  sendCommand.push_back(static_cast<uint8_t>(num >> 24));
  sendCommand.push_back(static_cast<uint8_t>(num >> 16));
  sendCommand.push_back(static_cast<uint8_t>(num >> 8));
  sendCommand.push_back(static_cast<uint8_t>(num >> 0));
  sendCommand.push_back(static_cast<uint8_t>(len >> 24));
  sendCommand.push_back(static_cast<uint8_t>(len >> 16));
  sendCommand.push_back(static_cast<uint8_t>(len >> 8));
  sendCommand.push_back(static_cast<uint8_t>(len >> 0));
  sendCommand.resize(sendCommand.size() + len, 0xFF);
  SerialParser::SerialStreamEncode(kOta, sendCommand);

  std::string sendMsg = BytePrinter::getInstance().printByteArrayToString(sendCommand);
  ProduceLogMessage("SEND: " + sendMsg);

  if (source_recv_->Send(sendCommand.data(), sendCommand.size(), 0) < 0) {
    return kInvalidEquipment;
  }

  UdpPacket udp_packet;
  int size = source_recv_->Receive(udp_packet, kBufSize, 1, 2000);
  if (size < 0) return kReadTimeout; 
  u8Array_t recvData;
  recvData.resize(size);
  memcpy(recvData.data(), udp_packet.buffer, size);

  std::string recvMsg = BytePrinter::getInstance().printByteArrayToString(recvData);
  ProduceLogMessage("RECV: " + recvMsg);

  byteStreamOut.resize(size - 13);
  memcpy(byteStreamOut.data(), udp_packet.buffer + 7, size - 13);
  return 0;
}

int SerialClient::UpgradeLidar(u8Array_t data, int mode, int &upgrade_progress) {
  if (mode == 0) ProduceLogMessage("begin to upgrade APP+FPGA");
  else ProduceLogMessage("begin to upgrade PBL");
  int ret = 0;
  do {
    source_recv_->Close();
    source_send_->Close();
    source_recv_->SetReceiveStype(SERIAL_COMMAND_RECV);
    if (source_recv_->Open() == false) {
      ret = kSerialOpenError;
      break;
    }
    u8Array_t byteStreamOut;
    ret = GetPblVersionIdInPbl(byteStreamOut);
    if (ret == kReadTimeout) {
      ProduceLogMessage("Currently may be located in app, begin to upgrade");
      ret = 0;
    } else if (ret != 0) {
      break;
    } else if (byteStreamOut.size() < 8 + 10) {
      ProduceLogMessage("Returned data is minimal. Currently may be located in app, begin to upgrade PBL");
      ret = 0; 
    } else {
      if (mode == 0) {
        ProduceLogMessage("now in PBL, begin to upgrade APP");
        ret = kInPblNotUpgrade;
      }
      else {
        ProduceLogMessage("now in PBL, can't upgrade PBL");
        ret = kInPblNotUpgrade;
        break;
      }
    }
    source_recv_->Close();
    
    source_recv_->SetReceiveStype(SERIAL_POINT_CLOUD_RECV);
    if (source_recv_->Open() == false) {
      ret = kSerialOpenError;
      break;
    }
    if (source_send_->Open() == false) {
      ret = kSerialOpenError;
      break;
    }
    if (source_recv_->IsOpened() == false || source_send_->IsOpened() == false) {
      ret = kSerialOpenError;
      break;
    }
    if (ret == 0) {
      ret = ChangeMode(0x04);
      if (ret == kReadTimeout) {
        ProduceLogMessage("ChangeMode to 0x04 timeout");
      }
      else if (ret != 0) break;
      ret = RequestUpgradeLargePackage(mode == 0 ? 0x04 : 0x02);
      if (ret != 0) {
        if (ret == kReadTimeout) {
          ProduceLogMessage("request upgrade large package timeout");
          ret = 0;
        }
        else {
          break;
        }
      }
    } else {
      source_recv_->Close();
      source_recv_->SetReceiveStype(SERIAL_COMMAND_RECV);
      source_recv_->Open();
    }
    ret = 0;
    ProduceLogMessage("begin to send ota data");
    int fileSize = data.size();
    int i = 0, send_len = 1024;
    int send_num = (fileSize - 1) / send_len + 1;
    uint8_t status, ret_code;
    for (i = 0; i < send_num - 1; i++) {
      ProduceLogMessage("ota send" + std::to_string(i + 1) + " / " + std::to_string(send_num));
      ret = OtaQueryCommand(send_num, i, send_len, (uint8_t *)data.data() + i * send_len, status, ret_code, mode == 0 ? 0x04 : 0x02);
      if (ret != 0) {
        break;
      }
      if (status != 0x05) {
        ret = (ret_code);
        break;
      }
      upgrade_progress = i + 1;
    }
    if (ret != 0) break;
    ProduceLogMessage("ota send" + std::to_string(i + 1) + " / " + std::to_string(send_num));
    ret = OtaQueryCommand(send_num, i, fileSize - i * send_len, (uint8_t *)data.data() + i * send_len, status, ret_code, mode == 0 ? 0x04 : 0x02);
    if (ret != 0) {
      break;
    }
    if (status != 0x05) {
      ret = (ret_code);
      break;
    }
    upgrade_progress = i + 1;
    ret = 0;
  } while(0);

  source_recv_->Close();
  source_send_->Close();
  return ret;
}
