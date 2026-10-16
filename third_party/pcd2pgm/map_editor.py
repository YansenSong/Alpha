#!/usr/bin/env python3
"""
地图编辑器：对 PGM 栅格地图进行区域擦除/填充操作。

用法：
  # 查看地图信息
  python3 map_editor.py map.pgm info

  # 将矩形区域 [x1,y1]~[x2,y2] 擦除为空闲(254) 或 未知(205)
  python3 map_editor.py map.pgm erase-rect 10 20 30 40          # 设为空闲
  python3 map_editor.py map.pgm erase-rect 10 20 30 40 --unknown # 设为未知

  # 将矩形区域设为占据（画墙）
  python3 map_editor.py map.pgm fill-rect 10 20 30 40           # 设为占据

  # 用 YAML 中的 origin 坐标（世界坐标 → 像素坐标）
  python3 map_editor.py map.pgm erase-world 5.0 -3.0 8.0 0.0   # 世界坐标矩形
"""

import sys
import argparse
import yaml
from PIL import Image
import numpy as np
from pathlib import Path


def load_map(pgm_path):
    """加载 PGM 地图，返回 (image, width, height, data 二维数组)"""
    img = Image.open(pgm_path)
    data = np.array(img)
    print(f"Map: {pgm_path}")
    print(f"  Size: {img.size[0]} x {img.size[1]} pixels")
    print(f"  Mode: {img.mode}")
    return img, data


def load_yaml(yaml_path):
    with open(yaml_path) as f:
        return yaml.safe_load(f)


def world_to_pixel(wx, wy, yaml_info):
    """世界坐标 → 像素坐标"""
    ox = yaml_info['origin'][0]
    oy = yaml_info['origin'][1]
    res = yaml_info['resolution']
    px = int((wx - ox) / res)
    py = int((wy - oy) / res)
    return px, py


def show_info(data):
    unique, counts = np.unique(data, return_counts=True)
    total = data.size
    print(f"\n  Pixel distribution:")
    labels = {0: "OCCUPIED (black)", 254: "FREE (white)", 205: "UNKNOWN (gray)"}
    for v, c in zip(unique, counts):
        label = labels.get(v, f"other({v})")
        print(f"    {label}: {c} ({100*c/total:.1f}%)")


def erase_rect(data, x1, y1, x2, y2, fill_value=254):
    """擦除矩形区域。坐标会自动排序（取 min 和 max 对调也没关系）"""
    x1, x2 = sorted([x1, x2])
    y1, y2 = sorted([y1, y2])
    x1, y1 = max(0, x1), max(0, y1)
    x2 = min(data.shape[1] - 1, x2)
    y2 = min(data.shape[0] - 1, y2)

    label = {254: "FREE", 205: "UNKNOWN", 0: "OCCUPIED"}[fill_value]
    print(f"  Erasing rect [{x1},{y1}] → [{x2},{y2}] → {label}")
    data[y1:y2+1, x1:x2+1] = fill_value


def cmd_info(args):
    img, data = load_map(args.pgm)
    show_info(data)

    yaml_path = args.pgm.replace('.pgm', '.yaml')
    if Path(yaml_path).exists():
        info = load_yaml(yaml_path)
        res = info['resolution']
        ox, oy = info['origin'][0], info['origin'][1]
        W = data.shape[1] * res
        H = data.shape[0] * res
        print(f"\n  YAML info from {yaml_path}:")
        print(f"    resolution: {res} m/pixel")
        print(f"    origin: [{ox}, {oy}]")
        print(f"    coverage: {W:.2f} x {H:.2f} meters")
        print(f"\n  坐标换算: 像素(row,col) = 世界(x,y) → pixel_x = (world_x - {ox})/{res}, pixel_y = (world_y - {oy})/{res}")


def cmd_erase_rect(args):
    img, data = load_map(args.pgm)
    fill = 205 if args.unknown else 254
    erase_rect(data, args.x1, args.y1, args.x2, args.y2, fill)
    img = Image.fromarray(data)
    img.save(args.pgm)
    print(f"  Saved: {args.pgm}")


def cmd_fill_rect(args):
    img, data = load_map(args.pgm)
    erase_rect(data, args.x1, args.y1, args.x2, args.y2, fill_value=0)
    img = Image.fromarray(data)
    img.save(args.pgm)
    print(f"  Saved: {args.pgm}")


def cmd_erase_world(args):
    """世界坐标擦除"""
    yaml_path = args.pgm.replace('.pgm', '.yaml')
    if not Path(yaml_path).exists():
        print(f"ERROR: {yaml_path} not found. Put map.yaml next to map.pgm.")
        return
    info = load_yaml(yaml_path)
    img, data = load_map(args.pgm)

    px1, py1 = world_to_pixel(args.wx1, args.wy1, info)
    px2, py2 = world_to_pixel(args.wx2, args.wy2, info)
    print(f"  World [{args.wx1},{args.wy1}]~[{args.wx2},{args.wy2}]")
    print(f"  → Pixel [{px1},{py1}]~[{px2},{py2}]")

    fill = 205 if args.unknown else 254
    erase_rect(data, px1, py1, px2, py2, fill)
    img = Image.fromarray(data)
    img.save(args.pgm)
    print(f"  Saved: {args.pgm}")


def main():
    parser = argparse.ArgumentParser(description='PGM Map Editor')
    parser.add_argument('pgm', help='Path to map.pgm')

    sub = parser.add_subparsers(dest='cmd', required=True)

    p_info = sub.add_parser('info', help='Show map information')

    p_erase = sub.add_parser('erase-rect', help='Erase a pixel rectangle → FREE')
    p_erase.add_argument('x1', type=int); p_erase.add_argument('y1', type=int)
    p_erase.add_argument('x2', type=int); p_erase.add_argument('y2', type=int)
    p_erase.add_argument('--unknown', action='store_true', help='Set to unknown(205) instead of free(254)')

    p_fill = sub.add_parser('fill-rect', help='Fill a pixel rectangle → OCCUPIED')
    p_fill.add_argument('x1', type=int); p_fill.add_argument('y1', type=int)
    p_fill.add_argument('x2', type=int); p_fill.add_argument('y2', type=int)

    p_world = sub.add_parser('erase-world', help='Erase using world coordinates (meters)')
    p_world.add_argument('wx1', type=float); p_world.add_argument('wy1', type=float)
    p_world.add_argument('wx2', type=float); p_world.add_argument('wy2', type=float)
    p_world.add_argument('--unknown', action='store_true', help='Set to unknown(205) instead of free(254)')

    args = parser.parse_args()

    cmds = {
        'info': cmd_info,
        'erase-rect': cmd_erase_rect,
        'fill-rect': cmd_fill_rect,
        'erase-world': cmd_erase_world,
    }
    cmds[args.cmd](args)


if __name__ == '__main__':
    main()
