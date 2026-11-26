"""Runtime settings for the independent OTA agent.
独立 OTA 代理的运行时配置。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    """OTA agent process settings resolved from environment variables.
    由环境变量解析的 OTA 代理进程配置。
    """

    host: str = '127.0.0.1'
    port: int = 8090
    package_dir: Path = Path('/var/lib/iir-ota/packages')
    work_dir: Path = Path('/var/lib/iir-ota/work')
    firmware_version: str = '0.0.0'
    master_version: str = '0.0.0'
    model_version: str = '0.0.0'
    target_mcu: str = 'STM32F407VET6'
    chassis_type: str = 'DIFF'
    host_arch: str = 'aarch64'

    @classmethod
    def from_env(cls) -> 'Settings':
        """Build settings from ``IIR_OTA_*`` environment variables.
        从 ``IIR_OTA_*`` 环境变量构建配置。
        """
        return cls(
            host=os.environ.get('IIR_OTA_HOST', '127.0.0.1'),
            port=int(os.environ.get('IIR_OTA_PORT', '8090')),
            package_dir=Path(os.environ.get('IIR_OTA_PACKAGE_DIR', '/var/lib/iir-ota/packages')).expanduser(),
            work_dir=Path(os.environ.get('IIR_OTA_WORK_DIR', '/var/lib/iir-ota/work')).expanduser(),
            firmware_version=os.environ.get('IIR_OTA_FW_VERSION', '0.0.0'),
            master_version=os.environ.get('IIR_OTA_MASTER_VERSION', '0.0.0'),
            model_version=os.environ.get('IIR_OTA_MODEL_VERSION', '0.0.0'),
            target_mcu=os.environ.get('IIR_OTA_TARGET_MCU', 'STM32F407VET6'),
            chassis_type=os.environ.get('IIR_OTA_CHASSIS_TYPE', 'DIFF'),
            host_arch=os.environ.get('IIR_OTA_HOST_ARCH', 'aarch64'),
        )
