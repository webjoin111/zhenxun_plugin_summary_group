from typing import TypedDict
import json
from pathlib import Path
import asyncio
import copy
import time

from nonebot import logger
from zhenxun.configs.path_config import DATA_PATH


class Data(TypedDict):
    hour: int
    minute: int
    least_message_count: int


class Store:
    def __init__(self, file_path: str | Path | None = None):
        if file_path:
            self.file_path = Path(file_path)
        else:
            plugin_data_dir = DATA_PATH / "summary_group"
            default_filename = "summary_settings.json"
            self.file_path = plugin_data_dir / default_filename

        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load_data()
        self._lock = asyncio.Lock()

    def _load_data(self) -> dict:
        try:
            if self.file_path.exists():
                with self.file_path.open("r", encoding="utf-8") as f:
                    content = f.read()
                    if not content:
                        logger.warning(f"存储文件为空: {self.file_path}")
                        return {}
                    return json.loads(content)
            return {}
        except json.JSONDecodeError as e:
            logger.error(
                f"加载存储数据失败: JSON 解析错误于 {self.file_path} - {e}",
                exc_info=True,
            )
            try:
                corrupted_path = self.file_path.with_suffix(
                    f".json.corrupted_{int(time.time())}"
                )
                self.file_path.rename(corrupted_path)
                logger.warning(f"损坏的配置文件已备份到: {corrupted_path}")
            except OSError as backup_e:
                logger.error(f"备份损坏的配置文件失败: {backup_e}")
            return {}
        except Exception as e:
            logger.error(f"加载存储数据时发生未知错误: {e}", exc_info=True)
            return {}

    def _save_data(self) -> bool:
        try:
            with self.file_path.open("w", encoding="utf-8") as f:
                if not isinstance(self.data, dict):
                    logger.error(f"尝试保存非字典类型的数据到 {self.file_path}")
                    return False
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            return True
        except TypeError as e:
            logger.error(
                f"保存存储数据失败: 数据无法序列化为 JSON - {e}", exc_info=True
            )
            return False
        except Exception as e:
            logger.error(f"保存存储数据失败: {e}", exc_info=True)
            return False

    def set(self, group_id: int, data: dict) -> bool:
        try:
            if not isinstance(data, dict):
                logger.warning(f"尝试为群 {group_id} 设置非字典类型的数据")
                return False

            required_fields = {"hour": int, "minute": int, "least_message_count": int}
            for field, field_type in required_fields.items():
                if field not in data or not isinstance(data[field], field_type):
                    logger.warning(
                        f"为群 {group_id} 设置的数据缺少字段 '{field}' 或类型错误 (应为 {field_type.__name__})"
                    )

            validated_data = {k: data.get(k) for k in required_fields if k in data}

            from datetime import datetime

            now_iso = datetime.now().isoformat()
            if str(group_id) not in self.data and "created_at" not in validated_data:
                validated_data["created_at"] = now_iso
            validated_data["updated_at"] = now_iso

            self.data[str(group_id)] = validated_data
            return self._save_data()
        except Exception as e:
            logger.error(f"设置群 {group_id} 配置失败: {e}", exc_info=True)
            return False

    def get(self, group_id: int) -> dict | None:
        return self.data.get(str(group_id))

    def remove(self, group_id: int) -> bool:
        try:
            group_id_str = str(group_id)
            if group_id_str in self.data:
                del self.data[group_id_str]
                return self._save_data()
            return True
        except Exception as e:
            logger.error(f"移除群 {group_id} 配置失败: {e}", exc_info=True)
            return False

    def remove_all(self) -> bool:
        try:
            self.data.clear()
            return self._save_data()
        except Exception as e:
            logger.error(f"移除所有群组配置失败: {e}", exc_info=True)
            return False

    def get_all_groups(self) -> list:
        return list(self.data.keys())

    def cleanup_invalid_groups(self) -> int:
        invalid_groups = [key for key in self.data if not key.isdigit()]
        if not invalid_groups:
            return 0

        cleaned_count = len(invalid_groups)
        for group_id in invalid_groups:
            del self.data[group_id]

        if self._save_data():
            logger.debug(f"自动清理了 {cleaned_count} 个无效的群配置")
        else:
            logger.error("清理无效群配置后保存失败")
        return cleaned_count

    async def transaction(self, operation_func):
        async with self._lock:
            data_backup = copy.deepcopy(self.data)
            try:
                result = operation_func()
                if not self._save_data():
                    logger.error("事务操作中保存数据失败，回滚更改")
                    self.data = data_backup
                    return False
                return True
            except Exception as e:
                logger.error(f"事务操作失败，回滚更改: {e}", exc_info=True)
                self.data = data_backup
                return False
