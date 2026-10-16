# Parsing Lidar Data Online

## Preparation

Copy the example configuration file and modify the parameters:
```bash
cp config/sample_config.example.ini config/sample_config.ini
```

Edit `config/sample_config.ini` to configure data source and parameters.

#### Ethernet-connected Lidar

Set `source_type = network` and configure the `[network]` section:

```ini
[source_type]
source_type = network

[network]
device_ip_address = 192.168.1.201       # Lidar IP address
ptc_port = 9347                          # PTC protocol port
udp_port = 2368                          # Point cloud data destination port
multicast_ip_address =                   # Optional: If destination IP is multicast IP
use_ptc_connected = true                 # Whether to use PTC connection
correction_file_path = /path/to/correction.csv   # Angle correction file (recommend using the lidar's own angle correction file)
firetimes_path = /path/to/firetimes.csv          # Optional: Channel firing timing (firing moment correction file)
host_ip_address =                        # Lidar IP address, ignore if same as point cloud source IP
fault_message_port = 0                   # Fault message destination port, ignore if same as udp_port
ptc_mode = tcp                           # PTC communication type, can be ignored if not using TLS/mTLS-based PTCS
certFile =                               # PTCS configurations, ignore if not used
privateKeyFile =
caFile =
```

#### Serial-connected Lidar (JT16)

Set `source_type = serial` and configure the `[serial]` section:

```ini
[source_type]
source_type = serial

[serial]
rs485_com = /dev/ttyUSB0                 # RS485 point cloud serial port (COM0 in Windows system), actual serial port number may vary
rs232_com = /dev/ttyUSB1                 # RS232 control serial port (COM1 in Windows system), actual serial port number may vary
point_cloud_baudrate = 3125000           # Point cloud baud rate
correction_save_path =                   # Internal lidar angle calibration file save path, if 232 port is set and angle calibration file is successfully obtained from lidar
correction_file_path = /path/to/correction.csv  # Angle correction file (recommend using the lidar's own angle correction file)
```

## Steps
```bash
# 1. Build executable sample program (from build folder): After successful compilation, generate executable program
make -j$(nproc)

# 2. Execute sample program: Start parsing data (must specify configuration file)
./sample /path/to/sample_config.ini
```

## Additional References

For complete configuration file parameters, see [sample_config.example.ini](../config/sample_config.example.ini)
