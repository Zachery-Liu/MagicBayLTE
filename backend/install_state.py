# SPDX-License-Identifier: AGPL-3.0-only
"""Explicit enable intent across fresh installs, upgrades and uninstalls."""
import json
from pathlib import Path
import shutil
from local_access import checked, write_json

RUNTIME_STATE = ('auto-state.json', 'helper-state.json', 'modem-state.json',
                 'auto-state.new', 'helper-state.new', 'modem-state.new', 'modem-state.json.new',
                 'signal-request', 'control.sock')


def read_preference(path):
    try:
        checked(path)
    except FileNotFoundError:
        return False
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or type(data.get('enabled')) is not bool:
        raise ValueError('Invalid root-owned LTE preference')
    return data['enabled']


def initialize(base):
    path = Path(base) / 'preferences.json'
    # A malformed setting aborts installation rather than guessing consent.
    enabled = read_preference(path)
    write_json(path, {'enabled': enabled}, private=True)
    return enabled


def reset_after_stop(base, remove_logs=False):
    """Only call after verified service/engine termination; retain disabled consent."""
    base = Path(base)
    write_json(base / 'preferences.json', {'enabled': False}, private=True)
    for name in RUNTIME_STATE:
        (base / name).unlink(missing_ok=True)
    logs = base / 'logs'
    if remove_logs and logs.exists():
        checked(logs, directory=True)
        shutil.rmtree(logs)
