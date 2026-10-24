#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公众号 HTML 排版质量检查。

检查项：
1. 没有 script / style / link / iframe 等公众号会过滤或带来风险的标签
2. 存在 id=wechat-article 的容器，且 max-width 为 677px
3. 只有一个 h1 标题
4. 没有外链资源（http / https / 协议相对地址）
5. 所有可见元素都带内联样式（公众号粘贴时 class 样式会丢失）
6. 正文文字对比度达到 WCAG AA（普通文字 4.5:1，大字 3:1）
7. 正文字号 14–20px、行高不小于 1.6

用法：
    python validate.py article.html
    python validate.py article.html --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
EXEMPT_STYLE_TAGS = {"html", "head", "meta", "title", "body", "br"}
TEXT_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "blockquote",
    "strong",
    "em",
    "span",
    "code",
    "pre",
    "td",
    "th",
    "a",
    "div",
}
REMOTE_RE = re.compile(r"^(https?:)?//", re.I)
URL_CSS_RE = re.compile(r"url\s*\(\s*['\"]?(https?:)?//", re.I)
NAMED_COLORS = {
    "white": "#FFFFFF",
    "black": "#000000",
    "red": "#FF0000",
    "gray": "#808080",
    "grey": "#808080",
}


class Node:
    """极简 DOM 节点，够用即可。"""

    __slots__ = ("tag", "attrs", "children", "parent", "text_parts")

    def __init__(self, tag: str, attrs: List[Any], parent: Optional["Node"] = None):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children: List["Node"] = []
        self.parent = parent
        self.text_parts: List[str] = []

    @property
    def text(self) -> str:
        return "".join(self.text_parts).strip()


class TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", [])
        self.stack: List[Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: List[Any]) -> None:
        node = Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: List[Any]) -> None:
        node = Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].text_parts.append(data)


def walk(node: Node) -> Iterator[Node]:
    yield node
    for child in node.children:
        yield from walk(child)


def parse_style(value: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for chunk in value.split(";"):
        if ":" in chunk:
            key, val = chunk.split(":", 1)
            result[key.strip().lower()] = val.strip()
    return result


def parse_color(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = value.strip().lower()
    if text in NAMED_COLORS:
        return NAMED_COLORS[text]
    short = re.fullmatch(r"#([0-9a-f]{3})", text)
    if short:
        return "#" + "".join(ch * 2 for ch in short.group(1))
    full = re.fullmatch(r"#([0-9a-f]{6})", text)
    if full:
        return "#" + full.group(1)
    rgb = re.fullmatch(
        r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", text
    )
    if rgb:
        return "#{:02X}{:02X}{:02X}".format(*(int(x) for x in rgb.groups()))
    return None


def _channel(value: int) -> float:
    normalized = value / 255.0
    if normalized <= 0.03928:
        return normalized / 12.92
    return ((normalized + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    red, green, blue = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return (
        0.2126 * _channel(red)
        + 0.7152 * _channel(green)
        + 0.0722 * _channel(blue)
    )


def contrast_ratio(color_a: str, color_b: str) -> float:
    lum_a = luminance(color_a)
    lum_b = luminance(color_b)
    high, low = max(lum_a, lum_b), min(lum_a, lum_b)
    return round((high + 0.05) / (low + 0.05), 2)


def inherited_style(node: Optional[Node], prop: str) -> Optional[str]:
    current = node
    while current is not None:
        style = parse_style(current.attrs.get("style", ""))
        if prop in style:
            return style[prop]
        current = current.parent
    return None


def parse_px(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    match = re.fullmatch(r"([\d.]+)px", value.strip())
    return float(match.group(1)) if match else None


def validate_html(source: Any) -> Dict[str, Any]:
    """校验 HTML 字符串或文件路径，返回 {passed, checks}。"""
    if isinstance(source, Path):
        source = source.read_text(encoding="utf-8")

    builder = TreeBuilder()
    builder.feed(source)
    builder.close()
    nodes = list(walk(builder.root))
    checks: List[Dict[str, Any]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append(
            {"id": check_id, "passed": bool(passed), "detail": detail}
        )

    # 1. 禁用标签
    forbidden = {"script", "link", "iframe", "object", "embed", "style"}
    bad_tags = sorted({node.tag for node in nodes if node.tag in forbidden})
    add(
        "no-forbidden-tags",
        not bad_tags,
        "未发现 script/style/link/iframe 等标签"
        if not bad_tags
        else f"发现禁用标签：{bad_tags}",
    )

    # 2. 容器宽度
    article = next(
        (node for node in nodes if node.attrs.get("id") == "wechat-article"),
        None,
    )
    if article is None:
        add("container-width", False, "未找到 id=wechat-article 的容器")
    else:
        width = parse_style(article.attrs.get("style", "")).get("max-width", "")
        add(
            "container-width",
            width == "677px",
            f"容器 max-width={width or '未设置'}（要求 677px）",
        )

    # 3. 标题
    h1_count = sum(1 for node in nodes if node.tag == "h1")
    add("single-h1", h1_count == 1, f"h1 数量：{h1_count}（要求 1 个）")

    # 4. 外链资源
    remote: List[str] = []
    for node in nodes:
        for attr in ("src", "href"):
            value = node.attrs.get(attr, "")
            if value and REMOTE_RE.match(value.strip()):
                remote.append(f"{node.tag}[{attr}]={value}")
        style = parse_style(node.attrs.get("style", ""))
        if any(URL_CSS_RE.search(item) for item in style.values()):
            remote.append(f"{node.tag} 的 CSS 含外链 url()")
    add(
        "no-remote-resources",
        not remote,
        "未发现外链资源" if not remote else "发现外链资源：" + "；".join(remote[:5]),
    )

    # 5. 内联样式
    missing = sorted(
        {
            node.tag
            for node in nodes
            if node.tag not in EXEMPT_STYLE_TAGS
            and node.tag != "#document"
            and not node.attrs.get("style")
        }
    )
    add(
        "inline-styles",
        not missing,
        "所有可见元素都带内联样式"
        if not missing
        else f"缺少 style 属性的标签：{missing}（粘贴进公众号会丢样式）",
    )

    # 6. 文字对比度
    contrast_failures: List[str] = []
    for node in nodes:
        if node.tag not in TEXT_TAGS or not node.text:
            continue
        color = parse_color(inherited_style(node, "color")) or "#000000"
        background = (
            parse_color(inherited_style(node, "background-color")) or "#FFFFFF"
        )
        ratio = contrast_ratio(color, background)
        size = parse_px(inherited_style(node, "font-size")) or 16.0
        weight = (inherited_style(node, "font-weight") or "400").lower()
        is_bold = weight in {"bold", "600", "700", "800", "900"}
        threshold = 3.0 if (size >= 24 or (size >= 18.66 and is_bold)) else 4.5
        if ratio < threshold:
            contrast_failures.append(
                f"<{node.tag}> 对比度 {ratio}:1（要求 ≥{threshold}:1）"
            )
    add(
        "text-contrast",
        not contrast_failures,
        "正文文字对比度达标"
        if not contrast_failures
        else "；".join(contrast_failures[:5]),
    )

    # 7. 正文字号与行高
    typo_failures: List[str] = []
    for node in nodes:
        if node.tag not in ("p", "li"):
            continue
        style = parse_style(node.attrs.get("style", ""))
        size = parse_px(style.get("font-size"))
        if size is not None and not 14 <= size <= 20:
            typo_failures.append(f"<{node.tag}> 字号 {size}px（要求 14–20px）")
        line_height = style.get("line-height")
        if line_height:
            if line_height.endswith("px") and size:
                if float(line_height[:-2]) / size < 1.6:
                    typo_failures.append(f"<{node.tag}> 行高不足 1.6")
            else:
                try:
                    if float(line_height) < 1.6:
                        typo_failures.append(
                            f"<{node.tag}> 行高 {line_height}（要求 ≥1.6）"
                        )
                except ValueError:
                    pass
    add(
        "body-typography",
        not typo_failures,
        "正文字号和行高达标"
        if not typo_failures
        else "；".join(typo_failures[:5]),
    )

    return {"passed": all(check["passed"] for check in checks), "checks": checks}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="检查公众号 HTML 的排版质量")
    parser.add_argument("html", help="要检查的 HTML 文件")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    args = parser.parse_args(argv)

    path = Path(args.html)
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"错误：无法读取 {path}：{exc}", file=sys.stderr)
        return 2

    report = validate_html(source)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"排版校验：{'通过' if report['passed'] else '未通过'}")
        for check in report["checks"]:
            mark = "通过" if check["passed"] else "失败"
            print(f"[{mark}] {check['id']}: {check['detail']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
