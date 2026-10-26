"""对外暴露的稳定错误信息，避免泄露 SDK 异常、请求头或密钥。"""

from astroagent.schemas import ErrorInfo


class ServiceError(Exception):
    def __init__(self, status_code: int, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.error = ErrorInfo(code=code, message=message, retryable=retryable)
