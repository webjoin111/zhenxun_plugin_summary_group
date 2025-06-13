import asyncio
from collections.abc import Callable
from enum import Enum
import json
import random
import time
from typing import Any

from nonebot_plugin_apscheduler import scheduler

from zhenxun.configs.path_config import DATA_PATH
from zhenxun.services.log import logger

from ..store import store


class ErrorCode(Enum):
    """错误代码枚举"""

    UNKNOWN_ERROR = 1000
    PERMISSION_DENIED = 1001
    INVALID_PARAMETER = 1002
    OPERATION_TIMEOUT = 1003
    RESOURCE_NOT_FOUND = 1004

    MODEL_INIT_FAILED = 2000
    MODEL_NOT_FOUND = 2001
    API_REQUEST_FAILED = 2002
    API_RESPONSE_INVALID = 2003
    API_KEY_INVALID = 2004
    API_QUOTA_EXCEEDED = 2005
    API_TIMEOUT = 2006
    API_RATE_LIMITED = 2007

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
        return self.message


class ScheduleException(SummaryException):
    """调度相关的异常"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.SCHEDULE_SET_FAILED,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
        cause: Exception | None = None,
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
        recoverable: bool = False,
        cause: Exception | None = None,
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

    def __init__(self, message: str, details: dict[str, Any] | None = None, cause: Exception | None = None):
        super().__init__(message, ErrorCode.SCHEDULE_INVALID_TIME, details, True, cause)

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
        cause: Exception | None = None,
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
        cause: Exception | None = None,
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
        cause: Exception | None = None,
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
        cause: Exception | None = None,
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
        recoverable: bool = False,
        cause: Exception | None = None,
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
        recoverable: bool = False,
        cause: Exception | None = None,
    ):
        super().__init__(message, code, details, recoverable, cause)

    @property
    def user_friendly_message(self) -> str:
        return "数据库操作失败，请联系管理员。"



async def with_retry(func: Callable, max_retries: int = 3, retry_delay: int = 2) -> Any:
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if attempt < max_retries - 1:
                delay = retry_delay * (2**attempt)
                logger.warning(
                    f"操作失败 ({attempt + 1}/{max_retries})，将在 {delay} 秒后重试: {e}",
                    command="with_retry",
                    e=e,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(f"操作失败，已达到最大重试次数 ({max_retries}): {e}", command="with_retry", e=e)
                raise


def check_job_consistency():
    """检查任务一致性，返回缺失和孤立的任务"""
    group_ids = store.get_all_groups()
    scheduled_job_ids = [job.id for job in scheduler.get_jobs() if job.id.startswith("summary_group_")]

    missing_jobs = []
    for group_id in group_ids:
        job_id = f"summary_group_{group_id}"
        if job_id not in scheduled_job_ids:
            missing_jobs.append(group_id)

    orphaned_jobs = []
    for job_id in scheduled_job_ids:
        group_id = job_id.replace("summary_group_", "")
        if group_id not in group_ids:
            orphaned_jobs.append(job_id)

    return missing_jobs, orphaned_jobs


async def check_system_health():
    from .scheduler_tasks import process_summary_queue, summary_queue, task_processor_started

    health_status = {
        "scheduler": {
            "running": scheduler.running,
            "jobs_count": len(scheduler.get_jobs()),
        },
        "task_queue": {
            "processor_active": task_processor_started,
            "queue_size": summary_queue.qsize() if summary_queue else None,
        },
        "repairs_applied": [],
        "warnings": [],
    }

    if not scheduler.running:
        health_status["warnings"].append("调度器未运行")

        try:
            scheduler.start()
            health_status["repairs_applied"].append("已启动调度器")
        except Exception as e:
            health_status["errors"] = [f"启动调度器失败: {e!s}"]

    all_tasks = asyncio.all_tasks()
    processor_tasks = [t for t in all_tasks if t.get_name() == "summary_queue_processor"]

    health_status["task_queue"]["processor_count"] = len(processor_tasks)

    if not processor_tasks:
        health_status["warnings"].append("未找到队列处理器任务")

        try:
            queue_task = asyncio.create_task(process_summary_queue())
            queue_task.set_name("summary_queue_processor")
            health_status["repairs_applied"].append("已重启队列处理器")
        except Exception as e:
            existing_errors = health_status.get("errors", [])
            health_status["errors"] = [*existing_errors, f"重启队列处理器失败: {e!s}"]
    else:
        for task in processor_tasks:
            if task.done():
                health_status["warnings"].append("队列处理器任务已完成")

                if task.exception():
                    health_status["warnings"].append(f"队列处理器异常: {task.exception()}")

                try:
                    queue_task = asyncio.create_task(process_summary_queue())
                    queue_task.set_name("summary_queue_processor")
                    health_status["repairs_applied"].append("已重启队列处理器")
                except Exception as e:
                    existing_errors = health_status.get("errors", [])
                    health_status["errors"] = [*existing_errors, f"重启队列处理器失败: {e!s}"]

    group_ids = store.get_all_groups()
    scheduled_job_ids = [job.id for job in scheduler.get_jobs() if job.id.startswith("summary_group_")]

    missing_jobs = []
    for group_id in group_ids:
        job_id = f"summary_group_{group_id}"
        if job_id not in scheduled_job_ids:
            missing_jobs.append(group_id)

    orphaned_jobs = []
    for job_id in scheduled_job_ids:
        group_id = job_id.replace("summary_group_", "")
        if group_id not in group_ids:
            orphaned_jobs.append(job_id)

    if missing_jobs:
        health_status["warnings"].append(f"发现 {len(missing_jobs)} 个未调度的任务")

    if orphaned_jobs:
        health_status["warnings"].append(f"发现 {len(orphaned_jobs)} 个孤立的调度任务")

        removed_count = 0
        for job_id in orphaned_jobs:
            try:
                scheduler.remove_job(job_id)
                removed_count += 1
            except Exception:
                pass

        if removed_count > 0:
            health_status["repairs_applied"].append(f"已移除 {removed_count} 个孤立的调度任务")

    health_status["healthy"] = (
        not health_status.get("errors")
        and not health_status.get("warnings")
        and scheduler.running
        and task_processor_started
    )

    logger.debug(f"系统健康检查结果: {health_status}", command="check_system_health")
    return health_status



class KeyStatus(Enum):
    """API Key 状态枚举"""

    NORMAL = "normal"
    UNAVAILABLE = "unavailable"


class KeyStatusStore:
    """API Key 状态管理存储"""

    def __init__(self):
        plugin_data_dir = DATA_PATH / "summary_group"
        plugin_data_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = plugin_data_dir / "api_key_status.json"
        self._lock = asyncio.Lock()
        self._data: dict[str, dict[str, Any]] = self._load_data()
        self._cooldown_periods = {
            401: 3600,
            429: 300,
            500: 300,
            502: 300,
            503: 600,
            504: 300,
        }
        self._default_cooldown = 300
        self._max_consecutive_failures = 3

        self._schedule_cleanup()

    def _load_data(self) -> dict[str, dict[str, Any]]:
        """加载 API Key 状态数据"""
        try:
            if self.file_path.exists():
                with self.file_path.open("r", encoding="utf-8") as f:
                    content = f.read()
                    if not content:
                        return {}
                    data = json.loads(content)
                    if isinstance(data, dict):
                        return data
                    else:
                        logger.error(f"API Key 状态文件格式错误: {self.file_path}")
                        return {}
            return {}
        except Exception as e:
            logger.error(f"加载 API Key 状态数据失败: {e}")
            return {}

    async def _save_data(self) -> bool:
        """保存 API Key 状态数据"""
        temp_path = self.file_path.with_suffix(".json.tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            temp_path.replace(self.file_path)
            return True
        except Exception as e:
            logger.error(f"保存 API Key 状态数据失败: {e}")
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            return False

    def _schedule_cleanup(self):
        """定期清理过期的不可用状态"""
        try:
            from nonebot import require

            require("nonebot_plugin_apscheduler")
            from nonebot_plugin_apscheduler import scheduler

            @scheduler.scheduled_job("interval", minutes=10, id="api_key_status_cleanup")
            async def cleanup_expired_keys():
                await self.cleanup_expired_keys()

            logger.debug("已设置 API Key 状态清理定时任务")
        except Exception as e:
            logger.warning(f"设置 API Key 状态清理定时任务失败: {e}")

    def _generate_key_id(self, key: str) -> str:
        """生成唯一的 Key 标识符"""
        if len(key) <= 10:
            return key

        if key.startswith("AIzaSy"):
            return f"AIzaS...{key[-8:]}"

        return f"{key[:5]}...{key[-5:]}"

    async def record_success(self, key: str) -> None:
        """记录 API Key 成功使用"""
        async with self._lock:
            key_id = self._generate_key_id(key)

            if key_id in self._data:
                self._data[key_id]["status"] = KeyStatus.NORMAL.value
                self._data[key_id]["consecutive_failures"] = 0
                self._data[key_id]["last_success"] = int(time.time())
                self._data[key_id]["success_count"] = self._data[key_id].get("success_count", 0) + 1
                self._data[key_id]["full_key"] = key
            else:
                self._data[key_id] = {
                    "status": KeyStatus.NORMAL.value,
                    "consecutive_failures": 0,
                    "failure_count": 0,
                    "success_count": 1,
                    "last_success": int(time.time()),
                    "full_key": key,
                }

            await self._save_data()

    async def record_failure(self, key: str, status_code: int | None = None, error_message: str = "") -> None:
        """记录 API Key 使用失败"""
        async with self._lock:
            key_id = self._generate_key_id(key)

            now = int(time.time())

            if key_id not in self._data:
                self._data[key_id] = {
                    "status": KeyStatus.NORMAL.value,
                    "consecutive_failures": 0,
                    "failure_count": 0,
                    "success_count": 0,
                    "full_key": key,
                }

            consecutive = self._data[key_id].get("consecutive_failures", 0) + 1
            self._data[key_id]["consecutive_failures"] = consecutive
            self._data[key_id]["failure_count"] = self._data[key_id].get("failure_count", 0) + 1
            self._data[key_id]["last_failure"] = now
            self._data[key_id]["full_key"] = key
            self._data[key_id]["last_error"] = {
                "status_code": status_code,
                "message": error_message,
                "timestamp": now,
            }

            if self._should_mark_unavailable(key_id, status_code):
                cooldown = self._get_cooldown_period(status_code)
                self._data[key_id]["status"] = KeyStatus.UNAVAILABLE.value
                self._data[key_id]["unavailable_until"] = now + cooldown
                logger.warning(
                    f"API Key {key_id} 已标记为不可用，将在 {cooldown} 秒后恢复 "
                    f"(状态码: {status_code}, 连续失败: {consecutive})"
                )

            await self._save_data()

    def _should_mark_unavailable(self, key_id: str, status_code: int | None) -> bool:
        """判断是否应该将 Key 标记为不可用"""
        if status_code in {401, 429, 503}:
            return True

        if self._data[key_id].get("consecutive_failures", 0) >= self._max_consecutive_failures:
            return True

        return False

    def _get_cooldown_period(self, status_code: int | None) -> int:
        """根据错误状态码获取冷却时间"""
        if status_code is None:
            return self._default_cooldown
        return self._cooldown_periods.get(status_code, self._default_cooldown)

    async def get_available_keys(self, keys: list[str]) -> list[str]:
        """获取可用的 API Keys"""
        async with self._lock:
            available_keys = []
            now = int(time.time())

            processed_keys = set()

            for key in keys:
                key_id = self._generate_key_id(key)

                if key_id in processed_keys:
                    continue
                processed_keys.add(key_id)

                if key_id not in self._data or self._data[key_id]["status"] == KeyStatus.NORMAL.value:
                    available_keys.append(key)
                    continue

                if self._data[key_id]["status"] == KeyStatus.UNAVAILABLE.value:
                    unavailable_until = self._data[key_id].get("unavailable_until", 0)
                    if now >= unavailable_until:
                        self._data[key_id]["status"] = KeyStatus.NORMAL.value
                        self._data[key_id]["consecutive_failures"] = 0
                        available_keys.append(key)
                        logger.info(f"API Key {key_id} 已自动恢复为可用状态")

            if not available_keys and keys:
                unavailable_keys = []
                for key in keys:
                    key_id = self._generate_key_id(key)
                    if key_id in self._data and self._data[key_id]["status"] == KeyStatus.UNAVAILABLE.value:
                        unavailable_until = self._data[key_id].get("unavailable_until", float("inf"))
                        unavailable_keys.append((key, unavailable_until))

                if unavailable_keys:
                    earliest_key, earliest_time = min(unavailable_keys, key=lambda x: x[1])
                    available_keys.append(earliest_key)
                    key_id = self._generate_key_id(earliest_key)
                    recovery_time = max(0, earliest_time - now)
                    minutes = int(recovery_time // 60)
                    seconds = int(recovery_time % 60)
                    logger.warning(
                        f"没有可用的 API Key，选择最早恢复的 Key: {key_id} "
                        f"(预计 {minutes}分{seconds}秒后恢复)"
                    )
                else:
                    available_keys = keys
                    logger.warning("没有可用的 API Key，返回所有 Key")

            if not available_keys and keys:
                logger.warning("所有 API Key 均不可用，返回所有 Key 作为备选")
                return keys

            random.shuffle(available_keys)
            return available_keys

    async def cleanup_expired_keys(self) -> int:
        """清理过期的不可用状态"""
        async with self._lock:
            cleaned_count = 0
            now = int(time.time())

            for key_id, data in list(self._data.items()):
                if data["status"] == KeyStatus.UNAVAILABLE.value:
                    unavailable_until = data.get("unavailable_until", 0)
                    if now >= unavailable_until:
                        data["status"] = KeyStatus.NORMAL.value
                        data["consecutive_failures"] = 0
                        cleaned_count += 1
                        logger.debug(f"API Key {key_id}... 状态已自动恢复为可用")

            if cleaned_count > 0:
                await self._save_data()
                logger.info(f"已清理 {cleaned_count} 个过期的 API Key 不可用状态")

            return cleaned_count

    async def get_key_status_summary(self) -> dict[str, Any]:
        """获取所有 API Key 状态摘要"""
        async with self._lock:
            now = int(time.time())
            summary = {
                "total_keys": 0,
                "available_keys": 0,
                "unavailable_keys": 0,
                "keys": {},
            }

            for key_id, data in self._data.items():
                status = data["status"]
                if status == KeyStatus.UNAVAILABLE.value:
                    unavailable_until = data.get("unavailable_until", 0)
                    if now >= unavailable_until:
                        status = KeyStatus.NORMAL.value

                summary["total_keys"] += 1
                if status == KeyStatus.NORMAL.value:
                    summary["available_keys"] += 1
                else:
                    summary["unavailable_keys"] += 1

                summary["keys"][key_id] = {
                    "status": status,
                    "success_count": data.get("success_count", 0),
                    "failure_count": data.get("failure_count", 0),
                    "consecutive_failures": data.get("consecutive_failures", 0),
                }

                if status == KeyStatus.UNAVAILABLE.value:
                    unavailable_until = data.get("unavailable_until", 0)
                    summary["keys"][key_id]["unavailable_until"] = unavailable_until
                    summary["keys"][key_id]["recovery_in_seconds"] = max(0, unavailable_until - now)

            return summary


key_status_store = KeyStatusStore()
