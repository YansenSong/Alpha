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
#ifndef Udp7_3_PARSER_GPU_H_
#define Udp7_3_PARSER_GPU_H_
#include "general_parser_gpu.h"
#include "udp_protocol_v7_2.h"  // for FT::FT2_CORRECTION_LEN
#include "udp_protocol_v7_3.h"

namespace hesai
{
namespace lidar
{

int compute_7_3_cuda(uint8_t* point_cloud_cu_, CudaPointXYZAER* points_cu_, uint32_t point_cloud_size, 
    const FT::CorrectionDis* correction_cu_, const FrameDecodeParam* fParam, 
    uint32_t packet_num, uint16_t block_num, uint16_t channel_num);

// class Udp7_3ParserGpu
// computes points for FTX/FT2 (protocol 7.3)
template <typename T_Point>
class Udp7_3ParserGpu: public GeneralParserGpu<T_Point>{
 private:
  FT::CorrectionDis* FT_correction_cu_;
  const FT::CorrectionDis* FT_correction_ptr_;
 public:
  Udp7_3ParserGpu(uint16_t maxPacket, uint16_t maxPoint) 
     : GeneralParserGpu<T_Point>(maxPacket, maxPoint) {
    cudaSafeMalloc((void**)&FT_correction_cu_, sizeof(FT::CorrectionDis) * FT::FT2_CORRECTION_LEN * FT::FT2_CORRECTION_LEN);
  }
  ~Udp7_3ParserGpu() {
    cudaSafeFree(FT_correction_cu_);
  }

  virtual void LoadCorrectionStruct(void *_correction) {
    if (this->init_suc_flag_ == false) return;
    FT_correction_ptr_ = (FT::CorrectionDis*)_correction;
    CUDACheck(cudaMemcpy(FT_correction_cu_, FT_correction_ptr_, 
              sizeof(FT::CorrectionDis) * FT::FT2_CORRECTION_LEN * FT::FT2_CORRECTION_LEN, 
              cudaMemcpyHostToDevice));
  }
  virtual void LoadFiretimesStruct(void *) {}
  virtual void updateCorrectionFile() {
    if (this->init_suc_flag_ == false) return;
    if (*this->get_correction_file_ && this->correction_load_sequence_num_cuda_use_ != *this->correction_load_sequence_num_) {
      this->correction_load_sequence_num_cuda_use_ = *this->correction_load_sequence_num_;
      CUDACheck(cudaMemcpy(FT_correction_cu_, FT_correction_ptr_, 
                sizeof(FT::CorrectionDis) * FT::FT2_CORRECTION_LEN * FT::FT2_CORRECTION_LEN, 
                cudaMemcpyHostToDevice));
    }
  }
  virtual void updateFiretimeFile() {}

  // compute xyzi of points from decoded packet, use gpu device
  virtual int ComputeXYZI(LidarDecodedFrame<T_Point> &frame) {
    if (!*this->get_correction_file_) return int(ReturnCode::CorrectionsUnloaded);  
    if (!this->init_suc_flag_) return int(ReturnCode::CudaInitError);
    this->reMalloc(frame.maxPacketPerFrame, frame.maxPointPerPacket, frame.point_cloud_size);
    cudaSafeCall(cudaMemcpy(this->point_cloud_cu_, frame.point_cloud_raw_data,
                            frame.point_cloud_size * frame.packet_num, 
                            cudaMemcpyHostToDevice), ReturnCode::CudaMemcpyHostToDeviceError);
    this->updateCorrectionFile();
    FrameDecodeParam cuda_Param = frame.fParam;
    // For 7_3 protocol: per_points_num is the channel count per packet
    int ret = compute_7_3_cuda(this->point_cloud_cu_, this->points_cu_, frame.point_cloud_size, 
      FT_correction_cu_, &cuda_Param, frame.packet_num, frame.block_num, frame.per_points_num);
    if (ret != 0) return ret;

    cudaSafeCall(cudaMemcpy(this->points_, this->points_cu_,
                            frame.per_points_num * frame.packet_num * sizeof(CudaPointXYZAER), 
                            cudaMemcpyDeviceToHost), ReturnCode::CudaMemcpyDeviceToHostError);
    for (uint32_t i = 0; i < frame.packet_num; i++) {
      uint8_t* data = frame.point_cloud_raw_data + i * frame.point_cloud_size;
      const HS_LIDAR_HEADER_FT_V3 *pHeader =
          reinterpret_cast<const HS_LIDAR_HEADER_FT_V3 *>(
              data + sizeof(HS_LIDAR_PRE_HEADER));
      bool is_zoom_mode = (pHeader->total_row == ZOOM_HEIGHT && pHeader->total_column == ZOOM_WIDTH);
      auto &packetData = frame.packetData[i];
      int point_index = i * frame.per_points_num;
      int point_num = 0;
      if (frame.fParam.remake_config.flag) {
        frame.fParam.remake_config.max_azi_scan = is_zoom_mode ? WIDTH_MAX : pHeader->total_column;
        frame.fParam.remake_config.max_elev_scan = is_zoom_mode ? HEIGHT_MAX : pHeader->total_row;
      }
      for (uint32_t channel_index = 0; channel_index < frame.per_points_num; channel_index++) {
        auto &point = this->points_[point_index + channel_index];
        // Check validity flag (reserved[6])
        if (point.reserved[6] == 0) {
          continue;
        }
        int row_id = point.reserved[1] + point.reserved[2] * 0x100;
        int col_id = point.reserved[3] + point.reserved[4] * 0x100;
        int row_id_use = row_id;
        if (pHeader->configuration_number == 1 || pHeader->configuration_number == 3) {
          row_id_use = HEIGHT_MAX - row_id - 1;
        }
        if (this->IsChannelFovFilter(point.azimuthCalib, row_id, frame.fParam) == 1) {
          continue;
        }
        int point_index_rerank = point_index + point_num;
        float azi_ = point.azimuthCalib; 
        float elev_ = point.elevationCalib; 
        if (frame.fParam.remake_config.flag) {
          point_index_rerank = col_id * frame.fParam.remake_config.max_elev_scan + row_id_use;
        }
        if(point_index_rerank >= 0) { 
          auto& ptinfo = frame.points[point_index_rerank]; 
          set_x(ptinfo, point.x);
          set_y(ptinfo, point.y);
          set_z(ptinfo, point.z);
          set_ring(ptinfo, row_id);
          set_intensity(ptinfo, point.reserved[0]);
          set_timestamp(ptinfo, double(packetData.t.sensor_timestamp) / kMicrosecondToSecond);
          set_confidence(ptinfo, point.reserved[5]);
          set_azimuth(ptinfo, azi_); 
          set_azimuthCalib(ptinfo, azi_); 
          set_elevation(ptinfo, elev_); 
          set_elevationCalib(ptinfo, elev_); 
          set_distance(ptinfo, point.distance); 

          point_num++;
        }
      }
      frame.valid_points[i] = point_num;
    }
    return 0;
  } 
};

}
}
#endif  // Udp7_3_PARSER_GPU_H_
