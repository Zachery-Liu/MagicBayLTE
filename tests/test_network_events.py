# SPDX-License-Identifier: AGPL-3.0-only
"""Notification wakeups and raced health checks. No USB or Internet requests."""
import io
from pathlib import Path
import subprocess
import threading
import time
import unittest
from unittest.mock import Mock,patch
import lte_auto as auto
from network_events import NetworkEvents


class Notifications(unittest.TestCase):
    def make_unavailable(self):
        with patch('network_events.subprocess.Popen',side_effect=FileNotFoundError('missing')):
            return NetworkEvents(Path('/missing-observer'))

    def test_missing_observer_keeps_periodic_fallback(self):
        events=self.make_unavailable()
        self.assertFalse(events.snapshot()['available'])
        self.assertFalse(events.wait(0))
        events.close()

    def test_event_wakes_sleep_and_retains_events_before_wait(self):
        events=self.make_unavailable()
        events.notify()
        self.assertTrue(events.wait(0))
        self.assertFalse(events.wait(0))
        thread=threading.Timer(0.02,events.notify);thread.start()
        start=time.monotonic();self.assertTrue(events.wait(1))
        self.assertLess(time.monotonic()-start,0.5)
        thread.join();self.assertEqual(events.snapshot()['event_count'],2)
        events.close()

    def test_reader_accepts_only_fixed_protocol_lines(self):
        process=Mock();process.stdin=io.StringIO()
        process.stdout=io.StringIO('NETWORK_READY\nignored\nNETWORK_CHANGE\nNETWORK_CHANGE\n')
        with patch('network_events.subprocess.Popen',return_value=process):
            events=NetworkEvents('/fixed-observer')
        events.thread.join(1)
        self.assertEqual(events.snapshot()['event_count'],2)
        self.assertFalse(events.snapshot()['available'])
        self.assertTrue(events.wait(0))
        events.close();self.assertTrue(process.stdin.closed)

    def test_system_notification_alone_never_proves_internet(self):
        events=self.make_unavailable();events.notify()
        from failover_policy import Policy
        p=Policy(active=True,switched_at=-20)
        for now in (0,4,8):
            self.assertTrue(p.step(now,None,True)[0])
        events.close()


class HealthRace(unittest.TestCase):
    def test_success_cancels_the_other_running_probe(self):
        barrier=threading.Barrier(2)
        processes=[]
        def spawn(args,**kwargs):
            fast='dns.alidns.com' in args[args.index('--resolve')+1]
            process=Mock(returncode=None)
            process.poll.side_effect=lambda:process.returncode
            def communicate(timeout):
                if fast:
                    process.returncode=0
                    return '{"Status":0,"Answer":[{}]}',''
                if process.returncode is not None: return '',''
                time.sleep(0.01)
                raise subprocess.TimeoutExpired('mock curl',timeout)
            def terminate():process.returncode=-15
            process.communicate.side_effect=communicate
            process.terminate.side_effect=terminate
            processes.append((fast,process));barrier.wait(timeout=1)
            return process
        start=time.monotonic()
        with patch.object(auto.subprocess,'Popen',side_effect=spawn),patch.object(auto,'STOP',False):
            self.assertTrue(auto.health('en2'))
        self.assertLess(time.monotonic()-start,0.8)
        slow=next(p for fast,p in processes if not fast)
        slow.terminate.assert_called_once()

    def test_stop_cancels_probe_and_does_not_wait_for_timeout(self):
        process=Mock(returncode=None);process.poll.return_value=None
        with patch.object(auto.subprocess,'Popen',return_value=process),patch.object(auto,'STOP',True):
            self.assertFalse(auto.health_request('en2',auto.ENDPOINTS[0],threading.Event()))
        process.terminate.assert_called_once()

    def test_invalid_interface_never_starts_a_process(self):
        with patch.object(auto.subprocess,'Popen') as spawn:
            self.assertFalse(auto.health('en2; echo invalid'))
        spawn.assert_not_called()


if __name__=='__main__':unittest.main()
