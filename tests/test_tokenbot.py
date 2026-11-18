import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tokenbot as tb  # noqa: E402

KST = timezone(timedelta(hours=9))
W = timedelta(hours=5)


def dt(h, m=0, day=18):
    return datetime(2026, 11, day, h, m, tzinfo=KST)


class WindowTests(unittest.TestCase):
    def test_no_activity(self):
        self.assertIsNone(tb.compute_window([], W, dt(12)))

    def test_active_window(self):
        self.assertEqual(tb.compute_window([dt(9), dt(10), dt(13)], W, dt(13, 30)), (dt(9), dt(14)))

    def test_expired_window(self):
        self.assertIsNone(tb.compute_window([dt(6)], W, dt(12)))

    def test_new_window_after_expiry(self):
        # 6시 시작 → 11시 만료, 11:30 사용 → 새 윈도우
        self.assertEqual(tb.compute_window([dt(6), dt(10), dt(11, 30)], W, dt(12)), (dt(11, 30), dt(16, 30)))

    def test_floor_to_hour(self):
        self.assertEqual(tb.compute_window([dt(9, 40)], W, dt(10), floor_to_hour=True), (dt(9), dt(14)))


class QuietHoursTests(unittest.TestCase):
    def test_simple_range(self):
        self.assertTrue(tb.in_quiet_hours(dt(3), ["01:00-06:00"]))
        self.assertFalse(tb.in_quiet_hours(dt(6), ["01:00-06:00"]))

    def test_wrapping_range(self):
        self.assertTrue(tb.in_quiet_hours(dt(23, 30), ["23:00-05:00"]))
        self.assertTrue(tb.in_quiet_hours(dt(4), ["23:00-05:00"]))
        self.assertFalse(tb.in_quiet_hours(dt(12), ["23:00-05:00"]))

    def test_next_allowed(self):
        self.assertEqual(tb.next_allowed_time(dt(2, 13), ["01:00-06:00"]), dt(6))


class NextPingTests(unittest.TestCase):
    cfg = {"buffer_minutes": 2, "quiet_hours": [], "window_hours": 5}

    def test_no_window_pings_now(self):
        self.assertEqual(tb.next_ping_time(None, {}, self.cfg, dt(12)), dt(12))

    def test_window_end_plus_buffer(self):
        self.assertEqual(tb.next_ping_time((dt(9), dt(14)), {}, self.cfg, dt(12)), dt(14, 2))

    def test_retry_after_respected(self):
        pstate = {"retry_after": dt(12, 10).isoformat()}
        self.assertEqual(tb.next_ping_time(None, pstate, self.cfg, dt(12)), dt(12, 10))


class LogParsingTests(unittest.TestCase):
    def test_collect_and_filter_types(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.jsonl"
            now = datetime.now().astimezone()
            rows = [
                {"type": "user", "timestamp": (now - timedelta(hours=1)).isoformat()},
                {"type": "queue-operation", "timestamp": (now - timedelta(minutes=30)).isoformat()},
                {"type": "assistant", "timestamp": (now - timedelta(hours=30)).isoformat()},
            ]
            p.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
            pcfg = {"log_globs": [str(Path(d) / "*.jsonl")], "activity_types": ["user", "assistant"]}
            stamps = tb.collect_activity(pcfg, now - timedelta(hours=15))
            self.assertEqual(len(stamps), 1)


class TickTests(unittest.TestCase):
    """가짜 명령으로 tick 전체 흐름 확인 (실제 Claude/Codex 호출 없음)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self._orig = {k: getattr(tb, k) for k in
                      ["BOT_HOME", "CONFIG_PATH", "DATA_DIR", "STATE_PATH", "LOG_PATH", "LOCK_PATH", "PING_WORKDIR"]}
        tb.BOT_HOME = home
        tb.CONFIG_PATH = home / "config.json"
        tb.DATA_DIR = home / "data"
        tb.STATE_PATH = tb.DATA_DIR / "state.json"
        tb.LOG_PATH = tb.DATA_DIR / "bot.log"
        tb.LOCK_PATH = tb.DATA_DIR / "tick.lock"
        tb.PING_WORKDIR = tb.DATA_DIR / "ping-workdir"

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(tb, k, v)
        self.tmp.cleanup()

    def write_cfg(self, command):
        tb.CONFIG_PATH.write_text(json.dumps({
            "notify_on_failure": False,
            "providers": {"fake": {"command": command, "log_globs": []}},
        }))

    def test_success_then_wait(self):
        self.write_cfg(["echo", "ok"])
        tb.main(["tick"])
        st = json.loads(tb.STATE_PATH.read_text())["providers"]["fake"]
        self.assertEqual(st["last_result"], "ok")
        first = st["last_success"]
        tb.main(["tick"])  # 윈도우가 살아 있으니 다시 보내지 않아야 함
        st = json.loads(tb.STATE_PATH.read_text())["providers"]["fake"]
        self.assertEqual(st["last_success"], first)

    def test_limit_message_schedules_retry(self):
        self.write_cfg(["sh", "-c", "echo 'Claude usage limit reached'; exit 1"])
        tb.main(["tick"])
        st = json.loads(tb.STATE_PATH.read_text())["providers"]["fake"]
        self.assertEqual(st["last_result"], "limited")
        self.assertIn("retry_after", st)
        self.assertEqual(len(st["failed_attempts"]), 1)


if __name__ == "__main__":
    unittest.main()
