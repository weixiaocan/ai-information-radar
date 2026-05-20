from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from html import unescape
from pathlib import Path
import re


@dataclass
class SiteSyncResult:
    daily_count: int
    weekly_count: int
    output_paths: list[Path]


def sync_site_content(project_root: Path, site_repo_root: Path) -> SiteSyncResult:
    reports_root = project_root / "reports"
    daily_reports = sorted((reports_root / "daily").glob("*.md"))
    weekly_reports = sorted((reports_root / "weekly").glob("*.md"))
    output_paths: list[Path] = []

    daily_content_root = site_repo_root / "src" / "content" / "daily"
    weekly_content_root = site_repo_root / "src" / "content" / "weekly"
    daily_content_root.mkdir(parents=True, exist_ok=True)
    weekly_content_root.mkdir(parents=True, exist_ok=True)

    expected_daily_paths: set[Path] = set()
    expected_weekly_paths: set[Path] = set()

    for report_path in daily_reports:
        synced_path = _sync_report(report_path, daily_content_root, "daily")
        expected_daily_paths.add(synced_path)
        output_paths.append(synced_path)
    for report_path in weekly_reports:
        synced_path = _sync_report(report_path, weekly_content_root, "weekly")
        expected_weekly_paths.add(synced_path)
        output_paths.append(synced_path)

    _prune_stale_files(daily_content_root, expected_daily_paths)
    _prune_stale_files(weekly_content_root, expected_weekly_paths)

    return SiteSyncResult(
        daily_count=len(daily_reports),
        weekly_count=len(weekly_reports),
        output_paths=output_paths,
    )


def _sync_report(report_path: Path, output_root: Path, report_type: str) -> Path:
    source_text = report_path.read_text(encoding="utf-8")
    normalized_source_text = _normalize_report_markdown(source_text, report_type)
    rendered_text = _transform_report_markdown(normalized_source_text, report_type)
    title = _extract_title(normalized_source_text, report_path.stem)
    slug = _build_slug(report_path, report_type)
    article_date = _build_article_date(report_path, report_type)
    published_date = _build_published_date(report_path, report_type)
    frontmatter = "\n".join(
        [
            "---",
            f'title: "{_escape_yaml(title)}"',
            f'date: "{article_date}"',
            f'publishedDate: "{published_date}"',
            f'type: "{report_type}"',
            f'routeSlug: "{slug}"',
            f'sourcePath: "{_escape_yaml(report_path.as_posix())}"',
            "published: true",
            "---",
            "",
        ]
    )
    output_path = output_root / f"{slug}.md"
    output_path.write_text(frontmatter + rendered_text.strip() + "\n", encoding="utf-8")
    return output_path


def _extract_title(source_text: str, fallback: str) -> str:
    for line in source_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def _build_slug(report_path: Path, report_type: str) -> str:
    stem = report_path.stem
    if report_type == "weekly":
        return stem.lower()
    return stem


def _build_article_date(report_path: Path, report_type: str) -> str:
    stem = report_path.stem
    if report_type == "daily":
        return stem
    year, week = stem.split("-W", maxsplit=1)
    return f"{year}-W{week}"


def _build_published_date(report_path: Path, report_type: str) -> str:
    stem = report_path.stem
    if report_type == "daily":
        return (date.fromisoformat(stem) + timedelta(days=1)).isoformat()
    year_str, week_str = stem.split("-W", maxsplit=1)
    sunday = date.fromisocalendar(int(year_str), int(week_str), 7)
    return (sunday + timedelta(days=1)).isoformat()


def _escape_yaml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _prune_stale_files(content_root: Path, expected_paths: set[Path]) -> None:
    for path in content_root.glob("*.md"):
        if path not in expected_paths:
            path.unlink()


def _transform_report_markdown(source_text: str, report_type: str) -> str:
    lines = source_text.splitlines()
    if report_type == "daily":
        return _transform_daily_lines(lines)
    if report_type == "weekly":
        return _transform_weekly_lines(lines)
    return source_text


def _normalize_report_markdown(source_text: str, report_type: str) -> str:
    lines = source_text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("# "):
            continue
        heading = stripped[2:].strip()
        lines[index] = line.replace(heading, _normalize_heading_text(heading, report_type), 1)
        break
    return "\n".join(lines)


def _normalize_heading_text(heading: str, report_type: str) -> str:
    if report_type == "daily":
        return re.sub(r"\bAI Radar\b", "AI Brief", heading, count=1)
    return re.sub(r"\bAI Radar\s*周报\s*·\s*", "AI Brief · ", heading, count=1)


def _transform_daily_lines(lines: list[str]) -> str:
    output: list[str] = []
    index = 0
    while index < len(lines):
        current = lines[index]
        if _looks_like_digest_triplet(lines, index):
            source_line = lines[index].strip()
            title_line = lines[index + 1].strip()
            summary_line = lines[index + 2].strip()
            output.extend(_render_entry_card(source_line, title_line, summary_line))
            index += 3
            while index < len(lines) and not lines[index].strip():
                index += 1
            continue
        output.append(current)
        index += 1
    return "\n".join(output)


def _transform_weekly_lines(lines: list[str]) -> str:
    output: list[str] = []
    index = 0
    while index < len(lines):
        current = lines[index]
        if current.strip().startswith("> "):
            quote_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("> "):
                quote_lines.append(lines[index].strip())
                index += 1
            output.extend(_render_quote_cards(quote_lines))
            continue
        if current.strip().startswith("• "):
            bullet_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("• "):
                bullet_lines.append(lines[index].strip())
                index += 1
            output.extend(_render_bullet_list(bullet_lines))
            continue
        output.append(current)
        index += 1
    return "\n".join(output)


def _looks_like_digest_triplet(lines: list[str], index: int) -> bool:
    if index + 2 >= len(lines):
        return False
    source_line = lines[index].strip()
    title_line = lines[index + 1].strip()
    summary_line = lines[index + 2].strip()
    if not source_line or not title_line or not summary_line:
        return False
    if source_line.startswith(("#", "-", ">", "<")):
        return False
    if title_line.startswith(("#", "-", ">", "<")):
        return False
    if summary_line.startswith(("#", "-", ">", "<")):
        return False
    return bool(re.fullmatch(r"\[(.+?)\]\((.+?)\)", title_line))


def _render_entry_card(source_line: str, title_line: str, summary_line: str) -> list[str]:
    source = _extract_source_label(source_line)
    title, url = _extract_link(title_line)
    return [
        '<div class="digest-entry">',
        f'  <div class="digest-source">{_escape_html(source)}</div>',
        f'  <div class="digest-title"><a href="{_escape_html(url)}">{_escape_html(title)}</a></div>',
        f'  <div class="digest-summary">{_escape_html(summary_line)}</div>',
        "</div>",
        "",
    ]


def _render_quote_cards(quote_lines: list[str]) -> list[str]:
    rendered = ['<ul class="weekly-reference-list">']
    for line in quote_lines:
        source = _extract_backticked_source(line)
        title, url = _extract_link(line)
        rendered.extend(
            [
                '  <li class="weekly-reference-item">',
                f'    <div class="digest-source">{_escape_html(source)}</div>',
                f'    <div class="digest-title"><a href="{_escape_html(url)}">{_escape_html(title)}</a></div>',
                "  </li>",
            ]
        )
    rendered.extend(["</ul>", ""])
    return rendered


def _render_bullet_list(bullet_lines: list[str]) -> list[str]:
    rendered = ['<ul class="article-bullet-list">']
    for line in bullet_lines:
        rendered.append(f'  <li>{_escape_html(line.removeprefix("• ").strip())}</li>')
    rendered.extend(["</ul>", ""])
    return rendered


def _extract_source_label(source_line: str) -> str:
    match = re.search(r"\*\*(.+?)\*\*", source_line)
    if match:
        return match.group(1).strip()
    return re.sub(r"^[^\w\u4e00-\u9fff]+", "", source_line).strip()


def _extract_backticked_source(line: str) -> str:
    match = re.search(r"`([^`]+)`", line)
    if match:
        return match.group(1).strip()
    return ""


def _extract_link(line: str) -> tuple[str, str]:
    match = re.search(r"\[(.+?)\]\((.+?)\)", line)
    if not match:
        return line, ""
    return match.group(1).strip(), match.group(2).strip()


def _escape_html(value: str) -> str:
    normalized = unescape(value)
    return (
        normalized.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
