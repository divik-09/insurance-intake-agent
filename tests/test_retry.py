import pytest

from app.retry import RetryExhausted, retry_call


def test_succeeds_after_transient_failures_with_exponential_backoff():
    calls, sleeps = {"n": 0}, []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("nope")
        return "ok"

    result, attempts = retry_call(flaky, attempts=5, base_delay=1.0, retry_on=(ConnectionError,), sleep=sleeps.append)
    assert (result, attempts) == ("ok", 3)
    assert sleeps == [1.0, 2.0]  # doubles each retry


def test_exhaustion_raises_with_attempt_count_and_no_trailing_sleep():
    sleeps = []

    def always_fails():
        raise ConnectionError("down")

    with pytest.raises(RetryExhausted) as info:
        retry_call(always_fails, attempts=3, base_delay=0.5, retry_on=(ConnectionError,), sleep=sleeps.append)
    assert info.value.attempts == 3
    assert isinstance(info.value.last_error, ConnectionError)
    assert sleeps == [0.5, 1.0]  # two sleeps between three attempts


def test_non_retryable_errors_propagate_immediately():
    calls = {"n": 0}

    def bug():
        calls["n"] += 1
        raise ValueError("programming error")

    with pytest.raises(ValueError):
        retry_call(bug, attempts=5, retry_on=(ConnectionError,), sleep=lambda s: None)
    assert calls["n"] == 1
