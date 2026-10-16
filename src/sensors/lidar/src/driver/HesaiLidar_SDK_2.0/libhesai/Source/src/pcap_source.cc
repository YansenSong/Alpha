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
#include "pcap_source.h"

#include <stdexcept>
#include <cassert>
#include <cstring>
#include <iostream>
#include <cstdint>

#ifdef _MSC_VER
#include <windows.h>
#else
#include <sys/mman.h>
#include <fcntl.h>
#include <sys/stat.h>
#endif

using namespace hesai::lidar;

static constexpr uint32_t pcap_magic_number_native = 0xa1b2c3d4;      // 微秒，主机字节序
static constexpr uint32_t pcap_magic_number_swapped = 0xd4c3b2a1;     // 微秒，网络字节序
static constexpr uint32_t pcap_magic_number_native_nsec = 0xa1b23c4d; // 纳秒，主机字节序
static constexpr uint32_t pcap_magic_number_swapped_nsec = 0x4d3cb2a1; // 纳秒，网络字节序
static constexpr uint32_t pcapng_magic_number = 0x0a0d0d0a;  // pcapng格式

PcapIPHeader::PcapIPHeader(uint8_t protocol, uint16_t pkt_len)
    : ether{ {0xff,0xff,0xff,0xff,0xff,0xff}, {0x00, 0x0a, 0x35, 0x00, 0x1e, 0x53}, 0x0008 }
    , ip{ 0x5, 0x4, 0x00, uint16_t((((pkt_len + 20) & 0xff) << 8) | ((pkt_len + 20) >> 8)), 0xf17a, 0x0040, 0x40, protocol, 0x80f8, 0xc901a8c0, 0xffffffff }
{}

PcapIPv6Header::PcapIPv6Header(uint8_t protocol, uint16_t pkt_len)
    : ether{ {0xff,0xff,0xff,0xff,0xff,0xff}, {0x00, 0x0a, 0x35, 0x00, 0x1e, 0x53}, 0xdd86 }
    , ipv6 { 0x6, 0, 0, 0, uint8_t((((pkt_len + 40) & 0xff) << 8) | ((pkt_len + 40) >> 8)), protocol, }
{}

PcapUDPHeader::PcapUDPHeader(uint16_t pkt_len, uint16_t port)
    : PcapIPHeader::PcapIPHeader(0x11, pkt_len + 8)
    , udp{ 0x1027, uint16_t(((port & 0xff) << 8) | (port >> 8)), uint16_t((((pkt_len + 8) & 0xff) << 8) | ((pkt_len + 8) >> 8)), 0x0000 }
{}

PcapUDPv6Header::PcapUDPv6Header(uint16_t pkt_len, uint16_t port)
    : PcapIPv6Header::PcapIPv6Header(0x11, pkt_len + 8)
    , udp{ 0x1027, uint16_t(((port & 0xff) << 8) | (port >> 8)), uint16_t((((pkt_len + 8) & 0xff) << 8) | ((pkt_len + 8) >> 8)), 0x0000 }
{}

PcapTCPHeader::PcapTCPHeader(uint16_t pkt_len, uint16_t port)
    : PcapIPHeader::PcapIPHeader(0x06, pkt_len + 20)
    , tcp{ 0x1027, uint16_t(((port & 0xff) << 8) | (port >> 8)), 0x000000000, 0x00000000, 0x50, 0x00, 0x0000, 0x0000, 0x0000 }
{}

PcapTCPv6Header::PcapTCPv6Header(uint16_t pkt_len, uint16_t port)
    : PcapIPv6Header::PcapIPv6Header(0x06, pkt_len + 20)
    , tcp{ 0x1027, uint16_t(((port & 0xff) << 8) | (port >> 8)), 0x000000000, 0x00000000, 0x50, 0x00, 0x0000, 0x0000, 0x0000 }
{}

class PcapSource::Private {
private:
#ifdef _MSC_VER
    // Windows平台使用HANDLE
    HANDLE _fd;
    HANDLE _file_mapping;
#else
    // Linux平台使用文件描述符
    int _fd;
#endif
    // 当前映射的内存地址
    void* _mapped_memory;
    // 当前映射的大小
    size_t _mapped_size;
    // 当前映射的起始偏移
    size_t _mapped_offset;
    // 文件总大小
    size_t _file_size;
    // 当前文件偏移
    size_t _fpos;
    // 块大小
    static const size_t CHUNK_SIZE = 64 * 1024 * 1024; // 64MB
    // 是否已经映射
    bool _is_mapped;

public:
    Private() : 
#ifdef _MSC_VER
        _fd(INVALID_HANDLE_VALUE),
        _file_mapping(NULL),
#else
        _fd(-1),
#endif
        _mapped_memory(nullptr), 
        _mapped_size(0),
        _mapped_offset(0), 
        _file_size(0), 
        _fpos(0), 
        _is_mapped(false) {}

    ~Private() { 
        close(); 
    }

    void open(const std::string& pcap_path) {
        close();
        
#ifdef _MSC_VER
        // Windows平台打开文件
        _fd = CreateFileA(pcap_path.c_str(),
                         GENERIC_READ,
                         FILE_SHARE_READ,
                         NULL,
                         OPEN_EXISTING,
                         FILE_ATTRIBUTE_NORMAL,
                         NULL);
        if (_fd == INVALID_HANDLE_VALUE) {
            LogError("Failed to open file: %s", pcap_path.c_str());
            return;
        }

        // 获取文件大小
        LARGE_INTEGER file_size;
        if (!GetFileSizeEx(_fd, &file_size)) {
            CloseHandle(_fd);
            LogError("Failed to get file size");
            _fd = INVALID_HANDLE_VALUE;
            return;
        }
        _file_size = file_size.QuadPart;
#else
        // Linux平台打开文件
        _fd = ::open(pcap_path.c_str(), O_RDONLY);
        if (_fd == -1) {
            LogError("Failed to open file: %s", pcap_path.c_str());
            return;
        }

        // 获取文件大小
        struct stat st;
        if (fstat(_fd, &st) == -1) {
            ::close(_fd);
            LogError("Failed to get file size");
            _fd = -1;
            return;
        }
        _file_size = st.st_size;
#endif

        // 映射第一个块
        map_chunk(0);
    }

    bool is_open() const { 
#ifdef _MSC_VER
        return _fd != INVALID_HANDLE_VALUE;
#else
        return _fd != -1;
#endif
    }

    void close() {
        if (_is_mapped) {
#ifdef _MSC_VER
            UnmapViewOfFile(_mapped_memory);
            if (_file_mapping) {
                CloseHandle(_file_mapping);
                _file_mapping = NULL;
            }
#else
            munmap(_mapped_memory, _mapped_size);
#endif
            _mapped_memory = nullptr;
            _is_mapped = false;
        }
#ifdef _MSC_VER
        if (_fd != INVALID_HANDLE_VALUE) {
            CloseHandle(_fd);
            _fd = INVALID_HANDLE_VALUE;
        }
#else
        if (_fd != -1) {
            ::close(_fd);
            _fd = -1;
        }
#endif
        _mapped_size = 0;
        _mapped_offset = 0;
        _fpos = 0;
    }

    inline bool eof() const { 
        return _fpos >= _file_size; 
    }

    inline size_t fpos() const { 
        return _fpos; 
    }

    inline void epos() {
        _fpos = _file_size;
        ensure_mapped();
    }

    inline void fpos(size_t new_fpos) { 
        if (new_fpos > _file_size) {
            LogError("Position out of file range");
            return;
        }
        _fpos = new_fpos;
        ensure_mapped();
    }

    template<typename T>
    bool read(T& value) {
        if (_fpos + sizeof(T) > _file_size) return false;
        
        check_and_map_chunk(_fpos);
        // 检查是否需要跨块读取
        if (_fpos + sizeof(T) > _mapped_offset + _mapped_size) {
            char temp_buffer[sizeof(T)] = {0};
            read_across_one_chunks(temp_buffer, sizeof(T), _fpos);
            
            // 组合数据
            value = *(T*)temp_buffer;
            _fpos += sizeof(T);
            return true;
        }

        value = *(T*)(static_cast<char*>(_mapped_memory) + (_fpos - _mapped_offset));
        _fpos += sizeof(T);
        return true;
    }

    bool read(void* dst, size_t length) {
        if (length == 0) return true;
        if (_fpos + length > _file_size) return false;

        size_t remaining = length;
        size_t current_pos = _fpos;
        char* current_dst = static_cast<char*>(dst);

        while (remaining > 0) {
            check_and_map_chunk(current_pos);
            // 计算当前块中可读取的数据量
            size_t available = _mapped_size - (current_pos - _mapped_offset);
            size_t to_read = std::min(remaining, available);

            // 复制数据
            std::memcpy(current_dst,
                       static_cast<char*>(_mapped_memory) + (current_pos - _mapped_offset),
                       to_read);

            current_dst += to_read;
            current_pos += to_read;
            remaining -= to_read;
            _fpos = current_pos;   
        }

        return true;
    }

    bool move(size_t length) {
        if (_fpos + length > _file_size) return false;
        
        size_t new_pos = _fpos + length;
        check_and_map_chunk(new_pos);
        
        _fpos = new_pos;
        return true;
    }

private:
    void map_chunk(size_t offset) {
        if (offset >= _file_size) {
            return;
        }
        if (_is_mapped) {
#ifdef _MSC_VER
            UnmapViewOfFile(_mapped_memory);
            if (_file_mapping) {
                CloseHandle(_file_mapping);
                _file_mapping = NULL;
            }
#else
            munmap(_mapped_memory, _mapped_size);
#endif
            _mapped_memory = nullptr;
            _is_mapped = false;
        }

        // 确保偏移量是块大小的整数倍
        offset = (offset / CHUNK_SIZE) * CHUNK_SIZE;
        
        // 计算要映射的大小
        _mapped_size = std::min(CHUNK_SIZE, _file_size - offset);
        _mapped_offset = offset;

#ifdef _MSC_VER
        // Windows平台内存映射
        _file_mapping = CreateFileMapping(_fd,
                                        NULL,
                                        PAGE_READONLY,
                                        0,
                                        0,
                                        NULL);
        if (!_file_mapping) {
            LogFatal("Failed to create file mapping");
            _is_mapped = false;
            return;
        }

        _mapped_memory = MapViewOfFile(_file_mapping,
                                     FILE_MAP_READ,
                                     (DWORD)(offset >> 32),
                                     (DWORD)(offset & 0xFFFFFFFF),
                                     _mapped_size);
        if (!_mapped_memory) {
            CloseHandle(_file_mapping);
            _file_mapping = NULL;
            LogFatal("Failed to map view of file");
            _is_mapped = false;
            return;
        }
#else
        // Linux平台内存映射
        _mapped_memory = mmap(nullptr, _mapped_size, PROT_READ, 
                             MAP_PRIVATE, _fd, offset);
        
        if (_mapped_memory == MAP_FAILED) {
            LogFatal("Failed to map file chunk");
            _is_mapped = false;
            return;
        }
#endif

        _is_mapped = true;
    }

    void map_next_chunk() {
        size_t new_offset = _mapped_offset + CHUNK_SIZE;
        if (new_offset >= _file_size) {
            return;
        }
        map_chunk(new_offset);
    }

    void check_and_map_chunk(size_t pos) {
        if (_is_mapped && pos >= _mapped_offset && pos < _mapped_offset + _mapped_size) {
            return;
        }
        map_chunk(pos);
    }

    void ensure_mapped() {
        // 检查当前偏移是否在已映射的范围内
        if (!_is_mapped || _fpos < _mapped_offset || 
            _fpos >= _mapped_offset + _mapped_size) {
            // 计算新的映射起始位置
            size_t new_offset = (_fpos / CHUNK_SIZE) * CHUNK_SIZE;
            map_chunk(new_offset);
        }
    }

    // 添加一个辅助函数来处理跨块读取
    bool read_across_one_chunks(void* dst, size_t length, size_t current_pos) {
        if (length > CHUNK_SIZE) {
            return false;
        }
        check_and_map_chunk(current_pos);
        if (!_is_mapped || current_pos < _mapped_offset || 
            current_pos >= _mapped_offset + _mapped_size) {
            return false;
        }
        // 计算当前块剩余可读数据
        size_t remaining_in_current = _mapped_offset + _mapped_size - current_pos;

        if (length <= remaining_in_current) {
            std::memcpy(dst,
                        static_cast<char*>(_mapped_memory) + (current_pos - _mapped_offset),
                        length);
            return true;
        }
        // 先读取当前块剩余的数据
        std::memcpy(dst,
                    static_cast<char*>(_mapped_memory) + (current_pos - _mapped_offset),
                    remaining_in_current);
        
        // 映射下一个块
        size_t next_chunk = (current_pos / CHUNK_SIZE) + 1;
        if (next_chunk * CHUNK_SIZE >= _file_size) {
            return false;
        }
        map_chunk(next_chunk * CHUNK_SIZE);
        if (!_is_mapped || next_chunk * CHUNK_SIZE < _mapped_offset || 
            next_chunk * CHUNK_SIZE >= _mapped_offset + _mapped_size || length - remaining_in_current > _mapped_size) {
            return false;
        }

        // 读取下一块的数据
        std::memcpy(static_cast<char*>(dst) + remaining_in_current,
                    _mapped_memory,
                    length - remaining_in_current);
        
        return true;
    }
};

PcapSource::PcapSource(std::string path, int packet_interval)
    : _p(new Private)
    , pcap_udp_header_{0, 0, 0, 0}
    , last_need_read_len(0)
{
    pcap_path_ = path;
    packet_interval_ = packet_interval;
}

PcapSource::~PcapSource() {
    PcapSource::Close();
    delete _p;
}

PcapSource::Callback PcapSource::callback() const {
    return udp_callback_;
}

void PcapSource::callback(Callback callback) {
    udp_callback_ = callback;
}
PcapSource::CallbackTcp PcapSource::tcp_callback() const {
    return tcp_callback_;
}

void PcapSource::tcp_callback(CallbackTcp callback) {
    tcp_callback_ = callback;
}

size_t PcapSource::fpos() const
{
    return _p->fpos();
}

void PcapSource::fpos(size_t new_fpos)
{
    _p->fpos(new_fpos);
}

bool PcapSource::Open() {

    try
    {
        PcapSource::Close();
        _p->open(pcap_path_);
        if (!_p->is_open()) {
            throw std::runtime_error(std::string("Fail to open .pcap file: \"") + (pcap_path_)+"\"");
        }
        _p->read(pcap_header_);
        bool valid_pcap = false;
        switch (pcap_header_.magic_number) {
            case pcap_magic_number_native:
                // 微秒精度，主机字节序
                time_precision_ = 1000000; // 微秒
                byte_order_ = BYTE_ORDER_NATIVE;
                valid_pcap = true;
                break;
            case pcap_magic_number_swapped:
                // 微秒精度，需要字节序转换
                time_precision_ = 1000000; // 微秒
                byte_order_ = BYTE_ORDER_SWAPPED;
                // 需要对后续读取的数据进行字节序转换
                valid_pcap = true;
                break;
            case pcap_magic_number_native_nsec:
                // 纳秒精度，主机字节序
                time_precision_ = 1000000000; // 纳秒
                byte_order_ = BYTE_ORDER_NATIVE;
                valid_pcap = true;
                break;
            case pcap_magic_number_swapped_nsec:
                // 纳秒精度，需要字节序转换
                time_precision_ = 1000000000; // 纳秒
                byte_order_ = BYTE_ORDER_SWAPPED;
                // 需要对后续读取的数据进行字节序转换
                valid_pcap = true;
                break;
            case pcapng_magic_number:
                is_pcapng = true;
                _p->fpos(0);
                valid_pcap = true;
                break;
            default:
                valid_pcap = false;
                break;
        }
        if (!valid_pcap) {
            throw std::runtime_error(std::string("Not a valid .pcap file: \"") + (pcap_path_)+"\"");
        }
        network = pcap_header_.network;
        begin_pos = _p->fpos();
        if (is_pcapng) network = 1;
        return true;
    }
    catch (const std::exception& e)
    {
        LogError("%s", e.what());
        return false;
    }

}

std::string PcapSource::pcap_path() const {
    return pcap_path_;
}

int PcapSource::next() {
    if (is_pcapng) {
        return nextPcapng();
    }
    else return nextPcap();
}

int PcapSource::parser_ethernet_type(uint8_t *data, uint32_t payload_len, uint16_t& ether_type) {
    switch (network)
    {
        case 0: {
            ether_type = 0x0008;
            uint32_t family = *(uint32_t*)data;
            if (family == 2) ether_type = 0x0008;
            else if (family == 24) ether_type = 0xdd86;
            else if (family == 28) ether_type = 0xdd86;
            return 4;
        }
        case 1: {
            if (payload_len < sizeof(Ethernet)) return -1;
            ether_type = ((Ethernet *)data)->ether_type;
            if (ether_type == 0x0081) {  // vlan tag
                ether_type = (*((uint16_t*)(data + sizeof(Ethernet) + 2)));
                return sizeof(Ethernet) + 4;
            }
            return sizeof(Ethernet);
        }
        case 6:
        case 10: {
            data += 16;
            ether_type = *(uint16_t*)data;
            if (ether_type == 0x0081) {  // vlan tag
                data += 4;
                ether_type = *(uint16_t*)data;
                return 18 + 4;
            }
            return 18;
        }
        case 7: {
            data += 2;
            uint8_t type = *(uint8_t*)data;
            ether_type = 0x0008;
            if (type == 0x1C || type == 0x1D) ether_type = 0x0008;
            else if (type == 0x1E) ether_type = 0xdd86;
            return 6;
        }
        case 8: {
            ether_type = 0x0008;
            return 0;
        }
        case 9: {
            data += 2;
            uint16_t protocol = *(uint16_t*)data;
            ether_type = 0x0008;
            if (protocol == 0x21) ether_type = 0x0008;
            else if (protocol == 0x57) ether_type = 0xdd86;
            return 4;
        }
        case 101: {
            uint8_t version = (data[0] >> 4) & 0x0F;
            ether_type = 0x0008;
            if (version == 4) {
                ether_type = 0x0008;
            } else if (version == 6) {
                ether_type = 0xdd86;
            }
            return 0;
        }
        case 113: {
            data += 14;
            ether_type = *(uint16_t*)data;
            if (ether_type == 0x0081) {  // vlan tag
                data += 4;
                ether_type = *((uint16_t*)(data));
                return 20;
            }
            return 16; 
        }
        case 276: {
            ether_type = (*((uint16_t*)(data)));
            return 20;
        }
        default:
            return -1;
    }
    return -1;
}

void PcapSource::clearLastNeedRead() {
    if (last_need_read_len > 0) {
        _p->move(last_need_read_len);
        last_need_read_len = 0;
    }
}

int PcapSource::nextPcapng() {
    if(_p->eof()) {
        if (is_loop) {
            _p->fpos(begin_pos);
        }
        else {
            is_pcap_end = true;
            return -1;
        }
    }
    uint32_t block_type;
    bool ret = _p->read(block_type);
    if (!ret) {
        _p->epos();
        return -1;
    }
    uint32_t block_total_len;
    ret = _p->read(block_total_len);
    if (!ret) {
        _p->epos();
        return -1;
    }
    if (block_total_len < 32) {
        if (block_total_len < 12) {
            _p->epos();
            return -1;
        }
        ret = _p->move(block_total_len - 8);
        if (!ret) {
            _p->epos();
            return -1;
        }
        return -1;
    }
    
    uint32_t captured_packet_len = 0;
    switch (block_type) {
        case IDB: {
            uint16_t link_type = 1;
            _p->read(link_type);
            ret = _p->move(block_total_len - 10);
            if (!ret) {
                _p->epos();
                return -1;
            }
            network = link_type;
        } break;
        case EPB: {
            uint8_t tmp_data[20];
            bool ret = _p->read(tmp_data, 20);
            if (!ret) {
                _p->epos();
                return -1;
            }
            captured_packet_len = *((uint32_t *)(tmp_data + 12));
            uint32_t original_packet_len = *((uint32_t *)(tmp_data + 16));
            captured_packet_len = HS_MIN(captured_packet_len, original_packet_len);
            captured_packet_len = HS_MIN(captured_packet_len, block_total_len - 32);
            packet_data_pcapng.resize(captured_packet_len);
            ret = _p->read(packet_data_pcapng.data(), captured_packet_len);
            if (!ret) {
                _p->epos();
                return -1;
            }
            ret = _p->move(block_total_len - 28 - captured_packet_len);
            if (!ret) {
                _p->epos();
                return -1;
            }
        } break;
        case SPB: {
            bool ret = _p->read(captured_packet_len);
            if (!ret) {
                _p->epos();
                return -1;
            }
            captured_packet_len = HS_MIN(captured_packet_len, block_total_len - 16);
            packet_data_pcapng.resize(captured_packet_len);
            ret = _p->read(packet_data_pcapng.data(), captured_packet_len);
            if (!ret) {
                _p->epos();
                return -1;
            }
            ret = _p->move(block_total_len - 12 - captured_packet_len);
            if (!ret) {
                _p->epos();
                return -1;
            }
        } break;
        default: {
            ret = _p->move(block_total_len - 8);
            if (!ret) {
                _p->epos();
                return -1;
            }
        } break;
    }
    
    if (captured_packet_len <= 0) {
        return -1;
    }

    uint16_t ether_type = 0x0008;
    uint8_t *data_ptr = packet_data_pcapng.data();
    uint32_t payload_len = captured_packet_len;
    int mac_offset = parser_ethernet_type(data_ptr, payload_len, ether_type);
    if (mac_offset < 0) {
        return -1;
    }
    data_ptr += mac_offset;
    payload_len -= mac_offset;
    switch (ether_type)
    {
    case 0x0008: // ipv4
        switch (((PcapIPHeader::IP*)data_ptr)->protocol)
        {
        case 17:
            if (payload_len > kBufSize) {
                break;
            }
            if (payload_len < sizeof(PcapIPHeader::IP) + sizeof(UDP)) break;
            pcap_udp_header_ = *(const UDP*)(data_ptr + sizeof(PcapIPHeader::IP));
            data_ptr += sizeof(PcapIPHeader::IP) + sizeof(UDP);
            payload_len -= sizeof(PcapIPHeader::IP) + sizeof(UDP);
            payload_len = HS_MIN(payload_len, ntohs(pcap_udp_header_.length) - sizeof(UDP));
            if (udp_callback_)
                return udp_callback_(data_ptr, payload_len);
            else 
                break;
            break;
        case 6: {
            if (payload_len < sizeof(PcapIPHeader::IP) + sizeof(TCP)) break;
            PcapIPHeader::IP* ip_header = (PcapIPHeader::IP*)(data_ptr);
            TcpCheckStruct tcp_check_struct;
            tcp_check_struct.src_ip = ntohl(ip_header->src_addr);
            tcp_check_struct.dst_ip = ntohl(ip_header->dst_addr);
            pcap_tcp_header_ = *(const TCP*)(data_ptr + sizeof(PcapIPHeader::IP));
            tcp_check_struct.src_port = ntohs(pcap_tcp_header_.source_port);
            tcp_check_struct.dst_port = ntohs(pcap_tcp_header_.destination_port);
            tcp_check_struct.seq = ntohl(pcap_tcp_header_.seq);
            tcp_check_struct.ack = ntohl(pcap_tcp_header_.ack);
            tcp_check_struct.is_ipv6 = false;
            data_ptr += sizeof(PcapIPHeader::IP) + sizeof(TCP);
            payload_len -= sizeof(PcapIPHeader::IP) + sizeof(TCP);
            if (tcp_callback_) {
                if(pcap_tcp_header_.getLenres() < sizeof(TCP)) {
                    break;
                }
                uint32_t header_options_len = pcap_tcp_header_.getLenres() - sizeof(TCP);
                if (payload_len < header_options_len) {
                    break;
                }
                uint32_t tcp_payload_len = payload_len - header_options_len;
                data_ptr += header_options_len;
                tcp_check_struct.recv_payload_len = tcp_payload_len;
                return tcp_callback_(data_ptr, tcp_payload_len, tcp_check_struct);
            }
            else {
                break;
            }
        } break;
        default:
            break;
        }
        break;
    case 0xdd86: // ipv6 
        switch (((PcapIPv6Header::IPv6*)data_ptr)->next_header)
        {
        case 17:
            if (payload_len > kBufSize) {
                break;
            }
            if (payload_len < sizeof(PcapUDPv6Header::IPv6) + sizeof(UDP)) break;
            pcap_udp_header_ = *(const UDP*)(data_ptr + sizeof(PcapIPv6Header::IPv6));
            data_ptr += sizeof(PcapUDPv6Header::IPv6) + sizeof(UDP);
            payload_len -= sizeof(PcapUDPv6Header::IPv6) + sizeof(UDP);
            payload_len = HS_MIN(payload_len, ntohs(pcap_udp_header_.length) - sizeof(UDP));
            if (udp_callback_)
                return udp_callback_(data_ptr, payload_len);
            else 
                break;
            break;
        case 6: {
            if (payload_len < sizeof(PcapIPv6Header::IPv6) + sizeof(TCP)) break;
            PcapIPv6Header::IPv6* ip_header = (PcapIPv6Header::IPv6*)(data_ptr);
            TcpCheckStruct tcp_check_struct;
            tcp_check_struct.src_ipv6 = (ip_header->src_addr);
            tcp_check_struct.dst_ipv6 = (ip_header->dst_addr);
            pcap_tcp_header_ = *(const TCP*)(data_ptr + sizeof(PcapIPv6Header::IPv6));
            tcp_check_struct.src_port = ntohs(pcap_tcp_header_.source_port);
            tcp_check_struct.dst_port = ntohs(pcap_tcp_header_.destination_port);
            tcp_check_struct.seq = ntohl(pcap_tcp_header_.seq);
            tcp_check_struct.ack = ntohl(pcap_tcp_header_.ack);
            tcp_check_struct.is_ipv6 = true;
            data_ptr += sizeof(PcapTCPv6Header::IPv6) + sizeof(TCP);
            payload_len -= sizeof(PcapTCPv6Header::IPv6) + sizeof(TCP);
            if (tcp_callback_) {
                if(pcap_tcp_header_.getLenres() < sizeof(TCP)) {
                    break;
                }
                uint32_t header_options_len = pcap_tcp_header_.getLenres() - sizeof(TCP);
                if (payload_len < header_options_len) {
                    break;
                }
                uint32_t tcp_payload_len = payload_len - header_options_len;
                data_ptr += header_options_len;
                tcp_check_struct.recv_payload_len = tcp_payload_len;
                return tcp_callback_(data_ptr, tcp_payload_len, tcp_check_struct);
            }
            else
                break;
        } break;
        default:
            break;
        }
        break;
    default:
        // LogWarning("can not parser Ethernet data, type = %x ", ((Ethernet*)payload_.data())->ether_type);
        break;
    }

    return -1;
}

int PcapSource::nextPcap() {          
    if(_p->eof()) {
        if (is_loop) {
            _p->fpos(begin_pos);
        }
        else {
            is_pcap_end = true;
            return -1;
        }
    }
    bool ret = _p->read(pcap_record_);
    if (!ret) {
        _p->epos();
        return -1;
    }
    if (byte_order_ == BYTE_ORDER_SWAPPED) {
        pcap_record_.incl_len = convert_endian_32(pcap_record_.incl_len);
        pcap_record_.orig_len = convert_endian_32(pcap_record_.orig_len);
        // 时间戳也需要转换
        pcap_record_.ts_sec = convert_endian_32(pcap_record_.ts_sec);
        pcap_record_.ts_usec = convert_endian_32(pcap_record_.ts_usec);
    }
    if (pcap_record_.incl_len <= kBufSize) {
        last_need_read_len = 0;
        ret = _p->read(payload_.data(), pcap_record_.incl_len);
    }
    else {
        last_need_read_len = pcap_record_.incl_len - kBufSize;
        ret = _p->read(payload_.data(), kBufSize);
    }
    if (!ret) return -1;
    uint16_t ether_type = 0x0008;
    uint8_t *data_ptr = payload_.data();
    uint32_t payload_len = pcap_record_.incl_len;
    int mac_offset = parser_ethernet_type(data_ptr, payload_len, ether_type);
    if (mac_offset < 0) {
        clearLastNeedRead();
        return -1;
    }
    data_ptr += mac_offset;
    payload_len -= mac_offset;
    switch (ether_type)
    {
    case 0x0008: // ipv4
        switch (((PcapIPHeader::IP*)data_ptr)->protocol)
        {
        case 17:
            if (last_need_read_len > 0) {
                break;
            }
            if (payload_len < sizeof(PcapIPHeader::IP) + sizeof(UDP)) break;
            pcap_udp_header_ = *(const UDP*)(data_ptr + sizeof(PcapIPHeader::IP));
            data_ptr += sizeof(PcapIPHeader::IP) + sizeof(UDP);
            payload_len -= sizeof(PcapIPHeader::IP) + sizeof(UDP);
            payload_len = HS_MIN(payload_len, ntohs(pcap_udp_header_.length) - sizeof(UDP));
            if (udp_callback_)
                return udp_callback_(data_ptr, payload_len);
            else 
                break;
            break;
        case 6: {
            if (payload_len < sizeof(PcapIPHeader::IP) + sizeof(TCP)) break;
            PcapIPHeader::IP* ip_header = (PcapIPHeader::IP*)(data_ptr);
            TcpCheckStruct tcp_check_struct;
            tcp_check_struct.src_ip = ntohl(ip_header->src_addr);
            tcp_check_struct.dst_ip = ntohl(ip_header->dst_addr);
            pcap_tcp_header_ = *(const TCP*)(data_ptr + sizeof(PcapIPHeader::IP));
            tcp_check_struct.src_port = ntohs(pcap_tcp_header_.source_port);
            tcp_check_struct.dst_port = ntohs(pcap_tcp_header_.destination_port);
            tcp_check_struct.seq = ntohl(pcap_tcp_header_.seq);
            tcp_check_struct.ack = ntohl(pcap_tcp_header_.ack);
            tcp_check_struct.is_ipv6 = false;
            data_ptr += sizeof(PcapIPHeader::IP) + sizeof(TCP);
            payload_len -= sizeof(PcapIPHeader::IP) + sizeof(TCP);
            if (tcp_callback_) {
                if(pcap_tcp_header_.getLenres() < sizeof(TCP)) {
                    break;
                }
                uint32_t header_options_len = pcap_tcp_header_.getLenres() - sizeof(TCP);
                if (payload_len < header_options_len) {
                    break;
                }
                uint32_t tcp_payload_len = payload_len - header_options_len;
                data_ptr += header_options_len;
                if (last_need_read_len > 0) {
                    uint32_t buf_tcp_len = tcp_payload_len - last_need_read_len;
                    memcpy(payload_tcp_.data(), data_ptr, buf_tcp_len);
                    ret = _p->read(payload_tcp_.data() + buf_tcp_len, last_need_read_len);
                    last_need_read_len = 0;
                    if (!ret) break;
                    data_ptr = payload_tcp_.data();
                }
                tcp_check_struct.recv_payload_len = tcp_payload_len;
                return tcp_callback_(data_ptr, tcp_payload_len, tcp_check_struct);
            }
            else {
                break;
            }
        } break;
        default:
            break;
        }
        break;
    case 0xdd86: // ipv6 
        switch (((PcapIPv6Header::IPv6*)data_ptr)->next_header)
        {
        case 17:
            if (last_need_read_len > 0) {
                break;
            }
            if (payload_len < sizeof(PcapUDPv6Header::IPv6) + sizeof(UDP)) break;
            pcap_udp_header_ = *(const UDP*)(data_ptr + sizeof(PcapIPv6Header::IPv6));
            data_ptr += sizeof(PcapUDPv6Header::IPv6) + sizeof(UDP);
            payload_len -= sizeof(PcapUDPv6Header::IPv6) + sizeof(UDP);
            payload_len = HS_MIN(payload_len, ntohs(pcap_udp_header_.length) - sizeof(UDP));
            if (udp_callback_)
                return udp_callback_(data_ptr, payload_len);
            else 
                break;
            break;
        case 6: {
            if (payload_len < sizeof(PcapIPv6Header::IPv6) + sizeof(TCP)) break;
            PcapIPv6Header::IPv6* ip_header = (PcapIPv6Header::IPv6*)(data_ptr);
            TcpCheckStruct tcp_check_struct;
            tcp_check_struct.src_ipv6 = (ip_header->src_addr);
            tcp_check_struct.dst_ipv6 = (ip_header->dst_addr);
            pcap_tcp_header_ = *(const TCP*)(data_ptr + sizeof(PcapIPv6Header::IPv6));
            tcp_check_struct.src_port = ntohs(pcap_tcp_header_.source_port);
            tcp_check_struct.dst_port = ntohs(pcap_tcp_header_.destination_port);
            tcp_check_struct.seq = ntohl(pcap_tcp_header_.seq);
            tcp_check_struct.ack = ntohl(pcap_tcp_header_.ack);
            tcp_check_struct.is_ipv6 = true;
            data_ptr += sizeof(PcapTCPv6Header::IPv6) + sizeof(TCP);
            payload_len -= sizeof(PcapTCPv6Header::IPv6) + sizeof(TCP);
            if (tcp_callback_) {
                if(pcap_tcp_header_.getLenres() < sizeof(TCP)) {
                    break;
                }
                uint32_t header_options_len = pcap_tcp_header_.getLenres() - sizeof(TCP);
                if (payload_len < header_options_len) {
                    break;
                }
                uint32_t tcp_payload_len = payload_len - header_options_len;
                data_ptr += header_options_len;
                if (last_need_read_len > 0) {
                    uint32_t buf_tcp_len = tcp_payload_len - last_need_read_len;
                    memcpy(payload_tcp_.data(), data_ptr, buf_tcp_len);
                    ret = _p->read(payload_tcp_.data() + buf_tcp_len, last_need_read_len);
                    last_need_read_len = 0;
                    if (!ret) break;
                    data_ptr = payload_tcp_.data();
                }
                tcp_check_struct.recv_payload_len = tcp_payload_len;
                return tcp_callback_(data_ptr, tcp_payload_len, tcp_check_struct);
            }
            else
                break;
        } break;
        default:
            break;
        }
        break;
    default:
        // LogWarning("can not parser Ethernet data, type = %x ", ((Ethernet*)payload_.data())->ether_type);
        break;
    }
    clearLastNeedRead();
    return -1;
}
int PcapSource::destinationPort() {
    uint16_t port = pcap_udp_header_.destination_port;
    return ((port & 0xff) << 8) | ((port >> 8) & 0xff);
}

void PcapSource::Close() {
    _p->close();
}


bool PcapSource::IsOpened() {
    return _p->is_open();
}

int PcapSource::Receive(UdpPacket& udpPacket, uint16_t u16Len, int flags,
                       int iTimeout) {
    if (dataIndex + 581 <= dataLength) {
        memcpy(udpPacket.buffer + 2, m_receiveBuffer, 581);
        udpPacket.buffer[0] = 0xEE;
        udpPacket.buffer[1] = 0xFF;
        dataIndex += 581;
        return 581 + 2;
    }
    callback([&](
        const uint8_t* data,
        uint32_t len
        ) ->int {
            memcpy(udpPacket.buffer, data, len);
            return len;
        }
    );
    tcp_callback([&](
        const uint8_t* data,
        uint32_t len,
        TcpCheckStruct& tcp_check_struct
        ) ->int {
            if (len % 581 != 0 || len > kBufSize
                || data[0] != 1 || data[1] != 10) return -1;
            memcpy(m_receiveBuffer + dataLength, data, len);
            dataLength += len;
            if (dataIndex + 581 <= dataLength) {
                memcpy(udpPacket.buffer + 2, m_receiveBuffer + dataIndex, 581);
                udpPacket.buffer[0] = 0xEE;
                udpPacket.buffer[1] = 0xFF;
                dataIndex += 581;
                return 581 + 2;
            }
            return -1;
        }
    );
    if (dataLength + kBufSize * 5 > kDataMaxLength) {
      if (dataIndex != dataLength) {
        memcpy(m_receiveBuffer, m_receiveBuffer + dataIndex, dataLength - dataIndex);
      }
      dataLength = dataLength - dataIndex;
      dataIndex = 0;
    }
    return next();
}

int PcapSource::Send(uint8_t* u8Buf, uint16_t u16Len, int flags) {
    (void)u8Buf;
    (void)flags;
    return u16Len;
}

void PcapSource::setPcapPath(std::string path) {
    pcap_path_ = path;
}

void PcapSource::setPacketInterval(int microsecond) {
    packet_interval_ = microsecond;
}

inline uint16_t PcapSource::convert_endian_16(uint16_t value) {
    if (byte_order_ == BYTE_ORDER_SWAPPED) {
        return ((value & 0xff) << 8) | ((value >> 8) & 0xff);
    }
    return value;
}

inline uint32_t PcapSource::convert_endian_32(uint32_t value) {
    if (byte_order_ == BYTE_ORDER_SWAPPED) {
        return ((value & 0xff) << 24) | 
               (((value >> 8) & 0xff) << 16) | 
               (((value >> 16) & 0xff) << 8) | 
               ((value >> 24) & 0xff);
    }
    return value;
}
uint64_t PcapSource::getPacketTimestamp(const PcapRecord& record) {
    uint64_t timestamp = record.ts_sec;
    if (time_precision_ == 1000000) {
        // 微秒精度
        timestamp = timestamp * 1000000 + record.ts_usec;
    } else {
        // 纳秒精度
        timestamp = timestamp * 1000000000 + record.ts_usec;
    }
    return timestamp;
}