import asyncio
import copy
import json
from pathlib import Path
import time
from typing import Any, TypedDict

from nonebot import logger

from zhenxun.configs.path_config import DATA_PATH


class ScheduleData(TypedDict):
    hour: int
    minute: int
    least_message_count: int
    style: str | None
    created_at: str | None
    updated_at: str | None


class GroupSettingData(TypedDict, total=False):
    default_model_name: str | None
    default_style: str | None
    updated_at: str | None


class Store:
    _instance = None
    _initialized = False

    def __new__(cls, file_path: str | Path | None = None):
        if cls._instance is None:
            cls._instance = super(Store, cls).__new__(cls)
        return cls._instance

    def __init__(self, file_path: str | Path | None = None):
        if Store._initialized:
            return

        plugin_data_dir = DATA_PATH / "summary_group"
        plugin_data_dir.mkdir(parents=True, exist_ok=True)

        if file_path:
            self.schedule_file_path = Path(file_path)
        else:
            default_schedule_filename = "summary_settings.json"
            self.schedule_file_path = plugin_data_dir / default_schedule_filename

        self.group_settings_file_path = plugin_data_dir / "group_specific_settings.json"

        self._lock = asyncio.Lock()

        self.schedule_data: dict[str, ScheduleData] = self._load_json_data(self.schedule_file_path)
        self.group_settings_data: dict[str, GroupSettingData] = self._load_json_data(
            self.group_settings_file_path
        )

        Store._initialized = True

    def _load_json_data(self, path: Path) -> dict:
        """通用加载 JSON 文件数据"""
        try:
            if path.exists():
                with path.open("r", encoding="utf-8") as f:
                    content = f.read()
                    if not content:
                        logger.warning(f"存储文件为空: {path}")
                        return {}
                    data = json.loads(content)
                    if isinstance(data, dict):
                        return data
                    else:
                        logger.error(f"存储文件顶层结构不是字典: {path}")
                        self._backup_corrupted_file(path)
                        return {}
            return {}
        except json.JSONDecodeError as e:
            logger.error(
                f"加载存储数据失败: JSON 解析错误于 {path} - {e}",
            )
            self._backup_corrupted_file(path)
            return {}
        except Exception as e:
            logger.error(f"加载存储数据时发生未知错误 ({path}): {e}", e=e)
            return {}

    def _backup_corrupted_file(self, path: Path):
        """备份损坏的 JSON 文件"""
        try:
            corrupted_path = path.with_suffix(f".json.corrupted_{int(time.time())}")
            path.rename(corrupted_path)
            logger.warning(f"损坏的配置文件已备份到: {corrupted_path}")
        except OSError as backup_e:
            logger.error(f"备份损坏的配置文件失败 ({path}): {backup_e}", e=backup_e)

    def _save_json_data(self, data: dict, path: Path) -> bool:
        """通用保存数据到 JSON 文件，使用原子写操作"""
        temp_path = path.with_suffix(".json.tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as f:
                if not isinstance(data, dict):
                    logger.error(f"尝试保存非字典类型的数据到 {path}")
                    return False
                json.dump(data, f, ensure_ascii=False, indent=2)
            temp_path.replace(path)
            return True
        except TypeError as e:
            logger.error(f"保存存储数据失败 ({path}): 数据无法序列化为 JSON - {e}", e=e)
            if temp_path.exists():
                temp_path.unlink()
            return False
        except Exception as e:
            logger.error(f"保存存储数据失败 ({path}): {e}", e=e)
            if temp_path.exists():
                temp_path.unlink()
            return False

    def set(self, group_id: int, data: dict) -> bool:
        group_id_str = str(group_id)
        try:
            required_fields = {"hour": int, "minute": int, "least_message_count": int}
            optional_fields = {"style": (str, type(None))}
            validated_data = {}

            if not isinstance(data, dict):
                logger.warning(f"[定时任务] 尝试为群 {group_id} 设置非字典类型的数据")
                return False

            for field, field_type in required_fields.items():
                if field not in data:
                    logger.warning(f"[定时任务] 为群 {group_id} 设置的数据缺少必填字段 '{field}'")
                elif not isinstance(data[field], field_type):
                    logger.warning(f"[定时任务] 为群 {group_id} 设置的数据字段 '{field}' 类型错误")
                else:
                    validated_data[field] = data[field]

            for field, allowed_types in optional_fields.items():
                if field in data:
                    if isinstance(data[field], allowed_types):
                        validated_data[field] = data[field]
                    elif data[field] is None and type(None) in allowed_types:
                        validated_data[field] = None
                    else:
                        logger.warning(f"[定时任务] 为群 {group_id} 设置的数据字段 '{field}' 类型错误")

            if not all(key in validated_data for key in required_fields):
                logger.error(f"[定时任务] 群 {group_id} 缺少必要的配置字段，无法保存")
                return False

            from datetime import datetime

            now_iso = datetime.now().isoformat()
            if group_id_str not in self.schedule_data:
                if "created_at" not in validated_data:
                    validated_data["created_at"] = now_iso
            validated_data["updated_at"] = now_iso

            self.schedule_data[group_id_str] = validated_data
            return self._save_json_data(self.schedule_data, self.schedule_file_path)
        except Exception as e:
            logger.error(f"[定时任务] 设置群 {group_id} 配置失败: {e}", e=e)
            return False

    def get(self, group_id: int) -> ScheduleData | None:
        """获取指定群组的定时任务设置"""
        return self.schedule_data.get(str(group_id))

    def remove(self, group_id: int) -> bool:
        """移除指定群组的定时任务设置"""
        try:
            group_id_str = str(group_id)
            if group_id_str in self.schedule_data:
                del self.schedule_data[group_id_str]
                return self._save_json_data(self.schedule_data, self.schedule_file_path)
            return True
        except Exception as e:
            logger.error(f"移除群 {group_id} 定时任务配置失败: {e}", e=e)
            return False

    def remove_all(self) -> bool:
        """移除所有群组的定时任务设置"""
        try:
            self.schedule_data.clear()
            return self._save_json_data(self.schedule_data, self.schedule_file_path)
        except Exception as e:
            logger.error(f"移除所有群组定时任务配置失败: {e}", e=e)
            return False

    def get_all_groups(self) -> list:
        """获取所有设置了定时任务的群组ID列表"""
        return list(self.schedule_data.keys())

    def cleanup_invalid_groups(self) -> int:
        """清理定时任务设置中的无效群组ID"""
        invalid_groups = [key for key in self.schedule_data if not key.isdigit()]
        if not invalid_groups:
            return 0

        cleaned_count = len(invalid_groups)
        for group_id in invalid_groups:
            del self.schedule_data[group_id]

        if self._save_json_data(self.schedule_data, self.schedule_file_path):
            logger.debug(f"自动清理了 {cleaned_count} 个无效的定时任务群配置")
        else:
            logger.error("清理无效定时任务群配置后保存失败")
        return cleaned_count

    def get_group_setting(self, group_id: str, key: str, default: Any = None) -> Any:
        """获取指定群组的特定设置项"""
        group_data = self.group_settings_data.get(group_id)
        if group_data and key in group_data:
            return group_data[key]
        return default

    def set_group_setting(self, group_id: str, key: str, value: Any) -> bool:
        """设置指定群组的特定设置项"""
        if not isinstance(group_id, str) or not group_id.isdigit():
            logger.warning(f"尝试为无效的 group_id '{group_id}' 设置分群配置")
            return False
        if key not in GroupSettingData.__annotations__:
            logger.warning(f"尝试设置无效的分群配置项 '{key}' for group {group_id}")
            return False

        if group_id not in self.group_settings_data:
            self.group_settings_data[group_id] = {}

        from datetime import datetime

        now_iso = datetime.now().isoformat()
        self.group_settings_data[group_id][key] = value
        self.group_settings_data[group_id]["updated_at"] = now_iso

        result = self._save_json_data(self.group_settings_data, self.group_settings_file_path)

        if result:
            logger.debug(f"群 {group_id} 的设置项 '{key}' 已更新为: {value}")
        else:
            logger.error(f"群 {group_id} 的设置项 '{key}' 更新失败")

        return result

    def remove_group_setting(self, group_id: str, key: str) -> bool:
        """移除指定群组的特定设置项"""
        if group_id in self.group_settings_data and key in self.group_settings_data[group_id]:
            old_value = self.group_settings_data[group_id].get(key)

            del self.group_settings_data[group_id][key]
            if not self.group_settings_data[group_id] or (
                len(self.group_settings_data[group_id]) == 1
                and "updated_at" in self.group_settings_data[group_id]
            ):
                del self.group_settings_data[group_id]
            else:
                from datetime import datetime

                now_iso = datetime.now().isoformat()
                self.group_settings_data[group_id]["updated_at"] = now_iso

            result = self._save_json_data(self.group_settings_data, self.group_settings_file_path)

            if result:
                logger.debug(f"群 {group_id} 的设置项 '{key}' (原值: {old_value}) 已移除")
            else:
                logger.error(f"群 {group_id} 的设置项 '{key}' 移除失败")

            return result
        return True

    def get_all_group_settings(self, group_id: str) -> GroupSettingData | None:
        """获取指定群组的所有设置"""
        return self.group_settings_data.get(group_id)

    async def transaction(self, operation_func):
        async with self._lock:
            schedule_backup = copy.deepcopy(self.schedule_data)
            group_settings_backup = copy.deepcopy(self.group_settings_data)
            try:
                result = await operation_func()
                save1_ok = self._save_json_data(self.schedule_data, self.schedule_file_path)
                save2_ok = self._save_json_data(self.group_settings_data, self.group_settings_file_path)
                if not (save1_ok and save2_ok):
                    logger.error("事务操作中保存数据失败，回滚更改")
                    self.schedule_data = schedule_backup
                    self.group_settings_data = group_settings_backup
                    return False
                return result
            except Exception as e:
                logger.error(f"事务操作失败，回滚更改: {e}", e=e)
                self.schedule_data = schedule_backup
                self.group_settings_data = group_settings_backup
                return False
