import time
import uuid
import httpx

APP_URL = "http://localhost:8000"

class CircuitBreakerOpen(Exception):
    pass

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_time: float = 6.0):
        self.failure_threshold = failure_threshold
        self.recovery_time = recovery_time
        self.failure_count = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF-OPEN
        self.last_failure_time = 0.0

    def record_success(self):
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"

    def can_execute(self) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if time.monotonic() - self.last_failure_time > self.recovery_time:
                self.state = "HALF-OPEN"
                print(
                    f"[Breaker] Cooldown expired ({self.recovery_time}s). "
                    "State transitioned to HALF-OPEN (probing)..."
                )
                return True
            return False
        return True  # HALF-OPEN allows a single probe call

class ResilientCaller:
    def __init__(self, timeout: float = 2.0, max_retries: int = 2):
        self.timeout = timeout
        self.max_retries = max_retries
        self.breaker = CircuitBreaker(failure_threshold=3, recovery_time=6.0)

    def send_order(self, product_id: int, idempotency_key: str, force_url: str = None):
        if not self.breaker.can_execute():
            raise CircuitBreakerOpen(f"Circuit Breaker is OPEN. Local execution short-circuited.")

        url = force_url or f"{APP_URL}/api/orders"
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key
        }
        payload = {
            "customer_reference": f"CALLER-{idempotency_key[:8]}",
            "items": [{"product_id": product_id, "quantity": 1}]
        }

        attempt = 0
        delay = 0.5

        while attempt <= self.max_retries:
            attempt += 1
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, json=payload, headers=headers)
                    if resp.status_code in (200, 201):
                        self.breaker.record_success()
                        return resp.status_code, resp.json()
                    elif resp.status_code >= 500:
                        raise httpx.HTTPStatusError("Server error", request=resp.request, response=resp)
                    else:
                        return resp.status_code, resp.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                print(f"    [Attempt {attempt}/{self.max_retries + 1}] Call failed: {type(exc).__name__}")
                if attempt <= self.max_retries:
                    print(f"    [Backoff] Waiting {delay:.1f}s before retrying idempotent request...")
                    time.sleep(delay)
                    delay *= 2.0
                else:
                    self.breaker.record_failure()
                    raise

def run_demo():
    caller = ResilientCaller(timeout=2.0, max_retries=2)
    product_id = 16  # Existing product with stock

    print("=== SCENARIO 1: Successful Safe Call ===")
    key1 = str(uuid.uuid4())
    status, body = caller.send_order(product_id, key1)
    print(f"Result: HTTP {status} (Order ID: {body.get('id')}) | Breaker state: {caller.breaker.state}\n")

    print("=== SCENARIO 2: Transient Failures & Retries with Backoff ===")
    # Send calls to a non-existent port (8001) to simulate network/server drops
    bad_url = "http://localhost:8001/api/orders"
    for i in range(3):
        print(f"\nSimulating failing call {i + 1}...")
        try:
            caller.send_order(product_id, str(uuid.uuid4()), force_url=bad_url)
        except Exception as e:
            print(f"Outcome: {e} | Breaker state: {caller.breaker.state}")

    print("\n=== SCENARIO 3: Circuit Breaker Tripped (Short-Circuit) ===")
    try:
        caller.send_order(product_id, str(uuid.uuid4()))
    except CircuitBreakerOpen as e:
        print(f"Blocked by Circuit Breaker: {e} | Breaker state: {caller.breaker.state}")

    print("\n=== SCENARIO 4: Recovery Period & Breaker Reset ===")
    print("Waiting 7 seconds for recovery window to expire...")
    time.sleep(7.0)
    key2 = str(uuid.uuid4())
    status, body = caller.send_order(product_id, key2)
    print(f"Probe Call Succeeded: HTTP {status} (Order ID: {body.get('id')}) | Breaker state: {caller.breaker.state}")

if __name__ == "__main__":
    run_demo()