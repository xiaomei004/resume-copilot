"""版式主题：把"长什么样"从"写什么"里分离出来。

换主题 = 换颜色/字号/留白，不改简历内容与结构。
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass
class Theme:
    key: str
    label: str
    font_latin: str = "Microsoft YaHei"
    font_east: str = "微软雅黑"
    accent: str = "1F4E79"
    accent_light: str = "E9EFF7"
    ink: str = "1A1A1A"
    grey: str = "5A6672"
    rule: str = "B8C6D9"
    body_pt: float = 10.0
    line: float = 1.02
    name_pt: float = 22.0
    heading_pt: float = 11.0
    meta_pt: float = 9.0
    margin_top: float = 1.0
    margin_bottom: float = 0.95
    margin_side: float = 1.55
    photo_cm: float = 2.2
    photo_col_cm: float = 2.78
    band: bool = True
    max_pages: int = 1

    def shrink(self, factor: float = 0.96) -> Theme:
        """页面溢出时按比例收紧正文与行距，作为最后一道保险。"""
        return replace(
            self,
            body_pt=round(max(8.6, self.body_pt * factor), 2),
            line=round(max(0.92, self.line * factor), 3),
            heading_pt=round(max(9.8, self.heading_pt * factor), 2),
            meta_pt=round(max(8.2, self.meta_pt * factor), 2),
        )


THEMES: dict[str, Theme] = {
    "navy": Theme(key="navy", label="深蓝（通用，打印最稳）", accent="1F4E79", accent_light="E9EFF7"),
    "teal": Theme(
        key="teal",
        label="墨绿（研发/技术岗）",
        accent="1D5C55",
        accent_light="E8F2F0",
        rule="B6CDC9",
        font_latin="Microsoft YaHei",
        font_east="微软雅黑",
    ),
    "brick": Theme(
        key="brick",
        label="砖红（市场/销售岗）",
        accent="8C3B2E",
        accent_light="F6ECE9",
        rule="D8C3BD",
    ),
    "mono": Theme(
        key="mono",
        label="单色（最保守，ATS 友好）",
        accent="222222",
        accent_light="F1F1F1",
        rule="C9C9C9",
        band=False,
    ),
}

ROLE_THEME = {"sales": "brick", "rnd": "teal", "support": "navy", "other": "navy"}


def get_theme(name: str | None = None, role_family: str = "other") -> Theme:
    key = name or ROLE_THEME.get(role_family, "navy")
    return THEMES.get(key, THEMES["navy"])
