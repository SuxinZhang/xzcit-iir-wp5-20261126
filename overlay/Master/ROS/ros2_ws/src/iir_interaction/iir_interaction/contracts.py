"""Define the metadata shared by Gateway and the future audio adapter.
定义 Gateway 与后续音频适配器共用的元数据。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AudioSource(str, Enum):
    """Identify output sources without carrying audio bytes.
    标识输出来源，不携带音频字节。
    """

    SOS = 'sos'
    REMOTE_ANNOUNCEMENT = 'remote_announcement'
    INTERCOM = 'intercom'
    PATROL_TTS = 'patrol_tts'
    LOCAL_DIALOGUE = 'local_dialogue'


@dataclass(frozen=True)
class AudioRequest:
    """Reserve output using a unique request ID and a trusted source.
    使用唯一请求标识与可信来源预留音频输出。
    """

    request_id: str
    source: AudioSource

    def __post_init__(self):
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ValueError('request_id must be a non-empty string / 请求标识必须为非空字符串')
        object.__setattr__(self, 'source', AudioSource(self.source))


@dataclass(frozen=True)
class AudioDecision:
    """Report a reservation decision, not physical playback completion.
    报告预留决策，不表示物理播放已完成。
    """

    accepted: bool
    owner: AudioRequest
    interrupted: Optional[AudioRequest]
