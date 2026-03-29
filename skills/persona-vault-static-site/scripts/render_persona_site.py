#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


@dataclass
class MarkdownDoc:
    title: str
    sections: dict[str, list[str]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a PersonaVault into a static profile page."
    )
    parser.add_argument("--persona-vault-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--site-title")
    return parser.parse_args()


def strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5 :]
    return text


def parse_markdown(path: Path) -> MarkdownDoc:
    text = strip_frontmatter(path.read_text(encoding="utf-8"))
    title = path.stem
    sections: dict[str, list[str]] = {}
    current_section: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("# "):
            title = line[2:].strip()
            continue
        if line.startswith("## "):
            current_section = line[3:].strip()
            sections[current_section] = []
            continue
        if current_section:
            sections[current_section].append(line)

    return MarkdownDoc(title=title, sections=sections)


def clean_inline(value: str) -> str:
    def replace_wiki(match: re.Match[str]) -> str:
        inner = match.group(1)
        if "|" in inner:
            return inner.split("|", 1)[1]
        return inner

    value = re.sub(r"\[\[([^\]]+)\]\]", replace_wiki, value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\s+", " ", value).strip()
    return html.escape(value)


def extract_bullets(lines: list[str]) -> list[str]:
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(clean_inline(stripped[2:]))
    return items


def extract_paragraphs(lines: list[str]) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(clean_inline(" ".join(current)))
                current = []
            continue
        if stripped.startswith("- ") or stripped.startswith("|") or stripped.startswith(">"):
            if current:
                paragraphs.append(clean_inline(" ".join(current)))
                current = []
            continue
        current.append(stripped)
    if current:
        paragraphs.append(clean_inline(" ".join(current)))
    return paragraphs


def extract_first_paragraph(lines: list[str]) -> str:
    paragraphs = extract_paragraphs(lines)
    return paragraphs[0] if paragraphs else ""


def extract_blockquote(lines: list[str]) -> str:
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(">"):
            return clean_inline(stripped[1:].strip())
    return ""


def parse_markdown_table(lines: list[str]) -> tuple[list[str], list[list[str]]]:
    table_lines = [line.strip() for line in lines if line.strip().startswith("|")]
    if len(table_lines) < 2:
        return [], []

    rows: list[list[str]] = []
    for line in table_lines:
        cells = [clean_inline(cell.strip()) for cell in line.strip("|").split("|")]
        rows.append(cells)

    if len(rows) >= 2 and all(set(cell) <= {"-", ":"} for cell in rows[1]):
        header = rows[0]
        body = rows[2:]
    else:
        header = rows[0]
        body = rows[1:]
    return header, body


def parse_preference_cards(lines: list[str]) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue

        depth = (len(line) - len(line.lstrip(" "))) // 2
        text = stripped[2:].strip()
        if depth == 0:
            if current:
                cards.append(current)
            current = {"title": clean_inline(text), "description": ""}
        elif depth > 0 and current and not current["description"]:
            current["description"] = clean_inline(text)

    if current:
        cards.append(current)

    return cards


def render_empty_state(message: str) -> str:
    return (
        '<div class="rounded-3xl border border-dashed border-stone-300 bg-stone-50 px-4 py-5 '
        'text-sm text-stone-500">'
        f"{clean_inline(message)}"
        "</div>"
    )


def render_list(items: list[str], tone: str = "light") -> str:
    if not items:
        return render_empty_state("No content available.")

    if tone == "dark":
        list_class = "space-y-3 text-sm leading-7 text-stone-100"
        bullet_class = "mt-[0.6rem] h-2 w-2 rounded-full bg-amber-300"
    else:
        list_class = "space-y-3 text-sm leading-7 text-stone-700"
        bullet_class = "mt-[0.6rem] h-2 w-2 rounded-full bg-stone-300"

    parts = [f'<ul class="{list_class}">']
    for item in items:
        parts.append(
            '<li class="flex gap-3">'
            f'<span class="{bullet_class} shrink-0"></span>'
            f"<span>{item}</span>"
            "</li>"
        )
    parts.append("</ul>")
    return "".join(parts)


def render_keyword_chips(items: list[str]) -> str:
    if not items:
        return '<span class="rounded-full bg-stone-200 px-3 py-1 text-sm text-stone-600">No keywords</span>'
    return "".join(
        f'<span class="rounded-full bg-stone-900 px-3 py-1 text-sm text-white">{item}</span>'
        for item in items
    )


def render_value_cards(cards: list[dict[str, str]]) -> str:
    if not cards:
        return render_empty_state("No values available.")

    parts: list[str] = []
    for card in cards:
        parts.append(
            '<article class="rounded-3xl border border-stone-200 bg-stone-50 p-5">'
            f'<h3 class="text-base font-semibold text-stone-900">{card["title"]}</h3>'
            f'<p class="mt-3 text-sm leading-7 text-stone-600">{card["description"] or " "}</p>'
            "</article>"
        )
    return "".join(parts)


def render_work_history(note: str, header: list[str], rows: list[list[str]], gaps: list[str]) -> str:
    parts: list[str] = []

    if note:
        parts.append(
            '<div class="mb-4 rounded-3xl border border-stone-200 bg-stone-50 px-5 py-4 text-sm leading-7 text-stone-600">'
            f"{note}"
            "</div>"
        )

    if header and rows:
        parts.append('<div class="overflow-x-auto rounded-3xl border border-stone-200">')
        parts.append('<table class="min-w-full divide-y divide-stone-200 text-left text-sm">')
        parts.append('<thead class="bg-stone-50"><tr>')
        for cell in header:
            parts.append(
                f'<th class="px-4 py-3 font-medium uppercase tracking-[0.16em] text-stone-500">{cell}</th>'
            )
        parts.append("</tr></thead><tbody class=\"divide-y divide-stone-100 bg-white\">")
        for row in rows:
            parts.append("<tr>")
            for cell in row:
                parts.append(f'<td class="px-4 py-3 align-top leading-7 text-stone-700">{cell}</td>')
            parts.append("</tr>")
        parts.append("</tbody></table></div>")

    if gaps:
        parts.append('<div class="mt-5">')
        parts.append('<div class="mb-3 text-sm font-medium text-stone-900">资料不足</div>')
        parts.append(render_list(gaps))
        parts.append("</div>")

    if not parts:
        return render_empty_state("No work history available.")

    return "".join(parts)


def drop_columns(
    header: list[str], rows: list[list[str]], blocked_headers: set[str]
) -> tuple[list[str], list[list[str]]]:
    if not header:
        return header, rows

    keep_indexes = [index for index, cell in enumerate(header) if cell not in blocked_headers]
    filtered_header = [header[index] for index in keep_indexes]
    filtered_rows = [
        [row[index] for index in keep_indexes if index < len(row)]
        for row in rows
    ]
    return filtered_header, filtered_rows


def render_capability_cards(items: list[dict[str, object]]) -> str:
    if not items:
        return render_empty_state("No capabilities available.")

    parts: list[str] = []
    for item in items:
        parts.append('<article class="rounded-[1.75rem] border border-stone-200 bg-white p-6 shadow-sm">')
        parts.append(
            f'<h3 class="text-xl font-semibold tracking-tight text-stone-900">{item["title"]}</h3>'
        )
        if item["summary"]:
            parts.append(
                f'<p class="mt-3 text-sm leading-7 text-stone-600">{item["summary"]}</p>'
            )
        bullets = item["highlights"]
        if bullets:
            parts.append('<div class="mt-5 text-sm font-medium text-stone-900">典型表现</div>')
            parts.append(f'<div class="mt-3">{render_list(bullets)}</div>')
        public_notes = item["public_notes"]
        if public_notes:
            parts.append(
                '<div class="mt-5 rounded-3xl bg-stone-50 px-4 py-4 text-sm leading-7 text-stone-600">'
                '<div class="mb-2 font-medium text-stone-900">可对外表述</div>'
                f'{render_list(public_notes)}'
                "</div>"
            )
        parts.append("</article>")
    return "".join(parts)


def render_project_cards(items: list[dict[str, object]]) -> str:
    if not items:
        return render_empty_state("No projects available.")

    parts: list[str] = []
    for item in items:
        capability_chips = "".join(
            f'<span class="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-800">{cap}</span>'
            for cap in item["capabilities"]
        )
        parts.append('<article class="rounded-[1.75rem] border border-stone-200 bg-white p-6 shadow-sm">')
        parts.append(
            f'<h3 class="text-xl font-semibold tracking-tight text-stone-900">{item["title"]}</h3>'
        )
        if item["definition"]:
            parts.append(
                f'<p class="mt-3 text-sm leading-7 text-stone-600">{item["definition"]}</p>'
            )
        if item["highlights"]:
            parts.append('<div class="mt-5 text-sm font-medium text-stone-900">项目亮点</div>')
            parts.append(f'<div class="mt-3">{render_list(item["highlights"])}</div>')
        if capability_chips:
            parts.append('<div class="mt-5 flex flex-wrap gap-2">')
            parts.append(capability_chips)
            parts.append("</div>")
        parts.append("</article>")
    return "".join(parts)


def normalize_capability_label(title: str) -> str:
    clean = html.unescape(title)
    if clean.startswith("能力-"):
        clean = clean[3:]
    return html.escape(clean)


def normalize_project_label(title: str) -> str:
    clean = html.unescape(title)
    if clean.startswith("项目-"):
        clean = clean[3:]
    return html.escape(clean)


def confidence_to_score(label: str) -> int:
    mapping = {
        "高": 90,
        "中高": 78,
        "中": 65,
        "中低": 52,
        "低": 38,
    }
    return mapping.get(html.unescape(label), 60)


def parse_capability_metrics(capability_map_doc: MarkdownDoc | None) -> list[dict[str, str | int]]:
    if not capability_map_doc:
        return []

    header, rows = parse_markdown_table(capability_map_doc.sections.get("核心能力总览", []))
    if not header or not rows:
        return []

    metrics: list[dict[str, str | int]] = []
    for row in rows:
        if len(row) < 3:
            continue
        title = row[0]
        judgment = row[1]
        confidence = row[2]
        metrics.append(
            {
                "title": title,
                "short_title": normalize_capability_label(title),
                "judgment": judgment,
                "confidence": confidence,
                "score": confidence_to_score(confidence),
            }
        )
    return metrics


def render_capability_bars(metrics: list[dict[str, str | int]]) -> str:
    if not metrics:
        return render_empty_state("No capability metrics available.")

    parts = [
        '<div class="mb-4">',
        '<div class="text-lg font-semibold text-stone-900">能力置信度</div>',
        '<p class="mt-2 text-sm leading-7 text-stone-600">根据能力地图里的当前判断与置信度，给出一个可快速浏览的能力强度概览。</p>',
        "</div>",
        '<div class="space-y-4">',
    ]
    for metric in metrics:
        score = int(metric["score"])
        width = max(12, min(score, 100))
        parts.append('<div class="rounded-2xl bg-white p-4 shadow-sm">')
        parts.append('<div class="flex items-start justify-between gap-4">')
        parts.append(
            f'<div><div class="text-sm font-semibold text-stone-900">{metric["short_title"]}</div>'
            f'<div class="mt-1 text-xs text-stone-500">{metric["judgment"]}</div></div>'
        )
        parts.append(
            f'<div class="text-right text-sm font-medium text-stone-700">{metric["confidence"]}<div class="text-xs text-stone-400">{score}/100</div></div>'
        )
        parts.append("</div>")
        parts.append('<div class="mt-3 h-2.5 rounded-full bg-stone-200">')
        parts.append(
            f'<div class="h-2.5 rounded-full bg-stone-900" style="width: {width}%"></div>'
        )
        parts.append("</div></div>")
    parts.append("</div>")
    return "".join(parts)


def render_capability_radar(metrics: list[dict[str, str | int]]) -> str:
    if not metrics:
        return render_empty_state("No capability radar available.")

    size = 320
    center = size / 2
    radius = 112
    angles = [((2 * math.pi) / len(metrics)) * index - math.pi / 2 for index in range(len(metrics))]

    grid_levels = [0.25, 0.5, 0.75, 1.0]
    grid_polygons: list[str] = []
    axis_lines: list[str] = []
    index_badges: list[str] = []
    legend_items: list[str] = []

    for level in grid_levels:
        points = []
        for angle in angles:
            x = center + math.cos(angle) * radius * level
            y = center + math.sin(angle) * radius * level
            points.append(f"{x:.1f},{y:.1f}")
        stroke = "#d6d3d1" if level < 1.0 else "#a8a29e"
        grid_polygons.append(
            f'<polygon points="{" ".join(points)}" fill="none" stroke="{stroke}" stroke-width="1" />'
        )

    value_points = []
    for index, (metric, angle) in enumerate(zip(metrics, angles), start=1):
        outer_x = center + math.cos(angle) * radius
        outer_y = center + math.sin(angle) * radius
        axis_lines.append(
            f'<line x1="{center:.1f}" y1="{center:.1f}" x2="{outer_x:.1f}" y2="{outer_y:.1f}" stroke="#d6d3d1" stroke-width="1" />'
        )

        badge_x = center + math.cos(angle) * (radius + 18)
        badge_y = center + math.sin(angle) * (radius + 18)
        index_badges.append(
            f'<circle cx="{badge_x:.1f}" cy="{badge_y:.1f}" r="13" fill="#1c1917" />'
            f'<text x="{badge_x:.1f}" y="{badge_y + 4:.1f}" text-anchor="middle" font-size="11" fill="#fafaf9">{index:02d}</text>'
        )

        score = int(metric["score"]) / 100
        value_x = center + math.cos(angle) * radius * score
        value_y = center + math.sin(angle) * radius * score
        value_points.append(f"{value_x:.1f},{value_y:.1f}")
        legend_items.append(
            '<li class="flex items-center gap-3 rounded-2xl bg-white px-3 py-2 shadow-sm">'
            f'<span class="inline-flex h-8 w-8 items-center justify-center rounded-full bg-stone-900 text-xs font-semibold text-white">{index:02d}</span>'
            f'<div><div class="text-sm font-medium text-stone-900">{metric["short_title"]}</div>'
            f'<div class="text-xs text-stone-500">{metric["confidence"]} / {metric["judgment"]}</div></div>'
            "</li>"
        )

    svg = (
        f'<svg viewBox="0 0 {size} {size}" class="mx-auto w-full max-w-[20rem]" role="img" aria-label="能力轮廓图">'
        + "".join(grid_polygons)
        + "".join(axis_lines)
        + f'<polygon points="{" ".join(value_points)}" fill="rgba(28, 25, 23, 0.18)" stroke="#1c1917" stroke-width="2" />'
        + "".join(
            f'<circle cx="{point.split(",")[0]}" cy="{point.split(",")[1]}" r="4" fill="#1c1917" />'
            for point in value_points
        )
        + "".join(index_badges)
        + "</svg>"
    )

    return (
        '<div>'
        '<div class="text-lg font-semibold text-stone-900">能力轮廓图</div>'
        '<p class="mt-2 text-sm leading-7 text-stone-600">把核心能力的当前置信度压缩成一张静态轮廓图，便于快速看出重心分布。</p>'
        f'<div class="mt-4">{svg}</div>'
        f'<ul class="mt-4 grid gap-3 md:grid-cols-2">{"".join(legend_items)}</ul>'
        "</div>"
    )


def render_project_capability_matrix(
    project_cards: list[dict[str, object]], capability_titles: list[str]
) -> str:
    if not project_cards or not capability_titles:
        return render_empty_state("No project capability matrix available.")

    headers = "".join(
        f'<th class="px-3 py-3 text-center text-xs font-medium uppercase tracking-[0.14em] text-stone-500">{normalize_capability_label(title)}</th>'
        for title in capability_titles
    )
    body_rows: list[str] = []
    for project in project_cards:
        cells = []
        project_capabilities = set(project["capabilities"])
        for capability_title in capability_titles:
            covered = capability_title in project_capabilities
            tone = "bg-stone-900 text-white" if covered else "bg-stone-200 text-stone-400"
            marker = "●" if covered else "○"
            cells.append(
                f'<td class="px-3 py-3 text-center"><span class="inline-flex h-8 w-8 items-center justify-center rounded-full {tone}">{marker}</span></td>'
            )
        body_rows.append(
            "<tr>"
            f'<td class="whitespace-nowrap px-4 py-3 text-sm font-medium text-stone-900">{normalize_project_label(project["title"])}</td>'
            + "".join(cells)
            + "</tr>"
        )

    return (
        '<div>'
        '<div class="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">'
        '<div>'
        '<div class="text-lg font-semibold text-stone-900">项目 x 能力覆盖</div>'
        '<p class="mt-2 text-sm leading-7 text-stone-600">查看代表项目分别支撑了哪些能力主题，帮助快速理解画像的落点。</p>'
        "</div>"
        '<div class="text-xs text-stone-500">● 覆盖 · ○ 未直接体现</div>'
        "</div>"
        '<div class="mt-4 overflow-x-auto rounded-2xl border border-stone-200 bg-white">'
        '<table class="min-w-full divide-y divide-stone-200 text-left">'
        '<thead class="bg-stone-50"><tr><th class="px-4 py-3 text-xs font-medium uppercase tracking-[0.14em] text-stone-500">项目</th>'
        + headers
        + '</tr></thead><tbody class="divide-y divide-stone-100">'
        + "".join(body_rows)
        + "</tbody></table></div></div>"
    )


def load_markdown_if_exists(path: Path) -> MarkdownDoc | None:
    if not path.exists():
        return None
    return parse_markdown(path)


def build_site_payload(persona_vault_path: Path, site_title: str | None) -> dict[str, str]:
    profile_dir = persona_vault_path / "00 - Profile"
    capability_dir = persona_vault_path / "01 - Capabilities"
    project_dir = persona_vault_path / "02 - Projects"

    primary_profile = load_markdown_if_exists(profile_dir / "主要人物画像.md")
    about = primary_profile or load_markdown_if_exists(profile_dir / "About Me.md")
    current_focus = load_markdown_if_exists(profile_dir / "Current Focus.md")
    values = load_markdown_if_exists(profile_dir / "Values And Preferences.md")
    work_history = load_markdown_if_exists(profile_dir / "Work History.md")
    capability_map = load_markdown_if_exists(capability_dir / "能力地图.md")

    hero_points = extract_bullets(about.sections.get("保守摘要", [])) if about else []
    if not hero_points and primary_profile:
        hero_points.extend(extract_bullets(primary_profile.sections.get("当前角色定位", [])))
        hero_points.extend(extract_bullets(primary_profile.sections.get("当前关注主题", [])))
        hero_points.extend(extract_bullets(primary_profile.sections.get("稳定偏好与决策风格", [])))
    keyword_header, keyword_rows = (
        parse_markdown_table(about.sections.get("画像关键词", [])) if about else ([], [])
    )
    keyword_index = 0 if keyword_header else 0
    keyword_chips = [row[keyword_index] for row in keyword_rows if row]

    focus_items = (
        extract_bullets(current_focus.sections.get("近期焦点", [])) if current_focus else []
    )
    if not focus_items and primary_profile:
        focus_items = extract_bullets(primary_profile.sections.get("当前关注主题", []))
    work_style_items = []
    if current_focus:
        work_style_items.extend(extract_bullets(current_focus.sections.get("当前可见任务风格", [])))
    if values:
        work_style_items.extend(extract_bullets(values.sections.get("协作偏好", [])))
    if not work_style_items and primary_profile:
        work_style_items.extend(extract_bullets(primary_profile.sections.get("稳定偏好与决策风格", [])))

    value_cards = parse_preference_cards(values.sections.get("核心偏好", [])) if values else []

    work_note = extract_blockquote(work_history.sections.get("可见工作轨迹", [])) if work_history else ""
    work_table_header, work_table_rows = (
        parse_markdown_table(work_history.sections.get("可见工作轨迹", []))
        if work_history
        else ([], [])
    )
    work_table_header, work_table_rows = drop_columns(
        work_table_header, work_table_rows, {"证据"}
    )
    work_gaps = extract_bullets(work_history.sections.get("资料不足", [])) if work_history else []
    capability_metrics = parse_capability_metrics(capability_map)

    capability_cards: list[dict[str, object]] = []
    for path in sorted(capability_dir.glob("能力-*.md")):
        doc = parse_markdown(path)
        capability_cards.append(
            {
                "title": clean_inline(doc.title),
                "summary": extract_first_paragraph(doc.sections.get("一句话定义", [])),
                "highlights": extract_bullets(doc.sections.get("典型表现", [])),
                "public_notes": extract_bullets(doc.sections.get("可对外表述", [])),
            }
        )

    project_cards: list[dict[str, object]] = []
    for path in sorted(project_dir.glob("项目-*.md")):
        doc = parse_markdown(path)
        highlights = extract_bullets(doc.sections.get("可见内容", []))
        if not highlights:
            highlights = extract_bullets(doc.sections.get("项目特征", []))
        project_cards.append(
            {
                "title": clean_inline(doc.title),
                "definition": extract_first_paragraph(doc.sections.get("项目定义", [])),
                "highlights": highlights,
                "capabilities": [
                    item
                    for item in extract_bullets(doc.sections.get("该项目体现的能力", []))
                    if item
                ],
            }
        )

    page_title = clean_inline(site_title or (about.title if about else "Persona Profile"))
    capability_titles_for_matrix = [str(metric["title"]) for metric in capability_metrics] or [
        str(card["title"]) for card in capability_cards
    ]
    obsidian_home_url = (
        f"obsidian://open?vault={quote(persona_vault_path.name)}&file={quote('Home.md')}"
    )

    return {
        "SITE_TITLE": page_title,
        "PAGE_TITLE": page_title,
        "GENERATED_AT": html.escape(datetime.now().strftime("%Y-%m-%d %H:%M")),
        "OBSIDIAN_HOME_URL": html.escape(obsidian_home_url),
        "HERO_POINTS": render_list(hero_points, tone="dark"),
        "KEYWORD_CHIPS": render_keyword_chips(keyword_chips),
        "CURRENT_FOCUS": render_list(focus_items),
        "WORK_STYLE": render_list(work_style_items),
        "VALUE_CARDS": render_value_cards(value_cards),
        "WORK_HISTORY": render_work_history(work_note, work_table_header, work_table_rows, work_gaps),
        "CAPABILITY_RADAR": render_capability_radar(capability_metrics),
        "CAPABILITY_BARS": render_capability_bars(capability_metrics),
        "PROJECT_CAPABILITY_MATRIX": render_project_capability_matrix(
            project_cards, capability_titles_for_matrix
        ),
        "CAPABILITY_CARDS": render_capability_cards(capability_cards),
        "PROJECT_CARDS": render_project_cards(project_cards),
    }


def render_template(template: str, payload: dict[str, str]) -> str:
    rendered = template
    for key, value in payload.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def main() -> int:
    args = parse_args()
    persona_vault_path = Path(args.persona_vault_path).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not persona_vault_path.is_dir():
        raise SystemExit(f"PersonaVault path does not exist: {persona_vault_path}")

    template_path = Path(__file__).resolve().parents[1] / "templates" / "index.template.html"
    template = template_path.read_text(encoding="utf-8")
    payload = build_site_payload(persona_vault_path, args.site_title)
    rendered_html = render_template(template, payload)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "index.html"
    output_path.write_text(rendered_html, encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
