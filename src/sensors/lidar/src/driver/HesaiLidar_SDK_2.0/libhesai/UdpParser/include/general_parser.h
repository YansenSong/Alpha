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
 * File:       general_parser.h
 * Author:     Zhang Yu <zhangyu@hesaitech.com>
 * Description: Declare GeneralParser class
*/

#ifndef GENERAL_PARSER_H_
#define GENERAL_PARSER_H_
#define CIRCLE (36000 * 256)
#define DEFAULT_MAX_LASER_NUM (256)
#define SOMEIP_OFFSET (21)
#ifndef M_PI
#define M_PI (3.14159265358979323846)
#endif
#define M_PI_DIVIDE_180 (0.01745329251994329575)
#define _180_DIVIDE_M_PI (57.29577951308232087721)

#ifndef _MSC_VER
#include <semaphore.h>
#endif
#include <list>
#include <cmath>
#include <vector>
#include <sstream>
#include <iostream>
#include <fstream>
#include <iomanip>
#include "logger.h"
#include "lidar_types.h"
#include "plat_utils.h"
#include "fault_message.h"
namespace hesai
{
namespace lidar
{  

DEFINE_MEMBER_CHECKER(intensity)
DEFINE_MEMBER_CHECKER(ring)
DEFINE_MEMBER_CHECKER(timestamp)
DEFINE_MEMBER_CHECKER(confidence)
DEFINE_MEMBER_CHECKER(timeSecond)
DEFINE_MEMBER_CHECKER(timeNanosecond)
DEFINE_MEMBER_CHECKER(weightFactor)
DEFINE_MEMBER_CHECKER(envLight)
DEFINE_MEMBER_CHECKER(azimuth)
DEFINE_MEMBER_CHECKER(azimuthCalib)
DEFINE_MEMBER_CHECKER(elevation)
DEFINE_MEMBER_CHECKER(elevationCalib)
DEFINE_MEMBER_CHECKER(distance)
DEFINE_MEMBER_CHECKER(noiseLevel)
DEFINE_MEMBER_CHECKER(dirtyLevel)

DEFINE_SET_GET(intensity, uint8_t)  
DEFINE_SET_GET(ring, uint16_t)  
DEFINE_SET_GET(timestamp, double)  
DEFINE_SET_GET(timeSecond, uint64_t)  
DEFINE_SET_GET(timeNanosecond, uint32_t)
DEFINE_SET_GET(confidence, uint8_t)  
DEFINE_SET_GET(weightFactor, uint8_t)
DEFINE_SET_GET(envLight, uint8_t)
DEFINE_SET_GET(azimuth, float)
DEFINE_SET_GET(azimuthCalib, float)
DEFINE_SET_GET(elevation, float)
DEFINE_SET_GET(distance, float)
DEFINE_SET_GET(noiseLevel, uint8_t)
DEFINE_SET_GET(dirtyLevel, uint8_t)

// elevationCalib
template <typename T_Point>                                                                                          
inline typename std::enable_if<!PANDAR_HAS_MEMBER(T_Point, elevationCalib)>::type set_elevationCalib(T_Point& point, const float& value) 
{                                                                                                                    
}                                                                                                                    
template <typename T_Point>                                                                                          
inline typename std::enable_if<PANDAR_HAS_MEMBER(T_Point, elevationCalib)>::type set_elevationCalib(T_Point& point, const float& value) 
{   
    point.elevationCalib = (value > 180.f) ? (value - 360.f) : value;                                                                                            
}                                                                                                                    
template <typename T_Point>                                                                                          
inline typename std::enable_if<!PANDAR_HAS_MEMBER(T_Point, elevationCalib)>::type get_elevationCalib(T_Point& point, float& value)  
{                                                                                                                    
}                                                                                                                    
template <typename T_Point>                                                                                          
inline typename std::enable_if<PANDAR_HAS_MEMBER(T_Point, elevationCalib)>::type get_elevationCalib(T_Point& point, float& value)  
{                                                                                                                    
    value = point.elevationCalib;                                                                                            
}  
template <typename T_Point, typename ValueFunc>                                                                      
inline typename std::enable_if<!PANDAR_HAS_MEMBER(T_Point, elevationCalib)>::type set_elevationCalib_lazy(T_Point& point, ValueFunc&& value_func) 
{                                                                                                                    
}                                                                                                                    
template <typename T_Point, typename ValueFunc>                                                                      
inline typename std::enable_if<PANDAR_HAS_MEMBER(T_Point, elevationCalib)>::type set_elevationCalib_lazy(T_Point& point, ValueFunc&& value_func) 
{                   
    auto value = value_func();                                                                                                 
    point.elevationCalib = (value > 180.f) ? (value - 360.f) : value;                                                                               
}    



inline float deg2Rad(float deg)
{
    return (float)(deg * 0.01745329251994329575);
}

inline float rad2Deg(float rad)
{
    return (float)(rad * 57.29577951308232087721);
}

enum DistanceCorrectionType {
  OpticalCenter,
  GeometricCenter,
};

struct PacketSeqnumLossMessage {
  uint64_t last_total_package_count;
  uint32_t last_seqnum;
  uint32_t loss_count;
  uint32_t start_time;
  uint32_t total_loss_count;
  uint64_t total_packet_count;
  uint32_t max_sequence;
  bool is_packet_loss;
  bool is_init;
  PacketSeqnumLossMessage() {
    last_total_package_count = 0;
    last_seqnum = 0;
    loss_count = 0;
    start_time = 0;
    total_loss_count = 0;
    total_packet_count = 0;
    max_sequence = 0xFFFFFFFF;
    is_packet_loss = false;
    is_init = false;
  }
};

struct PacketTimeLossMessage {
  uint64_t last_timestamp;
  uint32_t timeloss_count;
  uint32_t timeloss_start_time;
  uint32_t total_timeloss_count;
  uint64_t last_total_package_count;
  bool is_init;
  PacketTimeLossMessage() {
    last_timestamp = 0;
    timeloss_count = 0;
    timeloss_start_time = 0;
    total_timeloss_count = 0;
    last_total_package_count = 0;
    is_init = false;
  }
};

enum StructType {
  CORRECTION_STRUCT = 1,
  FIRETIME_STRUCT = 2,
  DCF_STRUCT = 3,
};

struct CorrectionData {
  float elevation[DEFAULT_MAX_LASER_NUM];
  float azimuth[DEFAULT_MAX_LASER_NUM];
  bool display[DEFAULT_MAX_LASER_NUM];
  std::string hash;
  CorrectionData() {
    memset(elevation, 0, sizeof(float) * DEFAULT_MAX_LASER_NUM);
    memset(azimuth, 0, sizeof(float) * DEFAULT_MAX_LASER_NUM);
    for (int i = 0; i < DEFAULT_MAX_LASER_NUM; ++i) {  
        display[i] = true;
    } 
    hash = "";
  }
};

// class GeneralParser
// the GenneralParser class is a base class for parsering packets and computing points
// you can parser the udp or pcap packets using the DecodePacket fuction
// you can compute xyzi of points using the ComputeXYZI fuction, which uses cpu to compute
template <typename T_Point>
class GeneralParser {
 public:
  GeneralParser() {
    this->default_remake_config.min_azi = 0.f;
    this->default_remake_config.max_azi = 360.f;
    this->default_remake_config.ring_azi_resolution = 0.2f;
    this->default_remake_config.max_azi_scan = 1800;   // (max_azi - min_azi) / ring_azi_resolution
    this->default_remake_config.min_elev = -25.f;
    this->default_remake_config.max_elev = 15.f;
    this->default_remake_config.ring_elev_resolution = 0.2f;
    this->default_remake_config.max_elev_scan = 200;   // (max_elev - min_elev) / ring_elev_resolution
    last_azimuth_ = 0;
    last_last_azimuth_ = 0;
    for (int i = 0; i < CIRCLE; ++i) {
      sin_all_angle_[i] = std::sin(i * 2 * M_PI / CIRCLE);
      cos_all_angle_[i] = std::cos(i * 2 * M_PI / CIRCLE);
    }
  }

  virtual ~GeneralParser() { LogInfo("release general parser"); }

  // load correction file, which is necessary for DecodePacket.
  virtual void LoadCorrectionFile(const std::string& correction_path) {
    try {
      std::ifstream fin(correction_path, std::ios::in);
      if (fin.is_open()) {
        int length = 0;
        fin.seekg(0, std::ios::end);
        length = static_cast<int>(fin.tellg());
        fin.seekg(0, std::ios::beg);
        char *buffer = new char[length + 1];
        buffer[length] = 0;
        fin.read(buffer, length);
        fin.close();
        int ret = LoadCorrectionString(buffer, length);
        delete[] buffer;
        if (ret != 0) {
          LogError("Parse local correction file Error");
        } else {
          LogInfo("Parser correction file success!");
        }
      } else {
        LogError("Open correction file failed");
        return;
      }
    } catch (const std::exception& e) {
      LogFatal("error loading correction file: %s", e.what());
      return;
    }
  }

  virtual int LoadCorrectionString(const char *correction_string, int len) {
    try {
      std::string correction_content_str(correction_string, len);
      std::istringstream ifs(correction_content_str);
      std::string line;

      // skip first line "Laser id,Elevation,Azimuth" or "eeff"
      std::getline(ifs, line);  
      float elevation_list[DEFAULT_MAX_LASER_NUM], azimuth_list[DEFAULT_MAX_LASER_NUM];
      std::vector<std::string> vfirstLine;
      split_string(vfirstLine, line, ',');
      if (vfirstLine.empty()) {
        throw std::invalid_argument("invalid correction input file!(first line)");
      }
      if (vfirstLine[0] == "EEFF" || vfirstLine[0] == "eeff") {
        // skip second line
        std::getline(ifs, line);  
      }

      int lineCount = 0;
      while (std::getline(ifs, line)) {
        std::vector<std::string> vLineSplit;
        split_string(vLineSplit, line, ',');
        // skip error line or hash value line
        if (vLineSplit.size() != 3) {  
          continue;
        } else {
          lineCount++;
        }
        float elevation, azimuth;
        int laserId = 0;
        laserId = std::stoi(vLineSplit[0]);
        elevation = std::stof(vLineSplit[1]);
        azimuth = std::stof(vLineSplit[2]);

        if (laserId > DEFAULT_MAX_LASER_NUM || laserId <= 0) {
          throw std::invalid_argument("laser id is wrong in correction file. laser Id: "   
                                        + std::to_string(laserId) + ", line: " + std::to_string(lineCount));
        }
        if (laserId != lineCount) {
          LogWarning("laser id is wrong in correction file. laser Id: %d, line: %d.  continue", laserId, lineCount);
          lineCount--;
          continue;
        }
        elevation_list[laserId - 1] = elevation;
        azimuth_list[laserId - 1] = azimuth;
      }

      for (int i = 0; i < lineCount; ++i) {
        this->correction.elevation[i] = elevation_list[i];
        this->correction.azimuth[i] = azimuth_list[i];
      }
      this->loadCorrectionSuccess();
    } catch (const std::exception &e) {
      LogFatal("load correction error: %s", e.what());
      this->get_correction_file_ = false;
      return -1;
    }
    return 0;
  }

  // load firetimes file
  virtual void LoadFiretimesFile(const std::string& firetimes_path) {
    try {
      std::ifstream inFile(firetimes_path, std::ios::in);
      if (inFile.is_open()) {
        std::string lineStr;
        //skip first line
        std::getline(inFile, lineStr); 
        int lineCount = 0;
        while (getline(inFile, lineStr)) {
          std::vector<std::string> vLineSplit;
          split_string(vLineSplit, lineStr, ',');
          // skip error line or hash value line
          if (vLineSplit.size() != 2) {  
            continue;
          } else {
            lineCount++;
          }
          float deltTime = 0.f;
          int laserId = 0;
          laserId = std::stoi(vLineSplit[0]);
          deltTime = std::stof(vLineSplit[1]);
          if (laserId > DEFAULT_MAX_LASER_NUM || laserId <= 0) {
            throw std::invalid_argument("laser id is wrong in firetimes file. laser Id: "   
                                        + std::to_string(laserId) + ", line: " + std::to_string(lineCount));
          }
          firetime_correction_[laserId - 1] = deltTime;
        }
        this->loadFiretimeSuccess();
        LogInfo("Open firetime file success!");
        inFile.close();
        return;
      } else {
        throw std::invalid_argument("Open firetime file failed");
      }
    } catch (const std::exception &e) {
      LogFatal("load firetime error: %s", e.what());
      this->get_firetime_file_ = false;
      return;
    }
  }

  virtual int LoadFiretimesString(const char *firetimes_string, int len) {
    (void)firetimes_string;
    LogWarning("don't load firetimes string");
    return 0;
  }

  // load channel config file
  virtual int LoadChannelConfigFile(const std::string channel_config_path) {
    (void)channel_config_path;
    LogWarning("don't support channel config file");
    return -1;
  }

  // load dcf config file
  virtual int LoadDcfConfigFile(const std::string& dcf_path) {
    (void)dcf_path;
    LogWarning("don't support dcf config file");
    return -1;
  }

  virtual int LoadDcfConfigString(const char *dcf_string, int len) {
    (void)len;
    (void)dcf_string;
    LogWarning("don't support dcf config string");
    return -1;
  }

  virtual int LoadChannelConfigString(char*) {
    LogWarning("don't support channel config file");
    return -1;
  }

  // load nonlinear mapping file (for reflectivity mapping)
  virtual int LoadNonlinearMappingFile(const std::string& mapping_path) {
    (void)mapping_path;
    LogWarning("don't support nonlinear mapping file");
    return -1;
  }

  virtual int LoadNonlinearMappingString(const char *mapping_string, int len) {
    (void)mapping_string;
    (void)len;
    LogWarning("don't support nonlinear mapping string");
    return -1;
  }

  virtual int ExportNonlinearMappingFile(const std::string& mapping_path) {
    (void)mapping_path;
    LogWarning("don't support export nonlinear mapping file");
    return -1;
  }

  // get the pointer to the struct of the parsed correction file or firetimes file
  virtual void* getStruct(const int type) { 
    if (type == CORRECTION_STRUCT)
      return (void*)&correction;
    else if (type == FIRETIME_STRUCT)
      return (void*)firetime_correction_;
    return nullptr;
  }

  // get display 
  virtual int getDisplay(bool **display) {
    *display = correction.display;
    return DEFAULT_MAX_LASER_NUM;
  }

  // get/set correction/firetimes file loading flag
  bool isSetCorrectionSucc() { return get_correction_file_; }
  bool isSetFiretimeSucc() { return get_firetime_file_; }

  // covert a origin udp packet to decoded data, and pass the decoded data to a frame struct to reduce memory copy
  virtual int DecodePacket(LidarDecodedFrame<T_Point> &frame, const UdpPacket& udpPacket, const int packet_index = -1) {
    (void)frame;
    (void)udpPacket;
    return -1;
  }

  // xyzi of points after computed is puted in frame  
  virtual int ComputeXYZI(LidarDecodedFrame<T_Point> &frame, uint32_t packet_index) {
    (void)frame;
    (void)packet_index;
    return 0;
  }

  // parse the detailed content of the fault message
  virtual int ParserFaultMessage(UdpPacket& udp_packet, FaultMessageInfo &fault_message_info) {
    (void)udp_packet;
    (void)fault_message_info;
    return -1;
  }

  // determine whether to frame based on azimuth
  bool IsNeedFrameSplit(uint16_t azimuth, FrameDecodeParam &param) {
    // The first two packet dont have the information of last_azimuth_  and last_last_azimuth, so do not need split frame
    // The initial value of last_azimuth_ is -1
    // Determine the rotation direction and division
    
    int32_t division = 0;
    // If last_last_azimuth_ != -1，the packet is the third, so we can determine whether the current packet requires framing
    if (this->last_last_azimuth_ != -1) 
    {
      // Get the division
      int32_t division1 = abs(this->last_azimuth_ - this->last_last_azimuth_);
      int32_t division2 = abs(this->last_azimuth_ - azimuth);
      division = division1 > division2 ? division2 : division1 ;
      // Prevent two consecutive packets from having the same angle when causing an error in framing
      if ( division == 0) return false;
      // In the three consecutive angle values, if the angle values appear by the division of the decreasing situation,it must be reversed
      // The same is true for FOV
      if( this->last_last_azimuth_ - this->last_azimuth_ == division || this->last_azimuth_ - azimuth == division)
      {
        param.UpdateRotation(-1);
      } else {
        param.UpdateRotation(1);
      }
    } else {
      // The first  and second packet do not need split frame
      return false;
    }
    if (param.rotation_flag > 0) {
      if (this->last_azimuth_- azimuth > division)
      {
        if (frame_start_azimuth_uint16_ > this->last_azimuth_ || frame_start_azimuth_uint16_ <= azimuth) {
          return true;
        } 
        return false;
      }  
      if (this->last_azimuth_ < azimuth && this->last_azimuth_ < frame_start_azimuth_uint16_ 
          && azimuth >= frame_start_azimuth_uint16_) {
        return true;
      }
      return false;
    } else {
      if (azimuth - this->last_azimuth_ > division)
      {
        if (frame_start_azimuth_uint16_ < this->last_azimuth_ || frame_start_azimuth_uint16_ >= azimuth) {
          return true;
        } 
        return false;
      }  
      if (this->last_azimuth_ > azimuth && this->last_azimuth_ > frame_start_azimuth_uint16_ 
          && azimuth <= frame_start_azimuth_uint16_) {
        return true;
      }
      return false;
    }
  }

  // In ComputeXYZI, thread-safely count the number of packets that have been parsed
  void FrameNumAdd() {
    compute_packet_num++;
  }

  // get/clear the number of parsed packets
  uint32_t GetComputePacketNum() { return compute_packet_num; }
  void SetComputePacketNumToZero() { compute_packet_num = 0; }

  // compute lidar firetime correciton
  double GetFiretimesCorrection(int laserId, double speed) {
    return this->firetime_correction_[laserId] * speed * 6E-6;
  }

  // compute optical center correction
  void GetDistanceCorrection(LidarOpticalCenter optical_center, int &azimuth, int &elevation, float &distance, DistanceCorrectionType type) {
    if (distance <= 0.09) return;
    CircleRevise(azimuth);
    CircleRevise(elevation);
    float tx = this->cos_all_angle_[elevation] * this->sin_all_angle_[azimuth];
    float ty = this->cos_all_angle_[elevation] * this->cos_all_angle_[azimuth];
    float tz = this->sin_all_angle_[elevation];
    float d  = distance;
    if (type == GeometricCenter) {
      float B = 2 * tx * optical_center.x + 2 * ty * optical_center.y + 2 * tz * optical_center.z;
      float C = optical_center.x * optical_center.x + optical_center.y * optical_center.y + optical_center.z * optical_center.z - d * d;
      float d_opitcal = std::sqrt(B * B / 4 - C) - B / 2;
      float x = d_opitcal * tx + optical_center.x;
      float y = d_opitcal * ty + optical_center.y;
      float z = d_opitcal * tz + optical_center.z;
      azimuth = static_cast<int>(std::atan2(x, y) * kHalfCircleFloat * kFineResolutionFloat / M_PI);
      elevation = static_cast<int>(std::asin(z / d) * kHalfCircleFloat * kFineResolutionFloat / M_PI);
      distance = d;
    } else if (type == OpticalCenter) {
      float x = d * tx + optical_center.x;
      float y = d * ty + optical_center.y;
      float z = d * tz + optical_center.z;
      float d_geometric_center = std::sqrt(x * x + y * y + z * z);
      azimuth = static_cast<int>(std::atan2(x, y) * kHalfCircleFloat * kFineResolutionFloat / M_PI);
      elevation = static_cast<int>(std::asin(z / d_geometric_center) * kHalfCircleFloat * kFineResolutionFloat / M_PI);
      distance = d_geometric_center;
    } else {
      // It should never have been executed here.
    }
    CircleRevise(azimuth);
    CircleRevise(elevation);
  }

  // compute coordinate transformation
  void TransformPoint(float& x, float& y, float& z, const TransformParam& transform) {
    if (transform.use_flag == false) return;

    float cosa = std::cos(transform.roll);
    float sina = std::sin(transform.roll);
    float cosb = std::cos(transform.pitch);
    float sinb = std::sin(transform.pitch);
    float cosc = std::cos(transform.yaw);
    float sinc = std::sin(transform.yaw);

    float x_ = cosb * cosc * x + (sina * sinb * cosc - cosa * sinc) * y +
                (sina * sinc + cosa * sinb * cosc) * z + transform.x;
    float y_ = cosb * sinc * x + (cosa * cosc + sina * sinb * sinc) * y +
                (cosa * sinb * sinc - sina * cosc) * z + transform.y;
    float z_ = -sinb * x + sina * cosb * y + cosa * cosb * z + transform.z;
    x = x_;
    y = y_;
    z = z_; 
  }

  // ensure the angle is between [0-360) with 1/25600 accuracy
  void CircleRevise(int &angle) {
    while (angle < 0) {
      angle += CIRCLE;
    }
    while (angle >= CIRCLE) {
      angle -= CIRCLE;
    }
  }

  // ensure the angle is between [0, 360) degrees
  void CircleRevise(float &angle) {
    while (angle < 0.0f) {
      angle += 360.0f;
    }
    while (angle >= 360.0f) {
      angle -= 360.0f;
    }
  }

  void CircleRevise(double &angle) {
    while (angle < 0.0) {
      angle += 360.0;
    }
    while (angle >= 360.0) {
      angle -= 360.0;
    }
  }

  // set frame azimuth
  virtual void SetFrameAzimuth(float frame_start_azimuth) {
    // Determine frame_start_azimuth [0,360)
    if (frame_start_azimuth < 0.0f || frame_start_azimuth >= 360.0f) {
      frame_start_azimuth = 0.0f;
    }
    frame_start_azimuth_uint16_ = frame_start_azimuth * kResolutionInt;
  }

  // Statistical packet loss data
  void CalPktLoss(uint32_t PacketSeqnum, FrameDecodeParam param) {
    if (param.enable_packet_loss_tool_ == false) {
      return;
    }
    this->seqnum_loss_message_.is_packet_loss = false;
    if (this->seqnum_loss_message_.is_init == false) {
      this->seqnum_loss_message_.loss_count = 0;
      this->seqnum_loss_message_.total_loss_count = 0;
      this->seqnum_loss_message_.start_time = GetMicroTickCount();
      this->seqnum_loss_message_.last_total_package_count = 0;
      this->seqnum_loss_message_.total_packet_count = 0;
      this->seqnum_loss_message_.last_seqnum = PacketSeqnum;
      this->seqnum_loss_message_.is_init = true;
      return;
    }
    uint32_t diff = 0;
    if (PacketSeqnum >= this->seqnum_loss_message_.last_seqnum) {
      diff = PacketSeqnum - this->seqnum_loss_message_.last_seqnum;
    } else {
      diff = (this->seqnum_loss_message_.max_sequence - this->seqnum_loss_message_.last_seqnum) + PacketSeqnum + 1;
    }
    this->seqnum_loss_message_.total_packet_count += diff;
    
    if (diff > 1) {
      this->seqnum_loss_message_.loss_count += (diff - 1);
      this->seqnum_loss_message_.total_loss_count += (diff - 1);
      this->seqnum_loss_message_.is_packet_loss = true;
    }
    // print log every 1s
    if (this->seqnum_loss_message_.loss_count != 0 && GetMicroTickCount() - this->seqnum_loss_message_.start_time >= 1 * 1000 * 1000) {
      LogWarning("pkt loss freq: %u/%u", this->seqnum_loss_message_.loss_count,
              this->seqnum_loss_message_.total_packet_count - this->seqnum_loss_message_.last_total_package_count);
      this->seqnum_loss_message_.loss_count = 0;
      this->seqnum_loss_message_.start_time = GetMicroTickCount();
      this->seqnum_loss_message_.last_total_package_count = this->seqnum_loss_message_.total_packet_count;
    }
    this->seqnum_loss_message_.last_seqnum = PacketSeqnum;
  }

  void CalPktTimeLoss(uint64_t PacketTimestamp, FrameDecodeParam param) {
    if(param.enable_packet_timeloss_tool_ == false){
      return;
    } 
    if(param.packet_timeloss_tool_continue_ == false && this->time_loss_message_.total_timeloss_count != 0){    
      return;
    }
    if (this->time_loss_message_.is_init == false) {
      this->time_loss_message_.timeloss_count = 0;
      this->time_loss_message_.total_timeloss_count = 0;
      this->time_loss_message_.timeloss_start_time = GetMicroTickCount();
      this->time_loss_message_.last_timestamp = PacketTimestamp;
      this->time_loss_message_.last_total_package_count = this->seqnum_loss_message_.total_packet_count;
      this->time_loss_message_.is_init = true;
      return;
    }
    // packet time loss reset
    else if(this->seqnum_loss_message_.is_packet_loss) {
      LogWarning("pkt time loss freq: %u/%u", this->time_loss_message_.timeloss_count, this->seqnum_loss_message_.total_packet_count - this->time_loss_message_.last_total_package_count);
      this->time_loss_message_.timeloss_count = 0;
      this->time_loss_message_.timeloss_start_time = GetMicroTickCount();
      this->time_loss_message_.last_timestamp = PacketTimestamp;
      this->time_loss_message_.last_total_package_count = this->seqnum_loss_message_.total_packet_count;
      return;
    }
    if (PacketTimestamp <= this->time_loss_message_.last_timestamp) {
      this->time_loss_message_.timeloss_count++;
      this->time_loss_message_.total_timeloss_count++;
    }
    // print log every 1s
    if (this->time_loss_message_.timeloss_count != 0 && GetMicroTickCount() - this->time_loss_message_.timeloss_start_time >= 1 * 1000 * 1000) {
      LogWarning("pkt time loss freq: %u/%u", this->time_loss_message_.timeloss_count,
             this->seqnum_loss_message_.total_packet_count - this->time_loss_message_.last_total_package_count);
      this->time_loss_message_.timeloss_count = 0;
      this->time_loss_message_.timeloss_start_time = GetMicroTickCount();
      this->time_loss_message_.last_total_package_count = this->seqnum_loss_message_.total_packet_count;
    }
    this->time_loss_message_.last_timestamp = PacketTimestamp;    
  }

  int IsChannelFovFilter(float fov, int channel_index, FrameDecodeParam &param) { 
    // high priority, filter some fov ranges for all channels. low cpu usage
    if (param.config.multi_fov_filter_ranges.size() > 0) {
      for (const auto & pair : param.config.multi_fov_filter_ranges) {
        if (fov >= pair.first && fov <= pair.second) {
          return 1;
        }
      }
    }
    // middle priority, filter some fov ranges for some channels, a little high cpu usage
    if (param.config.channel_fov_filter.size() > 0 && param.config.channel_fov_filter.count(channel_index) > 0) {
      for (const auto & pair : param.config.channel_fov_filter[channel_index]) {
        if (fov >= pair.first && fov <= pair.second) {
          // printf("channel %d, %d\n", channel_index, fov);
          return 1;
        }
      }
    }
    // low priority, show only [fov_start, fov_end]. low cpu usage
    if (param.config.fov_start != -1 && param.config.fov_end != -1) {
      if (fov < param.config.fov_start || fov > param.config.fov_end) { //不在fov范围continue
        return 1;
      }
    }
    return 0;
  }

  // remake 
  void setRemakeDefaultConfig(LidarDecodedFrame<T_Point> &frame) {
    auto &rq = frame.fParam.remake_config;
    if (rq.flag == false) return;
    if (rq.min_azi < 0) rq.min_azi = default_remake_config.min_azi;
    if (rq.max_azi < 0) rq.max_azi = default_remake_config.max_azi;
    if (rq.ring_azi_resolution < 0) rq.ring_azi_resolution = default_remake_config.ring_azi_resolution;
    if (rq.max_azi_scan < 0) rq.max_azi_scan = default_remake_config.max_azi_scan;

    if (rq.min_elev < 0) rq.min_elev = default_remake_config.min_elev;
    if (rq.max_elev < 0) rq.max_elev = default_remake_config.max_elev;
    if (rq.ring_elev_resolution < 0) rq.ring_elev_resolution = default_remake_config.ring_elev_resolution;
    if (rq.max_elev_scan < 0) rq.max_elev_scan = default_remake_config.max_elev_scan;

    if (static_cast<uint32_t>(rq.max_azi_scan) > frame.maxPacketPerFrame || static_cast<uint32_t>(rq.max_elev_scan) > frame.maxPointPerPacket) {
      int max_azi = HS_MAX(static_cast<uint32_t>(rq.max_azi_scan), frame.maxPacketPerFrame);
      int max_elev = HS_MAX(static_cast<uint32_t>(rq.max_elev_scan), frame.maxPointPerPacket);
      frame.resetMalloc(max_azi, max_elev);
    }
  }

  void DoRemake(int azi, int elev, int ring, const RemakeConfig& rq, int& point_idx) {
    if (rq.flag == false) return;
    float azi_ = azi / kAllFineResolutionFloat;
    float elev_ = elev / kAllFineResolutionFloat;
    elev_ = elev_ > 180.0 ? elev_ - 360.0 : elev_;
    point_idx = -1;
    int new_azi_iscan = static_cast<int>(std::round((azi_ - rq.min_azi) / rq.ring_azi_resolution));
    int new_elev_iscan = ring;
    if (!rq.use_ring_remake) {
      new_elev_iscan = static_cast<int>(std::round((elev_ - rq.min_elev) / rq.ring_elev_resolution));
    }
    if (new_azi_iscan >= 0 && new_azi_iscan < rq.max_azi_scan && new_elev_iscan >= 0 && new_elev_iscan < rq.max_elev_scan) {
      point_idx = new_azi_iscan * rq.max_elev_scan + new_elev_iscan;
    }
  }

  // update right memory space
  virtual void setFrameRightMemorySpace(LidarDecodedFrame<T_Point> &frame) {
    frame.resetMalloc(5000, 1024);
  }

  // used for updating cuda correction and firetime by itself
  uint32_t* getCorrectionLoadSequenceNum() { return &correction_load_sequence_num_; }
  uint32_t* getFiretimeLoadSequenceNum() { return &firetime_load_sequence_num_; }
  uint32_t* getDcfLoadSequenceNum() { return &dcf_load_sequence_num_; }
  bool* getCorrectionLoadFlag() { return &get_correction_file_; }
  bool* getFiretimeLoadFlag() { return &get_firetime_file_; }
  bool* getDcfLoadFlag() { return &get_dcf_file_; }
  void loadCorrectionSuccess() { get_correction_file_ = true; correction_load_sequence_num_++; }
  void loadFiretimeSuccess() { get_firetime_file_ = true; firetime_load_sequence_num_++; }
  void loadDcfSuccess() { get_dcf_file_ = true; dcf_load_sequence_num_++; }

  virtual int FrameProcess(LidarDecodedFrame<T_Point> &frame) {
    return 0;
  }



  PacketSeqnumLossMessage seqnum_loss_message_;
  PacketTimeLossMessage time_loss_message_;


 protected:
  float cos_all_angle_[CIRCLE];
  float sin_all_angle_[CIRCLE];
  CorrectionData correction;
  float firetime_correction_[DEFAULT_MAX_LASER_NUM];
  bool get_correction_file_ = false;
  bool get_firetime_file_ = false;
  bool get_dcf_file_ = false;
  uint32_t correction_load_sequence_num_ = 0;
  uint32_t firetime_load_sequence_num_ = 0;
  uint32_t dcf_load_sequence_num_ = 0;
  int32_t last_azimuth_;
  int32_t last_last_azimuth_;
  std::atomic<uint32_t> compute_packet_num{0};
  int rotation_flag;
  std::string lidar_type_;
  uint16_t frame_start_azimuth_uint16_;
  LidarOpticalCenter optical_center;
  RemakeConfig default_remake_config;
  LastUtcTime last_utc_time;
  uint32_t last_max_packet_num_ = 0;
};
}
}

#endif  // GENERAL_PARSER_H_
