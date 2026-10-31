# SPDX-License-Identifier: AGPL-3.0-only
"""No host networking or USB: policy sequences and supervisor failures are mocked."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock
import lte_auto as auto
import lte_service as service
import lte_control as legacy
from failover_policy import Policy


class Decisions(unittest.TestCase):
    def test_healthy_wifi_never_activates(self):
        p=Policy()
        for now in range(0,120,5):
            self.assertFalse(p.step(now,True,True)[0])

    def test_confirmed_outage_uses_verified_lte(self):
        p=Policy()
        self.assertFalse(p.step(0,False,True)[0])
        self.assertFalse(p.step(5,False,True)[0])
        self.assertTrue(p.step(10,False,True)[0])

    def test_failed_or_unknown_lte_cannot_activate(self):
        for lte in (False,None):
            p=Policy()
            for now in range(0,100,5):
                self.assertFalse(p.step(now,False,lte)[0])

    def test_unknown_physical_is_not_outage(self):
        p=Policy()
        p.step(0,False,True); p.step(5,False,True)
        self.assertFalse(p.step(10,None,True)[0])
        self.assertFalse(p.step(15,False,True)[0])

    def test_short_recovery_does_not_flap(self):
        p=Policy(active=True,switched_at=0)
        for now in (5,7,9):
            self.assertTrue(p.step(now,True,True)[0])
        self.assertTrue(p.step(10,False,True)[0])

    def test_stable_recovery_returns_to_wifi(self):
        p=Policy(active=True,switched_at=0)
        for now in (0,4,8):
            self.assertTrue(p.step(now,True,True)[0])
        self.assertFalse(p.step(10,True,True)[0])

    def test_three_recovery_samples_need_eight_seconds(self):
        p=Policy(active=True,switched_at=-20)
        self.assertTrue(p.step(0,True,True)[0])
        self.assertTrue(p.step(4,True,True)[0])
        self.assertFalse(p.step(8,True,True)[0])

    def test_events_do_not_bypass_failure_or_recovery_time_floor(self):
        p=Policy()
        for now in (0,0.1,0.2,0.3,0.4):
            self.assertFalse(p.step(now,False,True)[0])
        self.assertTrue(p.step(10,False,True)[0])
        for now in (10.1,10.2,10.3,10.4):
            self.assertTrue(p.step(now,True,True)[0])

    def test_unknown_resets_recovery_confirmation(self):
        p=Policy(active=True,switched_at=-20)
        p.step(0,True,True);p.step(4,True,True);p.step(8,None,True)
        self.assertTrue(p.step(10,True,True)[0])
        self.assertTrue(p.step(14,True,True)[0])
        self.assertFalse(p.step(18,True,True)[0])

    def test_failed_preferred_network_does_not_flap_back_after_return(self):
        p=Policy(active=True,switched_at=-20)
        for now in (0,4,8): p.step(now,True,True)
        for now in (9,14,19,24,29,34):
            self.assertFalse(p.step(now,False,True)[0])
        self.assertTrue(p.step(38,False,True)[0])

    def test_lte_loss_releases_without_holdoff(self):
        p=Policy(active=True,switched_at=0)
        self.assertFalse(p.step(1,False,False)[0])

    def test_wake_gap_does_not_count_as_outage(self):
        p=Policy()
        p.step(0,False,True); p.step(5,False,True)
        self.assertFalse(p.step(100,False,True)[0])


class Supervisor(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        p=patch.object(auto,'BASE',Path(self.temporary.name));p.start();self.addCleanup(p.stop)
        p=patch.object(auto,'STATE',auto.BASE/'auto-state.json');p.start();self.addCleanup(p.stop)
        for name in ('run','Popen'):
            p=patch.object(auto.subprocess,name,side_effect=AssertionError('Unmocked subprocess'))
            p.start();self.addCleanup(p.stop)

    def test_curl_is_bound_and_bypasses_proxy(self):
        process=Mock(returncode=0);process.communicate.return_value=('{"Status":0,"Answer":[{}]}','')
        process.poll.return_value=0
        with patch.object(auto.subprocess,'Popen',return_value=process) as call:
            self.assertTrue(auto.health('utun9'))
        for entry in call.call_args_list:
            args=entry.args[0]
            self.assertIn('--noproxy',args)
            self.assertEqual(args[args.index('--interface')+1],'utun9')
            self.assertIn('--resolve',args)

    def test_captive_or_invalid_response_is_unhealthy(self):
        for output in ('<html>sign in</html>','[]','{"Status":0,"Answer":[]}'):
            process=Mock(returncode=0);process.communicate.return_value=(output,'')
            process.poll.return_value=0
            with patch.object(auto.subprocess,'Popen',return_value=process):
                self.assertFalse(auto.health('en2'))

    def test_interface_inventory_excludes_link_local(self):
        results=[subprocess.CompletedProcess([],0,'(Device: en0)\n(Device: en2)\n',''),
                 subprocess.CompletedProcess([],0,'inet 169.254.1.1',''),
                 subprocess.CompletedProcess([],0,'inet 192.0.2.10','')]
        with patch.object(auto,'command',side_effect=results):
            self.assertEqual(auto.physical_interfaces(),['en2'])

    def test_close_disconnects_control_pipe_and_waits(self):
        engine=auto.Engine(); reader,writer=os.pipe()
        engine.writer=writer;engine.process=Mock();engine.process.poll.return_value=None
        self.assertTrue(engine.close())
        self.assertEqual(os.read(reader,1),b'')
        os.close(reader)
        engine.process.kill.assert_not_called()

    def test_close_timeout_does_not_start_another_session(self):
        engine=auto.Engine();engine.process=Mock();engine.process.poll.return_value=None
        engine.process.wait.side_effect=subprocess.TimeoutExpired('mock',25)
        self.assertFalse(engine.close())

    def test_return_ends_data_bearer_instead_of_just_changing_rank(self):
        engine=Mock(active=True);engine.close.return_value=True
        traffic=Mock();state={'phase':'LTE','interface':'utun9','active':True}
        calls=[]
        engine.switch.side_effect=lambda active:calls.append(('rank',active))
        engine.close.side_effect=lambda:calls.append(('close',None)) or True
        with patch.object(auto,'write_state',side_effect=lambda s:calls.append(('phase',s['phase']))):
            auto.release_data_session(engine,state,traffic)
        self.assertEqual(calls[:3],[('phase','returning'),('rank',False),('close',None)])
        self.assertNotIn('interface',state)
        self.assertFalse(state['return_verified'])
        self.assertIn('data_session_closed_utc',state)
        self.assertEqual(traffic.sample.call_count,2)

    def test_return_never_claims_complete_if_data_engine_cannot_close(self):
        engine=Mock(active=True);engine.close.return_value=False
        state={'phase':'LTE','interface':'utun9'}
        with patch.object(auto,'write_state'):
            with self.assertRaises(RuntimeError): auto.release_data_session(engine,state,Mock())
        self.assertEqual(state['phase'],'returning')
        self.assertFalse(state['return_verified'])
        self.assertNotIn('data_session_closed_utc',state)

    def test_transfer_totals_survive_control_only_restarts_and_reject_old_pid(self):
        totals=auto.TrafficTotals();path=auto.BASE/'modem-state.json'
        engine=Mock();engine.process.pid=42;engine.log_path=auto.BASE/'data-session.log'
        path.write_text(json.dumps({'engine_pid':42,'transfer_received':100,'transfer_sent':50}))
        totals.sample(engine);totals.sample(engine)
        self.assertEqual((totals.received,totals.sent),(100,50))
        path.write_text(json.dumps({'engine_pid':42,'transfer_received':140,'transfer_sent':80}))
        totals.sample(engine)
        engine.process.pid=43;engine.log_path=auto.BASE/'control-session.log'
        totals.sample(engine)
        path.write_text(json.dumps({'engine_pid':43,'transfer_received':0,'transfer_sent':0}))
        totals.sample(engine)
        self.assertEqual((totals.received,totals.sent),(140,80))

    def test_return_proof_needs_inactive_data_and_healthy_actual_exit(self):
        engine=Mock(monitoring=True)
        with patch.object(auto,'default_route',return_value={'interface':'en2'}),patch.object(auto,'app_health',return_value=True):
            self.assertTrue(auto.verify_preferred_return(engine,{'en2':True}))
            self.assertFalse(auto.verify_preferred_return(engine,{'en2':False,'en0':True}))
            engine.monitoring=False
            self.assertFalse(auto.verify_preferred_return(engine,{'en2':True}))

    def test_return_proof_checks_the_application_proxy_after_lte_is_gone(self):
        with patch.object(auto,'default_route',return_value={'interface':'en2'}),patch.object(auto,'app_health',return_value=False):
            self.assertFalse(auto.verify_preferred_return(Mock(monitoring=True),{'en2':True}))

    def test_supervisor_transitions_monitor_data_then_confirmed_monitor(self):
        calls=[];created=[];round_number=[0];route={'interface':'en2'};snapshots=[]
        class FakeEngine:
            def __init__(self):
                self.info=None;self.active=False;self.process=None
                self.log_path=auto.BASE/('engine-%d.log'%len(created));created.append(self)
            @property
            def monitoring(self):return bool(self.info and self.info.get('mode')=='monitor')
            @property
            def data_ready(self):return bool(self.info and self.info.get('interface'))
            def start(self,monitor=False):
                self.info={'mode':'monitor','activation_state':3} if monitor else {'interface':'utun9'}
                self.process=Mock(pid=100+len(created));self.process.poll.return_value=None
                calls.append(('start',monitor))
            def switch(self,active):
                assert self.data_ready
                self.active=active;route['interface']='utun9' if active else 'en2';calls.append(('rank',active))
            def close(self):
                calls.append(('close','monitor' if self.monitoring else 'data'))
                if self.process:self.process.poll.return_value=0
                self.info=None;self.active=False;return True
        policy=Mock(active=False,failed=0,recovered=0)
        def decision(*args):
            policy.active=round_number[0]==0
            return policy.active,'simulated outage' if policy.active else 'simulated recovery'
        policy.step.side_effect=decision
        events=Mock();events.snapshot.return_value={'available':True}
        def wait(*args):
            round_number[0]+=1
            if round_number[0]>=2:auto.STOP=True
        def write(state):snapshots.append(json.loads(json.dumps(state)))
        with contextlib.ExitStack() as stack:
            for name,value in [('Engine',FakeEngine),('Policy',lambda:policy),('NetworkEvents',lambda *a:events),
                ('birth',lambda p:'birth'),('default_route',lambda:dict(route)),('system_proxy',lambda:{}),
                ('physical_interfaces',lambda:['en2']),('health',lambda iface:iface=='utun9' or round_number[0]>0),
                ('proxy_compatibility',lambda *a:{'compatible':True}),('interface_expensive',lambda *a:True),
                ('app_health',lambda:True),('wait_for_observation',wait),('write_state',write)]:
                stack.enter_context(patch.object(auto,name,value))
            stack.enter_context(patch.object(auto,'STOP',False));stack.enter_context(patch.object(auto.signal,'signal'))
            stack.enter_context(patch.object(auto.time,'sleep'))
            auto.run()
        self.assertEqual([v for k,v in calls if k=='start'],[True,False,True])
        self.assertLess(calls.index(('close','data')),len(calls)-2)
        phases=[s['phase'] for s in snapshots]
        self.assertIn('LTE',phases);self.assertIn('returning',phases);self.assertIn('ready',phases)
        ready=next(s for s in snapshots if s['phase']=='ready')
        self.assertTrue(ready['return_verified']);self.assertNotIn('interface',ready)

    def test_unknown_tun_is_rejected(self):
        response=subprocess.CompletedProcess([],0,'default 1.2.3.4 utun4','')
        with patch.object(auto,'command',return_value=response), \
             patch.object(auto.UnixHTTP,'connect',side_effect=OSError('no controller')):
            self.assertFalse(auto.proxy_compatibility()['compatible'])

    def test_state_writes_atomically(self):
        auto.write_state({'phase':'standby'})
        self.assertEqual(json.loads(auto.STATE.read_text())['phase'],'standby')
        self.assertFalse(auto.STATE.with_suffix('.new').exists())

    def test_lte_cost_reads_actual_extended_interface_flags(self):
        for output,expected in [('eflags=0x2000<EXPENSIVE>',True),('eflags=0x0<>',False)]:
            result=subprocess.CompletedProcess([],0,output,'')
            with patch.object(auto,'command',return_value=result):
                self.assertEqual(auto.interface_expensive('utun9'),expected)
        with patch.object(auto,'command') as call:
            self.assertIsNone(auto.interface_expensive('en2'))
        call.assert_not_called()

    def test_signal_request_is_private_and_rejects_symlinks(self):
        request=auto.SignalRequest()
        request.close()
        path=auto.BASE/'signal-request'
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        path.unlink()
        target=auto.BASE/'untouched';target.write_text('safe')
        path.symlink_to(target)
        with self.assertRaises(OSError):
            auto.SignalRequest()
        self.assertEqual(target.read_text(),'safe')

    def test_orphan_requires_pid_birth_and_exact_engine(self):
        auto.STATE.write_text(json.dumps({'engine_pid':42,'engine_birth':'birth'}))
        with patch.object(auto,'birth',return_value='different'):
            self.assertIsNone(auto.orphan_engine())
        result=subprocess.CompletedProcess([],0,str(auto.ENGINE),'')
        with patch.object(auto,'birth',return_value='birth'), patch.object(auto,'command',return_value=result):
            self.assertEqual(auto.orphan_engine(),42)

    def test_launch_service_uses_root_owned_deployment(self):
        definition=service.definition()
        self.assertEqual(definition['ProgramArguments'],['/usr/bin/python3',
            '/Library/Application Support/MagicBayLTE/lte_helper.py'])
        self.assertTrue(definition['RunAtLoad'])
        self.assertNotIn('UserName',definition)
        self.assertTrue(definition['KeepAlive'])
        self.assertEqual(auto.LOCK,legacy.LOCK)

    def test_upgrade_waits_until_launchd_finishes_removing_old_helper(self):
        responses=[subprocess.CompletedProcess([],0,'exiting',''),
                   subprocess.CompletedProcess([],0,'removal pending',''),
                   subprocess.CompletedProcess([],113,'','not found')]
        with patch.object(service,'command',side_effect=responses) as call,patch.object(service.time,'sleep'):
            service.wait_unloaded()
        self.assertEqual(call.call_count,3)

    def test_upgrade_refuses_to_replace_a_helper_that_will_not_exit(self):
        response=subprocess.CompletedProcess([],0,'exiting','')
        with patch.object(service,'command',return_value=response),patch.object(service.time,'monotonic',side_effect=[0,20]):
            with self.assertRaises(RuntimeError): service.wait_unloaded(timeout=15)

    def test_observe_mode_cannot_activate(self):
        engine=Mock(info={'interface':'utun9'},active=False)
        engine.process.poll.return_value=None
        engine.close.return_value=True
        engine.log_path=auto.BASE/'mock.log'
        ticks=iter([0,1,2,3,4,5,6,7,8,9,10,11,100])
        # Force a policy that wants to activate; observe must still override it.
        policy=Mock(active=True,failed=3,recovered=0)
        policy.step.return_value=(True,'mock outage')
        events=Mock();events.snapshot.return_value={'available':True}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(auto,'Engine',return_value=engine))
            stack.enter_context(patch.object(auto,'Policy',return_value=policy))
            stack.enter_context(patch.object(auto,'NetworkEvents',return_value=events))
            stack.enter_context(patch.object(auto,'birth',return_value='birth'))
            stack.enter_context(patch.object(auto,'default_route',return_value={'interface':'en2'}))
            stack.enter_context(patch.object(auto,'system_proxy',return_value={}))
            stack.enter_context(patch.object(auto,'physical_interfaces',return_value=[]))
            stack.enter_context(patch.object(auto,'health',return_value=True))
            stack.enter_context(patch.object(auto,'interface_expensive',return_value=True))
            stack.enter_context(patch.object(auto,'proxy_compatibility',return_value={'compatible':True}))
            stack.enter_context(patch.object(auto.signal,'signal'))
            stack.enter_context(patch.object(auto.time,'sleep'))
            stack.enter_context(patch.object(auto.time,'monotonic',side_effect=lambda:next(ticks,100)))
            auto.run(observe=True,duration=20)
        engine.switch.assert_not_called()


if __name__=='__main__':
    unittest.main()
