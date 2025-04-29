from enum import Enum
from typing import Any


class ErrorCode(Enum):
    """错误代码枚举"""
    # 通用错误 (1000-1999)
    UNKNOWN_ERROR = 1000
    PERMISSION_DENIED = 1001
    INVALID_PARAMETER = 1002
    OPERATION_TIMEOUT = 1003
    RESOURCE_NOT_FOUND = 1004

    # 模型相关错误 (2000-2999)
    MODEL_INIT_FAILED = 2000
    MODEL_NOT_FOUND = 2001
    API_REQUEST_FAILED = 2002
    API_RESPONSE_INVALID = 2003
    API_KEY_INVALID = 2004
    API_QUOTA_EXCEEDED = 2005
    API_TIMEOUT = 2006
    API_RATE_LIMITED = 2007

    # 消息相关错误 (3000-3999)
    MESSAGE_FETCH_FAILED = 3000
    MESSAGE_PROCESS_FAILED = 3001
    MESSAGE_COUNT_INVALID = 3002
    MESSAGE_EMPTY = 3003
    MESSAGE_FORMAT_ERROR = 3004

    # 调度相关错误 (4000-4999)
    SCHEDULE_SET_FAILED = 4000
    SCHEDULE_REMOVE_FAILED = 4001
    SCHEDULE_INVALID_TIME = 4002
    SCHEDULER_NOT_RUNNING = 4003
    SCHEDULER_TASK_FAILED = 4004

    # 图片生成相关错误 (5000-5999)
    IMAGE_GENERATION_FAILED = 5000
    IMAGE_RENDER_ERROR = 5001
    IMAGE_SIZE_EXCEEDED = 5002
    IMAGE_FORMAT_ERROR = 5003

    # 存储相关错误 (6000-6999)
    STORAGE_READ_ERROR = 6000
    STORAGE_WRITE_ERROR = 6001
    STORAGE_FORMAT_ERROR = 6002
    STORAGE_PERMISSION_ERROR = 6003

    # 数据库相关错误 (7000-7999)
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
        cause: Exception | None = None
    ):
        self.message = message
        self.code = code
        self.details = details or {}
        self.recoverable = recoverable  # 是否可恢复的错误
        self.cause = cause
        super().__init__(message)

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (错误码: {self.code.name}, 详情: {self.details})"
        return f"{self.message} (错误码: {self.code.name})"

    @property
    def user_friendly_message(self) -> str:
        """返回适合向用户展示的错误消息"""
        return self.message


class ScheduleException(SummaryException):
    """调度相关的异常"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.SCHEDULE_SET_FAILED,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
        cause: Exception | None = None
    ):
        super().__init__(message, code, details, recoverable, cause)

    @property
    def user_friendly_message(self) -> str:
        """返回适合向用户展示的错误消息"""
        if self.code == ErrorCode.SCHEDULE_INVALID_TIME:
            return "定时设置失败：时间格式无效，请使用 HH:MM 或 HHMM 格式。"
        elif self.code == ErrorCode.SCHEDULE_SET_FAILED:
            return "定时设置失败，请检查参数后重试。"
        elif self.code == ErrorCode.SCHEDULE_REMOVE_FAILED:
            return "取消定时失败，可能该群未设置定时任务。"
        return self.message


class SchedulerException(SummaryException):
    """调度器相关的异常"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.SCHEDULER_NOT_RUNNING,
        details: dict[str, Any] | None = None,
        recoverable: bool = False,  # 调度器错误通常不可自动恢复
        cause: Exception | None = None
    ):
        super().__init__(message, code, details, recoverable, cause)

    @property
    def user_friendly_message(self) -> str:
        """返回适合向用户展示的错误消息"""
        if self.code == ErrorCode.SCHEDULER_NOT_RUNNING:
            return "定时系统未运行，请联系管理员检查。"
        return "定时系统出现问题，请联系管理员。"


class TimeParseException(SummaryException):
    """时间解析相关的异常"""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None
    ):
        super().__init__(
            message,
            ErrorCode.SCHEDULE_INVALID_TIME,
            details,
            True,  # 时间解析错误可以通过用户重新输入恢复
            cause
        )

    @property
    def user_friendly_message(self) -> str:
        return "时间格式无效，请使用 HH:MM 或 HHMM 格式。"


class ModelException(SummaryException):
    """模型相关的异常"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.API_REQUEST_FAILED,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
        cause: Exception | None = None
    ):
        super().__init__(message, code, details, recoverable, cause)

    @property
    def user_friendly_message(self) -> str:
        """返回适合向用户展示的错误消息"""
        if self.code == ErrorCode.MODEL_NOT_FOUND:
            return "AI模型未找到，请检查配置或联系管理员。"
        elif self.code == ErrorCode.API_KEY_INVALID:
            return "API密钥无效，请联系管理员更新配置。"
        elif self.code == ErrorCode.API_QUOTA_EXCEEDED:
            return "API使用配额已用尽，请稍后再试或联系管理员。"
        elif self.code == ErrorCode.API_TIMEOUT:
            return "AI服务响应超时，请稍后再试。"
        elif self.code == ErrorCode.API_RATE_LIMITED:
            return "请求过于频繁，已被AI服务限流，请稍后再试。"
        elif self.code == ErrorCode.MODEL_INIT_FAILED:
            return "AI模型初始化失败，请联系管理员检查配置。"
        return "AI服务出现问题，请稍后再试。"


class MessageFetchException(SummaryException):
    """消息获取相关的异常"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.MESSAGE_FETCH_FAILED,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
        cause: Exception | None = None
    ):
        super().__init__(message, code, details, recoverable, cause)

    @property
    def user_friendly_message(self) -> str:
        """返回适合向用户展示的错误消息"""
        if self.code == ErrorCode.MESSAGE_COUNT_INVALID:
            return "消息数量无效，请检查参数范围。"
        elif self.code == ErrorCode.MESSAGE_EMPTY:
            return "未找到任何消息，请确认群内有足够的聊天记录。"
        return "获取消息失败，请稍后再试。"


class MessageProcessException(SummaryException):
    """消息处理相关的异常"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.MESSAGE_PROCESS_FAILED,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
        cause: Exception | None = None
    ):
        super().__init__(message, code, details, recoverable, cause)

    @property
    def user_friendly_message(self) -> str:
        """返回适合向用户展示的错误消息"""
        if self.code == ErrorCode.MESSAGE_FORMAT_ERROR:
            return "消息格式处理失败，可能包含不支持的内容。"
        return "处理消息时出错，请稍后再试。"


class ImageGenerationException(SummaryException):
    """图片生成相关的异常"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.IMAGE_GENERATION_FAILED,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
        cause: Exception | None = None
    ):
        super().__init__(message, code, details, recoverable, cause)

    @property
    def user_friendly_message(self) -> str:
        """返回适合向用户展示的错误消息"""
        if self.code == ErrorCode.IMAGE_RENDER_ERROR:
            return "渲染图片失败，请检查系统环境或联系管理员。"
        elif self.code == ErrorCode.IMAGE_SIZE_EXCEEDED:
            return "生成的图片大小超出限制，请尝试减少内容量。"
        return "生成图片失败，将尝试使用文本模式。"


class StorageException(SummaryException):
    """存储相关的异常"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.STORAGE_READ_ERROR,
        details: dict[str, Any] | None = None,
        recoverable: bool = False,  # 存储错误通常需要管理员介入
        cause: Exception | None = None
    ):
        super().__init__(message, code, details, recoverable, cause)

    @property
    def user_friendly_message(self) -> str:
        return "存储系统出现问题，请联系管理员。"


class DatabaseException(SummaryException):
    """数据库相关的异常"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.DB_CONNECTION_ERROR,
        details: dict[str, Any] | None = None,
        recoverable: bool = False,  # 数据库错误通常需要管理员介入
        cause: Exception | None = None
    ):
        super().__init__(message, code, details, recoverable, cause)

    @property
    def user_friendly_message(self) -> str:
        return "数据库操作失败，请联系管理员。"
