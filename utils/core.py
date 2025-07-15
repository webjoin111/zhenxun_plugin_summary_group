from enum import Enum
from typing import Any


class ErrorCode(Enum):
    """错误代码枚举"""

    UNKNOWN_ERROR = 1000
    PERMISSION_DENIED = 1001
    INVALID_PARAMETER = 1002
    OPERATION_TIMEOUT = 1003
    RESOURCE_NOT_FOUND = 1004

    MESSAGE_FETCH_FAILED = 3000
    MESSAGE_PROCESS_FAILED = 3001
    MESSAGE_COUNT_INVALID = 3002
    MESSAGE_EMPTY = 3003
    MESSAGE_FORMAT_ERROR = 3004

    SCHEDULE_SET_FAILED = 4000
    SCHEDULE_REMOVE_FAILED = 4001
    SCHEDULE_INVALID_TIME = 4002
    SCHEDULER_NOT_RUNNING = 4003
    SCHEDULER_TASK_FAILED = 4004

    IMAGE_GENERATION_FAILED = 5000
    IMAGE_RENDER_ERROR = 5001
    IMAGE_SIZE_EXCEEDED = 5002
    IMAGE_FORMAT_ERROR = 5003

    STORAGE_READ_ERROR = 6000
    STORAGE_WRITE_ERROR = 6001
    STORAGE_FORMAT_ERROR = 6002
    STORAGE_PERMISSION_ERROR = 6003

    DB_CONNECTION_ERROR = 7000
    DB_QUERY_ERROR = 7001
    DB_WRITE_ERROR = 7002
    DB_MODEL_ERROR = 7003


class SummaryException(Exception):
    """总结功能相关的基础异常类"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
        cause: Exception | None = None,
    ):
        self.message = message
        self.code = code
        self.details = details or {}
        self.recoverable = recoverable
        self.cause = cause
        super().__init__(message)

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (错误码: {self.code.name}, 详情: {self.details})"
        return f"{self.message} (错误码: {self.code.name})"

    @property
    def user_friendly_message(self) -> str:
        """返回适合向用户展示的错误消息"""
        messages = {
            ErrorCode.PERMISSION_DENIED: "抱歉，你没有权限执行此操作。",
            ErrorCode.MESSAGE_FETCH_FAILED: "获取群聊消息失败，请稍后再试或联系管理员。",
            ErrorCode.MESSAGE_COUNT_INVALID: "请求的消息数量无效，请检查范围。",
            ErrorCode.MESSAGE_EMPTY: "未能获取到有效的聊天记录。",
            ErrorCode.MESSAGE_PROCESS_FAILED: "处理消息时发生内部错误。",
            ErrorCode.IMAGE_GENERATION_FAILED: "生成图片失败，请检查配置或联系管理员。",
            ErrorCode.SCHEDULE_INVALID_TIME: "定时设置失败：时间格式无效。",
        }
        return messages.get(self.code, self.message or "发生了一个未知错误。")
