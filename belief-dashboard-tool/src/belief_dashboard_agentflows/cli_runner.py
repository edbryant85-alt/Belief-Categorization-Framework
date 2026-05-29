from __future__ import annotations

import contextlib
import io
import os
from dataclasses import dataclass
from pathlib import Path

from belief_dashboard.cli import main as belief_dashboard_main
from belief_dashboard_agentflows.policies import CommandSpec, assert_command_allowed


@dataclass(frozen=True)
class CliResult:
    command: list[str]
    return_code: int
    stdout: str
    stderr: str
    policy: CommandSpec


def run_cli_command(
    command: list[str],
    *,
    project_dir: str | Path = ".",
    config_path: str | Path = "config.yaml",
    human_confirmed: bool = False,
) -> CliResult:
    policy = assert_command_allowed(command, human_confirmed=human_confirmed)
    command_with_config = _ensure_config(command, config_path)
    stdout = io.StringIO()
    stderr = io.StringIO()
    previous_cwd = Path.cwd()
    try:
        os.chdir(project_dir)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            return_code = belief_dashboard_main(command_with_config)
    finally:
        os.chdir(previous_cwd)
    return CliResult(
        command=command_with_config,
        return_code=return_code,
        stdout=stdout.getvalue(),
        stderr=stderr.getvalue(),
        policy=policy,
    )


def _ensure_config(command: list[str], config_path: str | Path) -> list[str]:
    if "--config" in command:
        return list(command)
    return [*command, "--config", str(config_path)]
