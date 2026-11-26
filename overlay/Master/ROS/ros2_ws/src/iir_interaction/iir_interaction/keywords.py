"""Detect the configured wake phrase from audio using a keyword model.
使用关键词模型从音频检测配置的唤醒短语。
"""

SAMPLE_RATE = 16000
# The upstream streaming example feeds 0.66 s of silence and calls
# input_finished() so the final chunk is decoded.  Without both, a wake phrase
# at the end of a VAD segment can be dropped.
# 上游流式示例在尾部补 0.66 秒静音并调用 input_finished()，否则片段末尾的
# 唤醒词可能不会被解码。
TAIL_PADDING_SECONDS = 0.66


class Spotter:
    """Wrap KeywordSpotter so optional inline wake words need no file edit.
    包装 KeywordSpotter，使可选的内联唤醒词无需修改关键词文件。
    """

    def __init__(self, inner, extra_keywords='', config=None):
        self.inner = inner
        self.extra_keywords = extra_keywords
        self.config = config or {}

    def create_stream(self):
        if self.extra_keywords:
            return self.inner.create_stream(self.extra_keywords)
        return self.inner.create_stream()

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _env_value(env, name):
    value = env.get(name)
    return '' if value is None else str(value).strip()


def _env_number(env, name, default, cast):
    value = _env_value(env, name)
    return default if not value else cast(value)


def create_spotter(env):
    """Build a spotter with explicit, deployable tuning knobs.
    构建关键词检测器，并暴露可部署的调参项。
    """
    import sherpa_onnx

    num_threads = _env_number(env, 'IIR_KWS_THREADS', 2, int)
    # 8 paths caught one more wake phrase than 4 on board recordings at the
    # same decode cost (~0.08x realtime), so it is the default.
    # 板端录音实测 8 路比 4 路多唤醒一条，解码开销相同，故设为默认值。
    max_active_paths = _env_number(env, 'IIR_KWS_MAX_ACTIVE_PATHS', 8, int)
    keywords_score = _env_number(env, 'IIR_KWS_SCORE', 1.0, float)
    keywords_threshold = _env_number(env, 'IIR_KWS_THRESHOLD', 0.25, float)
    num_trailing_blanks = _env_number(env, 'IIR_KWS_TRAILING_BLANKS', 1, int)
    if num_threads < 1:
        raise ValueError('IIR_KWS_THREADS must be at least 1')
    if max_active_paths < 1:
        raise ValueError('IIR_KWS_MAX_ACTIVE_PATHS must be at least 1')
    if num_trailing_blanks < 0:
        raise ValueError('IIR_KWS_TRAILING_BLANKS must not be negative')
    if not 0.0 <= keywords_threshold <= 1.0:
        raise ValueError('IIR_KWS_THRESHOLD must be between 0 and 1')

    config = {
        'num_threads': num_threads,
        'max_active_paths': max_active_paths,
        'keywords_score': keywords_score,
        'keywords_threshold': keywords_threshold,
        'num_trailing_blanks': num_trailing_blanks,
    }
    inner = sherpa_onnx.KeywordSpotter(
        tokens=env['IIR_KWS_TOKENS'], encoder=env['IIR_KWS_ENCODER'],
        decoder=env['IIR_KWS_DECODER'], joiner=env['IIR_KWS_JOINER'],
        keywords_file=env['IIR_KWS_KEYWORDS'], **config)
    return Spotter(inner, _env_value(env, 'IIR_KWS_EXTRA_KEYWORDS'), config)


def detect_keyword(spotter, samples):
    """Decode one completed speech segment and return its keyword result.
    解码一个完整语音片段并返回关键词结果。
    """
    import numpy as np

    stream = spotter.create_stream()
    samples = np.asarray(samples, dtype=np.float32)
    tail = np.zeros(int(TAIL_PADDING_SECONDS * SAMPLE_RATE), dtype=np.float32)
    stream.accept_waveform(SAMPLE_RATE, np.concatenate([samples, tail]))
    stream.input_finished()
    while spotter.is_ready(stream):
        spotter.decode_stream(stream)
        keyword = spotter.get_result(stream)
        if keyword:
            spotter.reset_stream(stream)
            return keyword
    return ''
