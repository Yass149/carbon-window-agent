"""One reusable transport with bounded TTL cache and limited transient retries."""

from collections import OrderedDict
from copy import deepcopy
from time import monotonic, sleep
from typing import Any

import httpx


class UpstreamError(RuntimeError):
    """A remote response could not be obtained or validated."""


class HTTPClient:
    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        ttl: float = 600,
        max_entries: int = 128,
        backoff: float = 0.25,
    ) -> None:
        if ttl < 0 or max_entries < 1 or backoff < 0:
            raise ValueError("Invalid cache or retry settings")
        self.client = client or httpx.Client(timeout=httpx.Timeout(10, connect=5))
        self.ttl, self.max_entries, self.backoff = ttl, max_entries, backoff
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get_json(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        """GET JSON; retry 5xx/timeouts twice and cache successful responses."""
        request = self.client.build_request("GET", url, params=params)
        key = str(request.url)
        cached = self._cache.get(key)
        if cached and monotonic() - cached[0] < self.ttl:
            self._cache.move_to_end(key)
            return deepcopy(cached[1])
        self._cache.pop(key, None)
        for attempt in range(3):
            try:
                response = self.client.send(request)
                if response.status_code >= 500 and attempt < 2:
                    sleep(self.backoff * 2**attempt)
                    continue
                response.raise_for_status()
                payload = response.json()
            except httpx.TimeoutException as exc:
                if attempt < 2:
                    sleep(self.backoff * 2**attempt)
                    continue
                raise UpstreamError("Upstream request timed out") from exc
            except (httpx.HTTPError, ValueError) as exc:
                raise UpstreamError("Upstream request failed or returned invalid JSON") from exc
            self._cache[key] = (monotonic(), deepcopy(payload))
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
            return payload
        raise UpstreamError("Retry limit exceeded")  # defensive

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "HTTPClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
