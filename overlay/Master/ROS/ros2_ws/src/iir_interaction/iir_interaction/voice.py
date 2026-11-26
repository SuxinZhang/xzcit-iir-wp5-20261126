"""Map patrol events and recognized phrases to explicit WP5 contracts.
将巡逻事件与已识别短语映射为明确的 WP5 契约。
"""

import re
import unicodedata
from enum import Enum
from typing import Optional


class PatrolEvent(str, Enum):
    """Name the six announcement events required by WP5.
    定义 WP5 要求的六种播报事件。
    """

    DEPARTURE = 'departure'
    TURNING = 'turning'
    OBSTACLE = 'obstacle'
    ARRIVAL = 'arrival'
    LOW_BATTERY_RETURN = 'low_battery_return'
    SOS = 'sos'


class VoiceCommand(str, Enum):
    """Express business intents for the existing control authority to handle.
    表达业务意图，由现有控制授权链处理。
    """

    PAUSE_PATROL = 'pause_patrol'
    RESUME_PATROL = 'resume_patrol'
    REPORT_BATTERY = 'report_battery'
    CALL_ADMIN = 'call_admin'


_ANNOUNCEMENTS = {
    PatrolEvent.DEPARTURE: '开始巡逻。',
    PatrolEvent.TURNING: '前方转弯，请注意避让。',
    PatrolEvent.OBSTACLE: '前方有障碍物，暂停通行。',
    PatrolEvent.ARRIVAL: '已到达巡检点。',
    PatrolEvent.LOW_BATTERY_RETURN: '电量不足，返回充电。',
    PatrolEvent.SOS: '紧急呼救，请管理员处理。',
}

_COMMANDS = {
    '暂停巡逻': VoiceCommand.PAUSE_PATROL,
    '继续巡逻': VoiceCommand.RESUME_PATROL,
    '报告电量': VoiceCommand.REPORT_BATTERY,
    '呼叫管理员': VoiceCommand.CALL_ADMIN,
}
_COMMAND_TEXTS = {command: text for text, command in _COMMANDS.items()}

# ASR often substitutes homophones in the four fixed commands.  Keep the
# resume rule deliberately strict: resuming motion is safety-sensitive.
# 识别模型常把固定指令写成同音字；继续巡逻涉及运动，匹配规则保持严格。
_NEGATIONS = ('不要', '别', '不用', '无需', '勿', '不必')
_COMMAND_PATTERNS = (
    (VoiceCommand.PAUSE_PATROL, (
        re.compile(r'暂[停亭](?:一下)?[巡寻询循旬][逻罗萝箩](?:一下)?'),
        re.compile(r'停[止之][巡寻询循旬][逻罗萝箩]'),
    )),
    (VoiceCommand.RESUME_PATROL, (
        re.compile(r'继[续绪](?:执行)?[巡寻询循旬][逻罗萝箩]'),
        re.compile(r'[恢回]复[巡寻询循旬][逻罗萝箩]'),
    )),
    (VoiceCommand.REPORT_BATTERY, (
        re.compile(r'报[告高](?:一下)?电[量亮]'),
        re.compile(r'汇[报抱]电[量亮]'),
        re.compile(r'电[量亮]报[告高]'),
    )),
    (VoiceCommand.CALL_ADMIN, (
        re.compile(r'呼[叫教]管[理里]员?'),
        re.compile(r'叫管[理里]员'),
    )),
)

# Remove spaces and punctuation before matching so "小巡，暂停巡逻。" and
# "小巡 暂停巡逻" take the same path. 匹配前去掉空格和标点。
_PUNCTUATION = re.compile(r'[\s，。！？、；：,.!?;:"“”‘’（）()\[\]【】《》〈〉…—\-·/]+')


def normalize_text(text: str) -> str:
    """Normalize recognized text without changing Chinese word order.
    归一化识别文本，不改变中文词序。
    """
    if not isinstance(text, str):
        text = '' if text is None else str(text)
    return _PUNCTUATION.sub('', unicodedata.normalize('NFKC', text).lower())


def match_command(text: str) -> Optional[VoiceCommand]:
    """Return the first non-negated business intent found in recognized text.
    返回识别文本中第一个未被否定的业务意图。
    """
    normalized = normalize_text(text)
    for command, patterns in _COMMAND_PATTERNS:
        for pattern in patterns:
            for match in pattern.finditer(normalized):
                prefix = normalized[max(0, match.start() - 4):match.start()]
                if not any(negation in prefix for negation in _NEGATIONS):
                    return command
    return None


def command_text(command: VoiceCommand) -> str:
    """Return the canonical Chinese phrase for a business intent.
    返回业务意图对应的规范中文短语。
    """
    return _COMMAND_TEXTS[VoiceCommand(command)]


def announcement_for(event: PatrolEvent) -> str:
    """Return text for a known event; reject unknown events explicitly.
    返回已知事件的文本；显式拒绝未知事件。
    """
    return _ANNOUNCEMENTS[PatrolEvent(event)]


def command_from_text(text: str) -> VoiceCommand:
    """Convert a recognized phrase without executing robot actions.
    转换已识别短语，不执行机器人动作。
    """
    command = match_command(text)
    if command is None:
        raise ValueError('unsupported voice command / 不支持的语音指令')
    return command
