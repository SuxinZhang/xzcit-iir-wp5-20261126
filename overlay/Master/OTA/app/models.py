"""Pydantic models for the independent OTA agent.
独立 OTA 代理使用的 Pydantic 数据模型。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ArtifactEntry(BaseModel):
    """One optional artifact in a release manifest.
    发布清单中的一个可选升级产物。
    """

    path: str
    version: str | None = None
    sha256: str
    size_bytes: int
    labels_path: str | None = None


class ManifestTarget(BaseModel):
    """Target compatibility fields from manifest.json.
    来自 manifest.json 的目标兼容性字段。
    """

    mcu: str
    chassis_type: str
    host_arch: str


class ReleaseManifest(BaseModel):
    """Validated release manifest.
    已校验的发布清单。
    """

    schema_version: int = 1
    release_version: str
    created_at: str = ''
    target: ManifestTarget
    artifacts: dict[str, ArtifactEntry] = Field(default_factory=dict)


class InterlockStatus(BaseModel):
    """Status of one OTA pre-flight interlock.
    单项 OTA 预检互锁状态。
    """

    lock_id: str
    name: str
    passed: bool
    detail: str = ''


class OtaStatus(BaseModel):
    """Current OTA status returned to the management UI.
    返回给管理端的当前 OTA 状态。
    """

    versions: dict[str, str] = Field(default_factory=dict)
    interlocks: list[InterlockStatus] = Field(default_factory=list)
    busy: bool = False
    last_job: dict | None = None
    history: list[dict] = Field(default_factory=list)


class ApplyRequest(BaseModel):
    """Request to apply an already uploaded package.
    对已上传升级包执行应用的请求。
    """

    scope: str = 'all'  # all | firmware | master | model
    package_id: str = ''


class UploadPreview(BaseModel):
    """Result of uploading and pre-checking an offline package.
    离线上传包的预检结果。
    """

    package_id: str
    release_version: str
    target: dict
    artifacts: dict
    warnings: list[str] = Field(default_factory=list)
