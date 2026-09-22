import csv
import importlib.util
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "scripts/fetch_lta_camera_images.py"
SPEC = importlib.util.spec_from_file_location("collector", MODULE)
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)
        self.cameras = c.load_cameras(c.ROOT / "reference/camera_sentosa.csv")
        self.now = datetime(2026, 9, 13, 6, 20, tzinfo=timezone.utc)

    def payload(self, timestamp=None):
        return json.dumps({"items": [{"cameras": [
            {"camera_id": row["CameraID"], "timestamp": timestamp or c.iso(self.now),
             "image": "https://example.test/image.jpg"} for row in self.cameras]}]}).encode()

    def collect(self, metadata=None, content=b"\xff\xd8\xfftest\xff\xd9", now=None):
        with patch.object(c, "fetch_bytes", side_effect=lambda url, headers=None:
                          metadata if url == c.ENDPOINTS["data-gov-sg"] else content):
            return c.collect_cycle(self.cameras, self.output, "data-gov-sg", {}, now=now or self.now)

    def test_real_configuration_has_eight_cameras_in_three_groups(self):
        cameras = c.load_cameras(c.ROOT / "reference/camera_info.csv")
        self.assertEqual({x["CameraID"] for x in cameras},
                         {"2701", "2702", "2704", "4703", "4712", "4713", "4798", "4799"})
        self.assertEqual({group: sum(x['RoadSegment'] == group for x in cameras)
                          for group in {x['RoadSegment'] for x in cameras}},
                         {'causeway': 3, 'second_link': 3, 'sentosa_gateway': 2})

    def test_week_plan_is_a_clean_campaign(self):
        # Asserts the properties any campaign must have rather than one week's
        # literals, so a re-dated plan does not fail a test that is still correct.
        plan = json.loads((c.ROOT / 'reference/collection_week.json').read_text())
        start, end = map(c.parse_timestamp, (plan['start_at'], plan['end_at']))
        interval = plan['interval_minutes']
        self.assertLess(start, end)
        local = start.astimezone(c.SG)
        self.assertEqual(local.second, 0)
        self.assertEqual(local.minute % interval, 0,
                         'start must sit on the sampling grid so ticks land on round minutes')
        rounds = math.ceil((end - start).total_seconds() / (interval * 60))
        self.assertEqual(rounds, (end - start).total_seconds() / (interval * 60),
                         'the window should be a whole number of sampling rounds')
        last = start + timedelta(minutes=(rounds - 1) * interval)
        self.assertLess(last, end, 'the final tick must fall inside the window')
        self.assertGreaterEqual(plan['max_age_minutes'], 240,
                                'quiet-hour frames age for hours; see the stale-frame finding')

    def test_future_start_grid_and_exclusive_end(self):
        anchor = datetime(2026, 9, 13, 16, 21, tzinfo=timezone.utc)
        clock = {'now': anchor - timedelta(seconds=2)}
        calls = []
        class FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock['now'].astimezone(tz)
        def sleep(seconds):
            clock['now'] += timedelta(seconds=seconds)
        def collect(*args, **kwargs):
            calls.append(clock['now'])
            clock['now'] += timedelta(seconds=5)
            return [{'status': 'downloaded'}]
        with patch.object(c, 'datetime', FakeDatetime), \
             patch.object(c.time, 'monotonic', side_effect=lambda: clock['now'].timestamp()), \
             patch.object(c.time, 'sleep', side_effect=sleep), \
             patch.object(c, 'collect_cycle', side_effect=collect):
            code = c.main(['--start-at', c.iso(anchor), '--end-at', c.iso(anchor+timedelta(minutes=60)),
                           '--interval-minutes', '10', '--active-start', '00:00',
                           '--output-dir', str(self.output)])
        self.assertEqual(code, 0)
        self.assertEqual(calls, [anchor+timedelta(minutes=i) for i in (0,10,20,30,40,50)])
        self.assertEqual([t.astimezone(c.SG).strftime('%H:%M') for t in calls],
                         ['00:21','00:31','00:41','00:51','01:01','01:11'])

    def test_expired_campaign_makes_no_requests(self):
        with patch.object(c, 'collect_cycle') as collect:
            result = c.main(['--start-at', '2020-01-01T00:00:00+08:00',
                             '--end-at', '2020-01-02T00:00:00+08:00'])
        self.assertEqual(result, 0)
        collect.assert_not_called()

    def test_restart_dedup_and_timezone_rollover(self):
        now = self.now.replace(hour=18)
        metadata = self.payload(c.iso(now))
        first = self.collect(metadata, now=now)
        self.assertEqual([r["status"] for r in first], ["downloaded"] * 2)
        self.assertTrue(first[0]["captured_at_sgt"].startswith("2026-09-14T02:20"))
        second = self.collect(metadata, now=now + timedelta(minutes=5))
        self.assertEqual([r["status"] for r in second], ["duplicate"] * 2)
        self.assertEqual(len(list(self.output.rglob("*.jpg"))), 2)
        with (self.output / "manifest.csv").open() as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 4)

    def test_stale_frames_are_not_training_samples(self):
        metadata = self.payload(c.iso(self.now - timedelta(hours=1)))
        self.assertEqual([r["status"] for r in self.collect(metadata)], ["stale"] * 2)
        self.assertFalse(list(self.output.rglob("*.jpg")))

    def test_missing_and_corrupt_images(self):
        empty = json.dumps({"items": [{"cameras": []}]}).encode()
        self.assertEqual([r["status"] for r in self.collect(empty)], ["missing"] * 2)
        self.assertEqual([r["status"] for r in self.collect(self.payload(), b"<html>error</html>")], ["error"] * 2)

    def test_network_failure_is_audited(self):
        with patch.object(c, "fetch_bytes", side_effect=RuntimeError("Network unavailable")):
            rows = c.collect_cycle(self.cameras, self.output, "data-gov-sg", {}, now=self.now)
        self.assertEqual([r["status"] for r in rows], ["error"] * 2)
        self.assertTrue((self.output / "manifest.csv").exists())

    def test_lta_signed_urls_are_not_archived(self):
        signed = "https://example.test/image.jpg?secret=ephemeral"
        payload = json.dumps({"value": [{"CameraID": "4798", "ImageLink": signed}]}).encode()
        with patch.object(c, "fetch_bytes", side_effect=lambda url, headers=None:
                          payload if url == c.ENDPOINTS["lta"] else b"\xff\xd8\xfftest\xff\xd9"):
            rows = c.collect_cycle(self.cameras, self.output, "lta", {"AccountKey": "test"}, now=self.now)
        self.assertEqual(rows[0]["timestamp_basis"], "collection_time_proxy")
        self.assertEqual(rows[1]["status"], "missing")
        for path in self.output.rglob("*"):
            if path.suffix in (".json", ".csv"):
                self.assertNotIn("ephemeral", path.read_text())

    def test_windows_and_invalid_intervals(self):
        self.assertTrue(c.active(23 * 3600, 22 * 3600, 5 * 3600))
        self.assertTrue(c.active(3600, 22 * 3600, 5 * 3600))
        self.assertFalse(c.active(5 * 3600, 22 * 3600, 5 * 3600))
        for value in ("nan", "inf", "0", "-1"):
            with self.assertRaises(c.argparse.ArgumentTypeError):
                c.positive(value)


if __name__ == "__main__":
    unittest.main()
