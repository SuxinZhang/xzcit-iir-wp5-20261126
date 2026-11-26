"""Verify recognized wake phrases and command forwarding.
验证已识别唤醒短语与命令转发。
"""
import contextlib
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from iir_interaction.asr import dispatch_text
from iir_interaction.wake import WakeSession


class WakeReplyTests(unittest.TestCase):
    def request_for(self, text, keyword):
        with patch('iir_interaction.asr.urllib.request.urlopen') as send:
            dispatch_text(text, keyword, '小巡', 'token')
            if not send.called:
                return None
            request = send.call_args.args[0]
            self.assertEqual(request.get_header('Authorization'), 'Bearer token')
            return request.full_url, json.loads(request.data)

    def test_double_wake_uses_local_dialogue_speech(self):
        self.assertEqual(self.request_for('小巡小巡', '小巡小巡'),
                         ('http://127.0.0.1:8095/speak',
                          {'text': '我在', 'source': 'local_dialogue'}))

    def test_original_command_keeps_recognition_route(self):
        self.assertEqual(self.request_for('小巡暂停巡逻', ''),
                         ('http://127.0.0.1:8095/recognize', {'text': '暂停巡逻'}))

    def test_homophone_command_is_sent_in_canonical_form(self):
        self.assertEqual(self.request_for('小巡暂停巡罗', ''),
                         ('http://127.0.0.1:8095/recognize', {'text': '暂停巡逻'}))

    def test_keyword_hit_with_command_forwards_without_reply(self):
        self.assertEqual(self.request_for('暂停巡逻', '小巡'),
                         ('http://127.0.0.1:8095/recognize', {'text': '暂停巡逻'}))

    def test_keyword_hit_responds_despite_asr_transcription(self):
        self.assertEqual(self.request_for('小群小群', '小巡小巡'),
                         ('http://127.0.0.1:8095/speak',
                          {'text': '我在', 'source': 'local_dialogue'}))

    def test_single_wake_and_unrelated_speech_have_no_reply(self):
        self.assertIsNone(self.request_for('小巡', ''))
        self.assertIsNone(self.request_for('你好', ''))
        self.assertIsNone(self.request_for('小区', ''))

    def test_fuzzy_wake_responds_without_keyword_model_hit(self):
        for text in ('小巡小巡', '小寻小寻', '小寻小巡', '小群小群',
                     '小巡小群', '面小群小群', '小群小群小群小群'):
            with self.subTest(text=text):
                self.assertEqual(self.request_for(text, ''),
                                 ('http://127.0.0.1:8095/speak',
                                  {'text': '我在', 'source': 'local_dialogue'}))

    def test_follow_up_segment_uses_the_same_wake_window(self):
        now = [100.0]
        session = WakeSession('小巡', window_seconds=6.0, clock=lambda: now[0])
        with patch('iir_interaction.asr.urllib.request.urlopen') as send:
            self.assertFalse(dispatch_text('小巡', '', '小巡', 'token', session=session))
            now[0] += 1.0
            self.assertTrue(dispatch_text('暂停巡逻', '', '小巡', 'token', session=session))
            request = send.call_args.args[0]
            self.assertEqual(request.full_url, 'http://127.0.0.1:8095/recognize')
            self.assertEqual(json.loads(request.data), {'text': '暂停巡逻'})

    def test_speech_failure_is_logged_without_killing_asr(self):
        for code in (400, 409, 502):
            with self.subTest(code=code):
                error = urllib.error.HTTPError('url', code, 'failure', {}, None)
                stderr = io.StringIO()
                try:
                    with patch('iir_interaction.asr.urllib.request.urlopen',
                               side_effect=error):
                        with contextlib.redirect_stderr(stderr):
                            delivered = dispatch_text('小巡小巡', '小巡小巡',
                                                      '小巡', 'token')
                finally:
                    error.close()
                self.assertFalse(delivered)
                event = json.loads(stderr.getvalue().strip().splitlines()[-1])
                self.assertEqual(event['event'], 'dispatch_error')
                self.assertEqual(event['code'], code)

    def test_connection_failure_is_logged_without_killing_asr(self):
        stderr = io.StringIO()
        with patch('iir_interaction.asr.urllib.request.urlopen',
                   side_effect=urllib.error.URLError('service down')):
            with contextlib.redirect_stderr(stderr):
                delivered = dispatch_text('小巡小巡', '小巡小巡', '小巡', 'token')
        self.assertFalse(delivered)
        event = json.loads(stderr.getvalue().strip().splitlines()[-1])
        self.assertEqual(event['event'], 'dispatch_error')
        self.assertEqual(event['error'], 'URLError')


if __name__ == '__main__':
    unittest.main()
