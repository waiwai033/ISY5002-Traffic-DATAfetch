#!/usr/bin/env python3
"""Run the dated eight-camera campaign, or inspect/test it without starting it."""
import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from fetch_lta_camera_images import ROOT, load_cameras, main, parse_timestamp, positive

TRIAL_DIR = 'data/trial-eight-cameras'


def load_plan(path):
    plan = json.loads(path.read_text())
    start, end = map(parse_timestamp, (plan['start_at'], plan['end_at']))
    if start >= end:
        raise ValueError('Campaign end must follow start')
    positive(str(plan['interval_minutes']))
    cameras = load_cameras(ROOT / plan['camera_csv'])
    return plan, start, end, cameras


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'reference/collection_week.json')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--once', action='store_true', help='Trial now; saves outside campaign dataset')
    mode.add_argument('--sample', action='store_true',
                      help='One campaign cycle now; skipped outside the campaign window')
    parser.add_argument('--max-runtime-minutes', type=positive, help='Limit one GitHub worker batch')
    parser.add_argument('--max-wait-minutes', type=float, default=0,
                        help='Idle this long for a campaign that has not opened yet')
    args = parser.parse_args(argv)
    plan, start, end, cameras = load_plan(args.config)
    if args.check:
        print(json.dumps({**plan, 'camera_ids': [c['CameraID'] for c in cameras],
                          'road_groups': sorted({c['RoadSegment'] for c in cameras}),
                          'start_utc': start.isoformat(), 'end_utc': end.isoformat(),
                          'planned_cycles': math.ceil((end-start).total_seconds() / (plan['interval_minutes']*60)),
                          'enabled': 'Check mode only; does not start or enable collection'}, indent=2))
        return 0
    output = TRIAL_DIR if args.once else plan['output_dir']
    command = ['--camera-csv', str(ROOT / plan['camera_csv']), '--output-dir', str(ROOT / output),
               '--source', plan['source'], '--interval-minutes', str(plan['interval_minutes']),
               '--active-start', plan['active_start'], '--active-end', plan['active_end']]
    # Quiet-hour frames sit unrefreshed for hours; without this the collector rejects
    # them as stale and the dataset loses its overnight samples entirely.
    if plan.get('max_age_minutes'):
        command += ['--max-age-minutes', str(plan['max_age_minutes'])]
    if args.once:
        command += ['--once']
    elif args.sample:
        # One cycle per worker: a delayed or dropped cron tick costs a single sample,
        # not the whole hour, and each job bills about a minute instead of fifty-five.
        now = datetime.now(timezone.utc)
        if not start <= now < end:
            print('Campaign window is not open; no sample taken')
            return 0
        command += ['--once']
    else:
        command += ['--start-at', plan['start_at'], '--end-at', plan['end_at']]
        if args.max_runtime_minutes:
            # A worker may be launched before the window opens so that collection can
            # begin on the minute rather than whenever a cron tick happens to land.
            # The collector idles until start_at; the workflow sizes the budget so the
            # wait plus the collecting fits inside one job. Never wait for days.
            wait = (start - datetime.now(timezone.utc)).total_seconds() / 60
            if wait > args.max_wait_minutes:
                print(f'Campaign opens in {wait:.0f} minutes, beyond the '
                      f'{args.max_wait_minutes:.0f}-minute launch window; worker skipped')
                return 0
            if wait > 0:
                print(f'Waiting {wait:.0f} minutes for the campaign to open at '
                      f'{plan["start_at"]}')
            command += ['--duration-days', str(args.max_runtime_minutes / 1440)]
        else:
            command += ['--duration-days', str((end-start).total_seconds() / 86400)]
    return main(command)


if __name__ == '__main__':
    try:
        raise SystemExit(run())
    except KeyboardInterrupt:
        raise SystemExit(130)
