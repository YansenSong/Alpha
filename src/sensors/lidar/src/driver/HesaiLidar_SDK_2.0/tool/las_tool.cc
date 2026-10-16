#include "hesai_lidar_sdk.hpp"
#include "../config/driver_sample_config.hpp"

#include <cstring>
#include <fstream>
#include <string>
#include <unordered_map>
#include <cfloat>
#include <ctime>
#include <sys/stat.h>
#ifdef _WIN32
#include <direct.h>
#define MKDIR(path) _mkdir(path)
#else
#define MKDIR(path) mkdir(path, 0755)
#endif

#include "lasreader.hpp"
#include "laswriter.hpp"

#ifndef SPEC_LIDAR
using ToolPointType = LidarPointXYZIRT;
#endif

std::mutex mex_viewer;
uint32_t last_frame_time = 0;
uint32_t cur_frame_time = 0;

namespace {
struct LasToolOptions {
  bool save_las = false;
  bool save_laz = true;
  std::string output_dir = "out_las";
  bool output_dir_with_timestamp = false;
};
LasToolOptions g_las_opts;
std::string g_output_dir;
}  // namespace

void lidarCallback(const LidarDecodedFrame<ToolPointType>& frame) {
  cur_frame_time = GetMicroTickCount();
  if (last_frame_time == 0) last_frame_time = GetMicroTickCount();
  if (cur_frame_time - last_frame_time > kMaxTimeInterval) {
    printf("Time between last frame and cur frame is: %u us\n", (cur_frame_time - last_frame_time));
  }
  last_frame_time = cur_frame_time;
  printf("frame:%d points:%u packet:%u start time:%lf end time:%lf\n",
         frame.frame_index, frame.points_num, frame.packet_num,
         frame.frame_start_timestamp, frame.frame_end_timestamp);

  if (!g_las_opts.save_las && !g_las_opts.save_laz) return;
  if (frame.points_num == 0) return;

  mex_viewer.lock();

  LASwriteOpener laswriteropener;
  std::string file_name_las = g_output_dir + "/PointCloudFrame" + std::to_string(frame.frame_index) + "_" +
                               std::to_string(frame.frame_start_timestamp) + ".las";
  std::string file_name_laz = g_output_dir + "/PointCloudFrame" + std::to_string(frame.frame_index) + "_" +
                               std::to_string(frame.frame_start_timestamp) + ".laz";

  const char* las_name = g_las_opts.save_laz ? file_name_laz.c_str() : file_name_las.c_str();
  laswriteropener.set_file_name(las_name);

  std::time_t t = std::time(nullptr);
  std::tm* now = std::localtime(&t);
  uint16_t las_year = now->tm_year + 1900;
  uint16_t las_day = now->tm_mday;

  LASheader header;
  header.point_data_format = 1;
  header.point_data_record_length = 28;
  header.number_of_point_records = frame.points_num;
  header.file_creation_day = las_day;
  header.file_creation_year = las_year;
  strcpy(header.generating_software, "Hesai SDK");

  header.x_scale_factor = 0.00001;
  header.y_scale_factor = 0.00001;
  header.z_scale_factor = 0.00001;

  LASwriter* laswriter = laswriteropener.open(&header);

  LASpoint point;
  point.init(&header, header.point_data_format, header.point_data_record_length, &header);

  double max_x = -DBL_MAX, max_y = -DBL_MAX, max_z = -DBL_MAX;
  double min_x = DBL_MAX, min_y = DBL_MAX, min_z = DBL_MAX;

  for (uint32_t i = 0; i < frame.points_num; i++) {
    double las_x = frame.points[i].x * 10000;
    double las_y = frame.points[i].y * 10000;
    double las_z = frame.points[i].z * 10000;
#ifndef SPEC_LIDAR
    uint16_t las_intensity = frame.points[i].intensity;
    double las_time = frame.points[i].timestamp;
    uint16_t las_ring = frame.points[i].ring;
#endif

    point.set_x(las_x);
    point.set_y(las_y);
    point.set_z(las_z);
    point.set_intensity(las_intensity);
    point.set_point_source_ID(las_ring);

    if (las_x > max_x) max_x = las_x;
    if (las_x < min_x) min_x = las_x;
    if (las_y > max_y) max_y = las_y;
    if (las_y < min_y) min_y = las_y;
    if (las_z > max_z) max_z = las_z;
    if (las_z < min_z) min_z = las_z;

    point.set_gps_time(las_time);
    laswriter->write_point(&point);
    laswriter->update_inventory(&point);
  }

  header.set_bounding_box(min_x, min_y, min_z, max_x, max_y, max_z);
  laswriter->update_header(&header, TRUE);
  laswriter->close();
  delete laswriter;

  mex_viewer.unlock();
}

bool IsPlayEnded(HesaiLidarSdk<ToolPointType>& sdk) {
  return sdk.lidar_ptr_->IsPlayEnded();
}

static void PrintUsage(const char* prog) {
  fprintf(stderr, "Usage: %s <config.ini> [use_gpu]\n", prog);
  fprintf(stderr, "  config.ini  - INI configuration file (required)\n");
  fprintf(stderr, "  use_gpu     - 1 to enable GPU acceleration (optional)\n");
  fprintf(stderr, "\nExample:\n");
  fprintf(stderr, "  %s tool_sample_config.ini\n", prog);
  fprintf(stderr, "  %s tool_sample_config.ini 1\n", prog);
}

int main(int argc, char* argv[]) {
#ifndef SPEC_LIDAR
  HesaiLidarSdk<LidarPointXYZIRT> sample;
#endif
  DriverParam param;

  if (argc < 2) {
    PrintUsage(argv[0]);
    return 1;
  }

  std::ifstream probe(argv[1]);
  if (!probe.good()) {
    fprintf(stderr, "[las_tool] error: config file not found: %s\n", argv[1]);
    PrintUsage(argv[0]);
    return 1;
  }
  probe.close();

  std::string err;
  std::unordered_map<std::string, std::string> kv;
  if (!hesai::lidar::sample_config::LoadIniMap(argv[1], &kv, &err)) {
    fprintf(stderr, "[las_tool] config error: %s\n", err.c_str());
    return 1;
  }
  if (!hesai::lidar::sample_config::PreprocessDriverSampleIniMap(&kv, &err)) {
    fprintf(stderr, "[las_tool] config error: %s\n", err.c_str());
    return 1;
  }
  if (!hesai::lidar::sample_config::ApplyToDriverParam(kv, "", &param, &err)) {
    fprintf(stderr, "[las_tool] config error: %s\n", err.c_str());
    return 1;
  }

  // Parse [las] section
  if (const std::string* v = hesai::lidar::sample_config::Get(kv, "las.save_las")) {
    hesai::lidar::sample_config::ParseBool(*v, &g_las_opts.save_las);
  }
  if (const std::string* v = hesai::lidar::sample_config::Get(kv, "las.save_laz")) {
    hesai::lidar::sample_config::ParseBool(*v, &g_las_opts.save_laz);
  }
  if (const std::string* v = hesai::lidar::sample_config::Get(kv, "las.output_dir")) {
    g_las_opts.output_dir = hesai::lidar::sample_config::Trim(*v);
    if (g_las_opts.output_dir.empty()) g_las_opts.output_dir = "out_las";
  }
  if (const std::string* v = hesai::lidar::sample_config::Get(kv, "las.output_dir_with_timestamp")) {
    hesai::lidar::sample_config::ParseBool(*v, &g_las_opts.output_dir_with_timestamp);
  }

  if (argc >= 3 && std::string(argv[2]) == "1") {
    param.use_gpu = true;
  }
  printf("[las_tool] loaded config: %s\n", argv[1]);

  g_output_dir = g_las_opts.output_dir;
  if (g_las_opts.output_dir_with_timestamp) {
    std::time_t now = std::time(nullptr);
    std::tm* tm_now = std::localtime(&now);
    char time_suffix[32];
    std::strftime(time_suffix, sizeof(time_suffix), "_%Y-%m-%d_%H-%M-%S", tm_now);
    g_output_dir += time_suffix;
  }
  if (MKDIR(g_output_dir.c_str()) == 0) {
    printf("[las_tool] created output directory: %s\n", g_output_dir.c_str());
  } else {
    struct stat st;
    if (stat(g_output_dir.c_str(), &st) == 0 && (st.st_mode & S_IFDIR)) {
      printf("[las_tool] output directory exists: %s\n", g_output_dir.c_str());
    } else {
      fprintf(stderr, "[las_tool] warning: failed to create output directory: %s\n", g_output_dir.c_str());
    }
  }

  if (param.decoder_param.socket_buffer_size == 0) {
    param.decoder_param.socket_buffer_size = 262144000;
  }

  sample.Init(param);
  sample.RegRecvCallback(lidarCallback);

  last_frame_time = GetMicroTickCount();
  sample.Start();
  if (sample.lidar_ptr_->GetInitFinish(FailInit)) {
    sample.Stop();
    return -1;
  }

  while (!IsPlayEnded(sample) || GetMicroTickCount() - last_frame_time < 1000000) {
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
  }

  std::this_thread::sleep_for(std::chrono::milliseconds(1000));
  printf("The file has been parsed and we will exit the program.\n");
  sample.Stop();
  return 0;
}
