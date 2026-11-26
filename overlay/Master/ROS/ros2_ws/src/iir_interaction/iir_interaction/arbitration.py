"""Apply WP5 priority rules without accessing microphones or speakers.
应用 WP5 优先级规则，不访问麦克风和喇叭。
"""

from typing import Optional

from .contracts import AudioDecision, AudioRequest, AudioSource


_PRIORITY = {
    AudioSource.SOS: 3,
    AudioSource.REMOTE_ANNOUNCEMENT: 2,
    AudioSource.INTERCOM: 2,
    AudioSource.PATROL_TTS: 1,
    AudioSource.LOCAL_DIALOGUE: 1,
}


class AudioArbiter:
    """Serialize calls in the adapter's single event loop.
    由适配器的单一事件循环串行调用。

    Ownership only reserves output; the adapter must stop and start media.
    所有权只预留输出；停止和启动媒体由适配器执行。
    """

    def __init__(self):
        self._owner: Optional[AudioRequest] = None

    @property
    def owner(self) -> Optional[AudioRequest]:
        """Expose the current reservation without implying device readiness.
        返回当前预留，不表示设备已就绪。
        """
        return self._owner

    def acquire(self, request: AudioRequest) -> AudioDecision:
        """Reject equal or lower priority and identify a preempted request.
        拒绝同级或低级请求，并标识被抢占的请求。
        """
        previous = self._owner
        if previous is not None:
            if previous.request_id == request.request_id:
                raise ValueError('request_id is already active / 请求标识已被占用')
            if _PRIORITY[request.source] <= _PRIORITY[previous.source]:
                return AudioDecision(False, previous, None)
        self._owner = request
        return AudioDecision(True, request, previous)

    def release(self, request_id: str) -> bool:
        """Release only the matching reservation; do not resume old audio.
        只释放匹配的预留，不恢复旧音频。
        """
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError('request_id must be a non-empty string / 请求标识必须为非空字符串')
        if self._owner is None or self._owner.request_id != request_id:
            return False
        self._owner = None
        return True
