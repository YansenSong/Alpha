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

#include "udp7_3_parser_gpu.h"
namespace hesai
{
namespace lidar
{

__global__ void compute_xyzs_7_3_impl(uint8_t* point_cloud_cu_, uint32_t point_cloud_size, 
    const FT::CorrectionDis* correction_cu_, TransformParam transform, CudaPointXYZAER* points_cu_) {
  auto packet_index = blockIdx.x;
  auto channel_index = threadIdx.x;
  auto block_index = threadIdx.y;
  auto channel_num = blockDim.x;
  auto block_num = blockDim.y;

  extern __shared__ uint8_t shared_data[];
  int tid = block_index * channel_num + channel_index;
  int thread_count = block_num * channel_num;
  const uint8_t* input_data = point_cloud_cu_ + packet_index * point_cloud_size;
  if (input_data[0] != 0xEE || input_data[1] != 0xFF) return;
  for (int i = tid; i < point_cloud_size; i += thread_count) {
    shared_data[i] = input_data[i];
  }
  __syncthreads();
  
  int point_index = packet_index * block_num * channel_num + block_index * channel_num + channel_index;
  
  // Parse header after the full 6-byte PRE_HEADER.
  int header_offset = sizeof(HS_LIDAR_PRE_HEADER);
  uint8_t dist_unit_raw = shared_data[header_offset + 7];
  float dist_unit = dist_unit_raw / 1000.0f;
  uint8_t configuration_number = shared_data[header_offset + 8];
  uint16_t total_column = shared_data[header_offset + 0] + shared_data[header_offset + 1] * 0x100;
  uint16_t total_row = shared_data[header_offset + 2] + shared_data[header_offset + 3] * 0x100;
  uint16_t chn_num = shared_data[header_offset + 9] + shared_data[header_offset + 10] * 0x100;
  
  // Parse body after the packed FT_V3 header.
  int body_offset = header_offset + sizeof(HS_LIDAR_HEADER_FT_V3);
  int unit_size = sizeof(HS_LIDAR_BODY_CHN_UNIT_FT_V3);
  int unit_offset = body_offset + unit_size * channel_index;
  
  uint16_t distance_raw = shared_data[unit_offset + 0] + shared_data[unit_offset + 1] * 0x100;
  float distance = distance_raw * dist_unit;
  uint8_t reflectivity = shared_data[unit_offset + 2];
  uint8_t confidence = shared_data[unit_offset + 4];
  
  // Parse tail (after all channel units)
  int tail_offset = body_offset + unit_size * chn_num;
  // ReservedInfo1: 3 bytes (offset 0-2), ReservedInfo2: 3 bytes (offset 3-5)
  // status_mode: 1 byte (offset 6), column_id: 1 byte (offset 7), row_id: 1 byte (offset 8)
  uint8_t column_id = shared_data[tail_offset + 7];
  uint8_t row_id = shared_data[tail_offset + 8];

  bool is_zoom_mode = (total_row == ZOOM_HEIGHT && total_column == ZOOM_WIDTH);
  int miniflash_row_max = is_zoom_mode ? ZOOM_MINIFLASH_ROW_V3 : MINIFLASH_ROW_V3;
  int miniflash_col_max = is_zoom_mode ? ZOOM_MINIFLASH_COL_V3 : MINIFLASH_COL_V3;
  int row_pixel_offset = is_zoom_mode ? ZOOM_ROW_OFFSET * PIXEL_ROW_V3 : 0;
  int col_pixel_offset = is_zoom_mode ? ZOOM_COL_OFFSET * PIXEL_COL_V3 : 0;

  if (row_id >= miniflash_row_max || column_id >= miniflash_col_max) {
    points_cu_[point_index].reserved[6] = 0;
    return;
  }
  
  // Calculate pixel coordinates
  int pixel_row = row_id * PIXEL_ROW_V3 + (channel_index % PIXEL_ROW_V3) + row_pixel_offset;
  int pixel_col = column_id * PIXEL_COL_V3 + (channel_index / PIXEL_ROW_V3) + col_pixel_offset;
  
  // Flip row based on configuration_number
  int row_id_use = pixel_row;
  if (configuration_number == 1 || configuration_number == 3) {
    row_id_use = HEIGHT_MAX - pixel_row - 1;
  }
  
  // Get correction data (unit direction vector)
  int corr_offset = row_id_use * FT::FT2_CORRECTION_LEN + pixel_col;
  float corr_x = correction_cu_[corr_offset].x;
  float corr_y = correction_cu_[corr_offset].y;
  float corr_z = correction_cu_[corr_offset].z;
  
  // Check for invalid correction data (zero vector means invalid point)
  bool is_valid = !(corr_x == 0.0f && corr_y == 0.0f && corr_z == 0.0f);
  
  // Calculate XYZ
  float x = distance * corr_x;
  float y = distance * corr_y;
  float z = distance * corr_z;
  
  // Calculate azimuth and elevation from direction vector
  float azimuth = 0.0f;
  float elevation = 0.0f;
  if (is_valid) {
    azimuth = atan2(corr_x, corr_y) * HALF_CIRCLE / M_PI;
    elevation = atan2(corr_z, sqrt(corr_x * corr_x + corr_y * corr_y)) * HALF_CIRCLE / M_PI;
  }

  // Apply transform if needed
  if (transform.use_flag) {
    float cosa = cos(transform.roll);
    float sina = sin(transform.roll);
    float cosb = cos(transform.pitch);
    float sinb = sin(transform.pitch);
    float cosc = cos(transform.yaw);
    float sinc = sin(transform.yaw);

    float x_ = cosb * cosc * x + (sina * sinb * cosc - cosa * sinc) * y +
                (sina * sinc + cosa * sinb * cosc) * z + transform.x;
    float y_ = cosb * sinc * x + (cosa * cosc + sina * sinb * sinc) * y +
                (cosa * sinb * sinc - sina * cosc) * z + transform.y;
    float z_ = -sinb * x + sina * cosb * y + cosa * cosb * z + transform.z;

    x = x_;
    y = y_;
    z = z_;
  }

  points_cu_[point_index].x = x;
  points_cu_[point_index].y = y;
  points_cu_[point_index].z = z;
  points_cu_[point_index].azimuthCalib = azimuth;
  while (points_cu_[point_index].azimuthCalib < 0) points_cu_[point_index].azimuthCalib += 360.0f;
  while (points_cu_[point_index].azimuthCalib >= 360.0f) points_cu_[point_index].azimuthCalib -= 360.0f;
  points_cu_[point_index].elevationCalib = elevation;
  while (points_cu_[point_index].elevationCalib < -180.0f) points_cu_[point_index].elevationCalib += 360.0f;
  while (points_cu_[point_index].elevationCalib >= 180.0f) points_cu_[point_index].elevationCalib -= 360.0f;
  points_cu_[point_index].distance = distance;
  points_cu_[point_index].reserved[0] = reflectivity;
  points_cu_[point_index].reserved[1] = pixel_row & 0xFF;
  points_cu_[point_index].reserved[2] = (pixel_row >> 8) & 0xFF;
  points_cu_[point_index].reserved[3] = pixel_col & 0xFF;
  points_cu_[point_index].reserved[4] = (pixel_col >> 8) & 0xFF;
  points_cu_[point_index].reserved[5] = confidence;
  points_cu_[point_index].reserved[6] = is_valid ? 1 : 0;  // validity flag
}

int compute_7_3_cuda(uint8_t* point_cloud_cu_, CudaPointXYZAER* points_cu_, uint32_t point_cloud_size, 
    const FT::CorrectionDis* correction_cu_, const FrameDecodeParam* fParam, 
    uint32_t packet_num, uint16_t block_num, uint16_t channel_num) {
  dim3 grid(packet_num);
  dim3 block(channel_num, block_num);
  compute_xyzs_7_3_impl<<<grid, block, point_cloud_size * sizeof(uint8_t)>>>(
    point_cloud_cu_, point_cloud_size, correction_cu_, fParam->transform, points_cu_);
  cudaDeviceSynchronize();
  cudaSafeCall(cudaGetLastError(), ReturnCode::CudaXYZComputingError);
  return 0;
}

}
}

