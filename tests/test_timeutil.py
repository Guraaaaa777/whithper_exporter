import unittest
from datetime import datetime, timedelta, timezone

from withper_exporter.timeutil import (
    TimeParseError,
    floor_to_interval,
    parse_duration,
    parse_timestamp,
    window_filename,
)

from .helpers import TZ, dt


class ParseDurationTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(parse_duration("90s"), timedelta(seconds=90))
        self.assertEqual(parse_duration("10m"), timedelta(minutes=10))
        self.assertEqual(parse_duration("1h"), timedelta(hours=1))
        self.assertEqual(parse_duration("1d"), timedelta(days=1))

    def test_compound(self):
        self.assertEqual(parse_duration("1h30m"), timedelta(minutes=90))
        self.assertEqual(parse_duration("1h 30m"), timedelta(minutes=90))

    def test_numeric_is_seconds(self):
        self.assertEqual(parse_duration(120), timedelta(seconds=120))

    def test_zero_only_when_allowed(self):
        self.assertEqual(parse_duration("0s", allow_zero=True), timedelta(0))
        with self.assertRaises(TimeParseError):
            parse_duration("0s")

    def test_rejects_garbage(self):
        for bad in ("", "abc", "1x", "1h!", "-5m"):
            with self.subTest(bad=bad), self.assertRaises(TimeParseError):
                parse_duration(bad)


class FloorTest(unittest.TestCase):
    def test_hourly(self):
        self.assertEqual(
            floor_to_interval(dt(hour=14, minute=37), timedelta(hours=1)),
            dt(hour=14),
        )

    def test_ten_minutes(self):
        self.assertEqual(
            floor_to_interval(dt(hour=14, minute=37, second=5), timedelta(minutes=10)),
            dt(hour=14, minute=30),
        )

    def test_daily_floors_to_midnight(self):
        self.assertEqual(floor_to_interval(dt(hour=23, minute=59), timedelta(days=1)), dt())

    def test_interval_longer_than_day(self):
        self.assertEqual(floor_to_interval(dt(hour=5), timedelta(days=3)), dt())


class FilenameTest(unittest.TestCase):
    def test_format(self):
        self.assertEqual(
            window_filename(dt(hour=14), dt(hour=15)),
            "202609111400-202609111500.txt",
        )

    def test_custom_suffix(self):
        self.assertEqual(
            window_filename(dt(hour=0), dt(hour=1), ".log"),
            "202609110000-202609110100.log",
        )


class ParseTimestampTest(unittest.TestCase):
    def test_iso_with_offset(self):
        parsed = parse_timestamp("2026-09-11T14:30:00+09:00", TZ)
        self.assertEqual(parsed, dt(hour=14, minute=30))

    def test_iso_zulu_is_converted(self):
        parsed = parse_timestamp("2026-09-11T05:30:00Z", TZ)
        self.assertEqual(parsed, dt(hour=14, minute=30))

    def test_naive_assumes_config_tz(self):
        self.assertEqual(parse_timestamp("2026-09-11 14:30:00", TZ), dt(hour=14, minute=30))

    def test_epoch_seconds_and_millis_agree(self):
        seconds = dt(hour=14, minute=30).timestamp()
        self.assertEqual(parse_timestamp(seconds, TZ), dt(hour=14, minute=30))
        self.assertEqual(parse_timestamp(seconds * 1000, TZ), dt(hour=14, minute=30))

    def test_explicit_format(self):
        self.assertEqual(
            parse_timestamp("20260911_1430", TZ, "%Y%m%d_%H%M"), dt(hour=14, minute=30)
        )

    def test_datetime_passthrough_normalizes_tz(self):
        utc_value = datetime(2026, 9, 11, 5, 30, tzinfo=timezone.utc)
        self.assertEqual(parse_timestamp(utc_value, TZ), dt(hour=14, minute=30))

    def test_unparsable(self):
        with self.assertRaises(TimeParseError):
            parse_timestamp("いつか", TZ)


if __name__ == "__main__":
    unittest.main()
