import asyncio
from enum import Enum
import json
import random
import time
from typing import Any

from zhenxun.configs.path_config import DATA_PATH
from zhenxun.services.log import logger


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

            @scheduler.scheduled_job(
                "interval", minutes=10, id="api_key_status_cleanup"
            )
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
                self._data[key_id]["success_count"] = (
                    self._data[key_id].get("success_count", 0) + 1
                )
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

    async def record_failure(
        self, key: str, status_code: int | None = None, error_message: str = ""
    ) -> None:
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
            self._data[key_id]["failure_count"] = (
                self._data[key_id].get("failure_count", 0) + 1
            )
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

        if (
            self._data[key_id].get("consecutive_failures", 0)
            >= self._max_consecutive_failures
        ):
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

                if (
                    key_id not in self._data
                    or self._data[key_id]["status"] == KeyStatus.NORMAL.value
                ):
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
                    if (
                        key_id in self._data
                        and self._data[key_id]["status"] == KeyStatus.UNAVAILABLE.value
                    ):
                        unavailable_until = self._data[key_id].get(
                            "unavailable_until", float("inf")
                        )
                        unavailable_keys.append((key, unavailable_until))

                if unavailable_keys:
                    earliest_key, earliest_time = min(
                        unavailable_keys, key=lambda x: x[1]
                    )
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
                    summary["keys"][key_id]["recovery_in_seconds"] = max(
                        0, unavailable_until - now
                    )

            return summary


key_status_store = KeyStatusStore()
