"""FastAPI application for the independent OTA agent.
独立 OTA 代理的 FastAPI 应用。

The service is intentionally independent from ``iir.target``; the systemd unit
must not be ``PartOf=iir.target``. The default runtime uses mock backends unless
real STM32/systemd/model backends are injected by deployment.
本服务有意独立于 ``iir.target``；systemd 单元不得设置 ``PartOf=iir.target``。
默认运行时使用 Mock 后端，部署时再注入真实 STM32/systemd/模型后端。
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from .backends import MockFlasherBackend, MockHostUpdater, MockModelUpdater
from .interlocks import InterlockInputs, all_passed, evaluate_interlocks
from .manifest import LoadedPackage, PackageError, load_package, remove_tree
from .models import ApplyRequest, InterlockStatus, OtaStatus, UploadPreview
from .settings import Settings


class OtaState:
    """In-memory state for the single active OTA job.
    单个活跃 OTA 任务的进程内状态。
    """

    def __init__(self):
        self.package: LoadedPackage | None = None
        self.package_id = ''
        self.busy = False
        self.last_job: dict | None = None
        self.history: list[dict] = []
        self.progress = 0
        self.stage = 'IDLE'


class ConnectionManager:
    """Fan out OTA progress messages to connected management clients.
    向已连接管理客户端广播 OTA 进度消息。
    """

    def __init__(self):
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register one WebSocket client.
        接受并登记一个 WebSocket 客户端。
        """
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove one WebSocket client.
        移除一个 WebSocket 客户端。
        """
        async with self._lock:
            self._clients.discard(websocket)

    async def broadcast(self, payload: dict) -> None:
        """Send a JSON payload to all connected clients.
        向所有已连接客户端发送 JSON 载荷。
        """
        text = json.dumps(payload, ensure_ascii=False)
        async with self._lock:
            targets = list(self._clients)
        for websocket in targets:
            try:
                await websocket.send_text(text)
            except Exception:
                await self.disconnect(websocket)


def _default_inputs(settings: Settings) -> InterlockInputs:
    """Return a safe mocked machine snapshot for a fresh/offline deployment.
    为全新/离线部署返回安全的模拟设备快照。
    """
    return InterlockInputs(
        target_mcu=settings.target_mcu,
        chassis_type=settings.chassis_type,
        host_arch=settings.host_arch,
        battery_pct=100.0,
        charging=False,
    )


def create_app(settings: Settings | None = None, *,
               flasher=None, host_updater=None, model_updater=None,
               interlock_provider=None) -> FastAPI:
    """Create the OTA FastAPI application with injectable backends.
    使用可注入后端创建 OTA FastAPI 应用。
    """
    settings = settings or Settings.from_env()
    settings.package_dir.mkdir(parents=True, exist_ok=True)
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    flasher = flasher or MockFlasherBackend()
    host_updater = host_updater or MockHostUpdater()
    model_updater = model_updater or MockModelUpdater()
    provider = interlock_provider or (lambda: _default_inputs(settings))
    state = OtaState()
    manager = ConnectionManager()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        """Yield the application lifespan; cleanup is best-effort.
        运行应用生命周期；清理工作为尽力而为。
        """
        yield

    app = FastAPI(title='XZCIT-IIR OTA Agent', version='0.1.0', lifespan=lifespan)

    @app.get('/api/ota/status', response_model=OtaStatus)
    async def status():
        """Return versions, five interlock states and recent history.
        返回版本、五重互锁状态与最近历史。
        """
        inputs = await run_in_threadpool(provider)
        return OtaStatus(
            versions={
                'firmware': settings.firmware_version,
                'master': settings.master_version,
                'model': settings.model_version,
            },
            interlocks=await run_in_threadpool(evaluate_interlocks, inputs),
            busy=state.busy,
            last_job=state.last_job,
            history=state.history[-20:],
        )

    @app.post('/api/ota/upload', response_model=UploadPreview)
    async def upload(file: UploadFile = File(...)):
        """Receive an offline .tar.gz package and run the pre-check.
        接收离线 .tar.gz 升级包并执行预检。
        """
        if not (file.filename or '').endswith('.tar.gz'):
            raise HTTPException(status_code=400, detail='package must be a .tar.gz')
        package_id = uuid.uuid4().hex[:16]
        archive = settings.package_dir / f'{package_id}.tar.gz'
        with archive.open('wb') as stream:
            shutil.copyfileobj(file.file, stream)
        work = settings.work_dir / package_id
        try:
            loaded = await run_in_threadpool(load_package, archive, work)
        except PackageError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if state.package is not None:
            remove_tree(state.package.package_dir)
        state.package = loaded
        state.package_id = package_id
        artifacts = {
            name: {'path': str(path), 'version': loaded.manifest.artifacts[name].version}
            for name, path in loaded.artifact_paths.items()
        }
        return UploadPreview(
            package_id=package_id,
            release_version=loaded.manifest.release_version,
            target=loaded.manifest.target.model_dump(),
            artifacts=artifacts,
        )

    @app.post('/api/ota/apply')
    async def apply(request: ApplyRequest):
        """Check the five interlocks and execute the selected update scope.
        校验五重互锁并执行选定的更新范围。
        """
        if request.scope not in ('all', 'firmware', 'master', 'model'):
            raise HTTPException(status_code=400, detail='invalid scope')
        if state.busy:
            raise HTTPException(status_code=409, detail='another OTA job is running')
        if state.package is None or state.package_id != request.package_id:
            raise HTTPException(status_code=404, detail='package not found; upload first')
        inputs = await run_in_threadpool(provider)
        inputs.manifest_target = state.package.manifest.target.model_dump()
        interlocks = await run_in_threadpool(evaluate_interlocks, inputs)
        if not all_passed(interlocks):
            return {'status': 'blocked', 'interlocks': [item.model_dump() for item in interlocks]}
        state.busy = True
        state.stage = 'PRECHECK'
        state.progress = 0
        await manager.broadcast({'t': 'ota_progress', 'stage': state.stage, 'percent': 0})
        job = {'job_id': uuid.uuid4().hex[:12], 'scope': request.scope, 'status': 'running'}
        try:
            if request.scope in ('all', 'firmware'):
                firmware = state.package.artifact_paths.get('firmware')
                if firmware is None:
                    raise HTTPException(status_code=400, detail='firmware artifact missing')
                result = await run_in_threadpool(
                    flasher.flash, firmware, version=state.package.manifest.release_version,
                    progress=lambda percent, stage: _record_progress(state, percent, stage))
                job['firmware'] = result.__dict__ if hasattr(result, '__dict__') else str(result)
            if request.scope in ('all', 'master'):
                master = state.package.artifact_paths.get('master_bundle')
                if master is None:
                    raise HTTPException(status_code=400, detail='master_bundle artifact missing')
                result = await run_in_threadpool(host_updater.apply, master)
                job['master'] = result
            if request.scope in ('all', 'model'):
                model = state.package.artifact_paths.get('rknn_model')
                if model is None:
                    raise HTTPException(status_code=400, detail='rknn_model artifact missing')
                result = await run_in_threadpool(model_updater.apply, model)
                job['model'] = result
            job['status'] = 'SUCCESS'
            state.stage = 'DONE'
            state.progress = 100
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).exception('OTA apply failed')
            job['status'] = 'FAILED'
            job['message'] = str(exc)
            state.stage = 'FAILED'
        finally:
            state.busy = False
            state.last_job = job
            state.history.append(dict(job))
            await manager.broadcast({'t': 'ota_progress', 'stage': state.stage,
                                     'percent': state.progress, 'job': job})
        if job['status'] != 'SUCCESS':
            raise HTTPException(status_code=500, detail=job)
        return job

    @app.post('/api/ota/rollback')
    async def rollback():
        """Trigger host and model rollback for the previous release.
        触发主机与模型回滚到上一版本。
        """
        host_result = await run_in_threadpool(host_updater.rollback)
        model_result = await run_in_threadpool(model_updater.rollback)
        job = {'status': 'ROLLED_BACK', 'host': host_result, 'model': model_result}
        state.last_job = job
        state.history.append(dict(job))
        await manager.broadcast({'t': 'ota_progress', 'stage': 'ROLLED_BACK', 'percent': 0, 'job': job})
        return job

    @app.websocket('/ws/ota/progress')
    async def progress_socket(websocket: WebSocket):
        """Push status on connect and live job progress afterward.
        连接时推送状态，之后推送实时任务进度。
        """
        await manager.connect(websocket)
        try:
            await websocket.send_json({'t': 'ota_status', 'stage': state.stage,
                                       'percent': state.progress, 'busy': state.busy})
            while True:
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=20.0)
                except asyncio.TimeoutError:
                    await websocket.send_json({'t': 'ping'})
        except WebSocketDisconnect:
            pass
        finally:
            await manager.disconnect(websocket)

    return app


def _record_progress(state: OtaState, percent: int, stage: str) -> None:
    """Record one progress event without blocking the flasher callback.
    在不阻塞刷写回调的情况下记录一条进度事件。
    """
    state.progress = int(percent)
    state.stage = str(stage)
