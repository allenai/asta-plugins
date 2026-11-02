"""Run `auto-discovery` with a relaxed experiment reviewer, without modifying the installed package.

    "$(uv tool dir)/asta-autodiscovery/bin/python" -I run_relaxed.py <same arguments as auto-discovery>

It has to run on AutoDiscovery's own Python, where the `autodiscovery` package is importable.

The stock reviewer (autodiscovery/agents.py, `get_agents`) is told to fail an experiment
"if you find issues or inconsistencies in any part of the experiment pipeline", with no
severity threshold, and transitions.py allows one plan revision. An ambitious plan then fails
on unreported secondary diagnostics even when its central result is sound. This wraps
`get_agents` and swaps the reviewer's system message for one that fails only on problems
that undermine the finding itself.

Tested with asta-autodiscovery 1.0.1. It patches AutoDiscovery's internals, so it checks that
the reviewer it expects exists and stops if not.

TODO: move this into AutoDiscovery itself (a reviewer option on the CLI) and delete this script.
"""

import sys

import autodiscovery.agents as agents
import autodiscovery.run as run

RELAXED_REVIEW = (
    "You are a research scientist responsible for holistically reviewing the entire experiment pipeline, "
    "i.e., the generated code, the output, and the analysis w.r.t. the original experiment plan. "
    "Assess whether the experiment was faithfully implemented and whether the hypothesis was in fact tested. "
    "Judge the experiment on whether its central finding is sound and supported by the code and the output. "
    "Return the success status as **false** only for problems that undermine that finding: the hypothesis was "
    "not actually tested, the code does not do what the analysis claims, the results are misreported, or the "
    "method is invalid for these data. "
    "Missing secondary diagnostics, unreported robustness or sensitivity checks, and deliverables listed in the "
    "plan that go beyond what the hypothesis requires are **not** grounds for failure: note them in your feedback "
    "and return the success status as **true**. "
    "When you return **true**, provide a summary of the hypothesis, experiment results, and findings."
)

_get_agents = agents.get_agents


def get_agents(*args, **kwargs):
    built = _get_agents(*args, **kwargs)
    reviewer = built.get("experiment_reviewer")
    if reviewer is None:
        raise SystemExit(
            "run_relaxed: experiment_reviewer not in get_agents(); this AutoDiscovery version is not supported"
        )
    reviewer.update_system_message(RELAXED_REVIEW)
    return built


# run.py imports get_agents by name, so patch both the module that defines it and the one that calls it.
agents.get_agents = get_agents
run.get_agents = get_agents

if __name__ == "__main__":
    from autodiscovery.easy import cli_main

    print("experiment_reviewer: relaxed system message active", file=sys.stderr)
    cli_main(sys.argv[1:])
