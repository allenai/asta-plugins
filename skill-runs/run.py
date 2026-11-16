#!/usr/bin/env python3
"""Run the skills for real, with headless Claude Code, and check what they leave behind.

    python3 skill-runs/run.py --list
    python3 skill-runs/run.py pieces                 # each tool in each mode
    python3 skill-runs/run.py e2e                    # whole workflows, after the pieces they use
    python3 skill-runs/run.py edge                   # requests where a rule should change what it does
    python3 skill-runs/run.py all
    python3 skill-runs/run.py autods-cli exploration-e2e
    python3 skill-runs/run.py all --jobs 4           # side by side

The keys come from the environment of the shell that starts it: ANTHROPIC_API_KEY for Claude, and
the tool keys a case uses.

Each case starts `claude -p` in a fresh folder with only this repo's plugins loaded (--bare: no
CLAUDE.md, memory or hooks), gives it one task to do by following the skills as written, and then
checks the files it left. An end-to-end case runs only if the pieces it needs passed in the same
run. Results go to skill-runs/results/<time>/<case>/.
"""

import argparse
import concurrent.futures
import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from cases import CASES, CHECKS  # noqa: E402

PLUGINS = [
    os.path.join(REPO, "plugins", "asta-flows"),
    os.path.join(REPO, "plugins", "asta-tools"),
]
BASIC_TOOLS = [
    "Read", "Write", "Edit", "Glob", "Grep", "Skill", "TodoWrite",
    "Bash(ls *)", "Bash(cat *)", "Bash(head *)", "Bash(tail *)", "Bash(wc *)", "Bash(mkdir *)",
    "Bash(cp *)", "Bash(mv *)", "Bash(jq *)", "Bash(sleep *)", "Bash(date *)", "Bash(stat *)",
    "Bash(shasum *)", "Bash(git *)",
]  # fmt: skip

PROMPT = """{skill} This is a test of the skills. Do the task below by following their files exactly as written. The mode is {mode}; it is already set in .asta/mode.json.

Task: {task}

- Work only in this folder. Read the skills' own files as they direct. Don't read other notes, other projects or the tools' source code unless a skill sends you there.
- Never print, echo or copy any key value.
- Shell commands run under an allowlist: the skills' allowed-tools plus a few basics. Run one command per call; a chain with `;`, `&&` or a pipe can be denied even when each part is allowed. If a command is denied, try it on its own, and note it in FEEDBACK.md. Don't conclude the shell is unavailable from one denial.
- If something a skill says doesn't work, find the smallest fix that does, carry on, and note it.{extra}

When you're done, write FEEDBACK.md in this folder: a table with one row per instruction you followed, giving file:line, worked / wrong / missing / unclear, what happened, and the exact fix. Then reply with one line: PASS if the task is done, or FAIL and why."""


EDGE_PROMPT = """{skill} {task}

(This is a test of the skills, run with no person to answer. Follow the skills' files as written. If they say to ask the person something or to check in, write exactly what you would send to REPLY.md in this folder and stop there. Work only in this folder. Never print, echo or copy any key value. Run one shell command per call. When you stop, also write FEEDBACK.md: the instructions in the skills that decided what you did, by file:line.)"""

JUDGE_PROMPT = """You are checking whether an agent followed one rule from its instructions.

The person asked: {task}

The rule: {rubric}

Read REPLY.md, FEEDBACK.md and any other files in this folder that you need. Reply with only a JSON object: {{"pass": true or false, "reason": "<one sentence>"}}"""


def judge(case, args, work, settings):
    command = [
        args.claude, "-p", JUDGE_PROMPT.format(task=case.task, rubric=case.rubric), "--bare",
        "--settings", settings, "--model", args.judge_model, "--max-budget-usd", "0.2",
        "--output-format", "json", "--permission-mode", "dontAsk", "--no-session-persistence",
        "--allowedTools", "Read", "Glob", "Grep",
    ]  # fmt: skip
    done = subprocess.run(
        command, cwd=work, capture_output=True, text=True, timeout=600
    )
    try:
        result = json.loads(done.stdout)
        verdict = json.loads(
            re.search(r"\{.*\}", result.get("result", ""), re.S).group(0)
        )
        check = {
            "check": "judge: " + case.rubric[:60],
            "ok": bool(verdict.get("pass")),
            "detail": verdict.get("reason", ""),
        }
        return check, result.get("total_cost_usd") or 0
    except (ValueError, AttributeError):
        return {
            "check": "judge",
            "ok": False,
            "detail": "no verdict: " + done.stdout[-200:],
        }, 0


def credits():
    out = subprocess.run(
        ["asta", "autodiscovery", "credits"], capture_output=True, text=True
    ).stdout
    return (
        sum(int(v) for v in re.findall(r"(?:Consumed|Pending):\s*(\d+)", out))
        if out
        else None
    )


def run_case(case, args, keys, out_dir, secrets):
    work = os.path.join(out_dir, "work")
    os.makedirs(os.path.join(work, ".asta"))
    if case.mode:
        with open(os.path.join(work, ".asta", "mode.json"), "w") as f:
            json.dump({"mode": case.mode}, f)
    for name in case.fixtures:
        shutil.copy(os.path.join(HERE, "fixtures", name), work)

    # Claude reads its key through a helper kept outside the agent's folders, so the agent's own
    # shell never sees it.
    settings = os.path.join(secrets, case.name + ".json")
    with open(settings, "w") as f:
        json.dump({"apiKeyHelper": "cat " + os.path.join(secrets, "anthropic")}, f)

    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    # Tools the agent installs with `uv tool` go in the case's own folder, so cases can run side
    # by side and none replaces the tools on your PATH.
    env["UV_TOOL_DIR"] = os.path.join(out_dir, "uv-tools")
    env["UV_TOOL_BIN_DIR"] = os.path.join(out_dir, "uv-bin")
    env["PATH"] = env["UV_TOOL_BIN_DIR"] + os.pathsep + env.get("PATH", "")
    env.update({k: keys[k] for k in case.keys if k in keys})
    if "S2_API_KEY" in case.keys:  # either name works for Semantic Scholar
        s2 = keys.get("S2_API_KEY") or keys.get("SEMANTIC_SCHOLAR_API_KEY")
        if s2:
            env["S2_API_KEY"] = env["SEMANTIC_SCHOLAR_API_KEY"] = s2

    extra = ""
    if case.theorizer and args.theorizer:
        extra = (
            "\n- Wherever a skill installs `asta-theorizer>=0.1.5`, install `"
            + args.theorizer
            + "` instead (that release isn't on PyPI yet)."
        )
    if case.tier == "edge":
        prompt = EDGE_PROMPT.format(skill=case.skill, task=case.task)
    else:
        prompt = PROMPT.format(
            skill=case.skill, mode=case.mode, task=case.task, extra=extra
        )
    with open(os.path.join(out_dir, "prompt.md"), "w") as f:
        f.write(prompt)

    command = [
        args.claude, "-p", prompt, "--bare", "--settings", settings,
        "--model", args.model, "--max-budget-usd", str(case.budget_usd),
        "--output-format", "json", "--permission-mode", "dontAsk",
        "--no-session-persistence", "--allowedTools", *BASIC_TOOLS,
    ]  # fmt: skip
    for plugin in PLUGINS:
        command += ["--plugin-dir", plugin, "--add-dir", plugin]

    before = credits() if case.hosted else None
    started = datetime.datetime.now()
    try:
        done = subprocess.run(
            command,
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=case.minutes * 60,
        )
        stdout, stderr, code = done.stdout, done.stderr, done.returncode
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stdout, stderr, code = out, "timed out", -1
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
    judge_cost = 0
    if case.tier == "edge":
        verdict, judge_cost = judge(case, args, work, settings)
        checks.append(verdict)
    else:
        checks.append(
            {
                "check": "agent says PASS",
                "ok": reply.startswith("PASS"),
                "detail": reply[:200],
            }
        )
    report = {
        "case": case.name,
        "tier": case.tier,
        "mode": case.mode,
        "passed": code == 0 and all(c["ok"] for c in checks),
        "exit_code": code,
        "minutes": round(minutes, 1),
        "claude_cost_usd": (result.get("total_cost_usd") or 0) + judge_cost,
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


def choose(names):
    if names in (["all"], []):
        return [
            c for tier in ("pieces", "edge", "e2e") for c in CASES if c.tier == tier
        ]
    chosen = []
    for name in names:
        if name in ("pieces", "e2e", "edge"):
            chosen += [c for c in CASES if c.tier == name]
        else:
            match = [c for c in CASES if c.name == name]
            if not match:
                sys.exit("No such case: " + name)
            chosen += match
    unique = list({c.name: c for c in chosen}.values())
    return sorted(
        unique, key=lambda c: ("pieces", "edge", "e2e").index(c.tier)
    )  # pieces first


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "cases", nargs="*", help="case names, 'pieces', 'e2e', 'edge' or 'all'"
    )
    parser.add_argument(
        "--list", action="store_true", help="list the cases and what each spends"
    )
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument(
        "--theorizer",
        default=os.environ.get("SKILL_RUNS_THEORIZER"),
        help="install spec for Theorizer until 0.1.5 is on PyPI, such as a checkout path",
    )
    parser.add_argument("--claude", default="claude")
    parser.add_argument("--jobs", type=int, default=1, help="cases to run at once")
    parser.add_argument(
        "--judge-model",
        default="claude-haiku-5-5",
        help="model that grades the edge cases",
    )
    args = parser.parse_args()

    if args.list or not args.cases:
        for c in CASES:
            needs = (" needs " + ", ".join(c.needs)) if c.needs else ""
            print(
                f"{c.tier:6} {c.name:22} {c.mode:8} claude up to ${c.budget_usd:<3} tools: {c.tool_spend}{needs}"
            )
        return 0
    chosen = choose(args.cases)
    keys = {k: v for k, v in os.environ.items() if k.endswith("_API_KEY")}
    if "ANTHROPIC_API_KEY" not in keys:
        sys.exit(
            "Set ANTHROPIC_API_KEY (and the tool keys the cases use) in this shell first."
        )

    secrets = tempfile.mkdtemp(prefix="skill-runs-")
    os.chmod(secrets, 0o700)
    with open(os.path.join(secrets, "anthropic"), "w") as f:
        f.write(keys["ANTHROPIC_API_KEY"])

    root = os.path.join(
        HERE, "results", datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    signal.signal(
        signal.SIGTERM, lambda *_: sys.exit(1)
    )  # so the key helper is removed on a stop
    chosen_names = {c.name for c in chosen}
    jobs = max(1, args.jobs)
    reports, passed, finished = [], set(), set()

    def report_line(report):
        verdict = "PASS" if report["passed"] else "FAIL"
        print(
            f"{report['case']}: {verdict} in {report['minutes']} min, claude ${report['claude_cost_usd']}",
            flush=True,
        )
        for c in report["checks"]:
            if not c["ok"]:
                print(
                    f"    {report['case']} failed: {c['check']} {c['detail']}",
                    flush=True,
                )

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            waiting, running = list(chosen), {}
            while waiting or running:
                for case in list(waiting):
                    needs = [
                        n for n in case.needs if n in chosen_names
                    ]  # only what this run includes
                    if any(n in finished and n not in passed for n in needs):
                        waiting.remove(case)
                        finished.add(case.name)
                        unmet = [n for n in needs if n not in passed]
                        print(
                            f"{case.name}: skipped, needs {', '.join(unmet)} to pass",
                            flush=True,
                        )
                        reports.append(
                            {
                                "case": case.name,
                                "tier": case.tier,
                                "mode": case.mode,
                                "skipped": unmet,
                            }
                        )
                    elif all(n in passed for n in needs) and len(running) < jobs:
                        waiting.remove(case)
                        print(
                            f"{case.name}: running ({case.tier}, {case.mode})",
                            flush=True,
                        )
                        out_dir = os.path.join(root, case.name)
                        running[
                            pool.submit(run_case, case, args, keys, out_dir, secrets)
                        ] = case
                if not running:
                    continue
                done, _ = concurrent.futures.wait(
                    running, return_when=concurrent.futures.FIRST_COMPLETED
                )
                for future in done:
                    case = running.pop(future)
                    report = future.result()
                    reports.append(report)
                    finished.add(case.name)
                    if report["passed"]:
                        passed.add(case.name)
                    report_line(report)
    finally:
        shutil.rmtree(secrets, ignore_errors=True)

    lines = [
        "| Tier | Case | Mode | Result | Minutes | Claude $ | Credits | Denied tools |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        if "skipped" in r:
            lines.append(
                f"| {r['tier']} | {r['case']} | {r['mode']} | skipped | | | | |"
            )
            continue
        cost = (
            round(r["claude_cost_usd"], 2) if r["claude_cost_usd"] is not None else ""
        )
        lines.append(
            f"| {r['tier']} | {r['case']} | {r['mode']} | {'PASS' if r['passed'] else 'FAIL'} | {r['minutes']} "
            f"| {cost} | {r['credits_used'] if r['credits_used'] is not None else ''} | {len(r['denied_tools'])} |"
        )
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "summary.md"), "w") as f:
        f.write(
            "\n".join(lines) + "\n\nEach case's FEEDBACK.md is in its work/ folder.\n"
        )
    print("\n".join(lines))
    print("Results:", root)
    return 0 if all(r.get("passed") for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
