"""Offline acceptance against independent building truth, never an invented UI IoU."""
import json
import math
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[4]/'Config/Acceptance.json'


def settings():
    data = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    if not 0 <= data['preview_iou_min'] <= data['target_iou'] <= 1:
        raise ValueError('Invalid IoU acceptance thresholds')
    if not all(0 < data[k] <= 1 for k in ('overall_success_min','class_success_min')):
        raise ValueError('Invalid success rate thresholds')
    return data


def grade(iou, config=None):
    config = config or settings()
    if iou is None or not math.isfinite(iou) or not 0 <= iou <= 1:
        return 'unknown'
    if iou >= config['target_iou']:
        return 'target'
    return 'review' if iou >= config['preview_iou_min'] else 'diagnostic'


def passed(iou, runs, config=None):
    config = config or settings()
    if grade(iou,config) not in ('target','review') or not runs:
        return False
    return all('error' not in r and r.get('rays',math.inf)<=config['max_rays'] and
        r.get('total_ms',math.inf)<config['total_time_ms_exclusive'] and
        r.get('process_cpu_peak',math.inf)<=config['process_cpu_percent_max'] for r in runs)


def coverage(cases, config=None):
    """cases contains (room_class, accepted_bool); every family must pass separately."""
    config = config or settings()
    classes = {}
    for kind,accepted in cases:
        row = classes.setdefault(kind,dict(total=0,passed=0))
        row['total'] += 1
        row['passed'] += int(accepted)
    total = sum(row['total'] for row in classes.values())
    successes = sum(row['passed'] for row in classes.values())
    for row in classes.values():
        row['rate'] = row['passed']/row['total']
        row['qualified'] = row['rate']>=config['class_success_min']
    rate = successes/total if total else 0
    return dict(total=total,passed=successes,rate=rate,classes=classes,
        qualified=bool(total) and rate>=config['overall_success_min'] and
                  all(row['qualified'] for row in classes.values()))
