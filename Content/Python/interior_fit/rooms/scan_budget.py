"""Editor-only admission limits. CPU and end-to-end values are acceptance targets.

The process-wide CPU percentage includes rendering and other editor work, so it
cannot be guaranteed by a ray counter. Measure it externally; do not subtract idle.
"""
import json
import time
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[4]/'Config/ScanBudget.json'


class BudgetExceeded(ValueError):
    """No further queries may be submitted; an existing candidate can be reviewed."""


def settings(profile=None):
    data = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    if profile is not None:
        override = data.get('profiles', {}).get(profile)
        if override is None or set(override) != {'max_rays'}:
            raise ValueError('Unknown or invalid scan budget profile: ' + str(profile))
        data.update(override)
    if type(data['enabled']) is not bool or type(data['max_rays']) is not int:
        raise ValueError('Invalid scan budget types')
    if not 1 <= data['max_rays'] <= 160000:
        raise ValueError('Scan ray budget must be between 1 and 160000')
    if not 0 < data['scan_time_ms'] < data['acceptance_total_ms']:
        raise ValueError('Reserve time after scanning for preview construction')
    return data


class RunBudget:
    def __init__(self, config, started=None, clock=time.perf_counter):
        self.config, self.clock = config, clock
        self.started = clock() if started is None else started
        self.rays = 0

    def check_time(self):
        if self.config['enabled'] and self.elapsed_ms() >= self.config['scan_time_ms']:
            raise BudgetExceeded('扫描时间预算已用完。')

    def admit(self, count):
        self.check_time()
        if self.config['enabled'] and self.rays+count > self.config['max_rays']:
            raise BudgetExceeded(f"下一批将超过射线预算（已用 {self.rays}，下一批 {count}，上限 {self.config['max_rays']}）。")
        self.rays += count

    def elapsed_ms(self):
        return (self.clock()-self.started)*1000

    def snapshot(self, status):
        return dict(status=status,rays=self.rays,scan_ms=self.elapsed_ms(),
                    max_rays=self.config['max_rays'],scan_time_ms=self.config['scan_time_ms'])
