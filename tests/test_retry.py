from src.shared.llm.retry import (
    RetryConfig,
    RetryExhaustedError,
    execute_with_retry,
)

attempt_counter = {"count": 0}


def succeeds_on_third_attempt() -> str:
    attempt_counter["count"] += 1

    if attempt_counter["count"] < 3:
        raise TimeoutError("Temporary timeout.")

    return "success"


result, retry_count = execute_with_retry(
    succeeds_on_third_attempt,
    config=RetryConfig(
        max_attempts=3,
        initial_delay_seconds=0.01,
        backoff_multiplier=2.0,
        max_delay_seconds=0.05,
    ),
    retryable_exceptions=(TimeoutError,),
)

print("Result:", result)
print("Retry count:", retry_count)
print("Total attempts:", attempt_counter["count"])

assert result == "success"
assert retry_count == 2
assert attempt_counter["count"] == 3


def always_fails() -> None:
    raise TimeoutError("Persistent timeout.")


try:
    execute_with_retry(
        always_fails,
        config=RetryConfig(
            max_attempts=2,
            initial_delay_seconds=0.01,
            max_delay_seconds=0.02,
        ),
        retryable_exceptions=(TimeoutError,),
    )
except RetryExhaustedError as error:
    print("Retry exhaustion correctly detected.")
    print(error)
else:
    raise AssertionError("RetryExhaustedError was expected but not raised.")


print("Retry tests completed successfully.")
