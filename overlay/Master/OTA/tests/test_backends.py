"""Tests for host and model atomic update/rollback backends.
主机与模型原子更新/回滚后端测试。
"""

from pathlib import Path

from app.backends import HostUpdater, ModelUpdater, MockFlasherBackend


def test_host_updater_switches_and_rolls_back(tmp_path):
    """Switch current -> previous and roll back using symlinks.
    使用软链接切换 current -> previous 并回滚。
    """
    root = tmp_path / 'iir'
    release_a = tmp_path / 'release-a'
    release_b = tmp_path / 'release-b'
    release_a.mkdir(); release_b.mkdir()
    (release_a / 'version').write_text('a', encoding='utf-8')
    (release_b / 'version').write_text('b', encoding='utf-8')
    restarts = []
    updater = HostUpdater(root, restart=lambda: restarts.append(1) or True,
                          health_check=lambda: True)
    result_a = updater.apply(release_a)
    result_b = updater.apply(release_b)
    assert result_a['success'] and result_b['success']
    assert (root / 'current').resolve() == root / 'releases' / 'release-b'
    rollback = updater.rollback()
    assert rollback['success']
    assert (root / 'current').resolve() == root / 'releases' / 'release-a'


def test_model_updater_switches_and_rolls_back(tmp_path):
    """Switch model current and roll back on demand.
    切换模型 current 并按需回滚。
    """
    root = tmp_path / 'iir'
    model_a = tmp_path / 'model-a'
    model_b = tmp_path / 'model-b'
    model_a.mkdir(); model_b.mkdir()
    updater = ModelUpdater(root, restart=lambda: True, health_check=lambda: True)
    assert updater.apply(model_a)['success']
    assert updater.apply(model_b)['success']
    assert (root / 'models' / 'current').resolve() == root / 'models' / 'model-b'
    assert updater.rollback()['success']
    assert (root / 'models' / 'current').resolve() == root / 'models' / 'model-a'


def test_mock_flasher_fails_at_injected_stage():
    """A mocked flasher failure is observable by the API/state machine.
    模拟刷写失败可被 API/状态机观察到。
    """
    backend = MockFlasherBackend(fail_at='FLASHING')
    try:
        backend.flash(Path('/tmp/fw.bin'), version='1.0.0', progress=lambda *_: None)
    except Exception as exc:
        assert 'FLASHING' in str(exc)
    else:
        raise AssertionError('expected flash failure')
