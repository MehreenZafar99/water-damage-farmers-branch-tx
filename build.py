#!/usr/bin/env python3
"""Build static HTML pages from markdown content files."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

SITE = {
    "BRAND": "BranchGuard Restoration",
    "PHONE": "(214) 836-4927",
    "PHONE_TEL": "2148364927",
    "EMAIL": "hello@branchguard.com",
    "DOMAIN": "branchguard.com",
    "DATE": "September 26, 2026",
}

PHONE_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">'
    '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/>'
    "</svg>"
)
CHEVRON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true">'
    '<path d="m9 6 6 6-6 6"/></svg>'
)
COMPARE_HEADERS = {
    ("do", "don't"),
    ("covered", "not covered"),
    ("usually covered", "often not covered"),
    ("myth", "fact"),
    ("saved", "removed"),
    ("removed and thrown out", "cleaned and disinfected"),
}

UNMAPPED: list[str] = []
ALL_URLS: list[str] = []
BUILT: list[tuple[str, str]] = []


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def esc_attr(text: str) -> str:
    return html.escape(text, quote=True)


def plain_text(md: str) -> str:
    """Strip markdown to plain text for JSON-LD."""
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", md)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"\*(.+?)\*", r"\1", t)
    return t


def inline(text: str) -> str:
    """Convert inline markdown to HTML. Preserve placeholders."""
    text = esc(text)

    def link_sub(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        return f'<a href="{esc(url)}">{label}</a>'

    # Links first (already escaped content inside labels needs undo for the pattern)
    # Re-parse from original for links/bold/italic
    return inline_from_raw(text)


def inline_from_raw(raw: str) -> str:
    """Parse inline markdown from raw (unescaped) text."""
    parts: list[str] = []
    i = 0
    s = raw
    while i < len(s):
        if s.startswith("[", i):
            m = re.match(r"\[([^\]]+)\]\(([^)]+)\)", s[i:])
            if m:
                parts.append(f'<a href="{esc_attr(m.group(2))}">{esc(m.group(1))}</a>')
                i += m.end()
                continue
        if s.startswith("**", i):
            m = re.match(r"\*\*(.+?)\*\*", s[i:])
            if m:
                parts.append(f"<strong>{inline_from_raw(m.group(1))}</strong>")
                i += m.end()
                continue
        if s.startswith("*", i) and not s.startswith("**", i):
            m = re.match(r"\*(.+?)\*", s[i:])
            if m:
                parts.append(f"<em>{inline_from_raw(m.group(1))}</em>")
                i += m.end()
                continue
        # plain char
        # accumulate plain run
        j = i + 1
        while j < len(s) and s[j] not in "*[":
            j += 1
        # but allow [ that isn't a link
        parts.append(esc(s[i:j]))
        i = j
    return "".join(parts)


def parse_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise ValueError("Missing front matter")
    end = text.find("\n---", 3)
    if end < 0:
        raise ValueError("Unclosed front matter")
    fm_raw = text[3:end].strip()
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, str] = {}
    for line in fm_raw.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        meta[key.strip()] = val.strip().strip('"')
    return meta, body


def strip_duplicate_h1(body: str, h1: str) -> str:
    lines = body.splitlines()
    out = []
    skipped = False
    for line in lines:
        if not skipped and line.startswith("# ") and line[2:].strip() == h1:
            skipped = True
            continue
        out.append(line)
    return "\n".join(out).lstrip("\n")


def is_compare_header(headers: list[str]) -> bool:
    if len(headers) != 2:
        return False
    key = (headers[0].strip().lower(), headers[1].strip().lower())
    if key in COMPARE_HEADERS:
        return True
    # also match "Usually covered | Often not covered"
    left, right = key
    pairs = [
        ("do", "don't"),
        ("myth", "fact"),
        ("saved", "removed"),
        ("covered", "not covered"),
    ]
    for a, b in pairs:
        if a in left and b in right:
            return True
    if "removed" in left and "cleaned" in right:
        return True
    if "usually covered" in left or (left == "usually covered"):
        return True
    return False


def parse_table_block(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    rows = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("|"):
        raw = lines[i].strip()
        cells = [c.strip() for c in raw.strip("|").split("|")]
        # skip separator
        if all(re.match(r"^:?-+:?$", c.replace(" ", "")) for c in cells):
            i += 1
            continue
        rows.append(cells)
        i += 1
    return rows, i


def checklist_html(title: str, items: list[str], uid: str) -> str:
    n = len(items)
    lis = []
    for idx, item in enumerate(items):
        # item may have **bold** leading
        content = inline_from_raw(item)
        # If starts with <strong>...</strong>, split title/desc
        m = re.match(r"^<strong>(.*?)</strong>\s*(.*)$", content)
        if m and m.group(2):
            inner = f"<strong>{m.group(1)}</strong><span>{m.group(2)}</span>"
        elif m:
            inner = f"<strong>{m.group(1)}</strong>"
        else:
            inner = f"<strong>{content}</strong>"
        lis.append(
            f'<li><label><input type="checkbox" id="{uid}-{idx}"><div>{inner}</div></label></li>'
        )
    done = (
        '<p class="done">All set. Reach us at '
        '<a href="tel:{{PHONE}}">{{PHONE}}</a> when you are ready.</p>'
    )
    return (
        f'<div class="checklist-panel" id="{uid}">'
        f'<p class="check-title">{esc(title)}</p>'
        f'<p class="sub">Tick each item as you go.</p>'
        f'<div class="progress" aria-hidden="true"><span></span></div>'
        f'<p class="progress-label" aria-live="polite">0 of {n} done</p>'
        f'<ul class="steps-check">{"".join(lis)}</ul>{done}</div>'
    )


def services_hub_cards(rows: list[list[str]]) -> str:
    """Clickable service blocks from hub table rows."""
    cards = []
    for r in rows[1:]:
        name = r[0].strip() if r else ""
        when = r[1].strip() if len(r) > 1 else ""
        link_cell = r[2].strip() if len(r) > 2 else ""
        m = re.search(r"\]\(([^)]+)\)", link_cell) or re.search(r'href="([^"]+)"', link_cell)
        href = m.group(1) if m else "#"
        # plain name if markdown link in first cell
        m2 = re.match(r"\[([^\]]+)\]\(([^)]+)\)", name)
        if m2:
            name, href = m2.group(1), m2.group(2)
        cards.append(
            f'<a class="hub-card" href="{esc_attr(href)}">'
            f"<h3>{esc(name)}</h3>"
            f'<p>{esc(when)}</p>'
            f"{CHEVRON}</a>"
        )
    return f'<div class="hub-grid">{"".join(cards)}</div>'


def areas_hub_cards(rows: list[list[str]]) -> str:
    """Clickable neighborhood blocks from hub table rows."""
    cards = []
    for r in rows[1:]:
        name_cell = r[0].strip() if r else ""
        blurb = r[1].strip() if len(r) > 1 else ""
        m = re.match(r"\[([^\]]+)\]\(([^)]+)\)", name_cell)
        if m:
            name, href = m.group(1), m.group(2)
        else:
            name, href = name_cell, "#"
        cards.append(
            f'<a class="hub-card hub-card-area" href="{esc_attr(href)}">'
            f"<h3>{esc(name)}</h3>"
            f"<p>{esc(blurb)}</p>"
            f"{CHEVRON}</a>"
        )
    return f'<div class="hub-grid">{"".join(cards)}</div>'


def table_html(
    rows: list[list[str]],
    caption: str | None = None,
    *,
    page_type: str = "",
) -> str:
    if not rows:
        return ""
    headers = rows[0]
    body_rows = rows[1:]
    header_l = [h.strip().lower() for h in headers]

    if page_type == "services-hub" and header_l and header_l[0] == "service":
        return services_hub_cards(rows)
    if page_type == "service-areas-hub" and header_l and "neighborhood" in header_l[0]:
        return areas_hub_cards(rows)

    if is_compare_header(headers):
        left_h, right_h = headers[0], headers[1]
        left_items = []
        right_items = []
        for r in body_rows:
            left_items.append(f"<li>{inline_from_raw(r[0] if r else '')}</li>")
            right_items.append(
                f"<li>{inline_from_raw(r[1] if len(r) > 1 else '')}</li>"
            )
        return (
            '<div class="compare">'
            f'<div class="compare-panel"><h3>{esc(left_h)}</h3><ul>{"".join(left_items)}</ul></div>'
            f'<div class="compare-panel right"><h3>{esc(right_h)}</h3><ul>{"".join(right_items)}</ul></div>'
            "</div>"
        )
    thead = "<thead><tr>" + "".join(f"<th>{inline_from_raw(h)}</th>" for h in headers) + "</tr></thead>"
    tbody_parts = []
    for r in body_rows:
        while len(r) < len(headers):
            r.append("")
        cells = "".join(f"<td>{inline_from_raw(c)}</td>" for c in r[: len(headers)])
        tbody_parts.append(f"<tr>{cells}</tr>")
    cap = f'<p class="table-caption">{esc(caption)}</p>' if caption else ""
    return f'{cap}<div class="table-wrap"><table>{thead}<tbody>{"".join(tbody_parts)}</tbody></table></div>'


def steps_html(items: list[str]) -> str:
    lis = []
    for item in items:
        # **Title.** rest OR plain
        m = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", item)
        if m:
            rest = m.group(2).strip()
            body = f'<span class="step-body">{inline_from_raw(rest)}</span>' if rest else ""
            lis.append(f"<li><strong>{esc(m.group(1))}</strong>{body}</li>")
        else:
            lis.append(f"<li><span class=\"step-body\">{inline_from_raw(item)}</span></li>")
    return f'<ol class="steps-light">{"".join(lis)}</ol>'


def related_list_html(items: list[tuple[str, str]]) -> str:
    lis = []
    for label, href in items:
        lis.append(f'<li><a href="{esc(href)}">{esc(label)} {CHEVRON}</a></li>')
    return f'<ul class="related-list">{"".join(lis)}</ul>'


def faq_accordion(faqs: list[tuple[str, str]]) -> str:
    parts = []
    for q, a in faqs:
        parts.append(
            f"<details><summary>{esc(q)}</summary><p>{inline_from_raw(a)}</p></details>"
        )
    return f'<div class="faq-list">{"".join(parts)}</div>'


def faq_page_section(title: str, faqs: list[tuple[str, str]]) -> str:
    """Click-to-open Q and A strips for the dedicated FAQ page."""
    items = []
    for i, (q, a) in enumerate(faqs, 1):
        items.append(
            f'<details class="faq-strip">'
            f'<summary class="faq-q">'
            f'<span class="faq-num">{i:02d}</span>'
            f"<span class=\"faq-q-text\">{esc(q)}</span>"
            f"</summary>"
            f'<div class="faq-a"><p>{inline_from_raw(a)}</p></div>'
            f"</details>"
        )
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (
        f'<section class="faq-topic" aria-labelledby="topic-{esc_attr(slug)}">'
        f'<h2 id="topic-{esc_attr(slug)}">{esc(title)}</h2>'
        f'<div class="faq-strips">{"".join(items)}</div></section>'
    )


def is_call_line(line: str) -> bool:
    s = line.strip()
    if not s.startswith("**") or not s.endswith("**"):
        return False
    inner = s[2:-2]
    return "call {{phone}}" in inner.lower()


def is_italic_note(line: str) -> bool:
    s = line.strip()
    return s.startswith("*") and s.endswith("*") and not s.startswith("**") and s.count("*") == 2


def extract_lede(body: str) -> tuple[str, str]:
    """First non-empty paragraph after optional blank lines (skip call lines for lede)."""
    lines = body.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    # Quick answer stays in body for the highlight box; text also used as lede
    if i < len(lines) and lines[i].strip().startswith("**Quick answer:**"):
        qa = lines[i].strip()
        lede = qa[len("**Quick answer:**") :].strip()
        rest = "\n".join(lines[i:]).lstrip("\n")
        return lede, rest
    para = []
    while i < len(lines) and lines[i].strip() and not lines[i].startswith("#") and not lines[i].startswith("---"):
        if lines[i].startswith("|") or lines[i].startswith("- ") or lines[i].startswith("1."):
            break
        if is_call_line(lines[i]):
            break
        para.append(lines[i].strip())
        i += 1
        if i < len(lines) and not lines[i].strip():
            break
    lede = " ".join(para)
    rest = "\n".join(lines[i:]).lstrip("\n")
    return lede, rest


CHECKLIST_COUNTER = 0


def next_check_id() -> str:
    global CHECKLIST_COUNTER
    CHECKLIST_COUNTER += 1
    return f"check-{CHECKLIST_COUNTER}"


def render_body(
    body: str,
    *,
    page_type: str,
    collect_faq: list[tuple[str, str]],
    related_out: list[tuple[str, str]],
    nearby_out: list[tuple[str, str]],
    source_name: str,
) -> str:
    """Convert markdown body to HTML components."""
    lines = body.splitlines()
    out: list[str] = []
    i = 0
    pending_caption: str | None = None
    in_faq_section = False
    faq_group_title: str | None = None
    faq_group_items: list[tuple[str, str]] = []
    question_guide_active = False
    qg_blocks: list[tuple[str, list[str]]] = []

    def flush_faq_group():
        nonlocal faq_group_title, faq_group_items
        if faq_group_title is not None and faq_group_items:
            if page_type == "faq":
                out.append(faq_page_section(faq_group_title, faq_group_items))
            else:
                out.append(faq_accordion(faq_group_items))
            collect_faq.extend(faq_group_items)
        elif faq_group_items:
            out.append(faq_accordion(faq_group_items))
            collect_faq.extend(faq_group_items)
        faq_group_title = None
        faq_group_items = []

    def flush_question_guide():
        nonlocal question_guide_active, qg_blocks
        if not qg_blocks:
            question_guide_active = False
            return
        parts = []
        for q, answers in qg_blocks:
            lis = "".join(f"<li>{inline_from_raw(a)}</li>" for a in answers)
            parts.append(f'<div class="q-block"><h3>{esc(q)}</h3><ul>{lis}</ul></div>')
        out.append(f'<div class="question-guide">{"".join(parts)}</div>')
        qg_blocks = []
        question_guide_active = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped == "---":
            flush_question_guide()
            i += 1
            continue

        # Sample drying log caption: paragraph before table under certain headings handled via pending
        if stripped.startswith("## "):
            flush_question_guide()
            flush_faq_group()
            title = stripped[3:].strip()

            # Contact: big phone block
            if page_type == "contact" and title.strip() == "Call {{PHONE}}":
                i += 1
                while i < len(lines) and not lines[i].strip():
                    i += 1
                meta_lines = []
                while i < len(lines) and lines[i].strip() and not lines[i].startswith("#") and not lines[i].startswith("---"):
                    meta_lines.append(lines[i].strip())
                    i += 1
                meta_html = "".join(
                    f'<p class="contact-meta">{inline_from_raw(m)}</p>' for m in meta_lines
                )
                out.append(
                    f'<div class="contact-phone"><a class="big-phone" href="tel:{{{{PHONE}}}}">{{{{PHONE}}}}</a>{meta_html}</div>'
                )
                continue

            # Contact: skip form section entirely (phone first)
            if page_type == "contact" and title == "Send Us a Message":
                i += 1
                while i < len(lines):
                    s = lines[i].strip()
                    if s.startswith("## "):
                        break
                    i += 1
                continue

            in_faq_section = title.lower() in (
                "frequently asked questions",
                "questions farmers branch callers ask",
            ) or title.lower().startswith("frequently asked")
            # FAQ hub groups
            if page_type == "faq":
                # Each ## is a group (except we already skipped h1)
                faq_group_title = title
                faq_group_items = []
                in_faq_section = True
                i += 1
                continue
            if in_faq_section or title.lower() == "frequently asked questions":
                in_faq_section = True
                out.append(f"<h2>{esc(title)}</h2>")
                i += 1
                continue
            # Related Services / Nearby
            if title.lower() in ("related services",):
                # collect list then render + sidebar
                i += 1
                items = []
                while i < len(lines):
                    s = lines[i].strip()
                    if not s:
                        i += 1
                        if items:
                            break
                        continue
                    if s.startswith("---") or s.startswith("## "):
                        break
                    m = re.match(r"^- \[([^\]]+)\]\(([^)]+)\)", s)
                    if m:
                        items.append((m.group(1), m.group(2)))
                        i += 1
                        continue
                    break
                related_out.extend(items)
                out.append(f"<h2>{esc(title)}</h2>")
                out.append(related_list_html(items))
                continue
            if title.lower() in (
                "other farmers branch neighborhoods we serve",
                "nearby neighborhoods",
            ):
                i += 1
                items = []
                while i < len(lines):
                    s = lines[i].strip()
                    if not s:
                        i += 1
                        if items:
                            break
                        continue
                    if s.startswith("---") or s.startswith("## "):
                        break
                    m = re.match(r"^- \[([^\]]+)\]\(([^)]+)\)", s)
                    if m:
                        items.append((m.group(1), m.group(2)))
                        i += 1
                        continue
                    break
                nearby_out.extend(items)
                out.append(f"<h2>{esc(title)}</h2>")
                out.append(related_list_html(items))
                continue
            # Question guide section (stacked Q and A blocks)
            is_qguide = ("?" in title) and any(
                k in title.lower()
                for k in ("how serious", "how bad", "which", "what kind", "is your")
            )
            if is_qguide:
                out.append(f"<h2>{esc(title)}</h2>")
                i += 1
                while i < len(lines) and not lines[i].strip():
                    i += 1
                while i < len(lines) and lines[i].strip() and not lines[i].startswith("**") and not lines[i].startswith("#") and not lines[i].startswith("---") and not lines[i].startswith("|") and not lines[i].startswith("- ") and not re.match(r"^\d+\.", lines[i].strip()):
                    out.append(f"<p>{inline_from_raw(lines[i].strip())}</p>")
                    i += 1
                # Collect all question blocks until next ##
                blocks = []
                while i < len(lines):
                    s = lines[i].strip()
                    if s.startswith("## ") or s.startswith("---"):
                        break
                    if not s:
                        i += 1
                        continue
                    if s.startswith("**") and s.endswith("**") and "?" in s:
                        q = s[2:-2]
                        i += 1
                        answers = []
                        while i < len(lines) and not lines[i].strip():
                            i += 1
                        while i < len(lines) and lines[i].strip().startswith("- "):
                            answers.append(lines[i].strip()[2:].strip())
                            i += 1
                        blocks.append((q, answers))
                        continue
                    break
                if blocks:
                    parts = []
                    for q, answers in blocks:
                        lis = "".join(f"<li>{inline_from_raw(a)}</li>" for a in answers)
                        parts.append(f'<div class="q-block"><h3>{esc(q)}</h3><ul>{lis}</ul></div>')
                    out.append(f'<div class="question-guide">{"".join(parts)}</div>')
                continue
            # Checklist section if next content is checkboxes
            out.append(f"<h2>{esc(title)}</h2>")
            # Sample drying log: set caption from following paragraph
            if "sample" in title.lower() and "log" in title.lower():
                i += 1
                # grab intro paragraph as caption context - keep as paragraph, table follows
                continue
            if "checklist" in title.lower() or title.lower().startswith("have these ready"):
                # will be handled when we see - [ ]
                i += 1
                # look ahead for checklist
                # store title for checklist
                check_title = title
                # skip blank
                while i < len(lines) and not lines[i].strip():
                    i += 1
                # optional intro
                while i < len(lines) and lines[i].strip() and not lines[i].startswith("- [ ]") and not lines[i].startswith("#") and not lines[i].startswith("---"):
                    out.append(f"<p>{inline_from_raw(lines[i].strip())}</p>")
                    i += 1
                items = []
                while i < len(lines) and lines[i].strip().startswith("- [ ]"):
                    items.append(lines[i].strip()[5:].strip())
                    i += 1
                if items:
                    out.append(checklist_html(check_title, items, next_check_id()))
                continue
            i += 1
            continue

        if stripped.startswith("### "):
            flush_question_guide()
            q = stripped[4:].strip()
            if in_faq_section or page_type == "faq":
                i += 1
                ans_lines = []
                while i < len(lines):
                    s = lines[i].strip()
                    if not s:
                        if ans_lines:
                            i += 1
                            break
                        i += 1
                        continue
                    if s.startswith("#") or s.startswith("---"):
                        break
                    ans_lines.append(s)
                    i += 1
                answer = " ".join(ans_lines)
                faq_group_items.append((q, answer))
                continue
            out.append(f"<h3>{esc(q)}</h3>")
            i += 1
            continue

        # Question guide bold questions
        if question_guide_active and stripped.startswith("**") and stripped.endswith("**") and "?" in stripped:
            q = stripped[2:-2]
            i += 1
            answers = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                answers.append(lines[i].strip()[2:].strip())
                i += 1
            qg_blocks.append((q, answers))
            continue

        if is_call_line(stripped):
            flush_question_guide()
            inner = stripped[2:-2]
            out.append(
                f'<div class="call-banner"><p>{inline_from_raw(inner)}</p>'
                f'{phone_btn()}</div>'
            )
            i += 1
            continue

        if is_italic_note(stripped):
            flush_question_guide()
            out.append(f'<p class="note-muted">{inline_from_raw(stripped[1:-1])}</p>')
            i += 1
            continue

        # Quick answer
        if stripped.startswith("**Quick answer:**"):
            flush_question_guide()
            rest = stripped[len("**Quick answer:**") :].strip()
            out.append(
                f'<div class="quick-answer"><p><strong>Quick answer:</strong> {inline_from_raw(rest)}</p></div>'
            )
            i += 1
            continue

        if stripped.startswith("|"):
            flush_question_guide()
            rows, i = parse_table_block(lines, i)
            # caption: if previous pending or recent sample text
            caption = pending_caption
            pending_caption = None
            # If last out was a paragraph that mentions "kind of record" use as caption stay as p
            out.append(table_html(rows, caption, page_type=page_type))
            continue

        # Checklist without special heading
        if stripped.startswith("- [ ]"):
            flush_question_guide()
            items = []
            while i < len(lines) and lines[i].strip().startswith("- [ ]"):
                items.append(lines[i].strip()[5:].strip())
                i += 1
            # use last h2 text if possible
            title = "Checklist"
            out.append(checklist_html(title, items, next_check_id()))
            continue

        # Numbered list
        if re.match(r"^\d+\.\s", stripped):
            flush_question_guide()
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s", lines[i].strip()):
                items.append(re.sub(r"^\d+\.\s+", "", lines[i].strip()))
                i += 1
            out.append(steps_html(items))
            continue

        # Bullet list (related already handled)
        if stripped.startswith("- "):
            flush_question_guide()
            items = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:].strip())
                i += 1
            # if all links, related style
            if all(re.match(r"^\[.+\]\(.+\)$", it) for it in items):
                parsed = []
                for it in items:
                    m = re.match(r"^\[([^\]]+)\]\(([^)]+)\)$", it)
                    parsed.append((m.group(1), m.group(2)))
                out.append(related_list_html(parsed))
            else:
                lis = "".join(f"<li>{inline_from_raw(it)}</li>" for it in items)
                out.append(f"<ul>{lis}</ul>")
            continue

        if not stripped:
            i += 1
            continue

        # Bold-only paragraphs (about page style)
        if stripped.startswith("**") and stripped.endswith("**") and stripped.count("**") == 2:
            flush_question_guide()
            out.append(f"<p><strong>{esc(stripped[2:-2])}</strong></p>")
            i += 1
            continue

        # Regular paragraph (may continue)
        flush_question_guide()
        para = [stripped]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith("#") and not lines[i].startswith("---") and not lines[i].startswith("|") and not lines[i].startswith("- ") and not re.match(r"^\d+\.", lines[i].strip()) and not lines[i].strip().startswith("- [ ]"):
            if is_call_line(lines[i].strip()) or is_italic_note(lines[i].strip()):
                break
            if lines[i].strip().startswith("**") and lines[i].strip().endswith("**"):
                break
            para.append(lines[i].strip())
            i += 1
        text = " ".join(para)
        # service-areas hub zip highlight (also shown in hero)
        if page_type == "service-areas-hub" and "75234" in text and "75244" in text:
            out.append(f"<p>{inline_from_raw(text)}</p>")
            continue
        # drying log intro as caption cue
        if "kind of record we keep" in text.lower() or "sample drying" in text.lower():
            out.append(f"<p>{inline_from_raw(text)}</p>")
            pending_caption = "Sample drying log"
            continue
        out.append(f"<p>{inline_from_raw(text)}</p>")

    flush_question_guide()
    flush_faq_group()
    return "\n".join(out)


def contact_form_html() -> str:
    return f'''<form class="contact-form" action="{{{{FORM_ENDPOINT}}}}" method="post">
  <div class="form-field">
    <label for="name">Name <span class="req">*</span></label>
    <input type="text" id="name" name="name" required autocomplete="name">
  </div>
  <div class="form-field">
    <label for="phone">Phone number <span class="req">*</span></label>
    <input type="tel" id="phone" name="phone" required autocomplete="tel">
  </div>
  <div class="form-field">
    <label for="email">Email <span class="req">*</span></label>
    <input type="email" id="email" name="email" required autocomplete="email">
  </div>
  <div class="form-field">
    <label for="address">Property address in Farmers Branch <span class="req">*</span></label>
    <input type="text" id="address" name="address" required autocomplete="street-address">
  </div>
  <div class="form-field">
    <label for="what">What happened? <span class="req">*</span></label>
    <select id="what" name="what_happened" required>
      <option value="">Select one</option>
      <option value="burst-pipe">Burst pipe</option>
      <option value="roof-leak">Roof leak</option>
      <option value="appliance-leak">Appliance leak</option>
      <option value="other">Other</option>
    </select>
  </div>
  <div class="form-field">
    <label for="when">When did it start?</label>
    <input type="text" id="when" name="when_started">
  </div>
  <div class="form-field">
    <label for="message">Message</label>
    <textarea id="message" name="message"></textarea>
  </div>
  <button class="btn btn-call" type="submit">Send Message</button>
</form>'''


def page_type_for(url: str) -> str:
    if url == "/":
        return "home"
    if url.startswith("/services/") and url != "/services/":
        return "service"
    if url == "/services/":
        return "services-hub"
    if url.startswith("/service-areas/") and url != "/service-areas/":
        return "service-area"
    if url == "/service-areas/":
        return "service-areas-hub"
    if url in ("/water-damage-restoration-cost/", "/water-damage-insurance-claims/"):
        return "cost-insurance"
    if url == "/faq/":
        return "faq"
    if url == "/contact/":
        return "contact"
    if url == "/about/":
        return "about"
    if url in ("/privacy-policy/", "/terms/"):
        return "legal"
    return "simple"


def has_sidebar(ptype: str) -> bool:
    return ptype in (
        "service",
        "service-area",
        "services-hub",
        "service-areas-hub",
        "cost-insurance",
        "faq",
        "contact",
    )


def nav_current(url: str) -> str:
    if url.startswith("/services"):
        return "services"
    if url.startswith("/service-areas"):
        return "areas"
    if url.startswith("/water-damage-restoration-cost"):
        return "cost"
    if url.startswith("/water-damage-insurance-claims"):
        return "insurance"
    if url.startswith("/faq"):
        return "faq"
    if url.startswith("/contact"):
        return "contact"
    return ""


def breadcrumbs(url: str, h1: str, ptype: str) -> list[tuple[str, str | None]]:
    crumbs = [("Home", "/")]
    if ptype == "service":
        crumbs.append(("Services", "/services/"))
        crumbs.append((h1, None))
    elif ptype == "services-hub":
        crumbs.append(("Services", None))
    elif ptype == "service-area":
        crumbs.append(("Service areas", "/service-areas/"))
        # shorten name
        name = h1.replace("Water Damage Restoration in ", "")
        crumbs.append((name, None))
    elif ptype == "service-areas-hub":
        crumbs.append(("Service areas", None))
    elif ptype == "cost-insurance":
        crumbs.append((h1.replace(" in Farmers Branch", ""), None))
    elif ptype == "faq":
        crumbs.append(("FAQ", None))
    elif ptype == "contact":
        crumbs.append(("Contact", None))
    elif ptype == "about":
        crumbs.append(("About", None))
    elif ptype == "legal":
        crumbs.append((h1, None))
    else:
        crumbs.append((h1, None))
    return crumbs


def crumbs_html(crumbs: list[tuple[str, str | None]]) -> str:
    parts = []
    for label, href in crumbs:
        if href:
            parts.append(f'<li><a href="{esc(href)}">{esc(label)}</a></li>')
        else:
            parts.append(f'<li><span aria-current="page">{esc(label)}</span></li>')
    return f'<nav aria-label="Breadcrumb"><ol class="breadcrumbs">{"".join(parts)}</ol></nav>'


def json_ld_blocks(meta: dict, ptype: str, faqs: list[tuple[str, str]], crumbs: list) -> str:
    blocks = []
    url = meta["url"]
    h1 = meta["h1"]
    # BreadcrumbList
    elements = []
    for i, (label, href) in enumerate(crumbs, 1):
        item = href if href else url
        elements.append(
            {
                "@type": "ListItem",
                "position": i,
                "name": label,
                "item": f"https://{{{{DOMAIN}}}}{item}",
            }
        )
    blocks.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": elements})

    if ptype == "service":
        blocks.append(
            {
                "@context": "https://schema.org",
                "@type": "Service",
                "name": h1,
                "areaServed": {
                    "@type": "City",
                    "name": "Farmers Branch",
                    "containedInPlace": {"@type": "State", "name": "TX"},
                },
                "provider": {
                    "@type": "HomeAndConstructionBusiness",
                    "name": "{{BRAND}}",
                    "telephone": "{{PHONE}}",
                    "url": "https://{{DOMAIN}}/",
                },
                "url": f"https://{{{{DOMAIN}}}}{url}",
            }
        )
    elif ptype == "service-area":
        place_name = h1.replace("Water Damage Restoration in ", "")
        blocks.append(
            {
                "@context": "https://schema.org",
                "@type": "HomeAndConstructionBusiness",
                "name": "{{BRAND}}",
                "telephone": "{{PHONE}}",
                "url": f"https://{{{{DOMAIN}}}}{url}",
                "areaServed": {
                    "@type": "Place",
                    "name": place_name,
                    "containedInPlace": {
                        "@type": "City",
                        "name": "Farmers Branch",
                        "containedInPlace": {"@type": "State", "name": "TX"},
                    },
                },
            }
        )

    if faqs and ptype not in ("contact", "legal"):
        blocks.append(
            {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": plain_text(q),
                        "acceptedAnswer": {"@type": "Answer", "text": plain_text(a)},
                    }
                    for q, a in faqs
                ],
            }
        )

    out = []
    for b in blocks:
        out.append(
            '<script type="application/ld+json">\n'
            + json.dumps(b, indent=2, ensure_ascii=False)
            + "\n</script>"
        )
    return "\n".join(out)


def topbar_header(current: str) -> str:
    def link(key: str, href: str, label: str) -> str:
        ac = ' aria-current="page"' if current == key else ""
        return f'<a href="{href}"{ac}>{label}</a>'

    return f'''<div class="topbar">
  <div class="wrap">
    <span class="live">Crews on call 24 hours in Farmers Branch, TX</span>
    <span class="hide-sm">Emergency line: <a href="tel:{{{{PHONE}}}}">{{{{PHONE}}}}</a></span>
  </div>
</div>

<header class="site-header">
  <div class="wrap">
    <a class="logo" href="/" aria-label="{{{{BRAND}}}} home">
      <svg viewBox="0 0 32 32" aria-hidden="true"><path d="M16 3C16 3 6 14.5 6 20.5a10 10 0 0 0 20 0C26 14.5 16 3 16 3z" fill="#5B2A5E"/><path d="M11.5 21.5a4.5 4.5 0 0 0 4.5 4.5" stroke="#E9C7DC" stroke-width="2.2" fill="none" stroke-linecap="round"/></svg>
      <span>{{{{BRAND}}}}<small>Water damage restoration, Farmers Branch</small></span>
    </a>
    <button class="menu-toggle" aria-expanded="false" aria-controls="site-nav">Menu</button>
    <nav class="nav" id="site-nav" aria-label="Main">
      {link("services", "/services/", "Services")}
      {link("areas", "/service-areas/", "Service areas")}
      {link("cost", "/water-damage-restoration-cost/", "Cost")}
      {link("insurance", "/water-damage-insurance-claims/", "Insurance")}
      {link("faq", "/faq/", "FAQ")}
      {link("contact", "/contact/", "Contact")}
      {phone_btn()}
    </nav>
  </div>
</header>'''


def final_cta_footer() -> str:
    return f'''<section class="final-cta" aria-labelledby="cta-title">
  <div class="wrap">
    <div>
      <h2 id="cta-title">Water still spreading?</h2>
      <p>Every hour counts. A crew will be on the way to your Farmers Branch property.</p>
    </div>
    {phone_btn()}
  </div>
</section>

</main>

<footer class="site-footer">
  <div class="wrap">
    <div class="footer-grid">
      <div>
        <h3>{{{{BRAND}}}}</h3>
        <p>Water damage restoration in Farmers Branch, TX 75234 and 75244.<br>Open 24 hours, 7 days a week.</p>
        <p>12801 Midway Rd, Farmers Branch, TX 75244</p>
        <p><a href="tel:{{{{PHONE}}}}">{{{{PHONE}}}}</a><br><a href="mailto:{{{{EMAIL}}}}">{{{{EMAIL}}}}</a></p>
      </div>
      <div>
        <h3>Top services</h3>
        <ul>
          <li><a href="/services/emergency-water-removal/">Emergency water removal</a></li>
          <li><a href="/services/burst-pipe-water-damage/">Burst pipes</a></li>
          <li><a href="/services/slab-leak-water-damage/">Slab leaks</a></li>
          <li><a href="/services/storm-damage-restoration/">Storm damage</a></li>
          <li><a href="/services/sewage-backup-cleanup/">Sewage backup</a></li>
          <li><a href="/services/mold-remediation/">Mold remediation</a></li>
        </ul>
      </div>
      <div>
        <h3>Neighborhoods</h3>
        <ul>
          <li><a href="/service-areas/mercer-crossing/">Mercer Crossing</a></li>
          <li><a href="/service-areas/kensington-place/">Kensington Place</a></li>
          <li><a href="/service-areas/brookhaven-estates/">Brookhaven Estates</a></li>
          <li><a href="/service-areas/valwood-park/">Valwood Park</a></li>
          <li><a href="/service-areas/">All service areas</a></li>
        </ul>
      </div>
      <div>
        <h3>Help</h3>
        <ul>
          <li><a href="/water-damage-restoration-cost/">Cost guide</a></li>
          <li><a href="/water-damage-insurance-claims/">Insurance claims</a></li>
          <li><a href="/faq/">FAQ</a></li>
          <li><a href="/about/">About</a></li>
          <li><a href="/contact/">Contact</a></li>
        </ul>
      </div>
    </div>
    <div class="footer-bottom">
      <span>&copy; <span id="year">2026</span> {{{{BRAND}}}}. Farmers Branch, Texas.</span>
      <span><a href="/privacy-policy/">Privacy policy</a> &nbsp; <a href="/terms/">Terms</a></span>
    </div>
  </div>
</footer>

<div class="call-bar"><a href="tel:{{{{PHONE}}}}">{PHONE_SVG}<span>{{{{PHONE}}}}</span> · 24/7</a></div>

<script src="/assets/js/site.js"></script>
</body>
</html>'''


def sidebar_html(ptype: str, related: list, nearby: list) -> str:
    links = related if ptype == "service" else nearby if ptype == "service-area" else related or nearby
    title = "Related services" if ptype in ("service", "services-hub", "cost-insurance", "faq", "contact") else "Nearby neighborhoods"
    if ptype == "service-area":
        title = "Nearby neighborhoods"
        links = nearby[:4] if nearby else related[:4]
    elif ptype == "service":
        title = "Related services"
        links = related
    elif ptype in ("services-hub", "service-areas-hub", "cost-insurance", "faq", "contact"):
        # default related from content if any; else a few services
        if not links:
            links = [
                ("Emergency Water Removal", "/services/emergency-water-removal/"),
                ("Burst Pipe Water Damage", "/services/burst-pipe-water-damage/"),
                ("Slab Leak Water Damage", "/services/slab-leak-water-damage/"),
                ("Storm Damage Restoration", "/services/storm-damage-restoration/"),
            ]
            title = "Related services"
        else:
            title = "Related services" if related else "Nearby neighborhoods"

    lis = "".join(
        f'<li><a href="{esc(href)}">{esc(label)} {CHEVRON}</a></li>' for label, href in links[:8]
    )
    return f'''<aside class="sidebar">
  <div class="side-call">
    <p class="open-note">Open 24/7</p>
    {phone_btn()}
  </div>
  <div class="side-related">
    <h2>{esc(title)}</h2>
    <ul class="area-list">{lis}</ul>
  </div>
</aside>'''


def sticky_cta_rail() -> str:
    """Sticky phone + free estimate rail for about, privacy, and terms."""
    return f'''<aside class="sticky-cta-rail" aria-label="Contact options">
  <p class="open-note">Open 24/7</p>
  {phone_btn()}
  <a class="btn btn-ghost btn-estimate" href="tel:{{{{PHONE}}}}">Free estimate</a>
</aside>'''


def head_html(meta: dict, jsonld: str) -> str:
    title = meta["title"]
    desc = meta["meta_description"]
    url = meta["url"]
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc_attr(desc)}">
<link rel="canonical" href="https://{{{{DOMAIN}}}}{esc_attr(url)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc_attr(title)}">
<meta property="og:description" content="{esc_attr(desc)}">
<meta property="og:url" content="https://{{{{DOMAIN}}}}{esc_attr(url)}">
<meta name="theme-color" content="#3B1D40">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><path d='M16 3C16 3 6 14.5 6 20.5a10 10 0 0 0 20 0C26 14.5 16 3 16 3z' fill='%235B2A5E'/></svg>">

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=Public+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/assets/css/site.css">
{jsonld}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
'''


def phone_btn() -> str:
    return (
        f'<a class="btn btn-call" href="tel:{{{{PHONE}}}}">'
        f"{PHONE_SVG}<span>{{{{PHONE}}}}</span></a>"
    )


def apply_site(content: str) -> str:
    # Drop "Call" immediately before the phone placeholder in copy and CTAs
    content = re.sub(r"\bCall\s+(\{\{PHONE\}\})", r"\1", content)
    content = re.sub(r"\bcall\s+(\{\{PHONE\}\})", r"\1", content)
    reps = {
        "{{BRAND}}": SITE["BRAND"],
        "{{PHONE}}": SITE["PHONE"],
        "{{EMAIL}}": SITE["EMAIL"],
        "{{DOMAIN}}": SITE["DOMAIN"],
        "{{DATE}}": SITE["DATE"],
        "{{FORM_ENDPOINT}}": "#",
    }
    for k, v in reps.items():
        content = content.replace(k, v)
    content = content.replace(f'tel:{SITE["PHONE"]}', f'tel:{SITE["PHONE_TEL"]}')
    # Catch leftover "Call (214)..." style phrases
    phone_esc = re.escape(SITE["PHONE"])
    content = re.sub(rf"\bCall\s+({phone_esc})", r"\1", content)
    content = re.sub(rf"\bcall\s+({phone_esc})", r"\1", content)
    content = content.replace("Call now", "Reach us")
    # Soften remaining UI/copy phrases that lead with Call
    content = content.replace("Have These Ready When You Call", "Have These Ready")
    content = content.replace("What Happens After You Call", "What Happens Next")
    content = content.replace("Call us any time", "Reach us any time")
    content = content.replace("Call us", "Reach us")
    content = content.replace("call us", "reach us")
    content = content.replace("Call any time", "Reach us any time")
    content = content.replace("Call and we will", "We will")
    content = content.replace("Then call us.", "Then reach us.")
    content = content.replace("Then call us", "Then reach us")
    content = content.replace("<strong>Call us</strong>", "<strong>Reach us</strong>")
    content = re.sub(
        r'\s*<p class="disclaimer">Services may be performed by independent local providers\.</p>\s*',
        "\n",
        content,
    )
    return content


def write_page(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(apply_site(content), encoding="utf-8")


def update_homepage() -> None:
    html_text = (ROOT / "index.html").read_text(encoding="utf-8")
    # Replace style block if still inline
    html_text = re.sub(
        r"<style>.*?</style>",
        '<link rel="stylesheet" href="/assets/css/site.css">',
        html_text,
        count=1,
        flags=re.S,
    )
    # Replace inline script if still present
    html_text = re.sub(
        r"<script>\n\(function \(\) \{.*?\}\)\(\);\n</script>",
        '<script src="/assets/js/site.js"></script>',
        html_text,
        count=1,
        flags=re.S,
    )
    # Phone buttons: icon + number only (drop the word Call)
    html_text = re.sub(
        r'(<a class="btn btn-call" href="tel:\{\{PHONE\}\}">\s*'
        r'<svg[^>]*>.*?</svg>)\s*Call \{\{PHONE\}\}',
        r"\1<span>{{PHONE}}</span>",
        html_text,
        flags=re.S,
    )
    html_text = re.sub(
        r'(<div class="call-bar"><a href="tel:\{\{PHONE\}\}"><svg[^>]*>.*?</svg>)Call \{\{PHONE\}\} now, 24/7',
        r"\1<span>{{PHONE}}</span> · 24/7",
        html_text,
        flags=re.S,
    )
    html_text = html_text.replace(
        "Every hour counts. Call now and a crew will be on the way to your Farmers Branch property.",
        "Every hour counts. A crew will be on the way to your Farmers Branch property.",
    )
    html_text = html_text.replace(
        "Now call <a href=\"tel:{{PHONE}}\">{{PHONE}}</a> so drying can start.",
        'Reach us at <a href="tel:{{PHONE}}">{{PHONE}}</a> so drying can start.',
    )
    html_text = re.sub(
        r'\s*<p class="disclaimer">Services may be performed by independent local providers\.</p>\s*',
        "\n",
        html_text,
    )
    # Ensure footer address
    if "12801 Midway Rd" not in html_text:
        html_text = html_text.replace(
            "<p><a href=\"tel:{{PHONE}}\">{{PHONE}}</a><br><a href=\"mailto:{{EMAIL}}\">{{EMAIL}}</a></p>",
            "<p>12801 Midway Rd, Farmers Branch, TX 75244</p>\n        <p><a href=\"tel:{{PHONE}}\">{{PHONE}}</a><br><a href=\"mailto:{{EMAIL}}\">{{EMAIL}}</a></p>",
            1,
        )
        html_text = html_text.replace(
            "<p><a href=\"tel:2148364927\">(214) 836-4927</a><br><a href=\"mailto:hello@branchguard.com\">hello@branchguard.com</a></p>",
            "<p>12801 Midway Rd, Farmers Branch, TX 75244</p>\n        <p><a href=\"tel:2148364927\">(214) 836-4927</a><br><a href=\"mailto:hello@branchguard.com\">hello@branchguard.com</a></p>",
            1,
        )
    (ROOT / "index.html").write_text(apply_site(html_text), encoding="utf-8")
    print("Updated homepage")


def update_404() -> None:
    path = ROOT / "404.html"
    if path.exists():
        path.write_text(apply_site(path.read_text(encoding="utf-8")), encoding="utf-8")


def update_sitemap_robots() -> None:
    for name in ("sitemap.xml", "robots.txt"):
        path = ROOT / name
        if path.exists():
            path.write_text(apply_site(path.read_text(encoding="utf-8")), encoding="utf-8")


def build_md_page(md_path: Path) -> None:
    global CHECKLIST_COUNTER
    CHECKLIST_COUNTER = 0
    text = md_path.read_text(encoding="utf-8")
    meta, body = parse_front_matter(text)
    url = meta["url"]
    if url == "/":
        ALL_URLS.append("/")
        BUILT.append(("Homepage (kept)", "/"))
        return

    ptype = page_type_for(url)
    body = strip_duplicate_h1(body, meta["h1"])
    lede, rest = extract_lede(body)

    faqs: list[tuple[str, str]] = []
    related: list[tuple[str, str]] = []
    nearby: list[tuple[str, str]] = []
    content_html = render_body(
        rest,
        page_type=ptype,
        collect_faq=faqs,
        related_out=related,
        nearby_out=nearby,
        source_name=md_path.name,
    )

    # Contact/legal: strip accidental FAQ
    if ptype in ("contact", "legal"):
        faqs = []

    crumbs = breadcrumbs(url, meta["h1"], ptype)
    jsonld = json_ld_blocks(meta, ptype, faqs, crumbs)
    # About has FAQ - keep. Legal no FAQ.
    if ptype == "legal":
        jsonld = json_ld_blocks(meta, ptype, [], crumbs)

    show_side = has_sidebar(ptype)
    sticky_rail = ptype in ("about", "legal")

    crumbs_mark = crumbs_html(crumbs)
    current = nav_current(url)

    hero = f'''<section class="page-hero" aria-labelledby="page-title">
  <div class="wrap">
    {crumbs_mark}
    <h1 id="page-title">{esc(meta["h1"])}</h1>
    <p class="lede">{inline_from_raw(lede)}</p>
    {"<div class=\"zips-row zips\" aria-label=\"ZIP codes served\"><span class=\"zip\">75234</span><span class=\"zip\">75244</span></div>" if ptype == "service-areas-hub" else ""}
    <div class="hero-actions">
      {phone_btn()}
    </div>
  </div>
</section>'''

    if sticky_rail:
        grid = f'''<div class="page-grid page-grid-sticky">
  <div class="content-col">
{content_html}
  </div>
  {sticky_cta_rail()}
</div>'''
    elif show_side:
        grid = f'''<div class="page-grid">
  <div class="content-col">
{content_html}
  </div>
  {sidebar_html(ptype, related, nearby)}
</div>'''
    else:
        grid = f'''<div class="page-grid single">
  <div class="content-col">
{content_html}
  </div>
</div>'''

    page = (
        head_html(meta, jsonld)
        + topbar_header(current)
        + '<main id="main">\n'
        + hero
        + f'<section class="page-layout"><div class="wrap">{grid}</div></section>\n'
        + final_cta_footer()
    )

    out_path = ROOT / url.strip("/") / "index.html" if url != "/" else ROOT / "index.html"
    # url like /about/ -> about/index.html
    rel = url.strip("/")
    out_path = ROOT / rel / "index.html"
    write_page(out_path, page)
    ALL_URLS.append(url)
    BUILT.append((meta["h1"], url))
    print(f"Built {url}")


def build_404() -> None:
    meta = {
        "title": "Page Not Found | {{BRAND}}",
        "meta_description": "The page you requested was not found. Visit our services, service areas, or contact page.",
        "url": "/404.html",
        "h1": "Page not found",
    }
    # noindex-ish canonical to 404 is odd; still set
    jsonld = ""
    content = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(meta["title"])}</title>
<meta name="description" content="{esc(meta["meta_description"])}">
<meta name="robots" content="noindex">
<meta property="og:title" content="{esc(meta["title"])}">
<meta property="og:description" content="{esc(meta["meta_description"])}">
<meta name="theme-color" content="#3B1D40">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><path d='M16 3C16 3 6 14.5 6 20.5a10 10 0 0 0 20 0C26 14.5 16 3 16 3z' fill='%235B2A5E'/></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=Public+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/assets/css/site.css">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
{topbar_header("")}
<main id="main">
<section class="error-page">
  <div class="wrap">
    <h1>Page not found</h1>
    <p class="lede">That page is not on this site. Try one of these:</p>
    <ul class="error-links">
      <li><a href="/services/">Services {CHEVRON}</a></li>
      <li><a href="/service-areas/">Service areas {CHEVRON}</a></li>
      <li><a href="/contact/">Contact {CHEVRON}</a></li>
    </ul>
  </div>
</section>
{final_cta_footer()}'''
    # final_cta_footer already closes main incorrectly - it includes </main>
    # Fix: build_404 used final_cta_footer which starts with section and closes main
    write_page(ROOT / "404.html", content)
    print("Built /404.html")


def build_sitemap_robots() -> None:
    urls = sorted(set(ALL_URLS), key=lambda u: (u != "/", u))
    items = []
    for u in urls:
        items.append(
            f"  <url>\n    <loc>https://{{{{DOMAIN}}}}{u}</loc>\n  </url>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(items)
        + "\n</urlset>\n"
    )
    (ROOT / "sitemap.xml").write_text(xml, encoding="utf-8")
    (ROOT / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\nSitemap: https://{{DOMAIN}}/sitemap.xml\n",
        encoding="utf-8",
    )
    print(f"Sitemap with {len(urls)} URLs")


def verify_links() -> list[str]:
    broken = []
    known = set(ALL_URLS)
    known.add("/404.html")
    html_files = list(ROOT.rglob("*.html"))
    for f in html_files:
        if "assets" in f.parts:
            continue
        text = f.read_text(encoding="utf-8")
        for href in re.findall(r'href="(/[^"]*)"', text):
            if href.startswith("/assets/") or href.startswith("tel:") or href.startswith("mailto:"):
                continue
            if href.startswith("#"):
                continue
            # normalize
            path = href.split("#")[0].split("?")[0]
            if path == "/404.html":
                continue
            if path.endswith(".xml") or path.endswith(".txt"):
                continue
            if path not in known:
                # check file exists
                if path.endswith(".html"):
                    if not (ROOT / path.lstrip("/")).exists():
                        broken.append(f"{f.relative_to(ROOT)} -> {path}")
                else:
                    candidate = ROOT / path.strip("/") / "index.html"
                    if path not in known and not candidate.exists():
                        broken.append(f"{f.relative_to(ROOT)} -> {path}")
    return broken


def main() -> None:
    update_homepage()
    ALL_URLS.append("/")
    md_files = sorted(ROOT.glob("*.md"))
    for md in md_files:
        if md.name.startswith("01-home"):
            continue
        build_md_page(md)
    build_404()
    build_sitemap_robots()
    update_sitemap_robots()
    broken = verify_links()
    print("\n=== BUILT PAGES ===")
    for name, url in BUILT:
        print(f"  {url}")
    print(f"\nTotal: {len(BUILT)} content pages + homepage + 404")
    if broken:
        print("\nBROKEN LINKS:")
        for b in broken:
            print(" ", b)
    else:
        print("\nNo broken internal links found.")
    print(f"\nBrand: {SITE['BRAND']} | Phone: {SITE['PHONE']}")


if __name__ == "__main__":
    main()
