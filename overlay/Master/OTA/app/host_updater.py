"""Host updater module alias and production implementation re-export.
主机更新模块别名与生产实现重新导出。
"""

from .backends import HostUpdater, MockHostUpdater

__all__ = ['HostUpdater', 'MockHostUpdater']
