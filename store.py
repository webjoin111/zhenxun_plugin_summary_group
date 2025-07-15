import asyncio
import json
from pathlib import Path
import time
from typing import Any, TypedDict

from nonebot import logger

from zhenxun.configs.path_config import DATA_PATH


class GroupSettingData(TypedDict, total=False):
    default_style: str | None
    default_model_name: str | None
    updated_at: str | None


class Store:
    def __init__(self):
        plugin_data_dir = DATA_PATH / "summary_group"
        plugin_data_dir.mkdir(parents=True, exist_ok=True)

        self.group_settings_file_path = plugin_data_dir / "group_specific_settings.json"
        self._lock = asyncio.Lock()
        self.group_settings_data: dict[str, GroupSettingData] = self._load_json_data(
            self.group_settings_file_path
        )
        logger.debug("Store instance for group settings initialized.")

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
                temp_path.unlink(missing_ok=True)
            return False
        except Exception as e:
            logger.error(f"保存存储数据失败 ({path}): {e}", e=e)
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            return False

    def get_group_setting(self, group_id: str, key: str, default: Any = None) -> Any:
        """获取指定群组的特定设置项"""
        group_data = self.group_settings_data.get(group_id)
        if group_data and key in group_data:
            return group_data.get(key, default)
        return default

    async def set_group_setting(self, group_id: str, key: str, value: Any) -> bool:
        async with self._lock:
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

            result = self._save_json_data(
                self.group_settings_data, self.group_settings_file_path
            )
            if result:
                logger.debug(f"群 {group_id} 的设置项 '{key}' 已更新为: {value}")
            else:
                logger.error(f"群 {group_id} 的设置项 '{key}' 更新失败")
            return result

    async def remove_group_setting(self, group_id: str, key: str) -> bool:
        async with self._lock:
            if (
                group_id in self.group_settings_data
                and key in self.group_settings_data[group_id]
            ):
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

                result = self._save_json_data(
                    self.group_settings_data, self.group_settings_file_path
                )
                if result:
                    logger.debug(
                        f"群 {group_id} 的设置项 '{key}' (原值: {old_value}) 已移除"
                    )
                else:
                    logger.error(f"群 {group_id} 的设置项 '{key}' 移除失败")
                return result
            return True

    def get_all_group_settings(self, group_id: str) -> GroupSettingData | None:
        """获取指定群组的所有设置"""
        return self.group_settings_data.get(group_id)


store = Store()
