/**
 * pcd2gridmap — 3D PCD 点云地图 → 2D 栅格地图 (PGM + YAML)
 *
 * 管线:
 *   1. RANSAC 地面分割 (SACMODEL_PLANE)
 *   2. 高度滤波 (距地面平面距离 ∈ [min_h, max_h])
 *   3. 半径离群点去除
 *   4. 投影到 2D OccupancyGrid → 写 PGM + YAML
 *
 * 编译: mkdir build && cd build && cmake .. && make
 * 用法: ./pcd2gridmap <input.pcd> [output_prefix] [options]
 */

#include <iostream>
#include <fstream>
#include <string>
#include <cmath>
#include <limits>
#include <vector>
#include <cstring>
#include <getopt.h>

#include <pcl/io/pcd_io.h>
#include <pcl/point_types.h>
#include <pcl/filters/extract_indices.h>
#include <pcl/segmentation/sac_segmentation.h>
#include <pcl/filters/radius_outlier_removal.h>
#include <pcl/common/common.h>

// ---- 默认参数 ----
struct Params {
    std::string  input_pcd;
    std::string  output_prefix  = "map";
    double       resolution      = 0.05;    // m/pixel
    double       ransac_dist     = 0.15;    // RANSAC 平面距离阈值
    double       height_min      = 0.1;     // 距地面最小高度 (m)
    double       height_max      = 1.0;     // 距地面最大高度 (m)
    double       radius_search   = 0.1;     // 离群点搜索半径 (m)
    int          min_neighbors   = 10;      // 最小邻居数
    bool         no_ground_filter = false;  // 跳过地面分割
    bool         verbose         = false;
};

// ---- PGM 写入 ----
// P5 格式: 二进制灰度图。值 0=空闲(白), 100=占据(黑) → 映射到 0..255
void write_pgm(const std::string &path,
               const std::vector<int8_t> &data,
               int width, int height)
{
    std::ofstream f(path, std::ios::binary);
    if (!f) {
        std::cerr << "ERROR: Cannot write " << path << "\n";
        return;
    }
    f << "P5\n" << width << " " << height << "\n255\n";

    // data uses ROS map indexing: row 0 is the south/bottom of the map.
    // PGM uses image indexing: row 0 is the north/top of the image.
    // Reverse rows here so map_server and the planner's PGM adapter recover
    // the original ROS y direction instead of mirroring the map vertically.
    for (int image_row = 0; image_row < height; ++image_row) {
        const int map_row = height - 1 - image_row;
        for (int col = 0; col < width; ++col) {
            const int8_t cell = data[map_row * width + col];
            uint8_t v;
            if (cell == 100)       v = 0;    // 占据 → 黑
            else if (cell == 0)    v = 254;  // 空闲 → 白
            else                   v = 205;  // 未知 → 灰
            f.write(reinterpret_cast<const char*>(&v), 1);
        }
    }
    std::cout << "Saved: " << path << " (" << width << "x" << height << ")\n";
}

// ---- YAML 写入 ----
void write_yaml(const std::string &path,
                const std::string &image_file,
                double resolution,
                double origin_x, double origin_y,
                bool negate = false)
{
    std::ofstream f(path);
    if (!f) {
        std::cerr << "ERROR: Cannot write " << path << "\n";
        return;
    }
    f << "image: " << image_file << "\n"
      << "mode: trinary\n"
      << "resolution: " << resolution << "\n"
      << "origin: [" << origin_x << ", " << origin_y << ", 0.0]\n"
      << "negate: " << (negate ? 1 : 0) << "\n"
      << "occupied_thresh: 0.65\n"
      << "free_thresh: 0.196\n";
    std::cout << "Saved: " << path << "\n";
}

// ---- 使用说明 ----
void usage(const char *prog) {
    std::cout <<
        "Usage: " << prog << " <input.pcd> [options]\n"
        "\n"
        "Options:\n"
        "  -o, --output PREFIX     Output prefix (default: map)\n"
        "  -r, --resolution VAL    Map resolution m/pixel (default: 0.05)\n"
        "  --ransac-dist VAL       RANSAC plane distance threshold (default: 0.15)\n"
        "  --height-min VAL        Min height above ground in m (default: 0.1)\n"
        "  --height-max VAL        Max height above ground in m (default: 1.0)\n"
        "  --radius-search VAL     Radius outlier search radius (default: 0.1)\n"
        "  --min-neighbors VAL     Min neighbors for radius filter (default: 10)\n"
        "  --no-ground-filter      Skip RANSAC ground segmentation\n"
        "  -v, --verbose           Verbose output\n"
        "  -h, --help              Show this help\n"
        "\n"
        "Example:\n"
        "  " << prog << " GlobalMap.pcd -o my_map -r 0.05\n"
        "  → my_map.pgm + my_map.yaml\n";
}

// ---- 参数解析 ----
bool parse_args(int argc, char **argv, Params &p) {
    if (argc < 2) return false;
    p.input_pcd = argv[1];

    static struct option long_opts[] = {
        {"output",           required_argument, 0, 'o'},
        {"resolution",       required_argument, 0, 'r'},
        {"ransac-dist",      required_argument, 0, 1000},
        {"height-min",       required_argument, 0, 1001},
        {"height-max",       required_argument, 0, 1002},
        {"radius-search",    required_argument, 0, 1003},
        {"min-neighbors",    required_argument, 0, 1004},
        {"no-ground-filter", no_argument,       0, 1005},
        {"verbose",          no_argument,       0, 'v'},
        {"help",             no_argument,       0, 'h'},
        {0, 0, 0, 0}
    };

    int c;
    while ((c = getopt_long(argc, argv, "o:r:vh", long_opts, nullptr)) != -1) {
        switch (c) {
        case 'o': p.output_prefix    = optarg;       break;
        case 'r': p.resolution       = atof(optarg); break;
        case 1000: p.ransac_dist     = atof(optarg); break;
        case 1001: p.height_min      = atof(optarg); break;
        case 1002: p.height_max      = atof(optarg); break;
        case 1003: p.radius_search   = atof(optarg); break;
        case 1004: p.min_neighbors   = atoi(optarg); break;
        case 1005: p.no_ground_filter = true;        break;
        case 'v': p.verbose          = true;         break;
        case 'h': usage(argv[0]);    return false;
        default:  return false;
        }
    }
    return true;
}

// ================================================================
// 主流程
// ================================================================
int main(int argc, char **argv) {
    Params p;
    if (!parse_args(argc, argv, p)) { usage(argv[0]); return 1; }

    // ---------- 1. 加载 PCD ----------
    pcl::PointCloud<pcl::PointXYZ>::Ptr cloud(new pcl::PointCloud<pcl::PointXYZ>);
    if (pcl::io::loadPCDFile(p.input_pcd, *cloud) == -1) {
        std::cerr << "ERROR: Failed to load " << p.input_pcd << "\n";
        return 1;
    }
    std::cout << "Loaded " << cloud->size() << " points from " << p.input_pcd << "\n";

    pcl::PointCloud<pcl::PointXYZ>::Ptr work_cloud(new pcl::PointCloud<pcl::PointXYZ>);

    // ---------- 2. 地面分割 (RANSAC) ----------
    pcl::ModelCoefficients::Ptr plane_coeff(new pcl::ModelCoefficients);
    float a = 0, b = 0, c = 1, d_norm = 0;  // 默认水平面
    float norm_factor = 1.0f;

    if (!p.no_ground_filter) {
        pcl::PointIndices::Ptr inliers(new pcl::PointIndices);
        pcl::SACSegmentation<pcl::PointXYZ> seg;
        seg.setOptimizeCoefficients(true);
        seg.setModelType(pcl::SACMODEL_PLANE);
        seg.setMethodType(pcl::SAC_RANSAC);
        seg.setMaxIterations(1000);
        seg.setDistanceThreshold(p.ransac_dist);
        seg.setInputCloud(cloud);
        seg.segment(*inliers, *plane_coeff);

        if (inliers->indices.empty()) {
            std::cout << "WARNING: No ground plane found, using all points\n";
            *work_cloud = *cloud;
        } else {
            a = plane_coeff->values[0];
            b = plane_coeff->values[1];
            c = plane_coeff->values[2];
            d_norm = plane_coeff->values[3];
            norm_factor = std::sqrt(a*a + b*b + c*c);

            std::cout << "Ground plane: " << a << "x + " << b << "y + "
                      << c << "z + " << d_norm << " = 0\n";
            std::cout << "Ground inliers: " << inliers->indices.size() << " points\n";

            // 提取非地面点
            pcl::ExtractIndices<pcl::PointXYZ> extract;
            extract.setInputCloud(cloud);
            extract.setIndices(inliers);
            extract.setNegative(true);   // 取非地面
            extract.filter(*work_cloud);
        }
    } else {
        *work_cloud = *cloud;
    }
    std::cout << "After ground removal: " << work_cloud->size() << " points\n";

    // ---------- 3. 高度滤波 (距地面垂直距离) ----------
    pcl::PointCloud<pcl::PointXYZ>::Ptr height_cloud(new pcl::PointCloud<pcl::PointXYZ>);
    for (const auto &pt : work_cloud->points) {
        float dist = std::abs(a*pt.x + b*pt.y + c*pt.z + d_norm) / norm_factor;
        if (dist >= p.height_min && dist <= p.height_max) {
            height_cloud->push_back(pt);
        }
    }
    std::cout << "After height filter [" << p.height_min << ", "
              << p.height_max << "m]: " << height_cloud->size() << " points\n";

    if (height_cloud->empty()) {
        std::cerr << "ERROR: No points remain after height filter!\n";
        return 1;
    }

    // 保存中间结果（调试用）
    if (p.verbose) {
        pcl::io::savePCDFile(p.output_prefix + "_height_filtered.pcd", *height_cloud);
    }

    // ---------- 4. 半径离群点去除 ----------
    pcl::PointCloud<pcl::PointXYZ>::Ptr clean_cloud(new pcl::PointCloud<pcl::PointXYZ>);
    pcl::RadiusOutlierRemoval<pcl::PointXYZ> ror;
    ror.setInputCloud(height_cloud);
    ror.setRadiusSearch(p.radius_search);
    ror.setMinNeighborsInRadius(p.min_neighbors);
    ror.filter(*clean_cloud);
    std::cout << "After radius filter (r=" << p.radius_search
              << ", min=" << p.min_neighbors << "): "
              << clean_cloud->size() << " points\n";

    if (clean_cloud->empty()) {
        std::cerr << "ERROR: No points remain after radius filter!\n";
        return 1;
    }

    if (p.verbose) {
        pcl::io::savePCDFile(p.output_prefix + "_radius_filtered.pcd", *clean_cloud);
    }

    // ---------- 5. 投影到 2D 栅格 ----------
    // 计算边界
    double x_min =  std::numeric_limits<double>::max();
    double x_max = -std::numeric_limits<double>::max();
    double y_min =  std::numeric_limits<double>::max();
    double y_max = -std::numeric_limits<double>::max();
    for (const auto &pt : clean_cloud->points) {
        if (pt.x < x_min) x_min = pt.x;
        if (pt.x > x_max) x_max = pt.x;
        if (pt.y < y_min) y_min = pt.y;
        if (pt.y > y_max) y_max = pt.y;
    }
    // 稍微扩展边界
    double margin = p.resolution * 5;
    x_min -= margin; x_max += margin;
    y_min -= margin; y_max += margin;

    int width  = static_cast<int>(std::ceil((x_max - x_min) / p.resolution));
    int height = static_cast<int>(std::ceil((y_max - y_min) / p.resolution));

    std::cout << "Map bounds: x=[" << x_min << ", " << x_max
              << "] y=[" << y_min << ", " << y_max
              << "]  →  " << width << "x" << height << " cells\n";

    // 初始化 → 全空闲 (0)
    std::vector<int8_t> grid(width * height, 0);

    // 投影：点落入的格子标为占据
    for (const auto &pt : clean_cloud->points) {
        int col = static_cast<int>((pt.x - x_min) / p.resolution);
        int row = static_cast<int>((pt.y - y_min) / p.resolution);
        if (col >= 0 && col < width && row >= 0 && row < height) {
            grid[row * width + col] = 100;
        }
    }

    int occupied = 0;
    for (auto v : grid) if (v == 100) occupied++;
    std::cout << "Occupied cells: " << occupied << " / " << grid.size()
              << " (" << (100.0 * occupied / grid.size()) << "%)\n";

    // ---------- 6. 写入 PGM + YAML ----------
    std::string pgm_file = p.output_prefix + ".pgm";
    std::string yaml_file = p.output_prefix + ".yaml";

    // 提取 pgm 文件名（不含路径），map_server 需要相对路径
    std::string pgm_basename = pgm_file;
    size_t slash_pos = pgm_file.find_last_of("/\\");
    if (slash_pos != std::string::npos)
        pgm_basename = pgm_file.substr(slash_pos + 1);

    write_pgm(pgm_file, grid, width, height);
    write_yaml(yaml_file, pgm_basename, p.resolution, x_min, y_min);

    std::cout << "\nDone! Output: " << pgm_file << " + " << yaml_file << "\n";
    return 0;
}
