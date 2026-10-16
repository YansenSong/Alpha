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
#ifndef HS_LIDAR_FT_V3_H
#define HS_LIDAR_FT_V3_H

#include <stdint.h>
#include <udp_protocol_header.h>
#include <cmath>
#include <iostream>
namespace hesai
{
namespace lidar
{
#define MINIFLASH_ROW_V3  32
#define MINIFLASH_COL_V3  16
#define PIXEL_ROW_V3   6
#define PIXEL_COL_V3   16
#define HEIGHT_MAX  (MINIFLASH_ROW_V3 * PIXEL_ROW_V3)
#define WIDTH_MAX   (MINIFLASH_COL_V3 * PIXEL_COL_V3)

#define ZOOM_MINIFLASH_ROW_V3  16
#define ZOOM_MINIFLASH_COL_V3  10
#define ZOOM_ROW_OFFSET  8   
#define ZOOM_COL_OFFSET  2   
#define ZOOM_HEIGHT  (ZOOM_MINIFLASH_ROW_V3 * PIXEL_ROW_V3)  // 96
#define ZOOM_WIDTH   (ZOOM_MINIFLASH_COL_V3 * PIXEL_COL_V3)  // 160

#pragma pack(push, 1)
  namespace FT {
    struct CorrectionDis {
      float x;
      float y;
      float z;
    };

    template<typename T>
    inline T interp(const T& x1, const T& x2, const T& y1, const T& y2, const T& x)
    {
        return (y2-y1)/(x2-x1)*(x-x1) + y1;
    }

    template<typename T>
    inline int binarySearch(const T& x, const std::vector<T>& vec)
    {
        int l = 0, r = vec.size()-1;
        if(x < vec[l]) return -1;
        if(x > vec[r]) return -1;
        while(l<=r){
            int mid = (l + r)/2;
            if(vec[mid] < x) l = mid + 1;
            else r = mid - 1;
        }
        return r; // 当前 vec[r] <= x <= vec[l]
    }

    struct CorrectionV3 {
      uint16_t m_u16Delimiter;    // 0xee 0xff
      uint8_t m_u8VersionMajor;   // 0x07
      uint8_t m_u8VersionMinor;   // 0x03
      uint8_t m_u8Reserved0;
      uint8_t m_u8Reserved1;
      uint16_t m_u16TotalRow;
      uint16_t m_u16TotalCol;
      float f;
      float cx;
      float cy;
      float k1;
      float k2;
      float k3;
      float k4;
      float p1;
      float p2;
      uint8_t m_u8Sha256[32];

      float distortion_func(float theta){
        return theta + k1 * std::pow(theta, 3) + k2 * std::pow(theta, 5) + k3 * std::pow(theta, 7) + k4 * std::pow(theta, 9);
      }

      std::vector<std::vector<float>> generate_pixel_vectors() {
        float phi, phi_rad, alpha_rad;
        alpha_rad = 2 * atan(p1);
        if (alpha_rad < 0) {
            alpha_rad = -alpha_rad;
            phi = p2 + M_PI;
        }else{
            phi = p2;
        }
        phi_rad = (phi / M_PI / 2 - int(phi/M_PI / 2)) * 2 * M_PI + M_PI;
        
        float R[3][3]; // rotation matrix
        float cos_a = cos(alpha_rad);
        float sin_a = sin(alpha_rad);
        float cos_p = cos(phi_rad);
        float sin_p = sin(phi_rad);
        R[0][0] = cos_a + (1 - cos_a) * cos_p*cos_p;
        R[0][1] = (1 - cos_a)*cos_p * sin_p;
        R[0][2] = sin_a * sin_p;
        R[1][0] = (1 - cos_a) * cos_p * sin_p;
        R[1][1] = cos_a + (1 - cos_a) * sin_p * sin_p;
        R[1][2] = -sin_a * cos_p;
        R[2][0] = -sin_a * sin_p;
        R[2][1] = sin_a * cos_p;
        R[2][2] = cos_a;

        // float thetaD_th = distortion_func(MATH_PI/2);
        float theta_th = std::pow(std::pow(HS_MAX(cx,767-cx), 2) + std::pow(HS_MAX(cy,575-cy), 2), 0.5)/f;
        float tan_theta_th = 750.0/f;

        int Ninterp = 1024;
        std::vector<float> theta_arr(Ninterp, 0.0);
        std::vector<float> thetaD_arr(Ninterp, 0.0);
        for (int i = 0; i < Ninterp; ++i) {
            theta_arr[i] = i * tan_theta_th/Ninterp;
            thetaD_arr[i] = distortion_func(theta_arr[i]);
            if (i > 0){
                if (thetaD_arr[i] < thetaD_arr[i - 1]) {
                  Ninterp = i;
                  break;
                }
            } // 保证曲线不下降
        }
        if (Ninterp<1024){
            theta_arr.resize(Ninterp);
            thetaD_arr.resize(Ninterp);
        }
    
        float x, y, x1, y1, z1, x2, y2, thetaD, theta, pvec_norm;
        std::vector<float> pvec = {0, 0, 0};
        std::vector<std::vector<float>> pixel_vectors(m_u16TotalRow*m_u16TotalCol, std::vector<float>(3, 0));

        int init_row = (192 - m_u16TotalRow) >> 1;
        int init_col = (256 - m_u16TotalCol) >> 1;
        int pos;
        for (int i = init_row; i < m_u16TotalRow+init_row; ++i) {
          for (int j = init_col; j < m_u16TotalCol+init_col; ++j) {
            x = (j*3 + 1 - cx) / f;
            y = (575 - (i*3 + 1) - cy) / f;
            x1 = x*R[0][0] + y*R[0][1] + 0;
            y1 = x*R[1][0] + y*R[1][1] + 0;
            z1 = x*R[2][0] + y*R[2][1] + 0;
            x2 = -x1/(z1-1);
            y2 = -y1/(z1-1);
            thetaD = sqrt(pow(x2, 2) + pow(y2, 2));
            
            // std::cout << "alpha_rad: " << alpha_rad << ", phi_rad: " << phi_rad << std::endl;
            // std::cout << "x" << j << ", y" << i << ": " << x << ", " << y << std::endl;
            // std::cout << "x1: " << x1 << ", y1: " << y1 << ", z1: " << z1 << std::endl;
            // std::cout << "x2: " << x2 << ", y2: " << y2 << std::endl;
            // std::cout << "thetaD: " << thetaD << ", theta_th: " << theta_th << std::endl;

            if(thetaD == 0){
                pvec = {0.0, 0.0, 1.0};
            }else if(thetaD > theta_th){
                pvec = {0.0, 0.0, 0.0};
            }else{
                pos = binarySearch(thetaD, thetaD_arr);
                if (pos == -1){
                    pvec = {0.0, 0.0, 0.0};
                }else{
                    theta = interp(thetaD_arr[pos], thetaD_arr[pos+1], theta_arr[pos], theta_arr[pos+1], thetaD);
                    // theta = distortion_func(thetaD);
                    pvec = {x2, y2, static_cast<float>(sqrt(x2*x2 + y2*y2) / tan(theta))};
                    pvec_norm = sqrt(pow(pvec[0], 2) + pow(pvec[1], 2) + pow(pvec[2], 2));
                    pvec = {pvec[0]/pvec_norm, pvec[1]/pvec_norm, pvec[2]/pvec_norm};
                }
            }
            pixel_vectors[(i-init_row)*m_u16TotalCol + (j-init_col)] = {pvec[2], -pvec[0], -pvec[1]};
          }
        }
        return pixel_vectors;
      }
    };
  }

struct HS_LIDAR_BODY_CHN_UNIT_FT_V3 {
  uint16_t distance;
  uint8_t reflectivity;
  uint8_t background;
  uint8_t confidence;

  uint16_t GetDistance() const { return little_to_native(distance); }
  uint8_t GetReflectivity() const { return reflectivity; }
  uint8_t GetConfidenceLevel() const { return confidence; }
};

struct HS_LIDAR_HEADER_IMU_FT_V3 {
  uint8_t m_u8UTC[6];
  uint32_t m_u32Timestamp;

  int64_t GetMicroLidarTimeU64(LastUtcTime &last_utc_time) const {
    if (m_u8UTC[0] != 0) {
      if (last_utc_time.last_utc[0] == m_u8UTC[0]
          && last_utc_time.last_utc[1] == m_u8UTC[1]
          && last_utc_time.last_utc[2] == m_u8UTC[2]
          && last_utc_time.last_utc[3] == m_u8UTC[3]
          && last_utc_time.last_utc[4] == m_u8UTC[4]
          && last_utc_time.last_utc[5] == m_u8UTC[5]) {
        return last_utc_time.last_time + GetTimestamp();
      }
      last_utc_time.last_utc[0] = m_u8UTC[0];
      last_utc_time.last_utc[1] = m_u8UTC[1];
      last_utc_time.last_utc[2] = m_u8UTC[2];
      last_utc_time.last_utc[3] = m_u8UTC[3];
      last_utc_time.last_utc[4] = m_u8UTC[4];
      last_utc_time.last_utc[5] = m_u8UTC[5];

			struct tm t = {0};
			t.tm_year = m_u8UTC[0];
			if (t.tm_year < 70) {
				return 0;
			}
			t.tm_mon = m_u8UTC[1] - 1;
			t.tm_mday = m_u8UTC[2] + 1;
			t.tm_hour = m_u8UTC[3];
			t.tm_min = m_u8UTC[4];
			t.tm_sec = m_u8UTC[5];
			t.tm_isdst = 0;
#ifdef _MSC_VER
  TIME_ZONE_INFORMATION tzi;
  GetTimeZoneInformation(&tzi);
  long int timezone =  tzi.Bias * 60;
#endif
      last_utc_time.last_time = (mktime(&t) - timezone - 86400) * 1000000;
      return last_utc_time.last_time + GetTimestamp();
		}
		else {
      uint32_t utc_time_big = *(uint32_t*)(&m_u8UTC[0] + 2);
      int64_t unix_second = ((utc_time_big >> 24) & 0xff) |
              ((utc_time_big >> 8) & 0xff00) |
              ((utc_time_big << 8) & 0xff0000) |
              ((utc_time_big << 24));
      return unix_second * 1000000 + GetTimestamp();
		}
  }

  inline uint32_t GetTimestamp() const { return little_to_native(m_u32Timestamp); }
  inline uint8_t GetUTCData(uint8_t index) const {
    return m_u8UTC[index < sizeof(m_u8UTC) ? index : 0];
  }
};

struct HS_LIDAR_BODY_IMU_FT_V3 {
  static constexpr double AccelUint = 1 / 8192.0;
  static constexpr double AngVelUint = 1 / 32.8;
  int16_t m_i16IMUXAccel;
  int16_t m_i16IMUYAccel;
  int16_t m_i16IMUZAccel;
  int16_t m_i16IMUXAngVel;
  int16_t m_i16IMUYAngVel;
  int16_t m_i16IMUZAngVel;
  int16_t m_i16SequenceNum;

  inline double GetIMUXAccel() const {
    return little_to_native(m_i16IMUXAccel) * AccelUint;
  }
  inline double GetIMUYAccel() const {
    return little_to_native(m_i16IMUYAccel) * AccelUint;
  }
  inline double GetIMUZAccel() const {
    return little_to_native(m_i16IMUZAccel) * AccelUint;
  }
  inline double GetIMUXAngVel() const {
    return little_to_native(m_i16IMUXAngVel) * AngVelUint;
  }
  inline double GetIMUYAngVel() const {
    return little_to_native(m_i16IMUYAngVel) * AngVelUint;
  }
  inline double GetIMUZAngVel() const {
    return little_to_native(m_i16IMUZAngVel) * AngVelUint;
  }
  inline uint16_t GetSequenceNum() const { return little_to_native(m_i16SequenceNum); }
};

struct HS_LIDAR_TAIL_FT_V3 {
  ReservedInfo1 m_reservedInfo1;
  ReservedInfo2 m_reservedInfo2;
  uint8_t status_mode;
  uint8_t column_id;
  uint8_t row_id;
  uint8_t frame_id;
  uint8_t high_temperature_shutdown_flag;
  uint8_t return_mode;
  uint16_t frame_duration;
  uint8_t utc[6];
  uint32_t timestamp;
  uint8_t factory;
  uint32_t sequence_num;

  inline uint8_t GetStsID0() const { return m_reservedInfo1.GetID(); }
  inline uint16_t GetData0() const { return m_reservedInfo1.GetData(); }

  inline uint8_t GetStsID1() const { return m_reservedInfo2.GetID(); }
  inline uint16_t GetData1() const { return m_reservedInfo2.GetData(); }


  inline uint16_t GetFrameDuration() const { return little_to_native(frame_duration); }

  inline uint32_t GetTimestamp() const { return little_to_native(timestamp); }

  inline uint8_t GetReturnMode() const { return return_mode; }

  inline uint8_t GetUTCData(uint8_t index) const {
    return utc[index < sizeof(utc) ? index : 0];
  }

  inline uint32_t GetSeqNum() const { return little_to_native(sequence_num); }

  uint64_t GetMicroLidarTimeU64(LastUtcTime &last_utc_time) const {
    if (utc[0] != 0) {
      if (last_utc_time.last_utc[0] == utc[0]
          && last_utc_time.last_utc[1] == utc[1]
          && last_utc_time.last_utc[2] == utc[2]
          && last_utc_time.last_utc[3] == utc[3]
          && last_utc_time.last_utc[4] == utc[4]
          && last_utc_time.last_utc[5] == utc[5]) {
        return last_utc_time.last_time + GetTimestamp();
      }
      last_utc_time.last_utc[0] = utc[0];
      last_utc_time.last_utc[1] = utc[1];
      last_utc_time.last_utc[2] = utc[2];
      last_utc_time.last_utc[3] = utc[3];
      last_utc_time.last_utc[4] = utc[4];
      last_utc_time.last_utc[5] = utc[5];

			struct tm t = {0};
			t.tm_year = utc[0];
			if (t.tm_year < 70) {
        t.tm_year += 100;
      }
			t.tm_mon = utc[1] - 1;
			t.tm_mday = utc[2] + 1;
			t.tm_hour = utc[3];
			t.tm_min = utc[4];
			t.tm_sec = utc[5];
			t.tm_isdst = 0;
#ifdef _MSC_VER
  TIME_ZONE_INFORMATION tzi;
  GetTimeZoneInformation(&tzi);
  long int timezone =  tzi.Bias * 60;
#endif
      last_utc_time.last_time = (mktime(&t) - timezone - 86400) * 1000000;
      return last_utc_time.last_time + GetTimestamp();
		}
		else {
      uint32_t utc_time_big = *(uint32_t*)(&utc[0] + 2);
      uint64_t unix_second = big_to_native(utc_time_big);
      return unix_second * 1000000 + GetTimestamp();
		}

  }
};

struct HS_LIDAR_HEADER_FT_V3 {
  uint16_t total_column;
  uint16_t total_row;
  uint8_t column_resolution;
  uint8_t row_resolution;
  uint8_t echo;
  uint8_t dist_unit;
  uint8_t configuration_number;
  uint16_t channel_num;
  uint8_t reserved[8];

  inline uint16_t GetChannelNum() const { return channel_num; }
  inline float GetDistUnit() const { return dist_unit / 1000.f; }
  inline uint16_t GetPacketSize() const {
    return sizeof(HS_LIDAR_PRE_HEADER) + sizeof(HS_LIDAR_HEADER_FT_V3) + 
           sizeof(HS_LIDAR_BODY_CHN_UNIT_FT_V3) * GetChannelNum() +
           sizeof(HS_LIDAR_TAIL_FT_V3)
           + 20; // Safety + Security
  }
};

struct HS_LIDAR_E2E_HEADER_FT_V3 {
  uint16_t m_u16Length;
  uint16_t m_u16Counter;
  uint32_t m_u32DataID;
  uint32_t m_u32CRC;

  inline uint16_t GetLength() const { return big_to_native(m_u16Length); }
  inline uint16_t GetCounter() const { return big_to_native(m_u16Counter); }
  inline uint32_t GetDataID() const { return big_to_native(m_u32DataID); }
  inline uint32_t GetCRC() const { return big_to_native(m_u32CRC); }
};

struct FaultMessageVersion7_3 {
  public:
   uint8_t version_info;
   uint8_t utc_time[6];
   uint32_t time_stamp;
   uint8_t operate_state;
   uint8_t fault_state;
   uint8_t total_fault_code_num;
   uint8_t fault_code_id;
   uint32_t fault_code;
   uint8_t time_division_multiplexing[27];
   uint8_t internal_fault_id;
   uint8_t fault_indicate[8];
   uint8_t software_version[3];
   uint8_t reversed[5];
   HS_LIDAR_E2E_HEADER_FT_V3 E2Eheader;
   uint8_t cycber_security[24];
   uint32_t GetTimestamp() const { return big_to_native(time_stamp); }
   uint32_t GetFaultCode() const { return big_to_native(fault_code); }
   uint64_t GetMicroLidarTimeU64(LastUtcTime &last_utc_time) const {
     if (utc_time[0] != 0) {
       if (last_utc_time.last_utc[0] == utc_time[0] 
           && last_utc_time.last_utc[1] == utc_time[1] 
           && last_utc_time.last_utc[2] == utc_time[2] 
           && last_utc_time.last_utc[3] == utc_time[3] 
           && last_utc_time.last_utc[4] == utc_time[4] 
           && last_utc_time.last_utc[5] == utc_time[5]) {
         return last_utc_time.last_time + GetTimestamp();
       }
       last_utc_time.last_utc[0] = utc_time[0];  
       last_utc_time.last_utc[1] = utc_time[1];
       last_utc_time.last_utc[2] = utc_time[2];
       last_utc_time.last_utc[3] = utc_time[3];
       last_utc_time.last_utc[4] = utc_time[4];
       last_utc_time.last_utc[5] = utc_time[5];
 
       struct tm t = {0};
       t.tm_year = utc_time[0];
       if (t.tm_year < 70) {
         return 0;
       }
       t.tm_mon = utc_time[1] - 1;
       t.tm_mday = utc_time[2] + 1;
       t.tm_hour = utc_time[3];
       t.tm_min = utc_time[4];
       t.tm_sec = utc_time[5];
       t.tm_isdst = 0;
 #ifdef _MSC_VER
       TIME_ZONE_INFORMATION tzi;
       GetTimeZoneInformation(&tzi);
       long int timezone =  tzi.Bias * 60;
 #endif
       last_utc_time.last_time = (mktime(&t) - timezone - 86400) * 1000000;
       return last_utc_time.last_time + GetTimestamp() ;
     }
     else {
       uint32_t utc_time_big = *(uint32_t*)(&utc_time[0] + 2);
       uint64_t unix_second = big_to_native(utc_time_big);
       return unix_second * 1000000 + GetTimestamp();
     }
   }
   
   void ParserFaultMessage(FaultMessageInfo &fault_message_info, LastUtcTime &last_utc_time) {
    fault_message_info.fault_parse_version = 0x0703;
    fault_message_info.version = version_info;
    memcpy(fault_message_info.utc_time, utc_time, sizeof(utc_time));
    fault_message_info.timestamp = GetTimestamp();
    fault_message_info.total_time = static_cast<double>(GetMicroLidarTimeU64(last_utc_time)) / 1000000.0;
    fault_message_info.operate_state = operate_state;
    fault_message_info.fault_state = fault_state;
    fault_message_info.total_faultcode_num = total_fault_code_num;
    fault_message_info.faultcode_id = fault_code_id;
    fault_message_info.faultcode = GetFaultCode();
    fault_message_info.union_info.fault7_3.tdm_data_indicate = time_division_multiplexing[0];
    memcpy(fault_message_info.union_info.fault7_3.time_division_multiplexing, time_division_multiplexing, sizeof(time_division_multiplexing));
    fault_message_info.union_info.fault7_3.internal_fault_id = internal_fault_id;
    memcpy(fault_message_info.union_info.fault7_3.fault_indicate, fault_indicate, sizeof(fault_indicate));
    memcpy(fault_message_info.union_info.fault7_3.software_version, software_version, sizeof(software_version));
    memcpy(fault_message_info.union_info.fault7_3.reserved0, reversed, sizeof(reversed));
  }
};
#pragma pack(pop)
}  // namespace lidar
}  // namespace hesai
#endif
