"""LPMS-IG1 binary LP-BUS transport (Linux, no external serial dependency)."""
import math
import os
import struct
import termios
import time


def packet(command, sensor_id=1, payload=b''):
    body = struct.pack('<HHH', sensor_id, command, len(payload)) + payload
    return b'\x3a' + body + struct.pack('<H', sum(body) & 0xffff) + b'\r\n'


class FrameParser:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        result = []
        while len(self.buffer) >= 11:
            if self.buffer[0] != 0x3a:
                del self.buffer[0]
                continue
            address, command, length = struct.unpack_from('<HHH', self.buffer, 1)
            if length > 512:
                del self.buffer[0]
                continue
            size = length + 11
            if len(self.buffer) < size:
                break
            frame = self.buffer[:size]
            checksum = struct.unpack_from('<H', frame, 7 + length)[0]
            if frame[-2:] != b'\r\n' or sum(frame[1:7 + length]) & 0xffff != checksum:
                del self.buffer[0]
                continue
            result.append((address, command, bytes(frame[7:7 + length])))
            del self.buffer[:size]
        return result


def decode(payload, mask, precision, radians):
    """Decode enabled fields in register bit order; return existing publisher units.

    Only floating point mode is supported: fixed point gyro scaling differs
    between firmware versions and must not be guessed.
    """
    if precision != 1:
        raise ValueError('RS232 requires LP-BUS 32-bit floating point precision')
    if mask & ~0x1ffff:
        raise ValueError('unsupported transmit mask')
    required = (1 << 1) | (1 << 7) | (1 << 9) | (1 << 11)
    if mask & required != required:
        raise ValueError('enable calibrated accel, aligned Gyro II, calibrated mag and quaternion')
    counts = [3] * 11 + [4, 3, 3, 1, 1, 1]
    expected = 4 + 4 * sum(n for bit, n in enumerate(counts) if mask & (1 << bit))
    if len(payload) != expected:
        raise ValueError(f'payload length {len(payload)} does not match mask ({expected})')
    fields = {}; offset = 4
    for bit, count in enumerate(counts):
        if mask & (1 << bit):
            values = struct.unpack_from('<' + 'f' * count, payload, offset)
            if not all(math.isfinite(v) for v in values):
                raise ValueError('non-finite sensor data')
            fields[bit] = values
            offset += count * 4
    q = fields[11]
    if not 0.5 < sum(v*v for v in q) < 1.5:
        raise ValueError('invalid quaternion norm')
    result = dict(zip(('ax_g', 'ay_g', 'az_g'), fields[1]))
    factor = 180 / math.pi if radians else 1.0
    result.update(zip(('gx_dps', 'gy_dps', 'gz_dps'), (v * factor for v in fields[7])))
    result.update(zip(('mx_uT', 'my_uT', 'mz_uT'), fields[9]))
    # LPMS reports world-to-body; conjugate to ROS body-to-world, as in
    # the IG1 ROS example. NWU->ENU is applied by the shared publisher.
    result.update(zip(('qw', 'qx', 'qy', 'qz'), (q[0], -q[1], -q[2], -q[3])))
    return result


class SerialBus:
    def __init__(self, port, baudrate, sensor_id):
        self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self.old = termios.tcgetattr(self.fd)
        self.parser = FrameParser()
        self.sensor_id = sensor_id
        self.settings = {}
        self.next_query = 0.0
        try:
            import fcntl
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            a = termios.tcgetattr(self.fd)
            a[0] = a[1] = a[3] = 0
            a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            a[4] = a[5] = getattr(termios, 'B' + str(baudrate))
            a[6][termios.VMIN] = a[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, a)
        except Exception:
            self.close()
            raise

    def recv(self, size):
        return os.read(self.fd, size)

    def samples(self):
        now = time.monotonic()
        if now >= self.next_query and len(self.settings) < 4:
            for command in (31, 35, 37, 137):
                if command not in self.settings:
                    os.write(self.fd, packet(command, self.sensor_id))
            self.next_query = now + 1.0
        result = []
        # Bound work per ROS callback, while draining several milliseconds of data.
        for _ in range(16):
            try:
                data = self.recv(65536)
            except BlockingIOError:
                break
            if not data:
                break
            for address, command, payload in self.parser.feed(data):
                if address != self.sensor_id:
                    continue
                if command in (31, 35, 37, 137) and len(payload) == 4:
                    self.settings[command] = struct.unpack('<I', payload)[0]
                elif command == 9 and all(c in self.settings for c in (31, 37, 137)):
                    result.append(decode(payload, self.settings[31], self.settings[137], self.settings[37]))
        return result

    def close(self):
        try:
            termios.tcsetattr(self.fd, termios.TCSANOW, self.old)
        finally:
            os.close(self.fd)
