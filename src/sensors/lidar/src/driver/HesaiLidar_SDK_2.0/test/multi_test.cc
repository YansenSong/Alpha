#include "hesai_lidar_sdk.hpp"
#include "../config/driver_sample_config.hpp"

#include <cstdio>
#include <cstring>
#include <fstream>
#include <functional>
#include <string>
#include <thread>

struct LidarConfig {
  DriverParam driver_param;
  std::function<void(const LidarDecodedFrame<LidarPointXYZICRT>&)> point_cloud_callback;
  std::function<void(const FaultMessageInfo&)> fault_callback;
  uint32_t* last_frame_time;
};

uint32_t last_frame_time_1 = 0;
uint32_t cur_frame_time_1 = 0;
uint32_t last_frame_time_2 = 0;
uint32_t cur_frame_time_2 = 0;

void lidarCallback1(const LidarDecodedFrame<LidarPointXYZICRT>& frame) {
  cur_frame_time_1 = GetMicroTickCount();
  if (last_frame_time_1 == 0) last_frame_time_1 = GetMicroTickCount();
  if (cur_frame_time_1 - last_frame_time_1 > kMaxTimeInterval) {
    printf("Lidar1 - Time between last frame and cur frame is: %u us\n",
           (cur_frame_time_1 - last_frame_time_1));
  }
  last_frame_time_1 = cur_frame_time_1;
  printf("Lidar1 - frame:%d points:%u packet:%u start time:%lf end time:%lf\n", frame.frame_index,
         frame.points_num, frame.packet_num, frame.frame_start_timestamp, frame.frame_end_timestamp);
}

void lidarCallback2(const LidarDecodedFrame<LidarPointXYZICRT>& frame) {
  cur_frame_time_2 = GetMicroTickCount();
  if (last_frame_time_2 == 0) last_frame_time_2 = GetMicroTickCount();
  if (cur_frame_time_2 - last_frame_time_2 > kMaxTimeInterval) {
    printf("Lidar2 - Time between last frame and cur frame is: %u us\n",
           (cur_frame_time_2 - last_frame_time_2));
  }
  last_frame_time_2 = cur_frame_time_2;
  printf("Lidar2 - frame:%d points:%u packet:%u start time:%lf end time:%lf\n", frame.frame_index,
         frame.points_num, frame.packet_num, frame.frame_start_timestamp, frame.frame_end_timestamp);
}

void faultMessageCallback1(const FaultMessageInfo& fault_message_info) {}

void faultMessageCallback2(const FaultMessageInfo& fault_message_info) {}

bool IsPlayEnded(HesaiLidarSdk<LidarPointXYZICRT>& sdk) { return sdk.lidar_ptr_->IsPlayEnded(); }

void lidarThread(const LidarConfig& config) {
#ifndef _MSC_VER
  if (system("sudo sh -c \"echo 562144000 > /proc/sys/net/core/rmem_max\"") == -1) {
    printf("Command execution failed!\n");
  }
#endif
  HesaiLidarSdk<LidarPointXYZICRT> sample;
  sample.Init(config.driver_param);
  sample.RegRecvCallback(config.point_cloud_callback);
  sample.RegRecvCallback(config.fault_callback);
  sample.Start();
  if (sample.lidar_ptr_->GetInitFinish(FailInit)) {
    sample.Stop();
    return;
  }
  while (!IsPlayEnded(sample) || GetMicroTickCount() - *config.last_frame_time < 1000000) {
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
  }
  std::this_thread::sleep_for(std::chrono::milliseconds(1000));
  printf("The PCAP file has been parsed and we will exit the program.\n");
}

static void PrintUsage(const char* prog) {
  fprintf(stderr, "Usage: %s <config.ini> [use_gpu]\n", prog);
  fprintf(stderr, "  config.ini  - INI configuration file with [lidar1] and [lidar2] sections (required)\n");
  fprintf(stderr, "  use_gpu     - 1 to enable GPU acceleration (optional)\n");
  fprintf(stderr, "\nExample:\n");
  fprintf(stderr, "  %s multi_sample_config.ini\n", prog);
  fprintf(stderr, "  %s multi_sample_config.ini 1\n", prog);
}

int main(int argc, char* argv[]) {
  LidarConfig config1;
  LidarConfig config2;
  config1.last_frame_time = &last_frame_time_1;
  config1.point_cloud_callback = lidarCallback1;
  config1.fault_callback = faultMessageCallback1;
  config2.last_frame_time = &last_frame_time_2;
  config2.point_cloud_callback = lidarCallback2;
  config2.fault_callback = faultMessageCallback2;

  if (argc < 2) {
    PrintUsage(argv[0]);
    return 1;
  }

  std::ifstream probe(argv[1]);
  if (!probe.good()) {
    fprintf(stderr, "[multi_test] error: config file not found: %s\n", argv[1]);
    PrintUsage(argv[0]);
    return 1;
  }
  probe.close();

  std::string err;
  if (!hesai::lidar::sample_config::LoadDriverSampleConfigForSection(argv[1], "lidar1",
                                                                      &config1.driver_param, &err)) {
    fprintf(stderr, "[multi_test] lidar1: %s\n", err.c_str());
    return 1;
  }
  if (!hesai::lidar::sample_config::LoadDriverSampleConfigForSection(argv[1], "lidar2",
                                                                      &config2.driver_param, &err)) {
    fprintf(stderr, "[multi_test] lidar2: %s\n", err.c_str());
    return 1;
  }
  if (argc >= 3 && std::string(argv[2]) == "1") {
    config1.driver_param.use_gpu = true;
    config2.driver_param.use_gpu = true;
  }
  printf("[multi_test] loaded config: %s\n", argv[1]);

  config1.driver_param.decoder_param.enable_packet_loss_tool = false;
  config2.driver_param.decoder_param.enable_packet_loss_tool = false;
  if (config1.driver_param.decoder_param.socket_buffer_size == 0) {
    config1.driver_param.decoder_param.socket_buffer_size = 262144000;
  }
  if (config2.driver_param.decoder_param.socket_buffer_size == 0) {
    config2.driver_param.decoder_param.socket_buffer_size = 262144000;
  }

  std::thread lidar_thread1(lidarThread, std::ref(config1));
  std::thread lidar_thread2(lidarThread, std::ref(config2));
  lidar_thread1.join();
  lidar_thread2.join();
  return 0;
}
