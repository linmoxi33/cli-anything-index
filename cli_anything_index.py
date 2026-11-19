#!/usr/bin/env python3
"""Offline capability index for a CLI-Anything checkout.

Reads only files on disk (never the network, never imports the harnesses) and
compiles every ``<software>/agent-harness`` into one machine-readable record:
skill frontmatter, CLI source, parser commands, flags and the commands the
skill documentation claims exist.

Exit codes: 0 ok, 1 findings detected (``check``), 2 usage/input error.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
BINARY_RE = re.compile(r"^\s*(?:\$\s+)?([A-Za-z0-9_.-]+)\s+(.+)$")
FLAG_RE = re.compile(r"^-{1,2}[A-Za-z]")
BOOL_FLAGS = {"--json", "--verbose", "-v", "--quiet", "-q", "--overwrite", "--force",
              "--help", "-h", "--dry-run", "--yes", "-y", "--debug"}


class InputError(Exception):
    """Raised when --root does not look like a CLI-Anything checkout."""


def _parse_frontmatter(text: str) -> dict:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    out = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key in ("name", "description") and value:
            out[key] = value.strip("'\"")
    return out


def _docstring_commands(source: str) -> set[str]:
    """Commands documented in SKILL.md lines that invoke a *-cli binary.

    Flags that are known booleans are skipped without consuming a value; every
    other flag consumes the next token (so ``--project scene.json scene info``
    yields ``scene``, not ``scene.json``). This is a documented heuristic:
    SKILL.md is prose, not a grammar.
    """
    commands: set[str] = set()
    for line in source.splitlines():
        match = BINARY_RE.match(line)
        if not match:
            continue
        binary, rest = match.group(1), match.group(2).strip()
        if not (binary.startswith("cli-anything") or binary.endswith(("-cli", "_cli"))):
            continue
        tokens = rest.split()
        args = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if FLAG_RE.match(token):
                value_attached = "=" in token
                is_bool = token.split("=")[0] in BOOL_FLAGS
                i += 1
                if not value_attached and not is_bool and i < len(tokens) and not FLAG_RE.match(tokens[i]):
                    i += 1
                continue
            args.append(token)
            i += 1
        for token in args:
            clean = token.strip("\"'`")
            if re.match(r"^[a-z][a-z0-9-]*$", clean):
                commands.add(clean)
                break
    return commands


def _call_name(node: ast.AST) -> str:
    func = node.func if isinstance(node, ast.Call) else None
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _decorator_names(func: ast.AST) -> list[str]:
    names = []
    for dec in getattr(func, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute):
            names.append(target.attr)
        elif isinstance(target, ast.Name):
            names.append(target.id)
    return names


def parse_cli_source(source: str) -> dict:
    """Extract commands/flags from a harness CLI module without importing it."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"parse_error": str(exc), "commands": [], "flags": [], "json_flag": False,
                "framework": None}

    commands: set[str] = set()
    flags: set[str] = set()
    framework = None

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decs = _decorator_names(node)
            if any(d in ("command", "group") for d in decs):
                framework = framework or "click"
                name = node.name.replace("_", "-")
                for dec in node.decorator_list:
                    target = dec.func if isinstance(dec, ast.Call) else dec
                    attr = target.attr if isinstance(target, ast.Attribute) else ""
                    if attr in ("command", "group") and isinstance(dec, ast.Call) and dec.args:
                        first = _const_str(dec.args[0])
                        if first:
                            name = first
                if name not in ("cli", "main"):
                    commands.add(name)
        elif isinstance(node, ast.Call):
            attr = _call_name(node)
            if attr == "add_parser":
                framework = framework or "argparse"
                name = _const_str(node.args[0]) if node.args else None
                for kw in node.keywords:
                    if kw.arg == "name" and _const_str(kw.value):
                        name = _const_str(kw.value)
                if name:
                    commands.add(name)
            elif attr in ("add_argument", "option", "argument"):
                if attr != "add_argument":
                    framework = framework or "click"
                for arg in node.args:
                    value = _const_str(arg)
                    if value and value.startswith("-") and value not in flags:
                        flags.add(value.split("/")[0])
                    elif value and value.startswith("--") and "/" in value:
                        flags.add(value.split("/")[0])

    if framework is None:
        if "click" in source:
            framework = "click"
        elif "argparse" in source:
            framework = "argparse"

    json_flag = "--json" in flags or bool(re.search(r"--json\b", source))
    return {
        "commands": sorted(commands),
        "flags": sorted(flags),
        "json_flag": json_flag,
        "framework": framework,
        "parse_error": None,
    }


def _pick(paths, prefer_suffix=None) -> Path | None:
    items = sorted(paths, key=lambda p: (len(p.parts), str(p)))
    if prefer_suffix:
        for item in items:
            if item.name.endswith(prefer_suffix):
                return item
    return items[0] if items else None


def inspect_harness(root: Path, software_dir: Path) -> dict:
    harness = software_dir / "agent-harness"
    skill = _pick(list(harness.glob("**/SKILL.md")))
    cli_file = _pick(list(harness.glob("**/*_cli.py")))
    if cli_file is None:
        cli_file = _pick(list(harness.glob("**/__main__.py")))
    entry = software_dir.name
    if skill is None and cli_file is None:
        entry = "_".join(p.name for p in [software_dir, Path("agent-harness")])

    record = {
        "software": software_dir.name,
        "path": str(harness.relative_to(root)),
        "skill_md": str(skill.relative_to(root)) if skill else None,
        "skill": {},
        "cli_source": str(cli_file.relative_to(root)) if cli_file else None,
        "commands": [],
        "flags": [],
        "json_flag": False,
        "framework": None,
        "documented_commands": [],
        "parse_error": None,
    }
    if skill is not None:
        text = skill.read_text(encoding="utf-8", errors="replace")
        record["skill"] = _parse_frontmatter(text)
        record["documented_commands"] = sorted(_docstring_commands(text))
    if cli_file is not None:
        parsed = parse_cli_source(cli_file.read_text(encoding="utf-8", errors="replace"))
        record.update({
            "commands": parsed["commands"],
            "flags": parsed["flags"],
            "json_flag": parsed["json_flag"],
            "framework": parsed["framework"],
            "parse_error": parsed["parse_error"],
        })
    return record


def build_index(root: Path) -> dict:
    if not root.is_dir():
        raise InputError(f"root is not a directory: {root}")
    harnesses = [d for d in sorted(root.iterdir()) if d.is_dir() and (d / "agent-harness").is_dir()]
    if not harnesses:
        raise InputError(
            f"no <software>/agent-harness directories under {root} "
            "(pass the checkout root of HKUDS/CLI-Anything)")
    entries = [inspect_harness(root, d) for d in harnesses]
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "totals": {
            "harnesses": len(entries),
            "with_skill": sum(1 for e in entries if e["skill_md"]),
            "with_cli_source": sum(1 for e in entries if e["cli_source"]),
            "with_json_flag": sum(1 for e in entries if e["json_flag"]),
            "parser_commands": sum(len(e["commands"]) for e in entries),
            "documented_commands": sum(len(e["documented_commands"]) for e in entries),
        },
        "entries": entries,
    }


def check_index(index: dict) -> list[dict]:
    findings = []
    for entry in index["entries"]:
        name = entry["software"]
        if not entry["skill_md"]:
            findings.append({"level": "error", "rule": "no-skill", "software": name,
                             "detail": "no SKILL.md found under agent-harness"})
        elif not entry["skill"].get("name"):
            findings.append({"level": "warn", "rule": "skill-no-name", "software": name,
                             "detail": "SKILL.md frontmatter has no name field"})
        if not entry["cli_source"]:
            findings.append({"level": "error", "rule": "no-cli-source", "software": name,
                             "detail": "no *_cli.py or __main__.py found under agent-harness"})
            continue
        if entry["parse_error"]:
            findings.append({"level": "error", "rule": "cli-syntax-error", "software": name,
                             "detail": entry["parse_error"]})
            continue
        if entry["framework"] is None:
            findings.append({"level": "warn", "rule": "parser-unparsed", "software": name,
                             "detail": "no click/argparse structure detected; commands unknown"})
        elif not entry["commands"]:
            findings.append({"level": "warn", "rule": "no-parser-commands", "software": name,
                             "detail": "parser defines no discoverable commands"})
        if not entry["json_flag"]:
            findings.append({"level": "warn", "rule": "no-json-flag", "software": name,
                             "detail": "no --json flag found in CLI source"})
        parsed = set(entry["commands"])
        for doc in entry["documented_commands"]:
            if parsed and doc not in parsed and len(findings) < 500:
                findings.append({"level": "warn", "rule": "documented-not-in-parser",
                                 "software": name,
                                 "detail": f"SKILL.md documents `{doc}` but parser has no such command"})
    return findings


def summarize(index: dict, findings: list[dict] | None = None) -> str:
    t = index["totals"]
    lines = [
        f"harnesses: {t['harnesses']}  skills: {t['with_skill']}  cli sources: {t['with_cli_source']}",
        f"parser commands: {t['parser_commands']}  documented commands: {t['documented_commands']}",
        f"--json flag: {t['with_json_flag']}/{t['harnesses']}",
    ]
    if findings is not None:
        by_level = {}
        for f in findings:
            by_level[f["level"]] = by_level.get(f["level"], 0) + 1
        lines.append("findings: " + ", ".join(f"{k}={by_level[k]}" for k in sorted(by_level)) or "findings: none")
    return "\n".join(lines)


def cmd_index(args) -> int:
    index = build_index(Path(args.root))
    if args.out:
        out = Path(args.out)
        out.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(index, indent=2, sort_keys=True))
    else:
        print(summarize(index))
        for e in index["entries"]:
            print(f"  {e['software']:<24} cmds={len(e['commands']):<4} json={'yes' if e['json_flag'] else 'no ':<3} {e['skill'].get('description','')[:60]}")
    return 0


def cmd_check(args) -> int:
    index = build_index(Path(args.root))
    findings = check_index(index)
    payload = {"schema_version": SCHEMA_VERSION, "totals": index["totals"],
               "findings": findings,
               "summary": {lvl: sum(1 for f in findings if f["level"] == lvl)
                           for lvl in ("error", "warn", "info")}}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(summarize(index, findings))
        for f in findings[:args.limit]:
            print(f"  [{f['level']}] {f['software']}: {f['detail']}")
        if len(findings) > args.limit:
            print(f"  ... {len(findings) - args.limit} more")
    return 1 if payload["summary"]["error"] else 0


def cmd_query(args) -> int:
    index = build_index(Path(args.root))
    entries = index["entries"]
    if args.software:
        needle = args.software.lower()
        entries = [e for e in entries if needle in e["software"].lower()]
    if args.json_only:
        entries = [e for e in entries if e["json_flag"]]
    if not entries:
        if args.json:
            print(json.dumps({"query": {"software": args.software, "json_only": args.json_only},
                              "matches": []}, indent=2, sort_keys=True))
        else:
            print("no matches", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"matches": entries}, indent=2, sort_keys=True))
    else:
        for e in entries:
            print(f"{e['software']}: {len(e['commands'])} commands, json={'yes' if e['json_flag'] else 'no'}")
            for c in e["commands"][:args.limit]:
                print(f"  - {c}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli-anything-index",
        description="Offline capability index for HKUDS/CLI-Anything checkouts.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="compile the capability index")
    p_index.add_argument("--root", default=".")
    p_index.add_argument("--json", action="store_true")
    p_index.add_argument("--out", default=None)
    p_index.set_defaults(func=cmd_index)

    p_check = sub.add_parser("check", help="report index findings (exit 1 on errors)")
    p_check.add_argument("--root", default=".")
    p_check.add_argument("--json", action="store_true")
    p_check.add_argument("--limit", type=int, default=40)
    p_check.set_defaults(func=cmd_check)

    p_query = sub.add_parser("query", help="query indexed harnesses")
    p_query.add_argument("--root", default=".")
    p_query.add_argument("--software", default=None)
    p_query.add_argument("--json-only", action="store_true")
    p_query.add_argument("--json", action="store_true")
    p_query.add_argument("--limit", type=int, default=25)
    p_query.set_defaults(func=cmd_query)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())