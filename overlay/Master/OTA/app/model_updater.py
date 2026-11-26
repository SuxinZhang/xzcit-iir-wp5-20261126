"""Model hot-update module alias and production implementation re-export.
模型热更新模块别名与生产实现重新导出。
"""

from .backends import MockModelUpdater, ModelUpdater

__all__ = ['MockModelUpdater', 'ModelUpdater']
