"""The expiry of an idempotency record is measured in elapsed seconds, also across a daylight saving time change."""

from __future__ import annotations

import datetime as dt
import time
from types import SimpleNamespace

import pytest

from aws_lambda_powertools.utilities.idempotency import IdempotencyConfig
from aws_lambda_powertools.utilities.idempotency.persistence import base
from aws_lambda_powertools.utilities.idempotency.persistence.base import BasePersistenceLayer, DataRecord

# 2025-11-02 00:30 in New York (EDT): the clocks go back one hour at 02:00 EDT
BEFORE_FALL_BACK = dt.datetime(2025, 11, 2, 4, 30, tzinfo=dt.timezone.utc).timestamp()


class RecordingPersistenceLayer(BasePersistenceLayer):
    def __init__(self, expires_after_seconds: int):
        super().__init__()
        self.configure(config=IdempotencyConfig(expires_after_seconds=expires_after_seconds), function_name="fn")
        self.saved: list[DataRecord] = []

    def _put_record(self, data_record: DataRecord) -> None:
        self.saved.append(data_record)

    def _update_record(self, data_record: DataRecord) -> None:
        self.saved.append(data_record)

    def _get_record(self, idempotency_key) -> DataRecord: ...

    def _delete_record(self, data_record: DataRecord) -> None: ...


@pytest.fixture
def new_york_clock(monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is not available on this platform")

    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()

    class FrozenDatetime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime.fromtimestamp(BEFORE_FALL_BACK, tz)

    monkeypatch.setattr(
        base,
        "dt",
        SimpleNamespace(datetime=FrozenDatetime, timedelta=dt.timedelta, timezone=dt.timezone),
    )
    yield
    monkeypatch.undo()
    time.tzset()


def test_record_expiry_is_measured_in_elapsed_seconds_across_dst(new_york_clock):
    # GIVEN a record saved at 00:30 EDT, before the clocks go back in New York, expiring after two hours
    layer = RecordingPersistenceLayer(expires_after_seconds=7200)

    # WHEN the in-progress record is saved
    layer.save_inprogress(data={"order": "A"}, remaining_time_in_millis=30_000)

    # THEN it expires two elapsed hours later, not three
    assert layer.saved[0].expiry_timestamp == int(BEFORE_FALL_BACK) + 7200


def test_in_progress_expiry_is_measured_in_elapsed_time_across_dst(new_york_clock):
    # GIVEN a record saved at 00:30 EDT with 30 seconds left before the Lambda times out
    layer = RecordingPersistenceLayer(expires_after_seconds=7200)

    # WHEN the in-progress record is saved
    layer.save_inprogress(data={"order": "A"}, remaining_time_in_millis=30_000)

    # THEN the in-progress expiry is 30 elapsed seconds later
    assert layer.saved[0].in_progress_expiry_timestamp == (int(BEFORE_FALL_BACK) + 30) * 1000
