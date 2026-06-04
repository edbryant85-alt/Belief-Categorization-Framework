from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CommandRisk(str, Enum):
    READ_ONLY = "read_only"
    INTERMEDIATE_WRITE = "intermediate_write"
    GUARDED_WRITE = "guarded_write"
    PROMOTION = "promotion"


@dataclass(frozen=True)
class CommandSpec:
    name: str
    risk: CommandRisk
    requires_human_confirmation: bool


COMMAND_POLICY: dict[str, CommandSpec] = {
    "inspect-workbook": CommandSpec("inspect-workbook", CommandRisk.READ_ONLY, False),
    "validate-queues": CommandSpec("validate-queues", CommandRisk.READ_ONLY, False),
    "validate-import": CommandSpec("validate-import", CommandRisk.READ_ONLY, False),
    "doctor": CommandSpec("doctor", CommandRisk.READ_ONLY, False),
    "operator-preflight": CommandSpec("operator-preflight", CommandRisk.READ_ONLY, False),
    "preview-workbook-export": CommandSpec("preview-workbook-export", CommandRisk.READ_ONLY, False),
    "verify-workbook-export": CommandSpec("verify-workbook-export", CommandRisk.READ_ONLY, False),
    "diagnose-import-shape": CommandSpec("diagnose-import-shape", CommandRisk.READ_ONLY, False),
    "cluster-extraction-batch": CommandSpec("cluster-extraction-batch", CommandRisk.READ_ONLY, False),
    "corpus-backlog-runner": CommandSpec("corpus-backlog-runner", CommandRisk.INTERMEDIATE_WRITE, False),
    "packet-batch-draft": CommandSpec("packet-batch-draft", CommandRisk.INTERMEDIATE_WRITE, False),
    "generate-extraction-workspace": CommandSpec(
        "generate-extraction-workspace",
        CommandRisk.INTERMEDIATE_WRITE,
        False,
    ),
    "clean-import": CommandSpec("clean-import", CommandRisk.INTERMEDIATE_WRITE, False),
    "append-import --dry-run": CommandSpec("append-import --dry-run", CommandRisk.READ_ONLY, False),
    "append-import": CommandSpec("append-import", CommandRisk.GUARDED_WRITE, True),
    "approve-proposal": CommandSpec("approve-proposal", CommandRisk.GUARDED_WRITE, True),
    "reject-proposal": CommandSpec("reject-proposal", CommandRisk.GUARDED_WRITE, True),
    "defer-proposal": CommandSpec("defer-proposal", CommandRisk.GUARDED_WRITE, True),
    "apply-approved-to-workbook": CommandSpec(
        "apply-approved-to-workbook",
        CommandRisk.GUARDED_WRITE,
        True,
    ),
    "verify-workbook-export --mark-exported": CommandSpec(
        "verify-workbook-export --mark-exported",
        CommandRisk.GUARDED_WRITE,
        True,
    ),
    "promote-output-workbook": CommandSpec("promote-output-workbook", CommandRisk.PROMOTION, True),
    "rollback-workbook": CommandSpec("rollback-workbook", CommandRisk.PROMOTION, True),
}


def resolve_command_policy(command: list[str]) -> CommandSpec:
    if not command:
        raise PermissionError("Command is empty.")
    if command[0] == "verify-workbook-export" and "--mark-exported" in command:
        return COMMAND_POLICY["verify-workbook-export --mark-exported"]
    if command[0] == "append-import" and "--dry-run" in command:
        return COMMAND_POLICY["append-import --dry-run"]
    command_name = command[0]
    if command_name not in COMMAND_POLICY:
        raise PermissionError(f"Command is not allowlisted for agent execution: {command_name}")
    return COMMAND_POLICY[command_name]


def assert_command_allowed(command: list[str], human_confirmed: bool = False) -> CommandSpec:
    spec = resolve_command_policy(command)
    if spec.requires_human_confirmation and not human_confirmed:
        raise PermissionError(f"{spec.name} requires explicit human confirmation.")
    if spec.risk == CommandRisk.PROMOTION and not human_confirmed:
        raise PermissionError("Workbook promotion and rollback must never be performed autonomously.")
    return spec
