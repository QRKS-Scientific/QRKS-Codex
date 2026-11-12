from __future__ import annotations


class NetError(Exception):
    pass


class Offline(NetError):
    """The server could not be reached (no internet, server down, timeout)."""


class ApiError(NetError):
    def __init__(self, status: int, code: str, message: str, retry_after: int | None = None, attempts_left: int | None = None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.retry_after, self.attempts_left = retry_after, attempts_left

    @classmethod
    def from_response(cls, r) -> "ApiError":
        try:
            detail = r.json().get("detail", {})
        except Exception:                                            # noqa: BLE001
            detail = {}
        if isinstance(detail, list):                                  # a validation error from the server
            detail = {"code": "invalid_request", "message": "The server rejected the request as invalid."}
        if not isinstance(detail, dict):
            detail = {"message": str(detail)}
        retry = detail.get("retry_after") or r.headers.get("retry-after")
        return cls(r.status_code, detail.get("code", f"http_{r.status_code}"), detail.get("message", f"The server answered {r.status_code}."),
                   int(retry) if retry else None, detail.get("attempts_left"))
