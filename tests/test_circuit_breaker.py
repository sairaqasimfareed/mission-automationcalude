from src.shared.llm.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
)

breaker = CircuitBreaker(
    failure_threshold=3,
    recovery_timeout_seconds=60,
)

print("Initial state:", breaker.state)
print("Can execute:", breaker.can_execute())

breaker.record_failure()
breaker.record_failure()

print("State after two failures:", breaker.state)
print("Failure count:", breaker.failure_count)

breaker.record_failure()

print("State after three failures:", breaker.state)
print("Can execute after opening:", breaker.can_execute())

assert breaker.state == CircuitState.OPEN
assert breaker.can_execute() is False

breaker.record_success()

print("State after success:", breaker.state)
print("Failure count after success:", breaker.failure_count)
print("Circuit breaker tests completed successfully.")
