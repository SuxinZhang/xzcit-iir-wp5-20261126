"""Tests for safe OTA archive parsing and manifest verification.
安全 OTA 归档解析与 manifest 校验测试。
"""

import hashlib
import json
import tarfile
from pathlib import Path

import pytest

from app.manifest import PackageError, load_package


def _make_package(tmp_path: Path, *, include: bool = True) -> Path:
    root = tmp_path / 'package'
    root.mkdir()
    artifact = root / 'firmware.bin'
    payload = b'IIR-OTA-FIRMWARE'
    artifact.write_bytes(payload)
    manifest = {
        'schema_version': 1,
        'release_version': '1.2.0',
        'created_at': '2026-11-26T12:00:00Z',
        'target': {'mcu': 'STM32F407VET6', 'chassis_type': 'DIFF', 'host_arch': 'aarch64'},
        'artifacts': {
            'firmware': {
                'path': 'firmware.bin',
                'version': '1.2.0',
                'sha256': hashlib.sha256(payload).hexdigest(),
                'size_bytes': len(payload),
            }
        },
    }
    (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    archive = tmp_path / 'release.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for item in root.iterdir():
            tar.add(item, arcname=item.name)
    if not include:
        archive.write_bytes(b'not a tar')
    return archive


def test_load_package_verifies_sha_and_size(tmp_path):
    """A valid package is extracted and its artifact hash matches.
    合法包被解压且产物哈希匹配。
    """
    package = load_package(_make_package(tmp_path), tmp_path / 'work')
    assert package.manifest.release_version == '1.2.0'
    assert package.artifact_paths['firmware'].read_bytes() == b'IIR-OTA-FIRMWARE'


def test_load_package_rejects_traversal_member(tmp_path):
    """Reject a tar member containing `..` before writing it.
    在写入前拒绝包含 `..` 的 tar 成员。
    """
    archive = tmp_path / 'evil.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        info = tarfile.TarInfo('../escape.txt')
        info.size = 1
        tar.addfile(info)
    with pytest.raises(PackageError):
        load_package(archive, tmp_path / 'work')


def test_load_package_rejects_corrupt_archive(tmp_path):
    """Reject a non-tar upload cleanly.
    干净拒绝非 tar 上传。
    """
    with pytest.raises((PackageError, tarfile.TarError)):
        load_package(_make_package(tmp_path, include=False), tmp_path / 'work')
