/************************************************************************************************
 * 轻量级 INI 风格配置，供 test/、tool/ 下示例程序加载 DriverParam，无第三方依赖。
 * 单雷达：
 *   - [source_type] source_type=network|pcap|... + 对应 [network]/[pcap]/... 节（等价原 test.cc 互斥宏）
 *   - 或扁平 [input]、[decoder]、[driver]
 * 双雷达 multi_test：仅用 [lidar1]、[lidar2] 前缀键，勿用顶层 [source_type]。
 * pcl_tool：[pcl] 保存与可视化；加载前会 PreprocessDriverSampleIniMap 合并 source_type profile。
 ************************************************************************************************/
#pragma once

#include "driver_param.h"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace hesai {
namespace lidar {
namespace sample_config {

/** pcl_tool 运行时选项（可由 [pcl] 覆盖编译期宏默认值）。 */
struct PclToolRuntimeOptions {
  bool save_pcd_ascii = false;
  bool save_pcd_binary = false;
  bool save_pcd_binary_compressed = false;
  bool save_ply = false;
  bool enable_viewer = false;
  int pcd_ascii_precision = 16;
  std::string output_dir = "out_pcd";
  bool output_dir_with_timestamp = false;
  bool save_valid_points_only = false;  // 只保存有效点（过滤零点）
};

inline std::string Trim(std::string s) {
  auto not_space = [](unsigned char c) { return !std::isspace(c); };
  s.erase(s.begin(), std::find_if(s.begin(), s.end(), not_space));
  s.erase(std::find_if(s.rbegin(), s.rend(), not_space).base(), s.end());
  return s;
}

inline bool ParseBool(const std::string& v, bool* out) {
  std::string t = Trim(v);
  std::transform(t.begin(), t.end(), t.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  if (t == "1" || t == "true" || t == "yes" || t == "on") {
    *out = true;
    return true;
  }
  if (t == "0" || t == "false" || t == "no" || t == "off") {
    *out = false;
    return true;
  }
  return false;
}

inline bool LoadIniMap(const std::string& path, std::unordered_map<std::string, std::string>* kv, std::string* err) {
  std::ifstream in(path);
  if (!in) {
    if (err) *err = "cannot open file: " + path;
    return false;
  }
  std::string line;
  std::string section;
  while (std::getline(in, line)) {
    line = Trim(line);
    if (line.empty() || line[0] == '#' || line[0] == ';') continue;
    if (line.size() >= 2 && line[0] == '[' && line.back() == ']') {
      section = Trim(line.substr(1, line.size() - 2));
      continue;
    }
    size_t eq = line.find('=');
    if (eq == std::string::npos) {
      eq = line.find(':');
    }
    if (eq == std::string::npos) {
      if (err) *err = "invalid line (no = or :): " + line;
      return false;
    }
    std::string key = Trim(line.substr(0, eq));
    std::string val = Trim(line.substr(eq + 1));
    if (!key.empty() && val.size() >= 2 && val.front() == '"' && val.back() == '"') {
      val = val.substr(1, val.size() - 2);
    }
    std::string full = section.empty() ? key : (section + "." + key);
    (*kv)[full] = val;
  }
  return true;
}

inline const std::string* Get(const std::unordered_map<std::string, std::string>& m, const std::string& k) {
  auto it = m.find(k);
  return it == m.end() ? nullptr : &it->second;
}

inline std::string PrefixedKey(const std::string& prefix, const char* key) {
  return prefix.empty() ? std::string(key) : prefix + "." + std::string(key);
}

inline const std::string* GetP(const std::unordered_map<std::string, std::string>& m, const std::string& prefix,
                               const char* key) {
  return Get(m, PrefixedKey(prefix, key));
}

inline std::string ToLowerStr(std::string s) {
  std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return s;
}

/**
 * [source_type] 选择数据场景（对应原 test.cc 中互斥宏的一种）：
 *   network / lidar / online  -> DATA_FROM_LIDAR，并从 [network] 合并到 input.*
 *   pcap / offline            -> DATA_FROM_PCAP，并从 [pcap] 合并
 *   serial                    -> [serial]
 *   ros / external            -> DATA_FROM_ROS_PACKET，并从 [ros] 合并
 *   tcp / lidar_tcp           -> DATA_FROM_LIDAR_TCP，并从 [tcp] 合并
 * 同名键若 [input] 已写则保留 [input]，不覆盖。
 */
inline bool MergeSourceTypeProfileIntoInput(std::unordered_map<std::string, std::string>* kv, std::string* err) {
  const std::string* mode_v = Get(*kv, "source_type.source_type");
  if (!mode_v) mode_v = Get(*kv, "source_type.mode");
  if (!mode_v) return true;

  const std::string mode = ToLowerStr(Trim(*mode_v));
  std::string profile_section;
  std::string input_source_type_token;

  if (mode == "network" || mode == "lidar" || mode == "online") {
    profile_section = "network";
    input_source_type_token = "lidar";
  } else if (mode == "pcap" || mode == "offline") {
    profile_section = "pcap";
    input_source_type_token = "pcap";
  } else if (mode == "serial") {
    profile_section = "serial";
    input_source_type_token = "serial";
  } else if (mode == "ros" || mode == "external") {
    profile_section = "ros";
    input_source_type_token = "ros_packet";
  } else if (mode == "tcp" || mode == "lidar_tcp") {
    profile_section = "tcp";
    input_source_type_token = "lidar_tcp";
  } else {
    if (err) *err = "source_type.source_type / mode unknown: " + *mode_v;
    return false;
  }

  auto merge_section = [&](const std::string& sec) {
    const std::string sec_prefix = sec + ".";
    std::vector<std::pair<std::string, std::string>> adds;
    for (const auto& e : *kv) {
      if (e.first.size() <= sec_prefix.size()) continue;
      if (e.first.compare(0, sec_prefix.size(), sec_prefix) != 0) continue;
      const std::string tail = e.first.substr(sec_prefix.size());
      if (tail.empty()) continue;
      const std::string input_key = "input." + tail;
      if (kv->find(input_key) == kv->end()) {
        adds.emplace_back(input_key, e.second);
      }
    }
    for (const auto& a : adds) {
      (*kv)[a.first] = a.second;
    }
  };

  merge_section(profile_section);
  if (profile_section == "network") {
    merge_section("lidar");
  }

  (*kv)["input.source_type"] = input_source_type_token;
  return true;
}

inline bool ApplyToDriverParam(const std::unordered_map<std::string, std::string>& m, const std::string& key_prefix,
                               DriverParam* p, std::string* err) {
  if (!p) return false;
  if (const std::string* v = GetP(m, key_prefix, "driver.use_gpu")) {
    if (!ParseBool(*v, &p->use_gpu)) {
      if (err) *err = "driver.use_gpu invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, key_prefix, "driver.log_level")) {
    try {
      p->log_level = static_cast<uint8_t>(std::stoul(*v));
    } catch (...) {
      if (err) *err = "driver.log_level invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, key_prefix, "driver.log_path")) p->log_path = *v;

  if (const std::string* v = GetP(m, key_prefix, "input.source_type")) {
    std::string t = *v;
    std::transform(t.begin(), t.end(), t.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (t == "lidar" || t == "data_from_lidar") p->input_param.source_type = DATA_FROM_LIDAR;
    else if (t == "pcap" || t == "data_from_pcap") p->input_param.source_type = DATA_FROM_PCAP;
    else if (t == "ros_packet" || t == "data_from_ros_packet" || t == "external") p->input_param.source_type = DATA_FROM_ROS_PACKET;
    else if (t == "serial" || t == "data_from_serial") p->input_param.source_type = DATA_FROM_SERIAL;
    else if (t == "lidar_tcp" || t == "tcp") p->input_param.source_type = DATA_FROM_LIDAR_TCP;
    else {
      if (err) *err = "input.source_type unknown: " + *v;
      return false;
    }
  }

  auto assign_str = [&](const char* key, std::string* dst) {
    if (const std::string* v = GetP(m, key_prefix, key)) *dst = *v;
  };
  assign_str("input.device_ip_address", &p->input_param.device_ip_address);
  assign_str("input.multicast_ip_address", &p->input_param.multicast_ip_address);
  assign_str("input.host_ip_address", &p->input_param.host_ip_address);
  assign_str("input.pcap_path", &p->input_param.pcap_path);
  assign_str("input.correction_file_path", &p->input_param.correction_file_path);
  assign_str("input.firetimes_path", &p->input_param.firetimes_path);
  assign_str("input.correction_save_path", &p->input_param.correction_save_path);
  assign_str("input.rs485_com", &p->input_param.rs485_com);
  assign_str("input.rs232_com", &p->input_param.rs232_com);
  assign_str("input.certFile", &p->input_param.certFile);
  assign_str("input.privateKeyFile", &p->input_param.privateKeyFile);
  assign_str("input.caFile", &p->input_param.caFile);

  if (const std::string* v = GetP(m, key_prefix, "input.ptc_mode")) {
    std::string t = *v;
    std::transform(t.begin(), t.end(), t.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (t == "tcp" || t == "0") p->input_param.ptc_mode = PtcMode::tcp;
    else if (t == "tcp_ssl" || t == "ssl" || t == "1") p->input_param.ptc_mode = PtcMode::tcp_ssl;
    else {
      if (err) *err = "input.ptc_mode invalid";
      return false;
    }
  }

  auto assign_u16 = [&](const char* key, uint16_t* dst) {
    if (const std::string* v = GetP(m, key_prefix, key)) {
      try {
        *dst = static_cast<uint16_t>(std::stoul(*v));
      } catch (...) {
        if (err) *err = std::string("invalid uint16: ") + key;
        return false;
      }
    }
    return true;
  };
  if (!assign_u16("input.device_tcp_src_port", &p->input_param.device_tcp_src_port)) return false;
  if (!assign_u16("input.device_udp_src_port", &p->input_param.device_udp_src_port)) return false;
  if (!assign_u16("input.device_fault_port", &p->input_param.device_fault_port)) return false;
  if (!assign_u16("input.udp_port", &p->input_param.udp_port)) return false;
  if (!assign_u16("input.fault_message_port", &p->input_param.fault_message_port)) return false;
  if (!assign_u16("input.ptc_port", &p->input_param.ptc_port)) return false;
  if (!assign_u16("input.host_ptc_port", &p->input_param.host_ptc_port)) return false;

  if (const std::string* v = GetP(m, key_prefix, "input.use_ptc_connected")) {
    if (!ParseBool(*v, &p->input_param.use_ptc_connected)) {
      if (err) *err = "input.use_ptc_connected invalid";
      return false;
    }
  }

  if (const std::string* v = GetP(m, key_prefix, "input.point_cloud_baudrate")) {
    try {
      p->input_param.point_cloud_baudrate = std::stoi(*v);
    } catch (...) {
      if (err) *err = "input.point_cloud_baudrate invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, key_prefix, "input.standby_mode")) {
    try {
      p->input_param.standby_mode = std::stoi(*v);
    } catch (...) {
      if (err) *err = "input.standby_mode invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, key_prefix, "input.speed")) {
    try {
      p->input_param.speed = std::stoi(*v);
    } catch (...) {
      if (err) *err = "input.speed invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, key_prefix, "input.recv_point_cloud_timeout")) {
    try {
      p->input_param.recv_point_cloud_timeout = std::stof(*v);
    } catch (...) {
      if (err) *err = "input.recv_point_cloud_timeout invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, key_prefix, "input.ptc_connect_timeout")) {
    try {
      p->input_param.ptc_connect_timeout = std::stof(*v);
    } catch (...) {
      if (err) *err = "input.ptc_connect_timeout invalid";
      return false;
    }
  }


  if (const std::string* v = GetP(m, key_prefix, "decoder.pcap_play_synchronization")) {
    if (!ParseBool(*v, &p->decoder_param.pcap_play_synchronization)) {
      if (err) *err = "decoder.pcap_play_synchronization invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, key_prefix, "decoder.pcap_play_in_loop")) {
    if (!ParseBool(*v, &p->decoder_param.pcap_play_in_loop)) {
      if (err) *err = "decoder.pcap_play_in_loop invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, key_prefix, "decoder.play_rate")) {
    try {
      p->decoder_param.play_rate_ = std::stof(*v);
    } catch (...) {
      if (err) *err = "decoder.play_rate invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, key_prefix, "decoder.frame_start_azimuth")) {
    try {
      p->decoder_param.frame_start_azimuth = std::stof(*v);
    } catch (...) {
      if (err) *err = "decoder.frame_start_azimuth invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, key_prefix, "decoder.enable_packet_loss_tool")) {
    if (!ParseBool(*v, &p->decoder_param.enable_packet_loss_tool)) {
      if (err) *err = "decoder.enable_packet_loss_tool invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, key_prefix, "decoder.enable_packet_timeloss_tool")) {
    if (!ParseBool(*v, &p->decoder_param.enable_packet_timeloss_tool)) {
      if (err) *err = "decoder.enable_packet_timeloss_tool invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, key_prefix, "decoder.packet_timeloss_tool_continue")) {
    if (!ParseBool(*v, &p->decoder_param.packet_timeloss_tool_continue)) {
      if (err) *err = "decoder.packet_timeloss_tool_continue invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, key_prefix, "decoder.socket_buffer_size")) {
    try {
      p->decoder_param.socket_buffer_size = static_cast<uint32_t>(std::stoul(*v));
    } catch (...) {
      if (err) *err = "decoder.socket_buffer_size invalid";
      return false;
    }
  }


  return true;
}

inline bool ApplyToDriverParam(const std::unordered_map<std::string, std::string>& m, DriverParam* p, std::string* err) {
  return ApplyToDriverParam(m, "", p, err);
}

/** [pcl] 节：仅覆盖 ini 中出现的键；建议先 InitPclOptsFromMacros 再调用以保留编译期默认。 */
inline bool ApplyPclToolOptions(const std::unordered_map<std::string, std::string>& m, PclToolRuntimeOptions* o,
                                std::string* err = nullptr) {
  if (!o) return true;
  const std::string pfx = "pcl";
  if (const std::string* v = GetP(m, pfx, "save_pcd_ascii")) {
    if (!ParseBool(*v, &o->save_pcd_ascii)) {
      if (err) *err = "pcl.save_pcd_ascii invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, pfx, "save_pcd_binary")) {
    if (!ParseBool(*v, &o->save_pcd_binary)) {
      if (err) *err = "pcl.save_pcd_binary invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, pfx, "save_pcd_binary_compressed")) {
    if (!ParseBool(*v, &o->save_pcd_binary_compressed)) {
      if (err) *err = "pcl.save_pcd_binary_compressed invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, pfx, "save_ply")) {
    if (!ParseBool(*v, &o->save_ply)) {
      if (err) *err = "pcl.save_ply invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, pfx, "enable_viewer")) {
    if (!ParseBool(*v, &o->enable_viewer)) {
      if (err) *err = "pcl.enable_viewer invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, pfx, "pcd_ascii_precision")) {
    try {
      o->pcd_ascii_precision = std::stoi(*v);
    } catch (...) {
      if (err) *err = "pcl.pcd_ascii_precision invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, pfx, "output_dir")) {
    o->output_dir = Trim(*v);
    if (o->output_dir.empty()) o->output_dir = "out_pcd";
  }
  if (const std::string* v = GetP(m, pfx, "output_dir_with_timestamp")) {
    if (!ParseBool(*v, &o->output_dir_with_timestamp)) {
      if (err) *err = "pcl.output_dir_with_timestamp invalid";
      return false;
    }
  }
  if (const std::string* v = GetP(m, pfx, "save_valid_points_only")) {
    if (!ParseBool(*v, &o->save_valid_points_only)) {
      if (err) *err = "pcl.save_valid_points_only invalid";
      return false;
    }
  }
  return true;
}

inline bool LoadDriverSampleConfig(const std::string& path, DriverParam* out, std::string* err = nullptr) {
  std::unordered_map<std::string, std::string> kv;
  if (!LoadIniMap(path, &kv, err)) return false;
  if (!MergeSourceTypeProfileIntoInput(&kv, err)) return false;
  return ApplyToDriverParam(kv, "", out, err);
}

/** 同一 ini 内 [lidar1] / [lidar2] 段：键名仍为 driver.*、input.*、decoder.* */
inline bool LoadDriverSampleConfigForSection(const std::string& path, const std::string& section, DriverParam* out,
                                           std::string* err = nullptr) {
  std::unordered_map<std::string, std::string> kv;
  if (!LoadIniMap(path, &kv, err)) return false;
  return ApplyToDriverParam(kv, section, out, err);
}

/** 加载 DriverParam，并在 pcl_out 非空时解析 [pcl]（可与 InitPclOptsFromMacros 组合）。 */
inline bool LoadDriverSampleConfigWithPcl(const std::string& path, DriverParam* out, PclToolRuntimeOptions* pcl_out,
                                          std::string* err = nullptr) {
  std::unordered_map<std::string, std::string> kv;
  if (!LoadIniMap(path, &kv, err)) return false;
  if (!MergeSourceTypeProfileIntoInput(&kv, err)) return false;
  if (!ApplyToDriverParam(kv, "", out, err)) return false;
  if (pcl_out && !ApplyPclToolOptions(kv, pcl_out, err)) return false;
  return true;
}

/** 供 pcl_tool 等：在 ApplyToDriverParam 之前对 map 做 source_type 合并。 */
inline bool PreprocessDriverSampleIniMap(std::unordered_map<std::string, std::string>* kv, std::string* err = nullptr) {
  return MergeSourceTypeProfileIntoInput(kv, err);
}

}  // namespace sample_config
}  // namespace lidar
}  // namespace hesai