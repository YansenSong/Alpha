#include "hesai_lidar_sdk.hpp"
#include "../config/driver_sample_config.hpp"

#include <cstring>
#include <fstream>
#include <string>

#ifndef SPEC_LIDAR
using TestPointType = LidarPointXYZICRT;
#endif

uint32_t last_frame_time = 0;
uint32_t cur_frame_time = 0;

//log info, display frame message
void lidarCallback(const LidarDecodedFrame<TestPointType>& frame) {
  cur_frame_time = GetMicroTickCount();
  if (last_frame_time == 0) last_frame_time = GetMicroTickCount();
  uint32_t diff = (frame.fParam.IsMultiFrameFrequency() == 0) ? kMaxTimeInterval : kMaxTimeInterval * frame.multi_rate;
  if (cur_frame_time - last_frame_time > diff) {
    printf("Time between last frame and cur frame is: %u us\n", (cur_frame_time - last_frame_time));
  }
  last_frame_time = cur_frame_time;
#ifndef SPEC_LIDAR
  if (frame.fParam.IsMultiFrameFrequency() == 0) {
    printf("%ld -> frame:%d points:%u packet:%u start time:%lf end time:%lf\n", GetMicroTimeU64(), frame.frame_index, frame.points_num, frame.packet_num, frame.frame_start_timestamp, frame.frame_end_timestamp);
  } else {
    printf("%ld -> frame:%d points:%u packet:%u start time:%lf end time:%lf\n", GetMicroTimeU64(), frame.multi_frame_index, frame.multi_points_num, frame.multi_packet_num, frame.multi_frame_start_timestamp, frame.multi_frame_end_timestamp);
  }
#endif
}

void faultMessageCallback(const FaultMessageInfo& fault_message_info) {
  // Use fault message messages to make some judgments
  // fault_message_info.Print();
  return;
}

// Determines whether the PCAP is finished playing
bool IsPlayEnded(HesaiLidarSdk<TestPointType>& sdk)
{
  return sdk.lidar_ptr_->IsPlayEnded();
}

static void PrintUsage(const char* prog) {
  fprintf(stderr, "Usage: %s <config.ini> [use_gpu]\n", prog);
  fprintf(stderr, "  config.ini  - INI configuration file (required)\n");
  fprintf(stderr, "  use_gpu     - 1 to enable GPU acceleration (optional)\n");
  fprintf(stderr, "\nExample:\n");
  fprintf(stderr, "  %s sample_config.ini\n", prog);
  fprintf(stderr, "  %s sample_config.ini 1\n", prog);
}

static void PrintPacketLossReport(HesaiLidarSdk<TestPointType>& sample, uint64_t elapsed_ms) {
  printf("\n========== Packet Loss Report ==========\n");
  printf("Total receive time: %lums\n", elapsed_ms);
  
  uint32_t total_packet_count = sample.lidar_ptr_->GetGeneralParser()->seqnum_loss_message_.total_packet_count;
  uint32_t total_packet_loss_count = sample.lidar_ptr_->GetGeneralParser()->seqnum_loss_message_.total_loss_count;
  
  printf("Total received packet count: %u\n", total_packet_count);
  printf("\n[Sequence Number Loss]\n");
  printf("  Total loss count: %u\n", total_packet_loss_count);
  if (total_packet_count > 0 && float(total_packet_loss_count) / float(total_packet_count) > 0.01) {
    printf("  ERROR: Packet seqnum loss rate exceeds 1%%\n");
  }
  
  uint32_t total_packet_timeloss_count = sample.lidar_ptr_->GetGeneralParser()->time_loss_message_.total_timeloss_count;
  printf("\n[Timestamp Loss]\n");
  printf("  Total loss count: %u\n", total_packet_timeloss_count);
  if (total_packet_count > 0 && float(total_packet_timeloss_count) / float(total_packet_count) > 0.01) {
    printf("  ERROR: Packet timestamp loss rate exceeds 1%%\n");
  }
  printf("=========================================\n");
}

int main(int argc, char *argv[])
{
#ifndef _MSC_VER
  if (system("sudo sh -c \"echo 562144000 > /proc/sys/net/core/rmem_max\"") == -1) {
    printf("Command execution failed!\n");
  }
#endif
  HesaiLidarSdk<TestPointType> sample;
  DriverParam param;

  if (argc < 2) {
    PrintUsage(argv[0]);
    return 1;
  }

  std::ifstream probe(argv[1]);
  if (!probe.good()) {
    fprintf(stderr, "[sample] error: config file not found: %s\n", argv[1]);
    PrintUsage(argv[0]);
    return 1;
  }
  probe.close();

  std::unordered_map<std::string, std::string> kv;
  std::string err;
  if (!hesai::lidar::sample_config::LoadIniMap(argv[1], &kv, &err)) {
    fprintf(stderr, "[sample] config error: %s\n", err.c_str());
    return 1;
  }
  if (!hesai::lidar::sample_config::MergeSourceTypeProfileIntoInput(&kv, &err)) {
    fprintf(stderr, "[sample] config error: %s\n", err.c_str());
    return 1;
  }
  if (!hesai::lidar::sample_config::ApplyToDriverParam(kv, "", &param, &err)) {
    fprintf(stderr, "[sample] config error: %s\n", err.c_str());
    return 1;
  }

  // Parse packet_loss.run_time (in seconds, 0 means disabled)
  float packet_loss_run_time = 0.0f;
  if (const std::string* v = hesai::lidar::sample_config::Get(kv, "packet_loss.run_time")) {
    try {
      packet_loss_run_time = std::stof(*v);
    } catch (...) {
      fprintf(stderr, "[sample] packet_loss.run_time invalid\n");
      return 1;
    }
  }

  if (argc >= 3 && std::string(argv[2]) == "1") {
    param.use_gpu = true;
  }

  printf("[sample] loaded config: %s, use %s\n", argv[1], param.use_gpu ? "gpu" : "cpu");

  if (param.decoder_param.socket_buffer_size == 0) {
    param.decoder_param.socket_buffer_size = 262144000;
  }

  sample.Init(param);
  sample.RegRecvCallback(lidarCallback);
  sample.RegRecvCallback(faultMessageCallback);

  sample.Start();
  if (sample.lidar_ptr_->GetInitFinish(FailInit)) {
    sample.Stop();
    return -1;
  }

  uint64_t start_time = GetMicroTickCountU64();

  if (param.decoder_param.enable_packet_loss_tool && packet_loss_run_time > 0) {
    printf("[sample] packet loss tool enabled, running for %.1f seconds...\n", packet_loss_run_time);
    uint64_t run_time_us = static_cast<uint64_t>(packet_loss_run_time * 1000000);
    while (true) {
      uint64_t now = GetMicroTickCountU64();
      if (now <= start_time) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        continue;
      }
      if (now - start_time >= run_time_us) {
        break;
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    sample.onRelease();
    uint64_t end_time = GetMicroTickCountU64();
    PrintPacketLossReport(sample, (end_time - start_time) / 1000);
  } else {
    while (!IsPlayEnded(sample) || GetMicroTickCount() - last_frame_time < 1000000) {
      std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1000));
    printf("The PCAP file has been parsed and we will exit the program.\n");
  }

  sample.Stop();
  return 0;
}
