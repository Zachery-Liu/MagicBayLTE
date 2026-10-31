# SPDX-License-Identifier: AGPL-3.0-only
"""Pure failover decisions. None means unknown, never proof of an outage."""
from dataclasses import dataclass


@dataclass
class Policy:
    active: bool = False
    failed: int = 0
    recovered: int = 0
    failed_since: float = 0
    recovered_since: float = 0
    switched_at: float = -1e9
    last_sample: float = -1

    def step(self, now, physical, lte):
        if self.last_sample >= 0 and now-self.last_sample > 30:
            # Wake/scheduling gaps are not consecutive observations.
            self.failed = self.recovered = 0
        self.last_sample = now
        if physical is True:
            if not self.recovered:
                self.recovered_since = now
            self.recovered += 1
            self.failed = 0
        elif physical is False:
            if not self.failed:
                self.failed_since = now
            self.failed += 1
            self.recovered = 0
        else:
            self.failed = self.recovered = 0
        target, reason = self.active, 'hold'
        if self.active and lte is False:
            target, reason = False, 'LTE health failed; release primary rank'
        elif (self.active and self.recovered >= 3 and now-self.recovered_since >= 8
              and now-self.switched_at >= 10):
            target, reason = False, 'preferred network recovered'
        elif (not self.active and physical is False and self.failed >= 3
              and now-self.failed_since >= 10 and lte is True
              and now-self.switched_at >= 30):
            target, reason = True, 'preferred network unavailable; LTE verified'
        if target != self.active:
            self.active, self.switched_at = target, now
        return target, reason
