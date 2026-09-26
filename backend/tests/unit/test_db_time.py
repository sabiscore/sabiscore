"""Reading a naive UTC column back out must carry its offset (directive v11 §3)."""

from datetime import datetime, timedelta, timezone

from src.utils.db_time import to_utc_iso


def test_a_naive_column_value_is_published_as_utc():
    # An offset-less string is parsed as local time by browsers, which put an
    # 18:00 UTC kickoff at "18:00 WAT" for a Lagos visitor.
    assert to_utc_iso(datetime(2026, 10, 9, 18, 0)) == "2026-10-09T18:00:00+00:00"


def test_an_aware_value_is_converted_to_utc_not_relabelled():
    lagos = timezone(timedelta(hours=1))
    assert to_utc_iso(datetime(2026, 10, 9, 19, 0, tzinfo=lagos)) == "2026-10-09T18:00:00+00:00"
