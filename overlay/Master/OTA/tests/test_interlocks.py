"""Tests for the five OTA pre-flight interlocks.
OTA 五重预检互锁测试。
"""

from app.interlocks import InterlockInputs, all_passed, evaluate_interlocks


def _inputs(**overrides):
    values = dict(
        vx_mps=0.0, vz_rad_s=0.0, nav_active=False, patrol_active=False,
        sos_active=False, battery_pct=100.0, charging=False,
        target_mcu='STM32F407VET6', chassis_type='DIFF', host_arch='aarch64',
        manifest_target={'mcu': 'STM32F407VET6', 'chassis_type': 'DIFF', 'host_arch': 'aarch64'},
    )
    values.update(overrides)
    return InterlockInputs(**values)


def test_all_interlocks_green_for_safe_stationary_robot():
    """A safe stationary robot passes all five pre-flight checks.
    安全静止机器人通过全部五项预检。
    """
    statuses = evaluate_interlocks(_inputs())
    assert all_passed(statuses)


def test_moving_sos_low_battery_and_wrong_target_are_blocked():
    """Each hard lock independently blocks an unsafe update.
    每个硬锁都能独立拦截不安全升级。
    """
    cases = [
        _inputs(vx_mps=0.5),
        _inputs(vz_rad_s=0.5),
        _inputs(patrol_active=True),
        _inputs(sos_active=True),
        _inputs(battery_pct=20.0, charging=False),
        _inputs(manifest_target={'mcu': 'MECANUM', 'chassis_type': 'MECANUM', 'host_arch': 'aarch64'}),
    ]
    for item in cases:
        assert not all_passed(evaluate_interlocks(item))


def test_charging_allows_low_battery_update():
    """Charging at 20% battery satisfies LOCK-3.
    20% 电量但正在充电时满足 LOCK-3。
    """
    statuses = evaluate_interlocks(_inputs(battery_pct=20.0, charging=True))
    assert all_passed(statuses)


def test_version_echo_lock_is_post_flash_only():
    """LOCK-5 is enforced only when post_flash is requested.
    仅在 post_flash=True 时强制 LOCK-5。
    """
    assert all_passed(evaluate_interlocks(_inputs(), post_flash=False))
    assert not all_passed(evaluate_interlocks(_inputs(version_match=False), post_flash=True))
