"""Provider-independent errors returned by external capability adapters."""


class ProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        transient: bool,
        detail: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.transient = transient
        # Non-secret diagnostic context such as the start of an unparseable model answer.
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds
