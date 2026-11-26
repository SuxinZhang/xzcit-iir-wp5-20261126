"""STM32 ST ROM ISP flashing backend using stm32flash.
使用 stm32flash 的 STM32 ST ROM ISP 刷写后端。

No custom bootloader is implemented. The CH9102F DTR/RTS sequence enters the
factory ROM ISP; the caller must release the serial owner before invoking this
backend.
不实现自定义 Bootloader；CH9102F DTR/RTS 序列进入出厂 ROM ISP；调用前必须由
调用方释放串口所有者。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .backends import FlashError, FlashResult, MockFlasherBackend


class Stm32Flasher:
    """Production wrapper around the ``stm32flash`` command line.
    ``stm32flash`` 命令行的生产封装。
    """

    def __init__(self, device: str = '/dev/iir_chassis', *,
                 init_seq: str = '', exit_seq: str = '',
                 timeout_s: float = 120.0, command_runner=subprocess.run):
        self.device = device
        self.init_seq = init_seq
        self.exit_seq = exit_seq
        self.timeout_s = float(timeout_s)
        self.command_runner = command_runner

    def command(self, firmware: Path) -> list[str]:
        """Build the stm32flash write/verify/reset command.
        构建 stm32flash 写入/校验/复位命令。
        """
        args = ['stm32flash', '-b', '115200']
        if self.init_seq:
            args += ['-i', self.init_seq]
        if self.exit_seq:
            args += ['-i', self.exit_seq]
        args += ['-w', str(firmware), '-v', '-g', '0x0', self.device]
        return args

    def flash(self, firmware: Path, *, version: str,
              progress) -> FlashResult:
        """Run stm32flash and return success/failure metadata.
        运行 stm32flash 并返回成功/失败元数据。
        """
        firmware = Path(firmware)
        if not firmware.is_file():
            raise FlashError(f'firmware not found: {firmware}')
        progress(5, 'BACKUP')
        try:
            completed = self.command_runner(
                self.command(firmware), capture_output=True, text=True,
                timeout=self.timeout_s, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FlashError(f'stm32flash execution failed: {exc}') from exc
        if completed.returncode != 0:
            raise FlashError((completed.stderr or completed.stdout or 'stm32flash failed').strip())
        progress(100, 'DONE')
        return FlashResult(True, version=version, message='stm32flash verified and reset')


__all__ = ['MockFlasherBackend', 'Stm32Flasher']
