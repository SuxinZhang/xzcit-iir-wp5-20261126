#!/usr/bin/env python3
import argparse
import subprocess

parser = argparse.ArgumentParser()
for name in ('chassis', 'lidar', 'camera'):
    parser.add_argument('--' + name, required=True)
args = parser.parse_args()
selected = []
rules = []
for name in ('chassis', 'lidar', 'camera'):
    device = getattr(args, name)
    result = subprocess.run(['udevadm', 'info', '--query=property', '--name', device],
                            check=True, capture_output=True, text=True)
    props = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    path = props['DEVPATH']
    subsystem = props['SUBSYSTEM']
    if subsystem != ('video4linux' if name == 'camera' else 'tty'):
        raise SystemExit(f'{name}: unexpected subsystem {subsystem}')
    if any(c in path for c in '"\\*?[]'):
        raise SystemExit(f'{name}: unsupported DEVPATH')
    if path in selected:
        raise SystemExit('selected devices overlap')
    selected.append(path)
    rules.append(f'SUBSYSTEM=="{subsystem}", DEVPATH=="{path}", SYMLINK+="iir_{name}"')
print('\n'.join(rules))
