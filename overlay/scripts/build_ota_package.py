#!/usr/bin/env python3
"""Build a standard XZCIT-IIR OTA .tar.gz package.
构建标准 XZCIT-IIR OTA .tar.gz 升级包。

The script intentionally has no hardware dependency; it just collects already
built artifacts, computes SHA256/size, writes manifest.json and creates the
tar.gz consumed by the OTA agent.
本脚本不依赖硬件；只收集已构建产物、计算 SHA256/大小、写入 manifest.json 并
打包供 OTA 代理消费。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(staging: Path, source: Path, relative: str, version: str,
              **extra) -> dict:
    destination = staging / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    entry = {
        'path': relative,
        'version': version,
        'sha256': _sha256(destination),
        'size_bytes': destination.stat().st_size,
    }
    entry.update(extra)
    return entry


def build_package(output: Path, version: str, *, firmware: Path | None = None,
                  master_bundle: Path | None = None, model: Path | None = None,
                  labels: Path | None = None) -> Path:
    """Create a release archive and return its path.
    创建发布归档并返回路径。
    """
    with tempfile.TemporaryDirectory() as temp:
        staging = Path(temp) / 'package'
        staging.mkdir()
        artifacts = {}
        if firmware:
            artifacts['firmware'] = _artifact(staging, firmware, 'firmware/xzcit_iir_diff.bin', version)
        if master_bundle:
            artifacts['master_bundle'] = _artifact(staging, master_bundle, 'master/xzcit_iir_master.tar.gz', version)
        if model:
            extra = {}
            if labels:
                labels_dst = staging / 'models/labels.txt'
                labels_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(labels, labels_dst)
                extra['labels_path'] = 'models/labels.txt'
            artifacts['rknn_model'] = _artifact(staging, model, 'models/power_defect_v1.rknn', version, **extra)
        manifest = {
            'schema_version': 1,
            'release_version': version,
            'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
            'target': {'mcu': 'STM32F407VET6', 'chassis_type': 'DIFF', 'host_arch': 'aarch64'},
            'artifacts': artifacts,
        }
        (staging / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output, 'w:gz') as tar:
            for item in staging.iterdir():
                tar.add(item, arcname=item.name)
    return output


def main() -> int:
    """Parse CLI arguments and build the package.
    解析命令行参数并构建升级包。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--firmware')
    parser.add_argument('--master-bundle')
    parser.add_argument('--model')
    parser.add_argument('--labels')
    args = parser.parse_args()
    build_package(Path(args.output), args.version,
                  firmware=Path(args.firmware) if args.firmware else None,
                  master_bundle=Path(args.master_bundle) if args.master_bundle else None,
                  model=Path(args.model) if args.model else None,
                  labels=Path(args.labels) if args.labels else None)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
