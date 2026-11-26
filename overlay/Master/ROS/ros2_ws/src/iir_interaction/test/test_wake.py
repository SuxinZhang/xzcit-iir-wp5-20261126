"""Verify wake decisions across acoustic, text, and follow-up evidence.
验证声学、文本以及后续窗口中的唤醒决策。
"""
import unittest

from iir_interaction.voice import VoiceCommand
from iir_interaction.wake import WakeSession


class WakeDecisionTests(unittest.TestCase):
    def make_session(self):
        now = [100.0]
        session = WakeSession('小巡', window_seconds=6.0, clock=lambda: now[0])
        return session, now

    def test_double_wake_replies_once(self):
        session, _ = self.make_session()
        event = session.handle('小巡小巡')
        self.assertTrue(event.woke)
        self.assertTrue(event.doubled)
        self.assertEqual(event.reply, '我在')
        self.assertIsNone(event.command)
        self.assertEqual(event.source, 'text')

    def test_single_wake_is_silent_then_opens_command_window(self):
        session, now = self.make_session()
        first = session.handle('小巡')
        self.assertTrue(first.woke)
        self.assertFalse(first.doubled)
        self.assertIsNone(first.reply)

        now[0] += 1.0
        second = session.handle('暂停巡逻')
        self.assertFalse(second.woke)
        self.assertEqual(second.command, VoiceCommand.PAUSE_PATROL)
        self.assertEqual(second.source, 'window')

    def test_window_expires(self):
        session, now = self.make_session()
        session.handle('小巡')
        now[0] += 6.1
        event = session.handle('暂停巡逻')
        self.assertFalse(event.woke)
        self.assertIsNone(event.command)
        self.assertEqual(event.source, 'none')

    def test_command_in_same_utterance_skips_spoken_reply(self):
        session, _ = self.make_session()
        event = session.handle('小巡小巡暂停巡逻')
        self.assertTrue(event.doubled)
        self.assertIsNone(event.reply)
        self.assertEqual(event.command, VoiceCommand.PAUSE_PATROL)

    def test_single_wake_with_command_does_not_need_reply(self):
        session, _ = self.make_session()
        event = session.handle('小巡，继续巡逻。')
        self.assertTrue(event.woke)
        self.assertEqual(event.command, VoiceCommand.RESUME_PATROL)

    def test_common_homophones_count_as_wake(self):
        for text in ('小寻小寻', '小巡小群', '小群小群', '小群小群小群小群'):
            with self.subTest(text=text):
                session, _ = self.make_session()
                event = session.handle(text)
                self.assertTrue(event.woke)
                self.assertEqual(event.reply, '我在')

    def test_ordinary_xiao_qun_ti_is_not_wake(self):
        for text in ('小群体', '小群体暂停巡逻'):
            with self.subTest(text=text):
                session, _ = self.make_session()
                event = session.handle(text)
                self.assertFalse(event.woke)
                self.assertIsNone(event.command)
                self.assertEqual(event.source, 'none')

    def test_ordinary_word_before_real_wake_still_wakes(self):
        session, _ = self.make_session()
        event = session.handle('小群体小巡')
        self.assertTrue(event.woke)
        self.assertFalse(event.doubled)
        self.assertIsNone(event.reply)

    def test_keyword_hit_is_authoritative(self):
        session, _ = self.make_session()
        event = session.handle('你好', '小巡')
        self.assertTrue(event.woke)
        self.assertFalse(event.doubled)
        self.assertEqual(event.source, 'kws')

        event = session.handle('你好', '小巡小巡')
        self.assertTrue(event.doubled)
        self.assertEqual(event.reply, '我在')

    def test_keyword_and_text_are_merged(self):
        session, _ = self.make_session()
        event = session.handle('小巡', '小巡')
        self.assertTrue(event.woke)
        self.assertEqual(event.source, 'kws+text')

    def test_token_spelling_keyword_still_detects_double_wake(self):
        session, _ = self.make_session()
        single = session.handle('', 'x iǎo x ún')
        self.assertTrue(single.woke)
        self.assertFalse(single.doubled)
        double = session.handle('', 'x iǎo x ún x iǎo x ún')
        self.assertTrue(double.doubled)
        self.assertEqual(double.reply, '我在')

    def test_negated_command_does_not_start_motion(self):
        session, _ = self.make_session()
        event = session.handle('小巡小巡不要暂停巡逻')
        self.assertTrue(event.doubled)
        self.assertIsNone(event.command)
        self.assertEqual(event.reply, '我在')

    def test_wake_with_unrelated_tail_is_ignored(self):
        for text in ('小巡今天天气', '小巡向前行驶', '小巡今天'):
            with self.subTest(text=text):
                session, _ = self.make_session()
                event = session.handle(text)
                self.assertFalse(event.woke)

    def test_garbled_second_wake_still_counts_as_double(self):
        # A speaker repeating the wake word can have the second copy heard as
        # a different 小-word; the repetition still deserves the reply.
        # 重复唤醒时第二遍被识别成别的“小X”，仍应按双唤醒处理。
        for text in ('小寻小声', '小巡小车'):
            with self.subTest(text=text):
                session, _ = self.make_session()
                event = session.handle(text)
                self.assertTrue(event.woke)
                self.assertTrue(event.doubled)
                self.assertEqual(event.reply, '我在')
                self.assertIsNone(event.command)

    def test_xiao_neng_counts_as_wake(self):
        session, _ = self.make_session()
        event = session.handle('小能小的意思')
        self.assertTrue(event.woke)
        self.assertTrue(event.doubled)
        self.assertEqual(event.reply, '我在')

    def test_configured_double_wake_word_is_normalized(self):
        session = WakeSession('小巡小巡', window_seconds=6.0, clock=lambda: 0.0)
        self.assertEqual(session.wake, '小巡')
        event = session.handle('小巡小巡')
        self.assertTrue(event.doubled)


if __name__ == '__main__':
    unittest.main()
