from pathlib import Path
from typing import Any

import aiofiles
from pydantic import Field

from zhenxun.ui.models import RenderableComponent

from . import base_config


class GroupSummaryComponent(RenderableComponent):
    """群聊总结报告的UI组件数据模型"""

    markdown_content: str = Field(..., description="由LLM生成的原始Markdown文本")
    user_info_cache: dict[str, str] = Field(
        ..., description="用于头像查找的用户信息缓存"
    )

    @property
    def template_name(self) -> str:
        return "@summary_group/summary_component"

    async def get_extra_css(self, context: Any) -> str:
        """加载并注入插件本地的CSS样式"""
        theme = base_config.get("summary_theme", "dark")
        css_file_map = {
            "light": "light.css",
            "dark": "dark.css",
            "cyber": "cyber.css",
        }
        css_file = css_file_map.get(theme, "dark.css")

        css_path = (Path(__file__).parent / "templates"/"assets" / css_file).resolve()

        if css_path.exists():
            async with aiofiles.open(css_path, encoding="utf-8") as f:
                return await f.read()
        return ""
