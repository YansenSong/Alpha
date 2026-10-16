import math
import struct
import pytest
from imu.lpbus import FrameParser, packet, decode


def test_fragmented_and_corrupt_frames():
    parser = FrameParser()
    frame = packet(31, 1, struct.pack('<I', 80895))
    bad = bytearray(frame); bad[8] ^= 1
    assert parser.feed(b'noise' + bad + frame[:8]) == []
    assert parser.feed(frame[8:] + frame) == [(1, 31, struct.pack('<I', 80895))] * 2


def test_byte_checksum_with_large_header():
    frame = packet(0x1234, 0x5678, bytes(range(256)))
    assert FrameParser().feed(frame) == [(0x5678, 0x1234, bytes(range(256)))]


def test_dynamic_mask_units_and_quaternion():
    mask = sum(1 << b for b in (1, 7, 9, 11))
    payload = struct.pack('<I13f', 42, 0, 0, -1, 0, 0, math.pi, 10, 20, 30, .8, 0, 0, .6)
    sample = decode(payload, mask, 1, True)
    assert sample['gz_dps'] == pytest.approx(180)
    assert sample['qz'] == pytest.approx(-.6)
    assert sample['az_g'] == -1
    with pytest.raises(ValueError): decode(payload[:-1], mask, 1, True)
    with pytest.raises(ValueError): decode(payload, mask, 0, True)
    with pytest.raises(ValueError): decode(payload, 0, 1, True)


def test_serial_transport_queries_and_restores_settings():
    import os
    import pty
    import termios
    from imu.lpbus import SerialBus
    master, slave = pty.openpty()
    old = termios.tcgetattr(slave)
    bus = SerialBus(os.ttyname(slave), 921600, 1)
    try:
        assert bus.samples() == []
        queries = FrameParser().feed(os.read(master, 1024))
        assert [c for _, c, _ in queries] == [31, 35, 37, 137]
        os.write(master, packet(31, 1, struct.pack('<I', 80895)))
        import select
        assert select.select([bus.fd], [], [], 1)[0]
        bus.samples()
        assert bus.settings[31] == 80895
    finally:
        bus.close()
        assert termios.tcgetattr(slave) == old
        os.close(master)
        os.close(slave)
