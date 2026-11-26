"""API tests for the OTA agent with mock backends.
使用 Mock 后端的 OTA 代理 API 测试。
"""

import hashlib
import io
import json
import tarfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.backends import MockFlasherBackend, MockHostUpdater, MockModelUpdater
from app.main import create_app
from app.settings import Settings


def _package_bytes(tmp_path: Path) -> bytes:
    root = tmp_path / 'pkg'
    root.mkdir()
    (root / 'firmware.bin').write_bytes(b'firmware-image')
    manifest = {
        'schema_version': 1,
        'release_version': '1.2.0',
        'target': {'mcu': 'STM32F407VET6', 'chassis_type': 'DIFF', 'host_arch': 'aarch64'},
        'artifacts': {
            'firmware': {
                'path': 'firmware.bin',
                'version': '1.2.0',
                'sha256': hashlib.sha256(b'firmware-image').hexdigest(),
                'size_bytes': len(b'firmware-image'),
            }
        },
    }
    (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as tar:
        for item in root.iterdir():
            tar.add(item, arcname=item.name)
    return buffer.getvalue()


def test_status_upload_and_firmware_apply(tmp_path):
    """Status, package upload and mocked firmware apply complete.
    状态、包上传与模拟固件应用完成。
    """
    settings = Settings(package_dir=tmp_path / 'packages', work_dir=tmp_path / 'work')
    app = create_app(settings, flasher=MockFlasherBackend(),
                     host_updater=MockHostUpdater(), model_updater=MockModelUpdater())
    with TestClient(app) as client:
        status = client.get('/api/ota/status')
        assert status.status_code == 200
        assert len(status.json()['interlocks']) == 5
        upload = client.post('/api/ota/upload', files={
            'file': ('release.tar.gz', _package_bytes(tmp_path), 'application/gzip'),
        })
        assert upload.status_code == 200, upload.text
        package_id = upload.json()['package_id']
        applied = client.post('/api/ota/apply', json={'package_id': package_id, 'scope': 'firmware'})
        assert applied.status_code == 200, applied.text
        assert applied.json()['status'] == 'SUCCESS'


def test_apply_without_package_is_rejected(tmp_path):
    """Applying before uploading a package returns 404.
    未上传包就应用返回 404。
    """
    settings = Settings(package_dir=tmp_path / 'packages', work_dir=tmp_path / 'work')
    app = create_app(settings, flasher=MockFlasherBackend())
    with TestClient(app) as client:
        assert client.post('/api/ota/apply', json={'package_id': 'missing', 'scope': 'all'}).status_code == 404
