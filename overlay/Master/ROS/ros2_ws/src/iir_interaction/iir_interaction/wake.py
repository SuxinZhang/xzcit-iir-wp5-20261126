"""Turn acoustic and textual wake evidence into one idempotent decision.
将声学与文本唤醒证据合并为一次幂等决策。
"""
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .voice import VoiceCommand, match_command, normalize_text

# Accept common homophones produced by the ASR for "小巡".  The acoustic
# keyword model still owns the authoritative hit; these aliases only recover
# the text path when the transcript is close but not exact.
# 接受识别模型对“小巡”的常见同音字；声学关键词模型仍是权威命中来源。
_WAKE_FIRST = '小晓筱肖'
_WAKE_SECOND = '巡寻群旬询循迅训逊熏勋勳薰能'

# "小群体" and "小群组" are ordinary words, not wake phrases.  Reject them
# even when a later command follows in the same segment.
# “小群体/小群组”是普通词，不属于唤醒短语。
_BLOCKED_AFTER_WAKE = ('体', '组')

# Fillers may sit between the wake word and the command ("小巡啊暂停巡逻").
# 唤醒词和指令之间可能出现语气词。
_FILLERS = '啊呀吧呢嗯哦呃那儿'

_REPLY = '我在'


@dataclass(frozen=True)
class WakeEvent:
    """Describe one segment's wake state for dispatch and structured logging.
    描述单个语音片段的唤醒状态，供派发与结构化日志使用。
    """

    woke: bool
    doubled: bool
    command: Optional[VoiceCommand]
    reply: Optional[str]
    source: str


class WakeSession:
    """Keep the short wake-to-command window across VAD segments.
    跨 VAD 片段维护短暂的“唤醒后继续说指令”窗口。
    """

    def __init__(self, wake: str, window_seconds: float = 6.0,
                 clock: Callable[[], float] = time.monotonic):
        base = normalize_text(wake)
        if not base:
            raise ValueError('wake word must not be empty')
        # Accept IIR_WAKE_WORD configured as either "小巡" or "小巡小巡".
        # 兼容配置为“小巡”或“小巡小巡”的唤醒词。
        while (len(base) >= 4 and len(base) % 2 == 0
               and base[:len(base) // 2] == base[len(base) // 2:]):
            base = base[:len(base) // 2]
        self.wake = base
        if base == '小巡':
            self.pattern = re.compile(f'[{_WAKE_FIRST}][{_WAKE_SECOND}]')
        else:
            self.pattern = re.compile(re.escape(base))
        self.window_seconds = max(0.0, float(window_seconds))
        self.clock = clock
        self.until = 0.0

    def _text_tokens(self, text):
        """Return (wake count, text without wake, text had a wake-looking token).
        返回（唤醒词数量、去掉唤醒词后的文本、文本是否出现过类似唤醒词）。
        """
        matches = list(self.pattern.finditer(text))
        if not matches:
            return 0, text, False
        # Drop matches that are actually the start of an ordinary word such as
        # "小群体"; the final match is validated by its tail below.
        # 丢弃“小群体”等普通词中的伪唤醒，最后一个匹配由尾部规则校验。
        kept = [match for match in matches
                if match is matches[-1]
                or text[match.end():match.end() + 1] not in _BLOCKED_AFTER_WAKE]
        if not kept:
            return 0, text, True
        matches = kept
        tail = text[matches[-1].end():]
        if tail and tail[0] in _BLOCKED_AFTER_WAKE:
            return 0, text, True
        # A single wake word must be followed by a command or only fillers;
        # a repeated wake word is already strong evidence and may be followed
        # by any speech ("小巡小巡不要暂停巡逻" still deserves a reply).
        # 单个唤醒词后必须是指令或语气词；重复唤醒本身已是强证据。
        if len(matches) == 1 and tail and tail.lstrip(_FILLERS):
            if match_command(tail) is not None:
                return 1, self.pattern.sub('', text), True
            # A speaker who repeats the wake word can have the second copy
            # garbled by the recognizer ("小巡小巡" heard as "小寻小声" or
            # "小能小的意思").  The garbled copy still starts with the wake
            # word's first character, so a tail that begins with it is that
            # repetition and not unrelated speech ("小巡今天…" keeps its
            # unrelated tail and is still ignored).
            # 重复唤醒时第二遍可能被识别成别的词，但开头仍是唤醒词首字，
            # 因此以该字开头的尾部按重复计。
            if tail[0] in _WAKE_FIRST:
                return 2, self.pattern.sub('', text), True
            return 0, text, True
        return len(matches), self.pattern.sub('', text), True

    def handle(self, text: str, keyword: str = '') -> WakeEvent:
        """Merge KWS and ASR evidence, then return the action for this segment.
        合并关键词模型与识别文本的证据，返回本片段的动作。
        """
        now = self.clock()
        text_norm = normalize_text(text)
        keyword_norm = normalize_text(keyword)
        keyword_hit = bool(keyword_norm)
        text_count, remainder, text_had_wake_shape = self._text_tokens(text_norm)
        keyword_count = len(self.pattern.findall(keyword_norm)) if keyword_norm else 0
        if keyword_hit and keyword_count == 0:
            # The keyword model may return the configured token spelling
            # instead of the Chinese display text.  A doubled token string is
            # still a double wake. 关键词模型可能返回 token 拼写；重复两遍仍算双唤醒。
            half = len(keyword_norm) // 2
            keyword_count = 2 if half and keyword_norm[:half] == keyword_norm[half:] else 1
        count = max(text_count, keyword_count)
        woke = keyword_hit or text_count > 0
        doubled = count >= 2
        command = None
        source = 'none'

        if woke:
            if keyword_hit and text_count:
                source = 'kws+text'
            elif keyword_hit:
                source = 'kws'
            else:
                source = 'text'
            # If the transcript only had a wake-shaped token that failed the
            # tail check ("小群体"), do not mine a command from the same text.
            # 若文本只出现类似唤醒词但未通过尾部检查（如“小群体”），
            # 不从同一句里提取指令。
            if text_count > 0 or not text_had_wake_shape:
                command = match_command(remainder)
        elif now < self.until:
            command = match_command(text_norm)
            if command is not None:
                source = 'window'

        if command is not None:
            self.until = 0.0
            return WakeEvent(woke=woke, doubled=doubled if woke else False,
                             command=command, reply=None, source=source)

        if woke:
            self.until = now + self.window_seconds
            return WakeEvent(woke=True, doubled=doubled, command=None,
                             reply=_REPLY if doubled else None, source=source)

        return WakeEvent(woke=False, doubled=False, command=None,
                         reply=None, source='none')
