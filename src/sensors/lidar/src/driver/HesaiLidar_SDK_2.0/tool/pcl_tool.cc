#define NOMINMAX
#include "hesai_lidar_sdk.hpp"
#include "../config/driver_sample_config.hpp"

#include <cstring>
#include <fstream>
#include <string>
#include <unordered_map>
#include <ctime>
#include <sys/stat.h>
#ifdef _WIN32
#include <direct.h>
#define MKDIR(path) _mkdir(path)
#else
#define MKDIR(path) mkdir(path, 0755)
#endif

#define PCL_NO_PRECOMPILE
#include <pcl/point_types.h>
#include <pcl/visualization/pcl_visualizer.h>
#include <pcl/io/pcd_io.h>
#include <pcl/io/ply_io.h>

/* ------------Select the fields to be exported ------------ */
#define ENABLE_TIMESTAMP
#define ENABLE_RING
#define ENABLE_INTENSITY
// #define ENABLE_CONFIDENCE
// #define ENABLE_WEIGHT_FACTOR
// #define ENABLE_ENV_LIGHT

#ifdef ENABLE_TIMESTAMP
  #define TIMESTAMP_PCL_STR  (double, timestamp, timestamp)
#else
  #define TIMESTAMP_PCL_STR
#endif
#ifdef ENABLE_RING
  #define RING_PCL_STR  (std::uint16_t, ring, ring)
#else
  #define RING_PCL_STR
#endif
#ifdef ENABLE_INTENSITY
  #define INTENSITY_PCL_STR  (std::uint8_t, intensity, intensity)
#else
  #define INTENSITY_PCL_STR
#endif
#ifdef ENABLE_CONFIDENCE
  #define CONFIDENCE_PCL_STR  (std::uint8_t, confidence, confidence)
#else
  #define CONFIDENCE_PCL_STR
#endif
#ifdef ENABLE_WEIGHT_FACTOR
  #define WEIGHT_FACTOR_PCL_STR  (std::uint8_t, weightFactor, weightFactor)
#else
  #define WEIGHT_FACTOR_PCL_STR
#endif
#ifdef ENABLE_ENV_LIGHT
  #define ENV_LIGHT_PCL_STR  (std::uint8_t, envLight, envLight)
#else
  #define ENV_LIGHT_PCL_STR
#endif
struct PointXYZIT {
  PCL_ADD_POINT4D   
#ifdef ENABLE_TIMESTAMP
  double timestamp;
#endif
#ifdef ENABLE_RING
  uint16_t ring;                   
#endif
#ifdef ENABLE_INTENSITY
  uint8_t intensity;
#endif
#ifdef ENABLE_CONFIDENCE
  uint8_t confidence;
#endif
#ifdef ENABLE_WEIGHT_FACTOR
  uint8_t weightFactor;
#endif
#ifdef ENABLE_ENV_LIGHT
  uint8_t envLight;
#endif
  EIGEN_MAKE_ALIGNED_OPERATOR_NEW  
} EIGEN_ALIGN16;                   

POINT_CLOUD_REGISTER_POINT_STRUCT(
    PointXYZIT,
    (float, x, x)(float, y, y)(float, z, z)
    TIMESTAMP_PCL_STR
    RING_PCL_STR
    INTENSITY_PCL_STR
    CONFIDENCE_PCL_STR
    WEIGHT_FACTOR_PCL_STR
    ENV_LIGHT_PCL_STR
)


#ifndef SPEC_LIDAR
using ToolPointType = PointXYZIT;
using PclPointType = PointXYZIT;
#endif

using namespace pcl::visualization;
std::shared_ptr<PCLVisualizer> pcl_viewer;
std::mutex mex_viewer;
uint32_t last_frame_time;
uint32_t cur_frame_time;

namespace {
using PclOpts = hesai::lidar::sample_config::PclToolRuntimeOptions;
PclOpts g_pcl_opts;
std::string g_output_dir;
}  // namespace


#ifndef SPEC_LIDAR
static bool IsValidPointXyzit(const PointXYZIT& pt) {
  return (pt.x != 0.0f || pt.y != 0.0f || pt.z != 0.0f);
}

//log info, display frame message
void lidarCallback(const LidarDecodedFrame<PointXYZIT>  &frame) {  
  cur_frame_time = GetMicroTickCount();
  if (cur_frame_time - last_frame_time > kMaxTimeInterval) {
    printf("Time between last frame and cur frame is: %u us\n", (cur_frame_time - last_frame_time));
  }
  last_frame_time = cur_frame_time;
  printf("frame:%d points:%u packet:%u start time:%lf end time:%lf\n",frame.frame_index, frame.points_num, frame.packet_num, frame.frame_start_timestamp, frame.frame_end_timestamp);  
  pcl::PointCloud<PointXYZIT>::Ptr pcl_pointcloud(new pcl::PointCloud<PointXYZIT>);
  if (frame.points_num == 0) return;
  mex_viewer.lock();
  pcl_pointcloud->clear();
  if (g_pcl_opts.save_valid_points_only) {
    pcl_pointcloud->reserve(frame.points_num);
    for (uint32_t i = 0; i < frame.points_num; ++i) {
      if (IsValidPointXyzit(frame.points[i])) {
        pcl_pointcloud->push_back(frame.points[i]);
      }
    }
  } else {
    pcl_pointcloud->resize(frame.points_num);
    pcl_pointcloud->points.assign(frame.points, frame.points + frame.points_num);
  }
  pcl_pointcloud->height = 1;
  pcl_pointcloud->width = static_cast<uint32_t>(pcl_pointcloud->size());
  pcl_pointcloud->is_dense = g_pcl_opts.save_valid_points_only;

  std::string file_name1 = g_output_dir + "/PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_start_timestamp)+ ".pcd";
  std::string file_name2 = g_output_dir + "/PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_start_timestamp)+ "_bin.pcd";
  std::string file_name3 = g_output_dir + "/PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_start_timestamp)+ ".ply";
  std::string file_name4 = g_output_dir + "/PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_start_timestamp)+ "_bin_compress" + ".pcd";
  if (g_pcl_opts.save_pcd_ascii) {
    pcl::PCDWriter writer;
    writer.writeASCII(file_name1, *pcl_pointcloud, g_pcl_opts.pcd_ascii_precision);
  }
  if (g_pcl_opts.save_pcd_binary) {
    pcl::io::savePCDFileBinary(file_name2, *pcl_pointcloud);
  }
  if (g_pcl_opts.save_pcd_binary_compressed) {
    pcl::io::savePCDFileBinaryCompressed(file_name4, *pcl_pointcloud);
  }
  if (g_pcl_opts.save_ply) {
    pcl::PLYWriter writer1;
    writer1.write(file_name3, *pcl_pointcloud, true);
  }
  if (g_pcl_opts.enable_viewer) {
    PointCloudColorHandlerGenericField<PointXYZIT> point_color_handle(pcl_pointcloud, "intensity");
    pcl_viewer->updatePointCloud<PointXYZIT>(pcl_pointcloud, point_color_handle, "pandar");
  }
mex_viewer.unlock();
}

void PclViewerInitXyzit(std::shared_ptr<PCLVisualizer>& pcl_viewer) {
  pcl_viewer = std::make_shared<PCLVisualizer>("HesaiPointCloudViewer");
  pcl_viewer->setBackgroundColor(0.0, 0.0, 0.0);
  pcl_viewer->addCoordinateSystem(1.0);
  pcl::PointCloud<PointXYZIT>::Ptr pcl_pointcloud(new pcl::PointCloud<PointXYZIT>);
  pcl_viewer->addPointCloud<PointXYZIT>(pcl_pointcloud, "pandar");
  pcl_viewer->setPointCloudRenderingProperties(PCL_VISUALIZER_POINT_SIZE, 2, "pandar");
}
#endif


static void PrintUsage(const char* prog) {
  fprintf(stderr, "Usage: %s <config.ini> [use_gpu]\n", prog);
  fprintf(stderr, "  config.ini  - INI configuration file (required)\n");
  fprintf(stderr, "  use_gpu     - 1 to enable GPU acceleration (optional)\n");
  fprintf(stderr, "\nExample:\n");
  fprintf(stderr, "  %s tool_sample_config.ini\n", prog);
  fprintf(stderr, "  %s tool_sample_config.ini 1\n", prog);
}

int main(int argc, char *argv[])
{
  HesaiLidarSdk<ToolPointType> sample;
  DriverParam param;

  if (argc < 2) {
    PrintUsage(argv[0]);
    return 1;
  }

  std::ifstream probe(argv[1]);
  if (!probe.good()) {
    fprintf(stderr, "[pcl_tool] error: config file not found: %s\n", argv[1]);
    PrintUsage(argv[0]);
    return 1;
  }
  probe.close();

  std::string err;
  std::unordered_map<std::string, std::string> kv;
  if (!hesai::lidar::sample_config::LoadIniMap(argv[1], &kv, &err)) {
    fprintf(stderr, "[pcl_tool] config error: %s\n", err.c_str());
    return 1;
  }
  if (!hesai::lidar::sample_config::PreprocessDriverSampleIniMap(&kv, &err)) {
    fprintf(stderr, "[pcl_tool] config error: %s\n", err.c_str());
    return 1;
  }
  if (!hesai::lidar::sample_config::ApplyToDriverParam(kv, "", &param, &err)) {
    fprintf(stderr, "[pcl_tool] config error: %s\n", err.c_str());
    return 1;
  }
  if (!hesai::lidar::sample_config::ApplyPclToolOptions(kv, &g_pcl_opts, &err)) {
    fprintf(stderr, "[pcl_tool] pcl section error: %s\n", err.c_str());
    return 1;
  }
  if (argc >= 3 && std::string(argv[2]) == "1") {
    param.use_gpu = true;
  }
  printf("[pcl_tool] loaded config: %s\n", argv[1]);

  g_output_dir = g_pcl_opts.output_dir;
  if (g_pcl_opts.output_dir_with_timestamp) {
    std::time_t now = std::time(nullptr);
    std::tm* tm_now = std::localtime(&now);
    char time_suffix[32];
    std::strftime(time_suffix, sizeof(time_suffix), "_%Y-%m-%d_%H-%M-%S", tm_now);
    g_output_dir += time_suffix;
  }
  if (MKDIR(g_output_dir.c_str()) == 0) {
    printf("[pcl_tool] created output directory: %s\n", g_output_dir.c_str());
  } else {
    struct stat st;
    if (stat(g_output_dir.c_str(), &st) == 0 && (st.st_mode & S_IFDIR)) {
      printf("[pcl_tool] output directory exists: %s\n", g_output_dir.c_str());
    } else {
      fprintf(stderr, "[pcl_tool] warning: failed to create output directory: %s\n", g_output_dir.c_str());
    }
  }

  if (g_pcl_opts.enable_viewer) {
#ifndef SPEC_LIDAR
    PclViewerInitXyzit(pcl_viewer);
#endif
  }

  param.decoder_param.enable_packet_loss_tool = false;
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

  while (1)
  {
    if (g_pcl_opts.enable_viewer) {
      mex_viewer.lock();
      if (pcl_viewer->wasStopped()) break;
      pcl_viewer->spinOnce();
      mex_viewer.unlock();
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(40));
  }
  return 0;
}
