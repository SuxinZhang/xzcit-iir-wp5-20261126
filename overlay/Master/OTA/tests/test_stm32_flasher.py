"""Tests for the production stm32flash wrapper with an injected command runner.
使用注入命令运行器的生产 stm32flash 包装测试。
"""

from pathlib import Path

from app.stm32_flasher import Stm32Flasher


class _Completed:
    def __init__(self, returncode=0, stdout='', stderr=''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_stm32_flasher_builds_expected_command(tmp_path):
    """Build a command containing the ROM ISP sequence and verify reset.
    构建包含 ROM ISP 时序与校验复位的命令。
    """
    firmware = tmp_path / 'firmware.bin'
    firmware.write_bytes(b'fw')
    calls = []
    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return _Completed()
    flasher = Stm32Flasher(device='/dev/iir_chassis', init_seq='rts,-dtr,dtr',
                           exit_seq='-rts,-dtr,dtr', command_runner=runner)
    result = flasher.flash(firmware, version='1.2.0', progress=lambda *_: None)
    assert result.success
    command = calls[0][0]
    assert '-w' in command and str(firmware) in command
    assert command[-1] == '/dev/iir_chassis'
    assert '-i' in command


def test_stm32_flasher_reports_failure(tmp_path):
    """Propagate stm32flash non-zero exit code as FlashError.
    将 stm32flash 非零退出码传播为 FlashError。
    """
    firmware = tmp_path / 'firmware.bin'
    firmware.write_bytes(b'fw')
    flasher = Stm32Flasher(command_runner=lambda *a, **k: _Completed(returncode=2, stderr='bad'))
    try:
        flasher.flash(firmware, version='1.2.0', progress=lambda *_: None)
    except Exception as exc:
        assert 'bad' in str(exc)
    else:
        raise AssertionError('expected flash failure')
