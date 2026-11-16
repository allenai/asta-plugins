#!/usr/bin/env python3
"""Run the skills for real, with headless Claude Code, and check what they leave behind.

    python3 skill-runs/run.py --list
    python3 skill-runs/run.py autods-cli theorizer-library
    python3 skill-runs/run.py all --env-file ~/keys.env

Each case starts `claude -p` in a fresh folder with only this repo's plugins loaded (--bare: no
CLAUDE.md, memory or hooks), gives it one small task to do by following a skill as written, and
then checks the files it left. Results go to skill-runs/results/<time>/<case>/.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from cases import CASES, CHECKS  # noqa: E402

PLUGINS = [
    os.path.join(REPO, "plugins", "asta-flows"),
    os.path.join(REPO, "plugins", "asta-tools"),
]
BASIC_TOOLS = [
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "Skill",
    "TodoWrite",
    "Bash(ls *)",
    "Bash(cat *)",
    "Bash(head *)",
    "Bash(tail *)",
    "Bash(wc *)",
    "Bash(mkdir *)",
    "Bash(cp *)",
    "Bash(mv *)",
    "Bash(jq *)",
    "Bash(sleep *)",
    "Bash(date *)",
    "Bash(stat *)",
    "Bash(shasum *)",
    "Bash(git *)",
]

PROMPT = """{skill} This is a test of the skill. Do the task below by following the skill's files exactly as written. The mode is {mode}; it is already set in .asta/mode.json.

Task: {task}

- Work only in this folder. Read the skill's own files as it directs. Don't read other notes, other projects or the tools' source code unless the skill sends you there.
- Never print, echo or copy any key value.
- If something the skill says doesn't work, find the smallest fix that does, carry on, and note it.{extra}

When you're done, write FEEDBACK.md in this folder: a table with one row per instruction you followed, giving file:line, worked / wrong / missing / unclear, what happened, and the exact fix. Then reply with one line: PASS if the task is done, or FAIL and why."""


def read_env(path):
    keys = {}
    if path and os.path.exists(path):
        for line in open(path):
            m = re.match(r"\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*)\s*$", line)
            if m:
                keys[m.group(1)] = m.group(2).strip().strip("'\"")
    return keys


def credits():
    out = subprocess.run(
        ["asta", "autodiscovery", "credits"], capture_output=True, text=True
    ).stdout
    used = sum(int(v) for v in re.findall(r"(?:Consumed|Pending):\s*(\d+)", out))
    return used if out else None


def run_case(case, args, keys, out_dir):
    work = os.path.join(out_dir, "work")
    os.makedirs(os.path.join(work, ".asta"))
    with open(os.path.join(work, ".asta", "mode.json"), "w") as f:
        json.dump({"mode": case.mode}, f)
    for name in case.fixtures:
        shutil.copy(os.path.join(HERE, "fixtures", name), work)

    # Claude reads its key through a helper, so the agent's own shell never sees it.
    helper = os.path.join(out_dir, "key.sh")
    with open(helper, "w") as f:
        f.write(
            f'#!/bin/sh\nset -a\n. "{args.env_file}" >/dev/null 2>&1\nprintf %s "$ANTHROPIC_API_KEY"\n'
        )
    os.chmod(helper, 0o700)
    settings = os.path.join(out_dir, "settings.json")
    with open(settings, "w") as f:
        json.dump({"apiKeyHelper": helper}, f)

    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env.update({k: keys[k] for k in case.keys if k in keys})
    if "S2_API_KEY" in case.keys:  # either name works for Semantic Scholar
        s2 = keys.get("S2_API_KEY") or keys.get("SEMANTIC_SCHOLAR_API_KEY")
        if s2:
            env["S2_API_KEY"] = env["SEMANTIC_SCHOLAR_API_KEY"] = s2

    extra = ""
    if "theorizer" in case.name and args.theorizer:
        extra = (
            "\n- Wherever the skill installs `asta-theorizer>=0.1.5`, install `"
            + args.theorizer
            + "` instead (that release isn't on PyPI yet)."
        )
    prompt = PROMPT.format(
        skill=case.skill, mode=case.mode, task=case.task, extra=extra
    )
    with open(os.path.join(out_dir, "prompt.md"), "w") as f:
        f.write(prompt)

    command = [
        args.claude,
        "-p",
        prompt,
        "--bare",
        "--settings",
        settings,
        "--model",
        args.model,
        "--max-budget-usd",
        str(case.budget_usd),
        "--output-format",
        "json",
        "--permission-mode",
        "dontAsk",
        "--no-session-persistence",
        "--allowedTools",
        *BASIC_TOOLS,
    ]
    for plugin in PLUGINS:
        command += ["--plugin-dir", plugin]

    before = credits() if case.hosted else None
    started = datetime.datetime.now()
    try:
        done = subprocess.run(
            command,
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=args.timeout * 60,
        )
        stdout, stderr, code = done.stdout, done.stderr, done.returncode
    except subprocess.TimeoutExpired as e:
        stdout, stderr, code = (
            (e.stdout or b"").decode()
            if isinstance(e.stdout, bytes)
            else (e.stdout or ""),
            "timed out",
            -1,
        )
    minutes = (datetime.datetime.now() - started).total_seconds() / 60
    after = credits() if case.hosted else None

    with open(os.path.join(out_dir, "claude.json"), "w") as f:
        f.write(stdout)
    with open(os.path.join(out_dir, "claude.stderr"), "w") as f:
        f.write(stderr)
    try:
        result = json.loads(stdout)
    except ValueError:
        result = {}

    checks = CHECKS[case.name](work)
    checks.append(
        {
            "check": "FEEDBACK.md written",
            "ok": os.path.exists(os.path.join(work, "FEEDBACK.md")),
            "detail": "",
        }
    )
    reply = (result.get("result") or "").strip()
    checks.append(
        {
            "check": "agent says PASS",
            "ok": reply.startswith("PASS"),
            "detail": reply[:200],
        }
    )
    report = {
        "case": case.name,
        "mode": case.mode,
        "passed": code == 0 and all(c["ok"] for c in checks),
        "exit_code": code,
        "minutes": round(minutes, 1),
        "claude_cost_usd": result.get("total_cost_usd"),
        "turns": result.get("num_turns"),
        "credits_used": (after - before)
        if (before is not None and after is not None)
        else None,
        "denied_tools": [
            d.get("tool_name", "") + " " + json.dumps(d.get("tool_input", {}))[:160]
            for d in (result.get("permission_denials") or [])
        ],
        "checks": checks,
    }
    with open(os.path.join(out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2)
    return report


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("cases", nargs="*", help="case names, or 'all'")
    parser.add_argument(
        "--list", action="store_true", help="list the cases and what each spends"
    )
    parser.add_argument(
        "--env-file",
        default=os.environ.get("SKILL_RUNS_ENV_FILE"),
        help="KEY=value file with ANTHROPIC_API_KEY and the tool keys (default $SKILL_RUNS_ENV_FILE)",
    )
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument(
        "--theorizer",
        default=os.environ.get("SKILL_RUNS_THEORIZER"),
        help="install spec for Theorizer until 0.1.5 is on PyPI, such as a checkout path",
    )
    parser.add_argument("--timeout", type=int, default=60, help="minutes per case")
    parser.add_argument("--claude", default="claude")
    args = parser.parse_args()

    if args.list or not args.cases:
        for c in CASES:
            print(
                f"{c.name:18} {c.mode:8} claude up to ${c.budget_usd:<4} tools: {c.tool_spend}"
            )
        return 0
    chosen = (
        CASES if args.cases == ["all"] else [c for c in CASES if c.name in args.cases]
    )
    missing = set(args.cases) - {c.name for c in CASES} - {"all"}
    if missing:
        sys.exit("No such case: " + ", ".join(sorted(missing)))
    keys = read_env(args.env_file)
    if "ANTHROPIC_API_KEY" not in keys:
        sys.exit(
            "Give --env-file (or $SKILL_RUNS_ENV_FILE): a KEY=value file with ANTHROPIC_API_KEY."
        )
    args.env_file = os.path.abspath(os.path.expanduser(args.env_file))

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    root = os.path.join(HERE, "results", stamp)
    reports = []
    for case in chosen:
        print(f"{case.name}: running ({case.mode})", flush=True)
        report = run_case(case, args, keys, os.path.join(root, case.name))
        reports.append(report)
        cost = report["claude_cost_usd"]
        print(
            f"{case.name}: {'PASS' if report['passed'] else 'FAIL'} in {report['minutes']} min, claude ${cost if cost is not None else '?'}",
            flush=True,
        )
        for c in report["checks"]:
            if not c["ok"]:
                print(f"    failed: {c['check']} {c['detail']}")

    lines = [
        "| Case | Mode | Result | Minutes | Claude $ | Credits | Denied tools |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        lines.append(
            f"| {r['case']} | {r['mode']} | {'PASS' if r['passed'] else 'FAIL'} | {r['minutes']} | {r['claude_cost_usd']} | {r['credits_used'] if r['credits_used'] is not None else ''} | {len(r['denied_tools'])} |"
        )
    with open(os.path.join(root, "summary.md"), "w") as f:
        f.write(
            "\n".join(lines) + "\n\nEach case's FEEDBACK.md is in its work/ folder.\n"
        )
    print("\n".join(lines))
    print("Results:", root)
    return 0 if all(r["passed"] for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
