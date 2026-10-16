# SDK启动流程介绍

## 1. HesaiLidarSdk类启动流程

### 1.1 初始化函数Init()

- 初始化一个Lidar类的实例。

- 拉起一个独立的线程运行函数InitThread()。

- 赋值一些传入参数，例如device_ip_address_等，主要是一些特殊的功能实现做参数传递。

### 1.2 独立线程的初始化函数InitThread()

- 调用Lidar类的初始化函数Init()，详见Lidar类中的介绍。

- 根据初始化结果，判断是否结束。其中Lidar类的GetInitFinish函数可以查询当前初始化状态，当查询状态FailInit时如果返回为True，代表初始化失败，需要结束整个程序。

- 初始化成功后，调用Lidar类的SetAllFinishReady函数，将初始化状态AllInitFinish置为True。（其他状态会在Lidar类的Init()函数中做修改）

### 1.3 启动函数Start()

- 循环查询当前初始化状态，判断是否可以进入解析流程，分为两种情况如下：

    - 当数据源为DATA_FROM_LIDAR时，当状态FaultMessParse为true时，代表雷达型号初始化成功，可以解析FaultMessage数据，提前开启Run()函数(Run函数为独立线程)。

    - 当其他模式下，需要等待AllInitFinish为True，即初始化全部完成后，再进入Run()函数。

- 轮询中，如果发现状态FailInit被置为True后，认为初始化失败，直接退出。

### 1.4 运行函数Run()

- 调用Lidar类的GetOnePacket函数获取一个udp数据包，实际存储udp数据包的中间数组命名为origin_packets_buffer_。

- 通过关键特征判断是否为FaultMessage包，如果是则进行FaultMessage解析，调用lidar_ptr_的解析函数，最终会调用UdpParser类的ParserFaultMessage函数。具体详见UdpParser类介绍。

- 判断是否已经初始化完成，否则continue。因为点云解析依赖初始化的相关配置，因此必须等待初始化完成后开始解析。

- 调用Lidar类的DecodePacket函数解析点云包。最终会调用UdpParser类的DecodePacket函数。该函数主要用于分帧，具体详见UdpParser类介绍。

- 进行IMU相关数据的发布。

- 判断是否分帧，分为两种情况：

    - 当未触发分帧时，调用Lidar类的ComputeXYZI函数，传入当前的包序号，该序号会存储在decoded_packets_buffer_中，作为执行UdpParser类中ComputeXYZI函数的输入。详见Lidar类中ParserThread的介绍。

    - 当触发分帧时，如果使用gpu版本，则会执行GPU对应的解析逻辑。否则调用Lidar类的ComputeXYZIComplete函数，等待ParserThread线程将数据解析完毕执行后续操作。后续操作包括数据的重新组合，点数统计，各类数据的发布，数组更新等。注意当前包是非超时包的情况下，由于触发分帧，并未解析，实际为下一帧的第一包，因此需要再次调用解析函数对其解析。

- 判断本帧包数是否超过上限，超过则清空该帧。

## 2. Lidar初始化

### 2.1 初始化函数Init(const DriverParam&)

- DriverParam中参数介绍详见Readme

- 初始化Logger类，用于记录日志

- 根据传入参数中source_type的类型选择不同的初始化方式：

    - 当为DATA_FROM_PCAP模式时，初始化为PcapSource类，用于从pcap中获取udp数据包。

    - 当为DATA_FROM_LIDAR模式时，初始化为SocketSource类，用于接收网络数据包，此时如果配置的fault_message数据目的端口与点云不同，则需要单独为fault_message数据初始化一个SocketSource类。

    - 当为DATA_FROM_SERIAL模式时，初始化两个SerialSource类，分别负责串口命令的发送，串口数据的接收，同时初始化一个SerialClient类，用于管理两个SerialSource类，实现串口命令的配置。

    - 当为DATA_FROM_ROS_PACKET模式时，不需要接收数据。

- 调用SetThreadNum函数，用于几个主要线程的启动，包括：

    - ReceiveUdpThread线程，用于接收udp数据，该线程会将接收到的数据放入origin_packets_buffer_中，供HesaiLidarSdk类的Run()中使用。

    - ReceiveUdpThreadFaultMessage线程，当fault_message为独立端口时，接收fault_message数据。

    - ParserThread线程，在单线程模式下，该线程会取用HesaiLidarSdk类的Run()函数放入decoded_packets_buffer_中的包序号，调用UdpParser类的ComputeXYZI函数，实现点云的解析功能。在多线程模式下，该函数负责包序号的分发，负责给多个HandleThread函数提供包序号。

    - HandleThread线程，多线程模式下启用，用于接收ParserThread的分发数据，并调用UdpParser类的ComputeXYZI函数，实现点云的解析功能。

- 根据传入参数use_ptc_connected，判断是否需要使用PTC连接，用于雷达参数文件的获取，以及一些雷达模式的配置。初始化PtcClient类，在PtcClient构造函数中会拉起独立的线程尝试异步PTC连接，因此该构造函数会很快返回，后续使用PtcClient类做通讯时，需要首先判断是否连接成功。

- 初始化雷达型号，等待接收到一包有效的udp点云数据包，将其传入UdpParser类的DecodePacket函数中，会根据点云包中携带的版本号来初始化雷达类型。所有类型雷达的类均继承类GeneralParser，支持型号见UdpParser中文件所示。

- 检查PTC连接，当PTC连接成功后，尝试通过PTC获取雷达的参数文件，如果获取失败，则会加载参数中配置路径下对应的参数文件。

## 3. UdpParser类

- 该类包含一个GeneralParser类的实例化对象，大部分函数实现均调用GeneralParser类中对应的函数。

- 在该类DecodePacket函数中，当第一次调用时，会使用CreatGeneralParser函数初始化雷达类型。后续调用GeneralParser类的DecodePacket函数做点云数据解析。在DATA_FROM_PCAP模式下，实现了根据点云时间戳来模拟播放频率的功能。

## 4. GeneralParser类

- 根据雷达型号，查看对应子类中的函数实现。

- DecodePacket函数，主要功能为：点云包分帧，时间戳获取，丢包统计，IMU数据获取等，将点云udp数据统一按顺序放入frame.point_cloud_raw_data中。

- ComputeXYZI函数，用于将点云udp数据包解析为最终的xyz坐标数据，通过定义的点云结构，取用对应字段的数据，并结合参数文件，计算出最终的xyz坐标，同步提取反射率等信息。

- LoadCorrection**函数，用于加载角度参数文件，所有雷达必备的参数文件，影响最终的解析结果。

- LoadFiretimes**函数，用于加载发光时间参数文件，部分雷达需要，微调解析结果。