"""Flash, host and model backends with mock implementations for CI.
刷写、主机与模型后端，并为 CI 提供 Mock 实现。
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


class FlashError(RuntimeError):
    """Raised when STM32 flashing or verification fails.
    STM32 刷写或校验失败时抛出。
    """


@dataclass
class FlashResult:
    """Result of one mocked/real flashing operation.
    一次模拟/真实刷写操作的结果。
    """

    success: bool
    version: str = ''
    message: str = ''
    rolled_back: bool = False


class FlasherBackend(Protocol):
    """Protocol for the STM32 flasher backend.
    STM32 刷写后端的协议。
    """

    def flash(self, firmware: Path, *, version: str, progress: Callable[[int, str], None]) -> FlashResult:
        """Flash one firmware image and return the result.
        刷写一份固件镜像并返回结果。
        """


class MockFlasherBackend:
    """Deterministic flasher used by OTA unit tests.
    OTA 单元测试使用的确定性刷写后端。
    """

    def __init__(self, *, fail_at: str | None = None):
        self.fail_at = fail_at
        self.calls: list[dict] = []

    def flash(self, firmware: Path, *, version: str,
              progress: Callable[[int, str], None]) -> FlashResult:
        """Simulate BACKUP/FLASHING/VERIFYING stages.
        模拟 BACKUP/FLASHING/VERIFYING 阶段。
        """
        self.calls.append({'firmware': str(firmware), 'version': version})
        for percent, stage in ((10, 'BACKUP'), (40, 'FLASHING'), (80, 'VERIFYING')):
            if self.fail_at == stage:
                raise FlashError(f'injected failure at {stage}')
            progress(percent, stage)
        progress(100, 'DONE')
        return FlashResult(True, version=version, message='mock flash complete')


class MockHostUpdater:
    """Deterministic host updater used by OTA unit tests.
    OTA 单元测试使用的确定性主机更新后端。
    """

    def __init__(self, *, health_ok: bool = True):
        self.health_ok = health_ok
        self.calls: list[str] = []

    def apply(self, release_dir: Path, *, restart: bool = True) -> dict:
        """Record a host update without touching /opt/iir.
        记录一次主机更新，不触碰 /opt/iir。
        """
        self.calls.append(str(release_dir))
        return {'success': self.health_ok, 'version': Path(release_dir).name}

    def rollback(self) -> dict:
        """Record a host rollback request.
        记录一次主机回滚请求。
        """
        self.calls.append('rollback')
        return {'success': True}


class MockModelUpdater:
    """Deterministic model updater used by OTA unit tests.
    OTA 单元测试使用的确定性模型更新后端。
    """

    def __init__(self, *, load_ok: bool = True):
        self.load_ok = load_ok
        self.calls: list[str] = []

    def apply(self, model_dir: Path) -> dict:
        """Record a model hot-update without restarting services.
        记录一次模型热更新，不重启服务。
        """
        self.calls.append(str(model_dir))
        return {'success': self.load_ok, 'version': Path(model_dir).name}

    def rollback(self) -> dict:
        """Record a model rollback request.
        记录一次模型回滚请求。
        """
        self.calls.append('rollback')
        return {'success': True}


class HostUpdater:
    """Real host updater using atomic /opt/iir/current symlinks.
    使用 /opt/iir/current 原子软链接的真实主机更新器。
    """

    def __init__(self, root: Path, *, restart: Callable[[], bool],
                 health_check: Callable[[], bool]):
        self.root = Path(root)
        self.restart = restart
        self.health_check = health_check

    def _atomic_link(self, link: Path, target: Path) -> None:
        """Atomically replace a symlink without deleting its target.
        原子替换符号链接，不删除目标目录。
        """
        temp = link.with_name(link.name + '.new')
        if temp.exists() or temp.is_symlink():
            temp.unlink()
        os.symlink(target, temp)
        os.replace(temp, link)

    def apply(self, release_dir: Path, *, restart: bool = True) -> dict:
        """Install a release directory and atomically switch current.
        安装发布目录并原子切换 current。
        """
        release_dir = Path(release_dir)
        if not release_dir.is_dir():
            raise FileNotFoundError(release_dir)
        releases = self.root / 'releases'
        releases.mkdir(parents=True, exist_ok=True)
        destination = releases / release_dir.name
        if not destination.exists():
            shutil.copytree(release_dir, destination)
        current = self.root / 'current'
        previous = self.root / 'previous'
        if current.is_symlink():
            old_target = Path(os.readlink(current))
            self._atomic_link(previous, old_target)
        self._atomic_link(current, destination)
        if restart and not self.restart():
            return self.rollback()
        if not self.health_check():
            return self.rollback()
        return {'success': True, 'version': destination.name}

    def rollback(self) -> dict:
        """Switch current back to previous and restart services.
        将 current 切回 previous 并重启服务。
        """
        current = self.root / 'current'
        previous = self.root / 'previous'
        if not previous.is_symlink():
            return {'success': False, 'message': 'no previous release'}
        target = Path(os.readlink(previous))
        self._atomic_link(current, target)
        self.restart()
        return {'success': self.health_check(), 'version': target.name}


class ModelUpdater:
    """Real RKNN model hot updater with atomic current symlink.
    使用原子 current 软链接的真实 RKNN 模型热更新器。
    """

    def __init__(self, root: Path, *, restart: Callable[[], bool],
                 health_check: Callable[[], bool]):
        self.root = Path(root)
        self.restart = restart
        self.health_check = health_check

    def apply(self, model_dir: Path) -> dict:
        """Install a model directory, switch current and restart vision.
        安装模型目录、切换 current 并重启视觉服务。
        """
        model_dir = Path(model_dir)
        if not model_dir.is_dir():
            raise FileNotFoundError(model_dir)
        models = self.root / 'models'
        models.mkdir(parents=True, exist_ok=True)
        destination = models / model_dir.name
        if not destination.exists():
            shutil.copytree(model_dir, destination)
        current = self.root / 'models' / 'current'
        previous = self.root / 'models' / 'previous'
        if current.is_symlink():
            self._atomic_link(previous, Path(os.readlink(current)))
        self._atomic_link(current, destination)
        if not self.restart() or not self.health_check():
            return self.rollback()
        return {'success': True, 'version': destination.name}

    def _atomic_link(self, link: Path, target: Path) -> None:
        """Atomically replace a model symlink.
        原子替换模型软链接。
        """
        temp = link.with_name(link.name + '.new')
        if temp.exists() or temp.is_symlink():
            temp.unlink()
        os.symlink(target, temp)
        os.replace(temp, link)

    def rollback(self) -> dict:
        """Switch model current back to previous.
        将模型 current 切回 previous。
        """
        current = self.root / 'models' / 'current'
        previous = self.root / 'models' / 'previous'
        if not previous.is_symlink():
            return {'success': False, 'message': 'no previous model'}
        target = Path(os.readlink(previous))
        self._atomic_link(current, target)
        self.restart()
        return {'success': self.health_check(), 'version': target.name}


__all__ = [
    'FlashError', 'FlashResult', 'FlasherBackend', 'HostUpdater',
    'MockFlasherBackend', 'MockHostUpdater', 'MockModelUpdater', 'ModelUpdater',
]
