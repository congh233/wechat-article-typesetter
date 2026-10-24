#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公众号文字稿一键排版助手。

把纯文字稿 / Markdown 文章转换成可直接粘贴进微信公众号编辑器的
单文件 HTML（全部使用内联样式，无 JS、无外链、无外部字体）。

用法示例：
    python typeset.py article.md --style heytea --output article.html --validate
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
STYLES_DIR = SKILL_DIR / "styles"

STYLE_IDS = ("heytea", "datawhale", "minimal", "academic")

BLOCK_RE = re.compile(r"^(#{1,3})\s+(.*)$")
UL_RE = re.compile(r"^[-*]\s+(.*)$")
OL_RE = re.compile(r"^\d+[.)]\s+(.*)$")
HR_RE = re.compile(r"^(---+|\*\*\*+)$")
ACCENT_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def load_style(style_id: str) -> Dict[str, Any]:
    """读取 styles/<style_id>.json。"""
    path = STYLES_DIR / f"{style_id}.json"
    if not path.exists():
        raise ValueError(
            f"未知风格：{style_id}；可选风格：{', '.join(STYLE_IDS)}"
        )
    with path.open("r", encoding="utf-8") as handle:
        style = json.load(handle)
    style["id"] = style.get("id", style_id)
    return style


def read_text(path: Path) -> str:
    """按 UTF-8 读取文字稿；编码不对时给出可操作的提示。"""
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"文件不是 UTF-8 编码：{path}；请用记事本或编辑器另存为 UTF-8 后重试"
        ) from exc


def parse_article(text: str, title: Optional[str] = None) -> Dict[str, Any]:
    """把文字稿解析成标题 + 结构化块列表。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    lines = text.split("\n")
    blocks: List[Dict[str, Any]] = []
    i = 0

    # 标题：优先 --title；其次第一个非空行（若带 # 则去掉 #）。
    if title is None:
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i < len(lines):
            first = lines[i].strip()
            match = BLOCK_RE.match(first)
            title = match.group(2).strip() if match else first
            i += 1
    else:
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i < len(lines) and BLOCK_RE.match(lines[i].strip()):
            i += 1

    if not title:
        raise ValueError(
            "没有找到标题：请在文件第一行写「# 标题」，或使用 --title 指定"
        )

    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue

        if stripped.startswith("```"):
            i += 1
            code_lines: List[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            blocks.append({"type": "code", "text": "\n".join(code_lines)})
            continue

        match = BLOCK_RE.match(stripped)
        if match:
            level = len(match.group(1))
            blocks.append(
                {
                    "type": "h3" if level >= 3 else "h2",
                    "text": match.group(2).strip(),
                }
            )
            i += 1
            continue

        if HR_RE.match(stripped):
            blocks.append({"type": "hr"})
            i += 1
            continue

        if stripped.startswith(">"):
            quote_lines: List[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append(
                {"type": "quote", "text": " ".join(x for x in quote_lines if x)}
            )
            continue

        if UL_RE.match(stripped):
            items: List[str] = []
            while i < len(lines) and UL_RE.match(lines[i].strip()):
                items.append(UL_RE.match(lines[i].strip()).group(1).strip())
                i += 1
            blocks.append({"type": "ul", "items": items})
            continue

        if OL_RE.match(stripped):
            items = []
            while i < len(lines) and OL_RE.match(lines[i].strip()):
                items.append(OL_RE.match(lines[i].strip()).group(1).strip())
                i += 1
            blocks.append({"type": "ol", "items": items})
            continue

        para_lines: List[str] = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if (
                not nxt
                or BLOCK_RE.match(nxt)
                or UL_RE.match(nxt)
                or OL_RE.match(nxt)
                or nxt.startswith(">")
                or nxt.startswith("```")
                or HR_RE.match(nxt)
            ):
                break
            para_lines.append(nxt)
            i += 1
        blocks.append({"type": "p", "lines": para_lines})

    return {"title": title, "blocks": blocks}


def _style(**kwargs: Optional[str]) -> str:
    """把关键字参数拼成可安全嵌入 HTML 属性的内联 style 字符串。

    font-family 里含有双引号（如 "KaiTi"），如果不转义会提前截断
    style="..." 属性，导致后面的样式全部失效。
    """
    parts = [
        f"{key.replace('_', '-')}:{value}"
        for key, value in kwargs.items()
        if value is not None
    ]
    return html.escape(";".join(parts) + ";", quote=True)


def render_inline(text: str, style: Dict[str, Any]) -> str:
    """转义文本并处理 **加粗**、`代码`、==关键词高亮==。"""
    colors = style["colors"]
    fonts = style["fonts"]
    style_id = style["id"]
    escaped = html.escape(text)

    if style_id == "heytea":
        code_style = _style(
            font_family=fonts["mono"],
            font_size="14px",
            color=colors["text"],
            background_color=colors["code_bg"],
            padding="1px 6px",
            border=f"1px solid #D8CBB0",
            border_radius="4px",
        )
    else:
        code_style = _style(
            font_family=fonts["mono"],
            font_size="14px",
            color=colors["text"],
            background_color=colors["code_bg"],
            padding="2px 5px",
            border_radius="2px",
        )
    escaped = re.sub(
        r"`([^`]+)`", lambda m: f'<code style="{code_style}">{m.group(1)}</code>', escaped
    )

    if style_id == "heytea":
        bold_style = _style(
            font_weight="400",
            color=colors["text"],
            border_bottom=f"2px solid {colors['accent']}",
        )
    elif style_id == "datawhale":
        bold_style = _style(font_weight="700")
    else:
        bold_style = _style(font_weight="600", color=colors["text"])
    escaped = re.sub(
        r"\*\*(.+?)\*\*",
        lambda m: f'<strong style="{bold_style}">{m.group(1)}</strong>',
        escaped,
    )

    if style_id == "heytea":
        mark_style = _style(
            background_color=colors["highlight_bg"],
            color=colors["text"],
            padding="1px 6px",
            border_radius="4px",
            box_decoration_break="clone",
        )
    else:
        mark_style = _style(
            background_color=colors["highlight_bg"],
            color=colors["text"],
            padding="0 2px",
            border_bottom=f"2px solid {colors['accent']}",
        )
    escaped = re.sub(
        r"==(.+?)==",
        lambda m: f'<span style="{mark_style}">{m.group(1)}</span>',
        escaped,
    )
    return escaped


def render_html(article: Dict[str, Any], style: Dict[str, Any]) -> str:
    """把结构化文章渲染成内联样式的 HTML 片段。"""
    colors = style["colors"]
    fonts = style["fonts"]
    layout = style["layout"]
    style_id = style["id"]

    container_style = _style(
        max_width=f"{layout['container_width']}px",
        margin="26px auto",
        padding=layout["padding"],
        background_color=colors["bg"],
        box_sizing="border-box",
        position="relative" if style_id in ("heytea", "datawhale") else None,
        border_radius="24px" if style_id in ("heytea", "datawhale") else None,
        box_shadow="0 26px 60px rgba(0,0,0,0.28)" if style_id in ("heytea", "datawhale") else None,
        font_family=fonts["body"],
        font_size=f"{layout['body_size']}px",
        line_height=str(layout["line_height"]),
        color=colors["text"],
        word_break="break-word",
    )
    parts = [
        f'<div id="wechat-article" data-style="{html.escape(style_id)}" '
        f'style="{container_style}">'
    ]
    if style_id == "heytea":
        parts.append(
            f'<div style="{_style(position="absolute", left="10px", top="46px", bottom="40px", width="1px", background_color="#C9BFA8")}"></div>'
        )
        parts.append(
            f'<div style="{_style(position="absolute", left="4px", top="11%", width="13px", height="13px", border="1.5px solid #AFA48A", border_radius="50%")}"></div>'
        )
        parts.append(
            f'<div style="{_style(position="absolute", left="4px", top="56%", width="13px", height="13px", border="1.5px solid #AFA48A", border_radius="50%")}"></div>'
        )
        parts.append(
            f'<div style="{_style(position="absolute", left="6px", top="52%", width="8px", height="8px", background_color=colors["ring"], border_radius="50%")}"></div>'
        )

    # 标题区
    meta_bits: List[str] = []
    if article.get("author"):
        meta_bits.append("文 / " + html.escape(article["author"]))
    if article.get("date"):
        meta_bits.append(html.escape(article["date"]))

    if style_id == "heytea":
        parts.append('<div style="margin:0 0 26px;">')
        kicker_style = _style(
            display="inline-block",
            font_family=fonts["mono"],
            font_size="10px",
            letter_spacing="3px",
            color=colors["muted"],
            transform="rotate(-2deg)",
        )
        h1_style = _style(
            font_family=fonts["heading"],
            font_size=f"{layout['h1_size']}px",
            line_height="1.3",
            font_weight="200",
            color=colors["text"],
            margin="24px 0 0",
            padding_right="96px",
            letter_spacing="0.14em",
            transform="rotate(-1.2deg)",
            transform_origin="left center",
        )
        marker_style = _style(
            width="56%",
            height="7px",
            background_color=colors["accent"],
            opacity="0.85",
            margin="-2px 0 0 6px",
            transform="rotate(-1deg)",
        )
        hero_rule_style = _style(
            margin="22px 0 0",
            padding_top="10px",
            border_top="1px dashed #C9BFA8",
        )
        meta_style = _style(
            font_family=fonts["mono"],
            font_size="11px",
            letter_spacing="2px",
            color=colors["muted"],
        )
        # 封面图案层：右上角水彩环群 + 散布圆点 + 左下角 3×3 圆坑材质
        parts.append(
            f'<div style="{_style(position="relative", min_height="164px", margin="0 0 10px")}">'
        )
        parts.append(
            f'<div style="{_style(position="absolute", right="-30px", top="-14px", width="150px", height="150px", border=f"2px solid {colors['ring']}", border_radius="50%")}"></div>'
        )
        parts.append(
            f'<div style="{_style(position="absolute", right="10px", top="16px", width="96px", height="96px", border=f"1.5px solid {colors['ring_soft']}", border_radius="50%")}"></div>'
        )
        parts.append(
            f'<div style="{_style(position="absolute", right="36px", top="42px", width="40px", height="40px", border=f"1px solid {colors['ring_soft']}", border_radius="50%")}"></div>'
        )
        parts.append(
            f'<div style="{_style(position="absolute", right="6px", top="124px", width="10px", height="10px", border_radius="50%", background_color=colors['ring'])}"></div>'
        )
        parts.append(
            f'<div style="{_style(position="absolute", right="140px", top="134px", width="7px", height="7px", border_radius="50%", background_color=colors['ring_soft'])}"></div>'
        )
        parts.append(
            f'<div style="{_style(position="absolute", right="62px", top="-8px", width="6px", height="6px", border_radius="50%", background_color=colors['ring_soft'])}"></div>'
        )
        pits = "".join(
            f'<span style="{_style(display="inline-block", width="24px", height="24px", background_color="#E0DBCC", border_radius="50%", box_shadow="inset 0 2px 4px rgba(0,0,0,0.14)", margin="0 4px 4px 0")}"></span>'
            for _ in range(9)
        )
        parts.append(
            f'<div style="{_style(position="absolute", left="0", bottom="-4px", width="92px", transform="rotate(4deg)")}">{pits}</div>'
        )
        parts.append(
            f'<div style="{_style(position="absolute", left="0", top="8px")}">'
            f'<span style="{kicker_style}">{html.escape(style["kicker"])}</span>'
            f"</div>"
        )
        parts.append("</div>")
        parts.append(f'<h1 style="{h1_style}">{html.escape(article["title"])}</h1>')
        parts.append(f'<div style="{marker_style}"></div>')
        if meta_bits:
            parts.append(
                f'<div style="{hero_rule_style}">'
                f'<span style="{meta_style}">{" · ".join(meta_bits)}</span></div>'
            )
        parts.append("</div>")
        # 黑页：题眼词（取自风格签名）+ 白色碎屑
        title_word = style["kicker"].split("/")[0].strip()
        parts.append(
            f'<div style="{_style(position="relative", height="170px", margin="0 -30px 30px", background_color=colors["black"])}">'
        )
        parts.append(
            f'<div style="{_style(position="absolute", right="56px", top="26px", font_size="26px", letter_spacing="0.5em", color=colors["bg"], font_weight="200")}">{html.escape(title_word)}</div>'
        )
        for left, top, size in ((90, 36, 6), (170, 96, 4), (260, 50, 5), (330, 110, 3), (420, 40, 5), (490, 100, 4)):
            parts.append(
                f'<div style="{_style(position="absolute", left=f"{left}px", top=f"{top}px", width=f"{size}px", height=f"{size}px", border_radius="50%", background_color=colors["bg"])}"></div>'
            )
        parts.append("</div>")
    elif style_id == "datawhale":
        parts.append('<div style="margin:0 0 30px;">')
        kicker_style = _style(
            display="inline-block",
            font_family=fonts["mono"],
            font_size="11px",
            letter_spacing="3px",
            color=colors["accent"],
            font_weight="700",
        )
        h1_style = _style(
            font_family=fonts["heading"],
            font_size=f"{layout['h1_size']}px",
            line_height="1.3",
            font_weight="700",
            color=colors["text"],
            margin="16px 0 0",
            letter_spacing="0.02em",
        )
        bar_style = _style(
            width="64px",
            height="6px",
            background_color=colors["accent"],
            margin="14px 0 0",
        )
        hero_rule_style = _style(
            margin="20px 0 0",
            padding_top="10px",
            border_top="1px dashed #C9C9C2",
        )
        meta_style = _style(
            font_family=fonts["mono"],
            font_size="11px",
            letter_spacing="2px",
            color=colors["muted"],
        )
        square_style = _style(
            display="inline-block",
            width="12px",
            height="12px",
            background_color=colors["yellow"],
            margin_right="12px",
            vertical_align="6px",
        )
        # 右上角几何装饰：黄色虚线方框 + 蓝色星芒（背景为浅色网格纸）
        parts.append(
            f'<div style="{_style(position="relative", min_height="110px", background_image="repeating-linear-gradient(0deg, transparent, transparent 22px, rgba(43,95,190,0.06) 23px), repeating-linear-gradient(90deg, transparent, transparent 22px, rgba(43,95,190,0.06) 23px)", padding="10px 0 0")}">'
        )
        parts.append(
            f'<div style="{_style(position="absolute", right="6px", top="-4px", width="62px", height="62px", border=f"2px dashed {colors['yellow']}", transform="rotate(6deg)")}"></div>'
        )
        parts.append(
            f'<div style="{_style(position="absolute", right="30px", top="18px", width="14px", height="14px", background_color=colors['accent'], transform="rotate(45deg)")}"></div>'
        )
        parts.append(
            f'<div style="{_style(position="absolute", left="0", top="4px")}">'
            f'<span style="{kicker_style}">{html.escape(style["kicker"])}</span>'
            f"</div>"
        )
        parts.append("</div>")
        parts.append(
            f'<h1 style="{h1_style}"><span style="{square_style}"></span>'
            f"{html.escape(article['title'])}</h1>"
        )
        parts.append(f'<div style="{bar_style}"></div>')
        wave_style = _style(
            margin="8px 0 0",
            width="168px",
            height="14px",
            background_image="radial-gradient(circle at 12px -4px, rgba(0,0,0,0) 8px, #FFC93C 8px, #FFC93C 10px, rgba(0,0,0,0) 10px)",
            background_size="24px 14px",
            background_repeat="repeat-x",
            transform="rotate(-0.6deg)",
        )
        parts.append(f'<div style="{wave_style}"></div>')
        if meta_bits:
            parts.append(
                f'<div style="{hero_rule_style}">'
                f'<span style="{meta_style}">{" · ".join(meta_bits)}</span></div>'
            )
        parts.append("</div>")
    else:
        heading_align = "center" if style_id == "minimal" else "left"
        header_style = _style(margin="0 0 32px", text_align=heading_align)
        kicker_style = _style(
            font_family=fonts["mono"],
            font_size="11px",
            letter_spacing="3px",
            color=colors["muted"],
            margin="0 0 14px",
        )
        h1_style = _style(
            font_family=fonts["heading"],
            font_size=f"{layout['h1_size']}px",
            line_height="1.35",
            font_weight="600",
            color=colors["text"],
            text_align=heading_align,
            margin="0",
        )
        bar_style = _style(
            width="56px",
            height="6px",
            background_color=colors["accent"],
            margin="20px auto 0" if heading_align == "center" else "20px 0 0",
        )
        parts.append(f'<div style="{header_style}">')
        parts.append(
            f'<div style="{kicker_style}">{html.escape(style["kicker"])}</div>'
        )
        parts.append(f'<h1 style="{h1_style}">{html.escape(article["title"])}</h1>')
        parts.append(f'<div style="{bar_style}"></div>')
        if meta_bits:
            meta_style = _style(
                font_family=fonts["mono"],
                font_size="12px",
                color=colors["muted"],
                margin="14px 0 0",
            )
            parts.append(f'<div style="{meta_style}">{" · ".join(meta_bits)}</div>')
        parts.append("</div>")

    # 正文块
    section_no = 0
    quote_no = 0
    lead_done = False
    para_no = 0
    for block in article["blocks"]:
        block_type = block["type"]

        if block_type == "h2":
            section_no += 1
            if style_id == "heytea":
                badge_left = section_no % 2 == 1
                badge_style = _style(
                    display="inline-block",
                    width="36px",
                    height="36px",
                    box_sizing="border-box",
                    line_height="32px",
                    text_align="center",
                    background_color=colors["paper"],
                    border=f"1.5px solid {colors['line']}",
                    border_radius="48% 52% 45% 55% / 54% 46% 52% 48%",
                    font_family=fonts["mono"],
                    font_size="12px",
                    font_weight="400",
                    color=colors["text"],
                    vertical_align="middle",
                    margin_right="14px" if badge_left else None,
                    margin_left="14px" if not badge_left else None,
                    transform="rotate(-6deg)" if badge_left else "rotate(5deg)",
                )
                h2_title_style = _style(
                    display="inline-block",
                    font_family=fonts["heading"],
                    font_size=f"{layout['h2_size']}px",
                    line_height="1.2",
                    font_weight="300",
                    letter_spacing="0.25em",
                    color=colors["text"],
                    vertical_align="middle",
                    padding_bottom="3px",
                    border_bottom=f"4px solid {colors['accent']}",
                    transform="rotate(-0.5deg)" if badge_left else "rotate(0.4deg)",
                )
                h2_style = _style(
                    margin="46px 0 18px",
                    line_height="1.2",
                )
                badge_html = (
                    f'<span style="{badge_style}">{section_no:02d}</span>'
                )
                title_html = (
                    f'<span style="{h2_title_style}">'
                    f"{render_inline(block['text'], style)}</span>"
                )
                inner = (
                    badge_html + title_html
                    if badge_left
                    else title_html + badge_html
                )
                parts.append(f'<h2 style="{h2_style}">{inner}</h2>')
            elif style_id == "datawhale":
                sec_label = _style(
                    font_family=fonts["mono"],
                    font_size="10px",
                    letter_spacing="2px",
                    color=colors["accent"],
                    font_weight="700",
                    display="block",
                    margin="0 0 6px",
                )
                square_style = _style(
                    display="inline-block",
                    width="10px",
                    height="10px",
                    background_color=colors["yellow"],
                    margin_right="10px",
                    vertical_align="4px",
                )
                shift = section_no % 2 == 0
                h2_style = _style(
                    font_family=fonts["heading"],
                    font_size=f"{layout['h2_size']}px",
                    line_height="1.4",
                    font_weight="700",
                    color=colors["text"],
                    margin="38px 0 16px",
                    margin_left="14px" if shift else None,
                    transform="rotate(0.4deg)" if shift else "rotate(-0.4deg)",
                    transform_origin="left center",
                )
                parts.append(
                    f'<h2 style="{h2_style}"><span style="{sec_label}">{section_no:02d} / SECTION</span>'
                    f'<span style="{square_style}"></span>'
                    f"{render_inline(block['text'], style)}</h2>"
                )
            elif style_id == "minimal":
                number_style = _style(
                    font_family=fonts["mono"],
                    font_size="13px",
                    letter_spacing="2px",
                    color=colors["accent"],
                    margin_right="10px",
                )
                h2_style = _style(
                    font_family=fonts["heading"],
                    font_size=f"{layout['h2_size']}px",
                    line_height="1.5",
                    font_weight="600",
                    color=colors["text"],
                    margin="36px 0 16px",
                )
                parts.append(
                    f'<h2 style="{h2_style}"><span style="{number_style}">'
                    f"{section_no:02d}</span>{render_inline(block['text'], style)}</h2>"
                )
            else:
                number_style = _style(
                    font_family=fonts["mono"],
                    font_size="14px",
                    color=colors["accent"],
                    margin_right="8px",
                )
                h2_style = _style(
                    font_family=fonts["heading"],
                    font_size=f"{layout['h2_size']}px",
                    line_height="1.5",
                    font_weight="600",
                    color=colors["text"],
                    margin="34px 0 14px",
                    border_left=f"4px solid {colors['accent']}",
                    padding_left="12px",
                )
                parts.append(
                    f'<h2 style="{h2_style}"><span style="{number_style}">'
                    f"{section_no}.</span>{render_inline(block['text'], style)}</h2>"
                )

        elif block_type == "h3":
            if style_id == "datawhale":
                h3_style = _style(
                    font_family=fonts["heading"],
                    font_size=f"{layout['h3_size']}px",
                    line_height="1.5",
                    font_weight="700",
                    color=colors["text"],
                    margin="26px 0 10px",
                    border_left=f"4px solid {colors['accent']}",
                    padding_left="10px",
                )
            elif style_id == "heytea":
                h3_style = _style(
                    font_family=fonts["heading"],
                    font_size=f"{layout['h3_size']}px",
                    line_height="1.5",
                    font_weight="300",
                    letter_spacing="0.22em",
                    color=colors["text"],
                    margin="28px 0 10px",
                    transform="rotate(-0.4deg)",
                )
                h3_bar_style = _style(
                    display="inline-block",
                    width="3px",
                    height="14px",
                    background_color=colors["accent"],
                    margin_right="10px",
                    vertical_align="-2px",
                )
            else:
                h3_style = _style(
                    font_family=fonts["heading"],
                    font_size=f"{layout['h3_size']}px",
                    line_height="1.6",
                    font_weight="600",
                    color=colors["text"],
                    margin="24px 0 10px",
                )
            h3_inner = render_inline(block["text"], style)
            if style_id == "heytea":
                h3_inner = f'<span style="{h3_bar_style}"></span>' + h3_inner
            parts.append(f'<h3 style="{h3_style}">{h3_inner}</h3>')

        elif block_type == "p":
            is_lead = False
            if style_id == "heytea" and not lead_done:
                lead_done = True
                is_lead = True
                # 阶梯式引言：逐行右移 + 背后淡色水彩环（杨梅晚熟手法）
                parts.append(
                    f'<div style="{_style(position="relative", margin=f"0 0 {layout["para_spacing"]}px", padding="6px 0")}">'
                )
                parts.append(
                    f'<div style="{_style(position="absolute", right="-40px", top="-10px", width="140px", height="140px", border=f"1.5px solid {colors["ring_soft"]}", border_radius="50%")}"></div>'
                )
                for idx, line in enumerate(block["lines"]):
                    parts.append(
                        f'<p style="{_style(width="fit-content", max_width="430px", margin=f"0 0 6px {idx * 26}px", font_size="18px", line_height="2.1", letter_spacing="0.2em", font_weight="300", color=colors["text"], transform="rotate(-0.3deg)")}">{render_inline(line, style)}</p>'
                    )
                parts.append("</div>")
                continue
            if style_id == "datawhale" and not lead_done:
                lead_done = True
                # 导语做成黑色大字块：白色正文 + 黄色短横线（科技蓝分享会风）
                parts.append(
                    f'<div style="{_style(margin=f"0 -30px {layout["para_spacing"]}px", padding="24px 30px", background_color=colors["line"])}">'
                )
                parts.append(
                    f'<div style="{_style(width="36px", height="4px", background_color=colors["yellow"], margin="0 0 14px")}"></div>'
                )
                for idx, line in enumerate(block["lines"]):
                    weight = "700" if idx == 0 else "400"
                    size = "18px" if idx == 0 else "15px"
                    is_quote_line = line.strip().startswith("——")
                    color = colors["yellow"] if is_quote_line else "#F5F5F2"
                    parts.append(
                        f'<p style="{_style(width="fit-content", margin=f"0 0 8px {idx * 14}px", font_size=size, line_height="2.0", font_weight=weight, color=color, letter_spacing="0.04em")}">{render_inline(line, style)}</p>'
                    )
                parts.append("</div>")
                continue
            else:
                if style_id == "datawhale":
                    joined = "".join(block["lines"])
                    if "时间" in joined and "报名" in joined:
                        # 蓝底信息引导区：白字信息 + 黄色三角 + 黄色虚线二维码框（海报同款）
                        parts.append(
                            f'<div style="{_style(position="relative", margin=f"0 -30px {layout["para_spacing"]}px", padding="26px 30px 28px", background_color=colors["accent"])}">'
                        )
                        parts.append(
                            f'<div style="{_style(font_size="22px", font_weight="700", color="#FFFFFF", letter_spacing="0.06em", margin="0 0 12px")}">活动信息</div>'
                        )
                        for line in block["lines"]:
                            parts.append(
                                f'<p style="{_style(margin="0 0 6px", font_size="14px", line_height="1.9", color="#FFFFFF", letter_spacing="0.04em")}">{render_inline(line, style)}</p>'
                            )
                        parts.append(
                            f'<div style="{_style(margin="18px 0 0", line_height="1")}">'
                            f'<span style="{_style(display="inline-block", width="0", height="0", border_top="10px solid transparent", border_bottom="10px solid transparent", border_left=f"16px solid {colors['yellow']}", margin_right="12px", vertical_align="middle")}"></span>'
                            f'<span style="{_style(display="inline-block", vertical_align="middle", font_size="12px", color="#FFFFFF", letter_spacing="0.05em")}">扫码加入分享群</span></div>'
                        )
                        parts.append(
                            f'<div style="{_style(display="inline-block", margin_top="12px", width="88px", height="88px", border=f"2px dashed {colors['yellow']}", text_align="center", font_size="11px", color="#FFFFFF", letter_spacing="0.1em", line_height="88px")}">二维码</div>'
                        )
                        parts.append("</div>")
                        continue
                p_style = _style(
                    margin=f"0 0 {layout['para_spacing']}px",
                    font_size=f"{layout['body_size']}px",
                    line_height=str(layout["line_height"]),
                    color=colors["text"],
                )
                if style_id == "minimal":
                    p_style += "text-indent:2em;"
                elif style_id == "academic":
                    p_style += "text-align:justify;"
                elif style_id == "heytea":
                    p_style += "letter-spacing:0.08em;"
                    para_no += 1
                    if para_no % 2 == 0:
                        p_style += "margin-left:14px;"
                elif style_id == "datawhale":
                    p_style += "letter-spacing:0.03em;"
                    para_no += 1
                    if para_no % 2 == 0:
                        p_style += "margin-left:12px;"
            body = "<br>".join(
                render_inline(line, style) for line in block["lines"]
            )
            parts.append(f'<p style="{p_style}">{body}</p>')

        elif block_type == "quote":
            if style_id == "datawhale":
                quote_no += 1
                stagger = quote_no % 2 == 0
                quote_style = _style(
                    margin="0 0 24px 8%" if stagger else "0 0 24px",
                    width="92%" if stagger else None,
                    box_sizing="border-box",
                    padding="22px 24px",
                    background_color=colors["paper"],
                    border=f"2px solid {colors['line']}",
                    border_radius="12px",
                    box_shadow="6px 6px 0 rgba(16,16,16,0.12)",
                    transform="rotate(0.6deg)" if stagger else "rotate(-0.5deg)",
                )
                quote_label = _style(
                    font_family=fonts["mono"],
                    font_size="10px",
                    letter_spacing="2px",
                    color=colors["accent"],
                    font_weight="700",
                    margin="0 0 8px",
                )
                spark_style = _style(
                    display="inline-block",
                    width="12px",
                    height="12px",
                    background_color=colors["accent"],
                    transform="rotate(45deg)",
                    margin_right="8px",
                    vertical_align="-1px",
                )
                quote_text_style = _style(
                    font_size="16px",
                    line_height="1.9",
                    color=colors["text"],
                )
                parts.append(
                    f'<blockquote style="{quote_style}">'
                    f'<div style="{quote_label}"><span style="{spark_style}"></span>QUOTE / 金句</div>'
                    f'<div style="{quote_text_style}">'
                    f"{render_inline(block['text'], style)}</div></blockquote>"
                )
            elif style_id == "heytea":
                quote_no += 1
                stagger = quote_no % 2 == 0
                quote_style = _style(
                    position="relative",
                    width="94%" if stagger else None,
                    margin="0 0 30px 6%" if stagger else "0 0 30px",
                    box_sizing="border-box",
                    padding="26px 24px 20px",
                    background_color=colors["note_bg"],
                    border=f"1.5px solid {colors['line']}",
                    border_radius="12% 10% 14% 9% / 9% 13% 8% 12%",
                    box_shadow="0 12px 26px rgba(0,0,0,0.12)",
                    transform="rotate(0.9deg)" if stagger else "rotate(-0.7deg)",
                )
                pin_style = _style(
                    position="absolute",
                    top="-9px",
                    left="50%",
                    margin_left="-9px",
                    width="18px",
                    height="18px",
                    border_radius="50%",
                    background_color="#8A8A86",
                    box_shadow="inset 0 -3px 4px rgba(0,0,0,0.25)",
                )
                quote_label = _style(
                    font_family=fonts["mono"],
                    font_size="10px",
                    letter_spacing="2px",
                    color=colors["accent_dark"],
                    margin="0 0 8px",
                    text_align="right" if stagger else None,
                )
                quote_text_style = _style(
                    font_size="17px",
                    line_height="1.9",
                    font_weight="300",
                    letter_spacing="0.08em",
                    color=colors["text"],
                    text_align="right" if stagger else None,
                )
                parts.append(
                    f'<blockquote style="{quote_style}">'
                    f'<div style="{pin_style}"></div>'
                    f'<div style="{quote_label}">↗ 批注</div>'
                    f'<div style="{quote_text_style}">'
                    f"{render_inline(block['text'], style)}</div></blockquote>"
                )
            elif style_id == "minimal":
                quote_style = _style(
                    margin="0 0 22px",
                    padding="4px 0 4px 16px",
                    border_left=f"3px solid {colors['accent']}",
                    color=colors["muted"],
                    font_family=fonts["heading"],
                    font_size=f"{layout['body_size']}px",
                    line_height=str(layout["line_height"]),
                )
            else:
                quote_style = _style(
                    margin="0 0 20px",
                    padding="14px 16px",
                    border_left=f"4px solid {colors['accent']}",
                    background_color=colors["paper"],
                    color=colors["text"],
                    font_size=f"{layout['body_size']}px",
                    line_height=str(layout["line_height"]),
                )
            if style_id != "heytea":
                parts.append(
                    f'<blockquote style="{quote_style}">'
                    f"{render_inline(block['text'], style)}</blockquote>"
                )

        elif block_type in ("ul", "ol"):
            if style_id == "datawhale":
                list_style = _style(
                    margin="0 0 20px",
                    padding="0",
                    list_style="none",
                    color=colors["text"],
                )
                parts.append(f'<{block_type} style="{list_style}">')
                for index, item in enumerate(block["items"], 1):
                    li_style = _style(
                        margin="0",
                        margin_left="10px" if index % 2 == 0 else None,
                        padding="13px 4px",
                        border_bottom="1px dashed #C9C9C2",
                        font_size=f"{layout['body_size']}px",
                        line_height="1.8",
                        color=colors["text"],
                        list_style="none",
                    )
                    num_style = _style(
                        display="inline-block",
                        width="30px",
                        height="30px",
                        box_sizing="border-box",
                        line_height="26px",
                        text_align="center",
                        background_color="transparent",
                        border=f"2px solid {colors['accent']}",
                        border_radius="50%",
                        font_family=fonts["mono"],
                        font_size="12px",
                        font_weight="700",
                        color=colors["accent_dark"],
                        margin_right="12px",
                        vertical_align="middle",
                    )
                    parts.append(
                        f'<li style="{li_style}">'
                        f'<span style="{num_style}">{index:02d}</span>'
                        f"{render_inline(item, style)}</li>"
                    )
                parts.append(f"</{block_type}>")
            elif style_id == "heytea":
                list_style = _style(
                    margin="0 0 22px",
                    padding="0",
                    list_style="none",
                    color=colors["text"],
                )
                parts.append(f'<{block_type} style="{list_style}">')
                for index, item in enumerate(block["items"], 1):
                    tilt = "-0.35deg" if index % 2 else "0.35deg"
                    li_style = _style(
                        margin="0",
                        padding="9px 2px",
                        border_bottom="1px dotted #B9AE96",
                        font_size=f"{layout['body_size']}px",
                        line_height="1.9",
                        color=colors["text"],
                        list_style="none",
                        transform=f"rotate({tilt})" if block_type == "ul" else None,
                    )
                    if block_type == "ul":
                        bullet_style = _style(
                            display="inline-block",
                            width="15px",
                            height="15px",
                            line_height="15px",
                            text_align="center",
                            background_color=colors["accent"],
                            border=f"1.5px solid {colors['line']}",
                            border_radius="3px",
                            font_size="10px",
                            color=colors["paper"],
                            margin_right="9px",
                            vertical_align="1px",
                        )
                        bullet = f'<span style="{bullet_style}">✓</span>'
                    else:
                        bullet_style = _style(
                            display="inline-block",
                            width="30px",
                            height="30px",
                            box_sizing="border-box",
                            line_height="26px",
                            text_align="center",
                            background_color=colors["accent"],
                            border=f"2px solid {colors['line']}",
                            border_radius="50%",
                            font_family=fonts["mono"],
                            font_size="11px",
                            font_weight="400",
                            color=colors["paper"],
                            margin_right="10px",
                            vertical_align="middle",
                            transform="rotate(-5deg)",
                        )
                        bullet = f'<span style="{bullet_style}">{index:02d}</span>'
                    parts.append(
                        f'<li style="{li_style}">{bullet}'
                        f"{render_inline(item, style)}</li>"
                    )
                parts.append(f"</{block_type}>")
            else:
                list_style = _style(
                    margin="0 0 20px",
                    padding_left="24px",
                    color=colors["text"],
                )
                parts.append(f'<{block_type} style="{list_style}">')
                for item in block["items"]:
                    li_style = _style(
                        margin="0 0 10px",
                        font_size=f"{layout['body_size']}px",
                        line_height=str(layout["line_height"]),
                        color=colors["text"],
                    )
                    parts.append(
                        f'<li style="{li_style}">{render_inline(item, style)}</li>'
                    )
                parts.append(f"</{block_type}>")

        elif block_type == "hr":
            if style_id == "datawhale":
                parts.append(
                    f'<div style="{_style(margin="30px 0", text_align="center", line_height="1")}">'
                    f'<span style="{_style(display="inline-block", width="80px", border_top=f"2px dashed {colors['yellow']}", vertical_align="middle")}"></span>'
                    f'<span style="{_style(display="inline-block", width="10px", height="10px", background_color=colors['accent'], transform="rotate(45deg)", margin="0 14px", vertical_align="middle")}"></span>'
                    f'<span style="{_style(display="inline-block", width="80px", border_top=f"2px dashed {colors['yellow']}", vertical_align="middle")}"></span></div>'
                )
            elif style_id == "heytea":
                circle_style = _style(
                    display="inline-block",
                    position="relative",
                    width="40px",
                    height="40px",
                    border=f"1.5px solid {colors['text']}",
                    border_radius="48% 52% 50% 50% / 52% 48% 50% 50%",
                    vertical_align="middle",
                )
                dot_style = _style(
                    position="absolute",
                    right="6px",
                    top="16px",
                    width="6px",
                    height="6px",
                    border_radius="50%",
                    background_color=colors["text"],
                )
                parts.append(
                    f'<div style="{_style(margin="34px 0", text_align="center", line_height="1")}">'
                    f'<span style="{circle_style}"><span style="{dot_style}"></span></span>'
                    f'<span style="{_style(display="inline-block", vertical_align="middle", margin_left="16px", font_size="14px", letter_spacing="0.6em", color=colors["muted"], padding_left="0.6em")}">· · ·</span></div>'
                )
            else:
                hr_style = _style(
                    border="none",
                    border_top=f"1px solid {colors['line']}",
                    margin="30px 0",
                )
                parts.append(f'<hr style="{hr_style}">')

        elif block_type == "code":
            if style_id == "datawhale":
                code_box_style = _style(
                    margin="0 0 22px",
                    padding="16px 18px",
                    background_color=colors["code_bg"],
                    border="1px solid #D8D8D2",
                    border_radius="8px",
                )
                code_label_style = _style(
                    font_family=fonts["mono"],
                    font_size="10px",
                    letter_spacing="2px",
                    color=colors["accent"],
                    font_weight="700",
                    margin="0 0 8px",
                )
                pre_style = _style(
                    margin="0",
                    padding="0",
                    background_color=colors["code_bg"],
                    color=colors["text"],
                    font_family=fonts["mono"],
                    font_size="13px",
                    line_height="1.7",
                    white_space="pre-wrap",
                    word_break="break-word",
                    overflow_x="auto",
                )
                parts.append(
                    f'<div style="{code_box_style}">'
                    f'<div style="{code_label_style}">DATA / 速览</div>'
                    f'<pre style="{pre_style}">{html.escape(block["text"])}</pre></div>'
                )
            elif style_id == "heytea":
                code_wrap_style = _style(
                    position="relative",
                    margin="0 0 28px",
                    transform="rotate(-0.4deg)",
                )
                code_tape_style = _style(
                    position="absolute",
                    top="-7px",
                    left="20px",
                    width="72px",
                    height="14px",
                    background_color=colors["tape"],
                    transform="rotate(-5deg)",
                )
                code_box_style = _style(
                    background_color=colors["code_block_bg"],
                    border_radius="6px",
                    padding="18px 18px 16px",
                )
                code_label_style = _style(
                    font_family=fonts["mono"],
                    font_size="10px",
                    letter_spacing="2px",
                    color=colors["accent_light"],
                    margin="0 0 10px",
                )
                pre_style = _style(
                    margin="0",
                    padding="0",
                    background_color=colors["code_block_bg"],
                    color=colors["code_block_text"],
                    font_family=fonts["mono"],
                    font_size="13px",
                    line_height="1.7",
                    white_space="pre-wrap",
                    word_break="break-word",
                    overflow_x="auto",
                )
                parts.append(
                    f'<div style="{code_wrap_style}">'
                    f'<div style="{code_tape_style}"></div>'
                    f'<div style="{code_box_style}">'
                    f'<div style="{code_label_style}">实验记录 / DATA</div>'
                    f'<pre style="{pre_style}">{html.escape(block["text"])}</pre>'
                    f"</div></div>"
                )
            else:
                pre_style = _style(
                    margin="0 0 20px",
                    padding="14px 16px",
                    background_color=colors["code_bg"],
                    border=f"1px solid {colors['line']}",
                    color=colors["text"],
                    font_family=fonts["mono"],
                    font_size="13px",
                    line_height="1.7",
                    white_space="pre-wrap",
                    word_break="break-word",
                    overflow_x="auto",
                )
                parts.append(
                    f'<pre style="{pre_style}">{html.escape(block["text"])}</pre>'
                )

    if style_id == "datawhale":
        footer_style = _style(
            margin="44px 0 0",
            padding_top="18px",
            border_top="2px dashed #C9C9C2",
            text_align="center",
        )
        footer_main = _style(
            font_size="20px",
            line_height="1.4",
            font_weight="700",
            letter_spacing="0.1em",
            color=colors["text"],
        )
        tag_style = _style(
            display="inline-block",
            margin_top="12px",
            background_color=colors["line"],
            color="#F5F5F2",
            font_family=fonts["mono"],
            font_size="11px",
            letter_spacing="2px",
            padding="7px 14px",
            border_radius="999px",
        )
        tag_word = "".join(
            ch for ch in style["kicker"].split("/")[-1].strip().split() if ch.isalnum()
        ).upper()
        parts.append(
            f'<div style="{footer_style}">'
            f'<div style="{footer_main}">— 完 —</div>'
            f'<div style="{_style(margin_top="12px")}"><span style="{tag_style}">#{tag_word}</span></div></div>'
        )
    elif style_id == "heytea":
        footer_style = _style(
            margin="48px 0 0",
            padding_top="18px",
            border_top="1px dashed #C9BFA8",
            text_align="center",
        )
        footer_main = _style(
            font_size="20px",
            line_height="1.3",
            font_weight="200",
            letter_spacing="0.35em",
            color=colors["text"],
            transform="rotate(-1deg)",
        )
        footer_sub = _style(
            margin_top="6px",
            font_family=fonts["mono"],
            font_size="10px",
            letter_spacing="2px",
            color=colors["muted"],
        )
        parts.append(
            f'<div style="{footer_style}">'
            f'<div style="{footer_main}">— 完 —</div>'
            f'<div style="{footer_sub}">EXPERIMENT LOG · 归档</div></div>'
        )
    else:
        footer_style = _style(
            margin="42px 0 0",
            padding_top="18px",
            border_top=f"1px solid {colors['line']}",
            text_align="center",
            font_family=fonts["mono"],
            font_size="12px",
            letter_spacing="2px",
            color=colors["muted"],
        )
        parts.append(f'<div style="{footer_style}">— 完 —</div>')
    parts.append("</div>")
    return "\n".join(parts)


def render(
    text: str,
    style_id: str = "heytea",
    title: Optional[str] = None,
    author: Optional[str] = None,
    date: Optional[str] = None,
    accent: Optional[str] = None,
) -> str:
    """生成完整 HTML 文档。"""
    style = load_style(style_id)
    if accent is not None:
        if not ACCENT_RE.match(accent):
            raise ValueError(
                f"点缀色格式不对：{accent}；请使用 #RRGGBB，例如 #F0B030"
            )
        style["colors"]["accent"] = accent

    article = parse_article(text, title)
    article["author"] = author
    article["date"] = date
    body = render_html(article, style)

    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(article['title'])}</title>\n"
        "</head>\n"
        f'<body style="margin:0;padding:0;background-color:{style["colors"].get("wall", style["colors"]["bg"])};">\n'
        f"{body}\n"
        "</body>\n"
        "</html>\n"
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="把文字稿转换成可直接粘贴进公众号编辑器的单文件 HTML"
    )
    parser.add_argument("input", nargs="?", help="输入文件（.txt / .md，UTF-8）")
    parser.add_argument(
        "--style",
        default="heytea",
        choices=STYLE_IDS,
        help="排版风格（默认 heytea）",
    )
    parser.add_argument("--title", help="文章标题；不填则取文件第一行")
    parser.add_argument("--author", help="作者署名（可选）")
    parser.add_argument("--date", help="日期文字，例如 2026-10-23（可选）")
    parser.add_argument("--accent", help="点缀色，格式 #RRGGBB（可选）")
    parser.add_argument("--output", "-o", help="输出 HTML 路径")
    parser.add_argument(
        "--validate", action="store_true", help="生成后自动运行排版质量检查"
    )
    parser.add_argument(
        "--list-styles", action="store_true", help="列出内置风格后退出"
    )
    args = parser.parse_args(argv)

    if args.list_styles:
        for style_id in STYLE_IDS:
            print(f"{style_id}\t{load_style(style_id)['name']}")
        return 0

    if not args.input:
        parser.error("缺少输入文件；使用 --help 查看用法")

    input_path = Path(args.input)
    try:
        text = read_text(input_path)
        document = render(
            text,
            style_id=args.style,
            title=args.title,
            author=args.author,
            date=args.date,
            accent=args.accent,
        )
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"错误：无法读取文件：{exc}", file=sys.stderr)
        return 2

    output_path = (
        Path(args.output)
        if args.output
        else input_path.with_name(f"{input_path.stem}-{args.style}.html")
    )
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(document, encoding="utf-8")
    except OSError as exc:
        print(f"错误：无法写入文件：{exc}", file=sys.stderr)
        return 2
    print(f"已生成：{output_path}")

    if args.validate:
        import validate

        report = validate.validate_html(document)
        print(
            f"排版校验：{'通过' if report['passed'] else '未通过'}"
            f"（{len(report['checks'])} 项检查）"
        )
        for check in report["checks"]:
            if not check["passed"]:
                print(f"  [失败] {check['id']}: {check['detail']}")
        return 0 if report["passed"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
