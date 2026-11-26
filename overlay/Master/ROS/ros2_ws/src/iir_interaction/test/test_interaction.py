"""Verify the WP5 contracts without ROS or audio devices.
在无 ROS 和音频设备的环境中验证 WP5 契约。
"""

import unittest

from iir_interaction.arbitration import AudioArbiter
from iir_interaction.contracts import AudioRequest, AudioSource
from iir_interaction.voice import (announcement_for, command_from_text,
                                   command_text)


class AudioArbitrationTests(unittest.TestCase):
    """Check ownership decisions before a future adapter touches hardware.
    检查后续适配器访问硬件前的所有权决策。
    """

    def test_first_request_gets_output(self):
        arbiter = AudioArbiter()
        result = arbiter.acquire(AudioRequest('patrol-1', 'patrol_tts'))
        self.assertTrue(result.accepted)
        self.assertEqual(result.owner.request_id, 'patrol-1')
        self.assertIsNone(result.interrupted)

    def test_sos_preempts_each_other_source(self):
        for source in ('remote_announcement', 'intercom', 'patrol_tts',
                       'local_dialogue'):
            with self.subTest(source=source):
                arbiter = AudioArbiter()
                arbiter.acquire(AudioRequest('old-1', source))
                result = arbiter.acquire(AudioRequest('sos-1', 'sos'))
                self.assertTrue(result.accepted)
                self.assertEqual(result.interrupted.request_id, 'old-1')
                self.assertEqual(arbiter.owner.request_id, 'sos-1')

    def test_remote_sources_preempt_both_local_sources(self):
        for remote in ('remote_announcement', 'intercom'):
            for local in ('patrol_tts', 'local_dialogue'):
                with self.subTest(remote=remote, local=local):
                    arbiter = AudioArbiter()
                    arbiter.acquire(AudioRequest('local-1', local))
                    result = arbiter.acquire(AudioRequest('remote-1', remote))
                    self.assertTrue(result.accepted)
                    self.assertEqual(result.interrupted.source.value, local)
                    self.assertEqual(arbiter.owner.source.value, remote)

    def test_sos_rejects_lower_priority(self):
        arbiter = AudioArbiter()
        arbiter.acquire(AudioRequest('sos-1', 'sos'))
        result = arbiter.acquire(AudioRequest('remote-1', 'remote_announcement'))
        self.assertFalse(result.accepted)
        self.assertEqual(result.owner.request_id, 'sos-1')
        self.assertIsNone(result.interrupted)

    def test_equal_priority_does_not_replace_owner(self):
        for first, second in (('intercom', 'remote_announcement'),
                              ('remote_announcement', 'intercom'),
                              ('patrol_tts', 'local_dialogue'),
                              ('sos', 'sos')):
            with self.subTest(first=first, second=second):
                arbiter = AudioArbiter()
                arbiter.acquire(AudioRequest('first-1', first))
                result = arbiter.acquire(AudioRequest('second-1', second))
                self.assertFalse(result.accepted)
                self.assertEqual(arbiter.owner.request_id, 'first-1')

    def test_old_completion_cannot_release_new_owner(self):
        arbiter = AudioArbiter()
        arbiter.acquire(AudioRequest('patrol-1', 'patrol_tts'))
        arbiter.acquire(AudioRequest('remote-1', 'intercom'))
        self.assertFalse(arbiter.release('patrol-1'))
        self.assertEqual(arbiter.owner.request_id, 'remote-1')

    def test_release_does_not_resume_interrupted_request(self):
        arbiter = AudioArbiter()
        arbiter.acquire(AudioRequest('patrol-1', 'patrol_tts'))
        arbiter.acquire(AudioRequest('sos-1', 'sos'))
        self.assertTrue(arbiter.release('sos-1'))
        self.assertIsNone(arbiter.owner)
        self.assertFalse(arbiter.release('sos-1'))

    def test_active_request_id_cannot_be_reused(self):
        arbiter = AudioArbiter()
        arbiter.acquire(AudioRequest('session-1', 'patrol_tts'))
        with self.assertRaises(ValueError):
            arbiter.acquire(AudioRequest('session-1', 'sos'))
        self.assertEqual(arbiter.owner.source, AudioSource.PATROL_TTS)

    def test_wire_request_rejects_invalid_contract(self):
        for request_id, source in (('', 'sos'), ('  ', 'sos'),
                                   (None, 'sos'), ('request-1', 'music')):
            with self.subTest(request_id=request_id, source=source):
                with self.assertRaises(ValueError):
                    AudioRequest(request_id, source)


class VoiceContractTests(unittest.TestCase):
    """Check that voice recognition produces intents, never movement commands.
    检查语音识别只产出意图，不产出运动命令。
    """

    def test_supported_phrases_produce_business_intents(self):
        cases = (
            ('暂停巡逻', 'pause_patrol'),
            ('继续巡逻', 'resume_patrol'),
            ('报告电量', 'report_battery'),
            ('呼叫管理员', 'call_admin'),
        )
        for text, intent in cases:
            with self.subTest(text=text):
                self.assertEqual(command_from_text(text).value, intent)

    def test_asr_homophones_and_punctuation_still_match(self):
        cases = (
            ('暂停巡逻。', 'pause_patrol'),
            ('小巡，暂停巡罗！', 'pause_patrol'),
            ('停止巡逻', 'pause_patrol'),
            ('继续寻逻', 'resume_patrol'),
            ('恢复巡逻', 'resume_patrol'),
            ('报告电亮', 'report_battery'),
            ('电量报告', 'report_battery'),
            ('呼叫管理', 'call_admin'),
        )
        for text, intent in cases:
            with self.subTest(text=text):
                self.assertEqual(command_from_text(text).value, intent)

    def test_negated_phrases_do_not_become_commands(self):
        for text in ('不要暂停巡逻', '先别继续巡逻', '无需呼叫管理员',
                     '不必恢复巡逻'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    command_from_text(text)

    def test_matched_alias_dispatches_a_canonical_phrase(self):
        cases = (
            ('暂停巡罗', '暂停巡逻'),
            ('继续寻逻', '继续巡逻'),
            ('报告电亮', '报告电量'),
            ('呼叫管理', '呼叫管理员'),
        )
        for text, canonical in cases:
            with self.subTest(text=text):
                self.assertEqual(command_text(command_from_text(text)), canonical)

    def test_unknown_phrase_fails_explicitly(self):
        with self.assertRaises(ValueError):
            command_from_text('向前行驶')

    def test_patrol_events_have_speech_text(self):
        cases = (
            ('departure', '开始巡逻。'),
            ('turning', '前方转弯，请注意避让。'),
            ('obstacle', '前方有障碍物，暂停通行。'),
            ('arrival', '已到达巡检点。'),
            ('low_battery_return', '电量不足，返回充电。'),
            ('sos', '紧急呼救，请管理员处理。'),
        )
        for event, text in cases:
            with self.subTest(event=event):
                self.assertEqual(announcement_for(event), text)

    def test_unknown_patrol_event_fails_explicitly(self):
        with self.assertRaises(ValueError):
            announcement_for('unknown')


if __name__ == '__main__':
    unittest.main()
