"""Five hard OTA pre-flight interlocks.
五重 OTA 预检硬互锁。

The checker is deliberately pure and injectable; ROS/Gateway adapters only
supply the current values.
校验器保持纯逻辑与可注入；ROS/Gateway 适配层只提供当前状态值。
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import InterlockStatus


@dataclass
class InterlockInputs:
    """Current machine state used by the five interlocks.
    五重互锁使用的当前设备状态。
    """

    vx_mps: float = 0.0
    vz_rad_s: float = 0.0
    nav_active: bool = False
    patrol_active: bool = False
    sos_active: bool = False
    battery_pct: float = 100.0
    charging: bool = False
    target_mcu: str = ''
    chassis_type: str = ''
    host_arch: str = ''
    manifest_target: dict | None = None
    version_match: bool | None = None


def evaluate_interlocks(inputs: InterlockInputs, *, post_flash: bool = False) -> list[InterlockStatus]:
    """Evaluate LOCK-1..LOCK-5 and return structured statuses.
    评估 LOCK-1..LOCK-5 并返回结构化状态。
    """
    target = inputs.manifest_target or {}
    expected = {
        'mcu': inputs.target_mcu,
        'chassis_type': inputs.chassis_type,
        'host_arch': inputs.host_arch,
    }
    manifest_match = all(
        target.get(key) == value for key, value in expected.items()
    ) and all(expected.values())

    lock1 = abs(inputs.vx_mps) < 0.01 and abs(inputs.vz_rad_s) < 0.02 \
        and not inputs.nav_active and not inputs.patrol_active
    lock2 = not inputs.sos_active
    lock3 = inputs.battery_pct >= 30.0 or inputs.charging
    lock5 = bool(inputs.version_match) if post_flash else True

    return [
        InterlockStatus(
            lock_id='LOCK-1', name='stationary',
            passed=lock1,
            detail='vehicle must be stationary and outside navigation/patrol' if not lock1 else 'stationary'),
        InterlockStatus(
            lock_id='LOCK-2', name='safety_state',
            passed=lock2,
            detail='SOS is active' if not lock2 else 'no active SOS'),
        InterlockStatus(
            lock_id='LOCK-3', name='battery',
            passed=lock3,
            detail=f'battery={inputs.battery_pct:.1f}% charging={inputs.charging}' if not lock3 else 'battery/charging sufficient'),
        InterlockStatus(
            lock_id='LOCK-4', name='manifest_target',
            passed=manifest_match,
            detail='manifest target mismatch' if not manifest_match else 'manifest target matches'),
        InterlockStatus(
            lock_id='LOCK-5', name='version_echo',
            passed=lock5,
            detail=('version echo verified' if lock5 else 'version echo timeout') if post_flash else 'checked after flashing'),
    ]


def all_passed(statuses: list[InterlockStatus]) -> bool:
    """Return True only when every interlock is green.
    仅当所有互锁均为绿灯时返回 True。
    """
    return bool(statuses) and all(item.passed for item in statuses)


__all__ = ['InterlockInputs', 'all_passed', 'evaluate_interlocks']
