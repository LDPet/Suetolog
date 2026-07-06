#!/usr/bin/env python3
"""
Создание GitHub Issues из markdown-файлов в каталоге issues/.

Prerequisites:
  - GitHub CLI 2.94+ (native issue dependencies): https://cli.github.com/
  - gh auth login
  - права на создание issues в целевом репозитории

Примеры:
  python3 scripts/create_github_issues.py --dry-run
  python3 scripts/create_github_issues.py --repo owner/Suetolog
  python3 scripts/create_github_issues.py --update-links   # body + native blocked-by
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

TICKET_ID_RE = re.compile(r"^[A-Z]+(?:-QA)?-\d+$")
TICKET_TOKEN_RE = re.compile(r"\b([A-Z]+(?:-QA)?-\d+)\b")
RANGE_RE = re.compile(r"\b([A-Z]+(?:-QA)?)-(\d+)\.\.([A-Z]+(?:-QA)?)-(\d+)\b")
MARKER_RE = re.compile(r"<!--\s*suetolog-ticket:\s*([A-Z]+(?:-QA)?-\d+)\s*-->")

EPIC_MILESTONES: dict[str, str] = {
    "APP": "EPIC-00. Проектная основа и окружение",
    "DB": "EPIC-01. Модель данных и PostgreSQL",
    "CORE": "EPIC-02. Сервисный слой",
    "TG": "EPIC-03. Telegram-бот и пользовательские сценарии",
    "AI": "EPIC-04. AI и голосовой пайплайн",
    "BG": "EPIC-05. Celery, Redis и фоновые рассылки",
    "QA": "EPIC-06. Документация",
    "DOC": "EPIC-06. Документация",
}

LABEL_COLORS: dict[str, str] = {
    "epic:APP": "1D76DB",
    "epic:DB": "5319E7",
    "epic:CORE": "0E8A16",
    "epic:TG": "006B75",
    "epic:AI": "D93F0B",
    "epic:BG": "FBCA04",
    "epic:QA": "C5DEF5",
    "epic:DOC": "BFD4F2",
    "type:qa": "FEF2C0",
    "type:dev": "EDEDED",
}


@dataclass
class IssueSpec:
    ticket_id: str
    title: str
    body: str
    source_path: Path
    epic_prefix: str
    dependencies: list[str] = field(default_factory=list)
    unresolved_dependencies: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    milestone: str | None = None


@dataclass
class CreatedIssue:
    ticket_id: str
    number: int
    url: str
    title: str


class GhError(RuntimeError):
    pass


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def discover_issue_files(issues_dir: Path) -> list[Path]:
    files: list[Path] = []

    for path in sorted(issues_dir.rglob("*.md")):
        if path.name == "README.md" and path.parent == issues_dir:
            continue
        if path.name == "README.md":
            ticket_id = path.parent.name
            if TICKET_ID_RE.match(ticket_id):
                files.append(path)
            continue
        if path.parent.parent == issues_dir and path.suffix == ".md":
            files.append(path)

    return files


def ticket_prefix(ticket_id: str) -> str:
    return ticket_id.split("-", 1)[0]


def parse_field(content: str, field_name: str) -> str | None:
    match = re.search(rf"^{re.escape(field_name)}:\s*(.+)$", content,
                      re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


def expand_ticket_range(start_id: str, end_id: str) -> list[str]:
    start_prefix, start_num = start_id.rsplit("-", 1)
    end_prefix, end_num = end_id.rsplit("-", 1)
    if start_prefix != end_prefix:
        raise ValueError(
            f"Диапазон с разными префиксами: {start_id}..{end_id}")
    width = max(len(start_num), len(end_num))
    start_i = int(start_num)
    end_i = int(end_num)
    if start_i > end_i:
        start_i, end_i = end_i, start_i
    return [
        f"{start_prefix}-{num:0{width}d}" for num in range(start_i, end_i + 1)
    ]


def parse_dependencies(raw: str | None,
                       known_tickets: set[str]) -> tuple[list[str], list[str]]:
    if not raw or raw.strip().lower() in {"нет", "—", "-", "none", "n/a"}:
        return [], []

    resolved: list[str] = []
    unresolved: list[str] = []
    seen: set[str] = set()

    def add_ticket(ticket_id: str) -> None:
        if ticket_id in seen:
            return
        seen.add(ticket_id)
        if ticket_id in known_tickets:
            resolved.append(ticket_id)
        else:
            unresolved.append(ticket_id)

    remaining = raw
    for match in RANGE_RE.finditer(raw):
        start_id = f"{match.group(1)}-{match.group(2)}"
        end_id = f"{match.group(3)}-{match.group(4)}"
        for ticket_id in expand_ticket_range(start_id, end_id):
            add_ticket(ticket_id)
        remaining = remaining.replace(match.group(0), " ")

    for token in TICKET_TOKEN_RE.findall(remaining):
        add_ticket(token)

    leftover = TICKET_TOKEN_RE.sub(" ", remaining)
    leftover = re.sub(r"[,\s]+", " ", leftover).strip(" ,.;")
    if leftover and leftover.lower() not in {"нет"}:
        unresolved.append(leftover)

    return resolved, unresolved


def load_wave_ranks(decomp_path: Path) -> dict[str, int]:
    """Порядок первого появления тикета в секции волн decomp.md (для tie-break)."""
    if not decomp_path.is_file():
        return {}

    content = decomp_path.read_text(encoding="utf-8")
    section_match = re.search(
        r"^## 4\.\s+Рекомендуемый порядок выполнения\s*$"
        r"(.*?)"
        r"(?=^## 5\.\s|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not section_match:
        return {}

    ranks: dict[str, int] = {}
    for match in TICKET_TOKEN_RE.finditer(section_match.group(1)):
        ticket_id = match.group(1)
        if ticket_id not in ranks:
            ranks[ticket_id] = len(ranks)
    return ranks


def wave_rank(ticket_id: str, wave_ranks: dict[str, int]) -> int:
    return wave_ranks.get(ticket_id, 10_000)


def topological_sort(
    specs: list[IssueSpec],
    wave_ranks: dict[str, int],
) -> list[str]:
    """
    Топологическая сортировка: зависимости идут раньше зависимых.
    При равном in-degree — меньший wave rank из decomp.md, затем ticket_id.
    """
    spec_ids = {spec.ticket_id for spec in specs}
    in_degree: dict[str, int] = {ticket_id: 0 for ticket_id in spec_ids}
    dependents: dict[str, list[str]] = {
        ticket_id: []
        for ticket_id in spec_ids
    }

    for spec in specs:
        for dep in spec.dependencies:
            if dep not in spec_ids:
                continue
            in_degree[spec.ticket_id] += 1
            dependents[dep].append(spec.ticket_id)

    ready = [
        ticket_id for ticket_id, degree in in_degree.items() if degree == 0
    ]
    ready.sort(key=lambda tid: (wave_rank(tid, wave_ranks), tid))

    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for dependent in sorted(
                dependents[current],
                key=lambda tid: (wave_rank(tid, wave_ranks), tid),
        ):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                ready.append(dependent)
        ready.sort(key=lambda tid: (wave_rank(tid, wave_ranks), tid))

    if len(order) != len(spec_ids):
        remaining = sorted(spec_ids - set(order))
        raise ValueError("Цикл или неразрешимые зависимости между тикетами: " +
                         ", ".join(remaining))

    return order


def creation_order(
    specs: list[IssueSpec],
    wave_ranks: dict[str, int],
) -> list[IssueSpec]:
    """
    Порядок создания issues для backlog при сортировке GitHub «Newest first».

    Issues list по умолчанию сортируется по дате создания (новые сверху).
    Создаём в обратном топологическом порядке: последним создаётся APP-01 и
    прочие ранние волны — они оказываются сверху списка.
    """
    spec_by_id = {spec.ticket_id: spec for spec in specs}
    topo = topological_sort(specs, wave_ranks)
    return [spec_by_id[ticket_id] for ticket_id in reversed(topo)]


def build_labels(ticket_id: str, epic_prefix: str) -> list[str]:
    labels = [
        f"ticket:{ticket_id}",
        f"epic:{epic_prefix}",
        epic_prefix,
        "type:qa" if re.search(r"-QA-\d+$", ticket_id) else "type:dev",
    ]
    deduped: list[str] = []
    for label in labels:
        if label not in deduped:
            deduped.append(label)
    return deduped


def parse_issue_file(path: Path, issues_dir: Path,
                     known_tickets: set[str]) -> IssueSpec:
    content = path.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if not title_match:
        raise ValueError(f"Не найден заголовок H1 в {path}")

    title = title_match.group(1).strip()
    ticket_id = parse_field(content, "Тег")
    if not ticket_id:
        ticket_id = path.parent.name if path.name == "README.md" else path.stem
    ticket_id = ticket_id.strip()

    if not TICKET_ID_RE.match(ticket_id):
        raise ValueError(f"Некорректный ticket id {ticket_id!r} в {path}")

    epic_prefix = ticket_prefix(ticket_id)
    rel_path = path.relative_to(repo_root()).as_posix()
    deps_raw = parse_field(content, "Зависимости")
    dependencies, unresolved = parse_dependencies(deps_raw, known_tickets)

    marker = f"<!-- suetolog-ticket: {ticket_id} -->"
    header = textwrap.dedent(f"""\
        {marker}

        > Источник: `{rel_path}`

        """)
    body = header + content.strip() + "\n"

    return IssueSpec(
        ticket_id=ticket_id,
        title=title,
        body=body,
        source_path=path,
        epic_prefix=epic_prefix,
        dependencies=dependencies,
        unresolved_dependencies=unresolved,
        labels=build_labels(ticket_id, epic_prefix),
        milestone=EPIC_MILESTONES.get(epic_prefix),
    )


def run_gh(
        args: list[str],
        *,
        repo: str | None,
        dry_run: bool,
        input_text: str | None = None
) -> subprocess.CompletedProcess[str] | None:
    cmd = ["gh", *args]
    if repo:
        cmd.extend(["--repo", repo])

    if dry_run:
        preview_parts: list[str] = []
        skip_next = False
        for index, part in enumerate(cmd):
            if skip_next:
                skip_next = False
                continue
            if part in {"--body", "-b"} and index + 1 < len(cmd):
                body_len = len(cmd[index + 1])
                preview_parts.extend([part, f"<body {body_len} chars>"])
                skip_next = True
                continue
            preview_parts.append(part)
        preview = " ".join(preview_parts)
        if input_text is not None:
            preview += f"  # stdin: <body {len(input_text)} chars>"
        print(f"[dry-run] {preview}")
        return None

    result = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise GhError(result.stderr.strip() or result.stdout.strip()
                      or "gh command failed")
    return result


def detect_repo(explicit: str | None) -> str:
    if explicit:
        return explicit
    result = subprocess.run(
        [
            "gh", "repo", "view", "--json", "nameWithOwner", "-q",
            ".nameWithOwner"
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()

    remote = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=repo_root(),
        text=True,
        capture_output=True,
        check=False,
    )
    if remote.returncode != 0 or not remote.stdout.strip():
        raise GhError(
            "Не удалось определить репозиторий. Укажите --repo owner/name "
            "или выполните gh auth login в корне git-репозитория.")

    url = remote.stdout.strip()
    match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)", url)
    if not match:
        raise GhError(f"Не удалось распарсить remote origin: {url}")
    return f"{match.group('owner')}/{match.group('repo')}"


def gh_json(args: list[str], *, repo: str, dry_run: bool) -> list[dict]:
    if dry_run:
        return []
    result = run_gh([*args, "--json", "number,title,url,labels,body"],
                    repo=repo,
                    dry_run=False)
    assert result is not None
    return json.loads(result.stdout or "[]")


def load_existing_issues(repo: str, dry_run: bool) -> dict[str, CreatedIssue]:
    if dry_run:
        return {}

    issues = gh_json(["issue", "list", "--state", "all", "--limit", "1000"],
                     repo=repo,
                     dry_run=False)
    mapping: dict[str, CreatedIssue] = {}

    for issue in issues:
        ticket_id = None
        for label in issue.get("labels", []):
            name = label.get("name", "")
            if name.startswith("ticket:"):
                ticket_id = name.split(":", 1)[1]
                break
        if not ticket_id:
            marker_match = MARKER_RE.search(issue.get("body") or "")
            if marker_match:
                ticket_id = marker_match.group(1)
        if not ticket_id:
            title_match = re.match(r"^([A-Z]+(?:-QA)?-\d+):",
                                   issue.get("title", ""))
            if title_match:
                ticket_id = title_match.group(1)
        if ticket_id and ticket_id not in mapping:
            mapping[ticket_id] = CreatedIssue(
                ticket_id=ticket_id,
                number=issue["number"],
                url=issue["url"],
                title=issue["title"],
            )
    return mapping


def ensure_label(repo: str, label: str, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] ensure label {label}")
        return

    color = LABEL_COLORS.get(label, "BFDADC")
    create = subprocess.run(
        [
            "gh",
            "label",
            "create",
            label,
            "--repo",
            repo,
            "--color",
            color,
            "--description",
            f"Suetolog label {label}",
            "--force",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if create.returncode != 0 and "already exists" not in (create.stderr
                                                           or "").lower():
        raise GhError(create.stderr.strip() or create.stdout.strip())


def ensure_milestone(repo: str, title: str, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] ensure milestone {title}")
        return

    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/milestones", "--paginate"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise GhError(result.stderr.strip() or result.stdout.strip())

    milestones = json.loads(result.stdout or "[]")
    if any(item.get("title") == title for item in milestones):
        return

    create = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{repo}/milestones",
            "-f",
            f"title={title}",
            "-f",
            "state=open",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if create.returncode != 0:
        raise GhError(create.stderr.strip() or create.stdout.strip())


def create_issue(spec: IssueSpec, repo: str, dry_run: bool) -> CreatedIssue:
    print(
        f"{'[dry-run] ' if dry_run else ''}issue {spec.ticket_id}: {spec.title}"
    )

    if dry_run:
        print(f"  labels: {', '.join(spec.labels)}")
        if spec.milestone:
            print(f"  milestone: {spec.milestone}")
        if spec.dependencies:
            print(f"  depends on: {', '.join(spec.dependencies)}")
        if spec.unresolved_dependencies:
            print(
                f"  unresolved deps: {', '.join(spec.unresolved_dependencies)}"
            )
        return CreatedIssue(
            ticket_id=spec.ticket_id,
            number=0,
            url=f"https://github.com/{repo}/issues/DRYRUN-{spec.ticket_id}",
            title=spec.title,
        )

    cmd = [
        "issue",
        "create",
        "--title",
        spec.title,
        "--body",
        spec.body,
    ]
    for label in spec.labels:
        cmd.extend(["--label", label])
    if spec.milestone:
        cmd.extend(["--milestone", spec.milestone])

    result = run_gh(cmd, repo=repo, dry_run=False)
    assert result is not None
    url = result.stdout.strip()
    number_match = re.search(r"/issues/(\d+)(?:$|[?#])", url)
    if not number_match:
        raise GhError(f"Не удалось получить номер issue из ответа gh: {url}")
    return CreatedIssue(
        ticket_id=spec.ticket_id,
        number=int(number_match.group(1)),
        url=url,
        title=spec.title,
    )


def strip_blocked_by_section(body: str) -> str:
    pattern = re.compile(
        r"\n## Blocked by\n(?:.*?\n)*?(?=\n## |\Z)",
        re.DOTALL,
    )
    return pattern.sub("\n", body).rstrip() + "\n"


def get_existing_blocked_by(
    repo: str,
    issue_number: int,
    dry_run: bool,
) -> set[int]:
    if dry_run or issue_number <= 0:
        return set()

    result = run_gh(
        ["issue", "view",
         str(issue_number), "--json", "blockedBy"],
        repo=repo,
        dry_run=False,
    )
    assert result is not None
    payload = json.loads(result.stdout or "{}")
    numbers: set[int] = set()
    for item in payload.get("blockedBy") or []:
        if isinstance(item, dict) and "number" in item:
            numbers.add(int(item["number"]))
        elif isinstance(item, int):
            numbers.add(item)
    return numbers


def add_native_blocked_by(
    spec: IssueSpec,
    issue: CreatedIssue,
    created: dict[str, CreatedIssue],
    repo: str,
    dry_run: bool,
) -> None:
    blocker_numbers: list[int] = []
    for dep in spec.dependencies:
        dep_issue = created.get(dep)
        if dep_issue and dep_issue.number:
            blocker_numbers.append(dep_issue.number)

    if not blocker_numbers:
        return

    existing = get_existing_blocked_by(repo, issue.number, dry_run)
    to_add = sorted({num for num in blocker_numbers if num not in existing})
    if not to_add:
        print(
            f"skip native blocks for {spec.ticket_id} -> #{issue.number} (already set)"
        )
        return

    blockers_csv = ",".join(str(num) for num in to_add)
    print(
        f"{'[dry-run] ' if dry_run else ''}"
        f"native blocked-by for {spec.ticket_id} -> #{issue.number}: {blockers_csv}"
    )

    if dry_run:
        run_gh(
            [
                "issue",
                "edit",
                str(issue.number),
                "--add-blocked-by",
                blockers_csv,
            ],
            repo=repo,
            dry_run=True,
        )
        return

    result = subprocess.run(
        [
            "gh",
            "issue",
            "edit",
            str(issue.number),
            "--add-blocked-by",
            blockers_csv,
            *(["--repo", repo] if repo else []),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return

    combined = f"{result.stderr}\n{result.stdout}".lower()
    if any(phrase in combined for phrase in (
            "already",
            "exists",
            "duplicate",
            "nothing to add",
    )):
        print(f"note: native blocked-by for {spec.ticket_id} already present "
              f"(gh: {(result.stderr or result.stdout).strip()})")
        return

    raise GhError(result.stderr.strip() or result.stdout.strip()
                  or "gh issue edit failed")


def apply_native_blocked_by(
    specs: list[IssueSpec],
    created: dict[str, CreatedIssue],
    repo: str,
    dry_run: bool,
) -> None:
    print("Phase: native GitHub blocked-by relationships")
    for spec in specs:
        issue = created.get(spec.ticket_id)
        if not issue:
            print(
                f"warn: issue for {spec.ticket_id} not found, skip native blocks",
                file=sys.stderr,
            )
            continue
        add_native_blocked_by(spec, issue, created, repo, dry_run)


def render_blocked_by_section(
    spec: IssueSpec,
    created: dict[str, CreatedIssue],
) -> str:
    lines = ["## Blocked by", ""]
    has_content = False

    for dep in spec.dependencies:
        issue = created.get(dep)
        if issue and issue.number:
            lines.append(f"- {dep}: #{issue.number}")
            has_content = True
        else:
            lines.append(f"- {dep}: _issue не найден_")
            has_content = True

    for dep in spec.unresolved_dependencies:
        lines.append(f"- {dep}")
        has_content = True

    if not has_content:
        return ""

    lines.append("")
    lines.append(
        "> Native GitHub **Blocked by** выставляются скриптом через "
        "`gh issue edit --add-blocked-by`. Секция ниже — дублирующий ориентир "
        "с ticket ID и номерами issues.")
    lines.append("")
    return "\n".join(lines)


def update_issue_body(
    spec: IssueSpec,
    issue: CreatedIssue,
    created: dict[str, CreatedIssue],
    repo: str,
    dry_run: bool,
) -> None:
    blocked_by = render_blocked_by_section(spec, created)
    if not blocked_by:
        return

    body = strip_blocked_by_section(spec.body)
    body = body.rstrip() + "\n\n" + blocked_by

    print(
        f"{'[dry-run] ' if dry_run else ''}update links for {spec.ticket_id} -> #{issue.number}"
    )
    run_gh(
        ["issue", "edit", str(issue.number), "--body", body],
        repo=repo,
        dry_run=dry_run,
    )


def collect_specs(issues_dir: Path) -> list[IssueSpec]:
    files = discover_issue_files(issues_dir)
    known_tickets = {
        (path.parent.name if path.name == "README.md" else path.stem)
        for path in files
    }
    return [
        parse_issue_file(path, issues_dir, known_tickets) for path in files
    ]


def print_creation_plan(
    ordered_specs: list[IssueSpec],
    wave_ranks: dict[str, int],
) -> None:
    topo = topological_sort(ordered_specs, wave_ranks)
    print(
        "Creation order (reverse topo → backlog top = earliest wave with Newest first):"
    )
    for index, spec in enumerate(ordered_specs, start=1):
        deps = ", ".join(spec.dependencies) if spec.dependencies else "—"
        print(f"  {index:3d}. {spec.ticket_id}  (depends: {deps})")
    print(f"Topological order (dependencies first): {' → '.join(topo[:8])}" +
          (" → …" if len(topo) > 8 else ""))


def ensure_metadata(repo: str, specs: Iterable[IssueSpec],
                    dry_run: bool) -> None:
    labels: set[str] = set()
    milestones: set[str] = set()
    for spec in specs:
        labels.update(spec.labels)
        if spec.milestone:
            milestones.add(spec.milestone)

    for label in sorted(labels):
        ensure_label(repo, label, dry_run)
    for milestone in sorted(milestones):
        ensure_milestone(repo, milestone, dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Создать GitHub Issues из markdown-файлов issues/.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Примеры:
              python3 scripts/create_github_issues.py --dry-run
              python3 scripts/create_github_issues.py --repo my-org/Suetolog
              python3 scripts/create_github_issues.py --update-links
              python3 scripts/create_github_issues.py --skip-native-blocks

            Порядок создания — обратная топологическая сортировка зависимостей,
            чтобы при сортировке Issues «Newest first» ранние волны были сверху.
            """),
    )
    parser.add_argument(
        "--issues-dir",
        type=Path,
        default=repo_root() / "issues",
        help="Каталог с markdown-тикетами (по умолчанию issues/)",
    )
    parser.add_argument(
        "--repo",
        help="GitHub repo в формате owner/name (по умолчанию из gh/git remote)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать действия без вызова GitHub API",
    )
    parser.add_argument(
        "--skip-milestones",
        action="store_true",
        help="Не назначать milestones",
    )
    parser.add_argument(
        "--skip-label-bootstrap",
        action="store_true",
        help="Не создавать labels/milestones заранее",
    )
    parser.add_argument(
        "--update-links",
        action="store_true",
        help=
        "Только обновить секцию Blocked by и native blocked-by у существующих issues",
    )
    parser.add_argument(
        "--skip-native-blocks",
        action="store_true",
        help="Не выставлять native GitHub blocked-by (--add-blocked-by)",
    )
    parser.add_argument(
        "--decomp",
        type=Path,
        default=repo_root() / "decomp.md",
        help="decomp.md для tie-break порядка волн (по умолчанию decomp.md)",
    )
    args = parser.parse_args()

    if not args.issues_dir.is_dir():
        print(f"Каталог не найден: {args.issues_dir}", file=sys.stderr)
        return 1

    specs = collect_specs(args.issues_dir)
    if not specs:
        print("Markdown-тикеты не найдены.", file=sys.stderr)
        return 1

    wave_ranks = load_wave_ranks(args.decomp)
    if wave_ranks:
        print(
            f"Wave ranks loaded from {args.decomp}: {len(wave_ranks)} tickets")
    else:
        print(f"Wave ranks not loaded ({args.decomp}); tie-break by ticket ID")

    try:
        ordered_specs = creation_order(specs, wave_ranks)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print_creation_plan(ordered_specs, wave_ranks)

    repo = args.repo or "OWNER/REPO"
    if not args.dry_run:
        try:
            repo = detect_repo(args.repo)
        except GhError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    if args.skip_milestones:
        for spec in specs:
            spec.milestone = None

    print(f"Repository: {repo}")
    print(f"Tickets found: {len(specs)}")

    if not args.skip_label_bootstrap:
        ensure_metadata(repo, specs, args.dry_run)

    existing = load_existing_issues(repo, args.dry_run)
    created: dict[str, CreatedIssue] = dict(existing)

    if not args.update_links:
        for spec in ordered_specs:
            if spec.ticket_id in created and created[spec.ticket_id].number:
                print(
                    f"skip existing {spec.ticket_id} -> #{created[spec.ticket_id].number}"
                )
                continue
            issue = create_issue(spec, repo, args.dry_run)
            created[spec.ticket_id] = issue

    if args.dry_run:
        for index, spec in enumerate(ordered_specs, start=1):
            issue = created.setdefault(
                spec.ticket_id,
                CreatedIssue(
                    ticket_id=spec.ticket_id,
                    number=index,
                    url=f"https://github.com/{repo}/issues/{index}",
                    title=spec.title,
                ),
            )
            if issue.number == 0:
                issue.number = index
                issue.url = f"https://github.com/{repo}/issues/{index}"

    for spec in ordered_specs:
        issue = created.get(spec.ticket_id)
        if not issue:
            print(
                f"warn: issue for {spec.ticket_id} not found, skip link update",
                file=sys.stderr)
            continue
        update_issue_body(spec, issue, created, repo, args.dry_run)

    if not args.skip_native_blocks:
        apply_native_blocked_by(ordered_specs, created, repo, args.dry_run)
    else:
        print("Skip native blocked-by (--skip-native-blocks)")

    print("Done.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GhError as exc:
        print(f"gh error: {exc}", file=sys.stderr)
        raise SystemExit(1)
