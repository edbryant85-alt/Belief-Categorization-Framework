from __future__ import annotations

import pytest

from belief_dashboard_agentflows.git_policy import assert_paths_allowed, assert_push_allowed, changed_paths_from_porcelain
from belief_dashboard_agentflows.policies import CommandRisk, assert_command_allowed, resolve_command_policy


def test_read_only_command_allowed_without_confirmation() -> None:
    spec = assert_command_allowed(["validate-import", "--type", "extracted_claims"], human_confirmed=False)

    assert spec.risk == CommandRisk.READ_ONLY


def test_guarded_write_rejected_without_confirmation() -> None:
    with pytest.raises(PermissionError, match="requires explicit human confirmation"):
        assert_command_allowed(["append-import", "--type", "extracted_claims"], human_confirmed=False)


def test_promotion_rejected_without_confirmation() -> None:
    with pytest.raises(PermissionError, match="requires explicit human confirmation"):
        assert_command_allowed(["promote-output-workbook", "--workbook", "output.xlsx"], human_confirmed=False)


def test_verify_mark_exported_is_guarded_write() -> None:
    spec = resolve_command_policy(["verify-workbook-export", "--workbook", "output.xlsx", "--mark-exported"])

    assert spec.risk == CommandRisk.GUARDED_WRITE


def test_packet_batch_draft_is_intermediate_write() -> None:
    spec = resolve_command_policy(["packet-batch-draft", "--source-id", "SRC0018"])

    assert spec.risk == CommandRisk.INTERMEDIATE_WRITE
    assert not spec.requires_human_confirmation


def test_corpus_backlog_runner_is_intermediate_write() -> None:
    spec = resolve_command_policy(["corpus-backlog-runner", "--corpus", "mosaic", "--background-safe"])

    assert spec.risk == CommandRisk.INTERMEDIATE_WRITE
    assert not spec.requires_human_confirmation


def test_promotion_and_rollback_remain_promotion() -> None:
    promote = resolve_command_policy(["promote-output-workbook", "--workbook", "output.xlsx"])
    rollback = resolve_command_policy(["rollback-workbook", "--archive", "archive.xlsx"])

    assert promote.risk == CommandRisk.PROMOTION
    assert rollback.risk == CommandRisk.PROMOTION


def test_unknown_command_rejected() -> None:
    with pytest.raises(PermissionError, match="not allowlisted"):
        resolve_command_policy(["mutate-workbook-directly"])


def test_changed_paths_from_porcelain_handles_renames() -> None:
    paths = changed_paths_from_porcelain([" M belief-dashboard-tool/reports/x.md", "R  old.md -> belief-dashboard-tool/reports/y.md"])

    assert paths == ["belief-dashboard-tool/reports/x.md", "belief-dashboard-tool/reports/y.md"]


def test_forbidden_path_changes_block_git_policy() -> None:
    with pytest.raises(PermissionError, match="not allowed"):
        assert_paths_allowed(["belief-dashboard-tool/data/workbooks/main.xlsx"], ("belief-dashboard-tool/reports/",))


def test_push_requires_confirmation_and_non_main_branch() -> None:
    with pytest.raises(PermissionError, match="requires explicit human confirmation"):
        assert_push_allowed(human_confirmed=False, branch="agent/test")
    with pytest.raises(PermissionError, match="main/master"):
        assert_push_allowed(human_confirmed=True, branch="main")
