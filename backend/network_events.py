# SPDX-License-Identifier: AGPL-3.0-only
"""Network notifications wake health checks; they never establish Internet health."""
from datetime import datetime, timezone
import subprocess
import threading


class NetworkEvents:
    def __init__(self, executable):
        self.condition=threading.Condition()
        self.sequence=self.consumed=0
        self.last_utc=None
        self.ready=False
        self.error=None
        self.process=None
        self.thread=None
        self.closing=False
        self.module_present=None
        self.module_sequence=0
        try:
            self.process=subprocess.Popen([str(executable)],stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1,close_fds=True)
            self.thread=threading.Thread(target=self._read,name='LTE network notifications',daemon=True)
            self.thread.start()
        except OSError as error:
            self.error=str(error)

    def _read(self):
        try:
            for line in self.process.stdout:
                if line.strip()=='NETWORK_READY':
                    self.ready=True
                elif line.strip()=='NETWORK_CHANGE':
                    self.notify()
                elif line.strip() in ('MODEM_PRESENT','MODEM_ABSENT'):
                    self.notify_module(line.strip()=='MODEM_PRESENT')
                elif line.strip()=='MODEM_OBSERVER_UNAVAILABLE':
                    with self.condition: self.module_present=None
        except (OSError,ValueError) as error:
            if not self.closing: self.error=str(error)
        finally:
            self.ready=False
            if not self.closing and self.error is None:
                self.error='Network observer exited; periodic checks continue'

    def notify(self):
        with self.condition:
            self.sequence+=1
            self.last_utc=datetime.now(timezone.utc).isoformat()
            self.condition.notify_all()

    def notify_module(self,present):
        with self.condition:
            self.module_present=present
            self.module_sequence+=1
            self.sequence+=1
            self.last_utc=datetime.now(timezone.utc).isoformat()
            self.condition.notify_all()

    def wait(self, timeout):
        with self.condition:
            self.condition.wait_for(lambda:self.sequence!=self.consumed or self.closing,timeout)
            pending=self.sequence!=self.consumed
            self.consumed=self.sequence
            return pending

    def snapshot(self):
        with self.condition:
            return {'available':self.ready,'event_count':self.sequence,
                    'last_event_utc':self.last_utc,'error':self.error,
                    'module_present':self.module_present if self.ready else None,
                    'module_sequence':self.module_sequence}

    def close(self):
        self.closing=True
        with self.condition: self.condition.notify_all()
        if self.process:
            self.process.stdin.close()
            try: self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try: self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.kill();self.process.wait(timeout=1)
            if self.thread: self.thread.join(timeout=1)
            self.process.stdout.close()
