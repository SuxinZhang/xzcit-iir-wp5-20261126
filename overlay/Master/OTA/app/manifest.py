"""Safe OTA archive parsing and manifest verification.
安全的 OTA 归档解析与 manifest 校验。

All archives are extracted with explicit path checks; tar/zip slip, absolute
paths, symlinks and hardlinks are rejected before any file is written.
所有归档均执行显式路径检查；在写入文件前拒绝 Tar/Zip Slip、绝对路径、符号链接与硬链接。
"""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .models import ReleaseManifest


class PackageError(RuntimeError):
    """Raised when an OTA package is malformed or unsafe.
    OTA 包格式错误或存在安全隐患时抛出。
    """


@dataclass
class LoadedPackage:
    """A verified package extracted into a private directory.
    已校验并解压到独立目录的升级包。
    """

    package_dir: Path
    manifest: ReleaseManifest
    artifact_paths: dict[str, Path]


def _safe_member(member: tarfile.TarInfo) -> PurePosixPath:
    """Validate one tar member path and reject links/traversal.
    校验单个 tar 成员路径并拒绝链接/路径穿越。
    """
    name = PurePosixPath(member.name)
    if member.name.startswith('/') or any(part == '..' for part in name.parts):
        raise PackageError(f'unsafe archive path: {member.name!r}')
    if member.issym() or member.islnk():
        raise PackageError(f'links are not allowed in OTA packages: {member.name!r}')
    return name


def verify_sha256(path: Path, expected: str) -> bool:
    """Return True when the file SHA256 matches the manifest value.
    文件 SHA256 与清单值匹配时返回 True。
    """
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest().lower() == str(expected).lower()


def extract_package(archive: Path, target_dir: Path) -> Path:
    """Safely extract a .tar.gz package into an empty target directory.
    安全地将 .tar.gz 包解压到空目标目录。
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive, mode='r:gz') as tar:
        for member in tar.getmembers():
            relative = _safe_member(member)
            destination = target_dir.joinpath(*relative.parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise PackageError(f'unsupported tar member type: {member.name!r}')
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                raise PackageError(f'cannot read tar member: {member.name!r}')
            with destination.open('wb') as stream:
                stream.write(source.read())
    return target_dir


def load_package(archive: Path, work_dir: Path) -> LoadedPackage:
    """Extract, parse and fully verify an OTA package.
    解压、解析并完整校验一个 OTA 升级包。
    """
    archive = Path(archive)
    if not archive.is_file():
        raise PackageError('package archive does not exist')
    extract_root = extract_package(archive, Path(work_dir))
    manifest_path = extract_root / 'manifest.json'
    if not manifest_path.is_file():
        raise PackageError('manifest.json is missing at package root')
    try:
        raw = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest = ReleaseManifest.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        raise PackageError(f'invalid manifest.json: {exc}') from exc
    artifact_paths: dict[str, Path] = {}
    for name, artifact in manifest.artifacts.items():
        relative = PurePosixPath(artifact.path)
        if relative.is_absolute() or any(part == '..' for part in relative.parts):
            raise PackageError(f'unsafe artifact path for {name}: {artifact.path!r}')
        path = extract_root.joinpath(*relative.parts)
        if not path.is_file():
            raise PackageError(f'artifact {name} not found: {artifact.path!r}')
        if path.stat().st_size != int(artifact.size_bytes):
            raise PackageError(f'artifact {name} size mismatch')
        if not verify_sha256(path, artifact.sha256):
            raise PackageError(f'artifact {name} sha256 mismatch')
        artifact_paths[name] = path
    return LoadedPackage(extract_root, manifest, artifact_paths)


def remove_tree(path: Path) -> None:
    """Remove a private extraction directory without following symlinks.
    删除私有解压目录，不跟随符号链接。
    """
    import shutil

    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        os.unlink(path)
