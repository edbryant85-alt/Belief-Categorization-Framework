from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

import pytest

from belief_dashboard.config import load_config
from belief_dashboard.dossiers import register_source
from belief_dashboard.evidence_clusters import (
    EvidenceClusterError,
    add_source_to_cluster,
    build_cluster_summary,
    bulk_add_sources_to_cluster,
    cluster_candidates_for_extraction,
    create_cluster,
    generate_cluster_triage_packet,
    init_cluster_queues,
    list_clusters,
)
from belief_dashboard.manual_imports import queue_summary
from belief_dashboard.queues import init_queues, validate_queues
from belief_dashboard.schemas import QUEUE_SCHEMAS


def test_init_cluster_queues_creates_cluster_queue_files(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"

    result = init_cluster_queues(queue_dir, config)

    assert len(result["created"]) == 2
    assert _read_header(queue_dir / "evidence_clusters.csv") == QUEUE_SCHEMAS["evidence_clusters"]
    assert _read_header(queue_dir / "source_cluster_members.csv") == QUEUE_SCHEMAS["source_cluster_members"]


def test_create_cluster_appends_valid_cluster(tmp_path: Path) -> None:
    config, queue_dir = _prepared_queue(tmp_path)

    result = create_cluster(
        queue_dir,
        config,
        cluster_id="CLUST-SIM-001",
        title="Simulation Argument and Theological Implications",
        core_question="What follows theologically if simulated worlds are possible?",
        hypotheses="CT; MT; N",
        topic_tags="simulation argument; theology",
        created_on=date(2026, 5, 28),
    )

    rows = _read_rows(queue_dir / "evidence_clusters.csv")
    assert result["cluster_id"] == "CLUST-SIM-001"
    assert rows[0]["cluster_title"] == "Simulation Argument and Theological Implications"
    assert rows[0]["status"] == "active"
    assert rows[0]["created_date"] == "2026-05-28"


def test_create_cluster_rejects_duplicate_cluster_id(tmp_path: Path) -> None:
    config, queue_dir = _prepared_queue(tmp_path)
    _create_sim_cluster(queue_dir, config)

    with pytest.raises(EvidenceClusterError, match="already exists"):
        _create_sim_cluster(queue_dir, config)


def test_create_cluster_validates_status(tmp_path: Path) -> None:
    config, queue_dir = _prepared_queue(tmp_path)

    with pytest.raises(EvidenceClusterError, match="invalid value"):
        create_cluster(
            queue_dir,
            config,
            cluster_id="CLUST-BAD-001",
            title="Bad",
            core_question="Bad?",
            status="exported",
        )


def test_add_source_to_cluster_validates_cluster_id_exists(tmp_path: Path) -> None:
    config, queue_dir = _prepared_queue(tmp_path)
    source_id = _register_source(tmp_path, queue_dir, config, "source.txt")

    with pytest.raises(EvidenceClusterError, match="cluster_id not found"):
        add_source_to_cluster(queue_dir, config, cluster_id="CLUST-NOPE", source_id=source_id, role="core_argument")


def test_add_source_to_cluster_validates_source_id_exists(tmp_path: Path) -> None:
    config, queue_dir = _prepared_queue(tmp_path)
    _create_sim_cluster(queue_dir, config)

    with pytest.raises(EvidenceClusterError, match="source_id not found"):
        add_source_to_cluster(queue_dir, config, cluster_id="CLUST-SIM-001", source_id="SRC9999", role="core_argument")


def test_add_source_to_cluster_appends_valid_membership(tmp_path: Path) -> None:
    config, queue_dir = _prepared_queue(tmp_path)
    _create_sim_cluster(queue_dir, config)
    source_id = _register_source(tmp_path, queue_dir, config, "bostrom.txt", title="Bostrom Paper")

    add_source_to_cluster(
        queue_dir,
        config,
        cluster_id="CLUST-SIM-001",
        source_id=source_id,
        role="core_argument",
        subtopic="Bostrom original trilemma",
        relevance=5,
        priority=5,
    )

    rows = _read_rows(queue_dir / "source_cluster_members.csv")
    assert rows[0]["source_id"] == "SRC0001"
    assert rows[0]["source_role"] == "core_argument"
    assert rows[0]["status"] == "active"


def test_add_source_to_cluster_rejects_duplicate_pair(tmp_path: Path) -> None:
    config, queue_dir = _prepared_queue(tmp_path)
    _create_sim_cluster(queue_dir, config)
    source_id = _register_source(tmp_path, queue_dir, config, "bostrom.txt")
    add_source_to_cluster(queue_dir, config, cluster_id="CLUST-SIM-001", source_id=source_id, role="core_argument")

    with pytest.raises(EvidenceClusterError, match="Membership already exists"):
        add_source_to_cluster(queue_dir, config, cluster_id="CLUST-SIM-001", source_id=source_id, role="core_argument")


def test_bulk_add_sources_to_cluster_filters_by_source_type(tmp_path: Path) -> None:
    config, queue_dir = _prepared_queue(tmp_path)
    _create_sim_cluster(queue_dir, config)
    _register_source(tmp_path, queue_dir, config, "video.txt", source_type="youtube_transcript")
    _register_source(tmp_path, queue_dir, config, "paper.txt", source_type="paper")

    result = bulk_add_sources_to_cluster(
        queue_dir,
        config,
        cluster_id="CLUST-SIM-001",
        source_type="youtube_transcript",
        role="popular_summary",
    )

    assert result["considered"] == 1
    assert len(result["added"]) == 1
    assert result["added"][0]["source_id"] == "SRC0001"


def test_bulk_add_sources_to_cluster_filters_by_source_folder(tmp_path: Path) -> None:
    config, queue_dir = _prepared_queue(tmp_path)
    _create_sim_cluster(queue_dir, config)
    cluster_folder = tmp_path / "raw" / "clusters" / "simulation"
    other_folder = tmp_path / "raw" / "other"
    cluster_folder.mkdir(parents=True)
    other_folder.mkdir(parents=True)
    _register_path(queue_dir, config, cluster_folder / "clip.txt")
    _register_path(queue_dir, config, other_folder / "clip.txt")

    result = bulk_add_sources_to_cluster(
        queue_dir,
        config,
        cluster_id="CLUST-SIM-001",
        source_folder=cluster_folder,
        role="popular_summary",
    )

    assert result["considered"] == 1
    assert result["added"][0]["source_id"] == "SRC0001"


def test_cluster_summary_reports_role_counts_and_source_counts(tmp_path: Path) -> None:
    config, queue_dir = _prepared_queue(tmp_path)
    _create_sim_cluster(queue_dir, config)
    first = _register_source(tmp_path, queue_dir, config, "bostrom.txt", title="Bostrom Paper", source_type="paper")
    second = _register_source(tmp_path, queue_dir, config, "objection.txt", title="Objection", source_type="blog")
    add_source_to_cluster(queue_dir, config, cluster_id="CLUST-SIM-001", source_id=first, role="core_argument", relevance=5, priority=5)
    add_source_to_cluster(queue_dir, config, cluster_id="CLUST-SIM-001", source_id=second, role="objection", relevance=4, priority=4)

    summary = build_cluster_summary(queue_dir, config, cluster_id="CLUST-SIM-001")

    assert summary["source_count"] == 2
    assert summary["counts_by_source_role"] == {"core_argument": 1, "objection": 1}
    assert summary["counts_by_source_type"] == {"blog": 1, "paper": 1}


def test_list_clusters_filters_by_status_topic_and_hypothesis(tmp_path: Path) -> None:
    config, queue_dir = _prepared_queue(tmp_path)
    _create_sim_cluster(queue_dir, config)
    create_cluster(
        queue_dir,
        config,
        cluster_id="CLUST-OTHER-001",
        title="Other Topic",
        core_question="Other?",
        hypotheses="EC",
        topic_tags="church history",
        status="archived",
    )

    result = list_clusters(queue_dir, config, status="active", topic="simulation", hypothesis="CT")

    assert [row["cluster_id"] for row in result["rows"]] == ["CLUST-SIM-001"]


def test_generate_cluster_triage_packet_includes_metadata_and_member_sources(tmp_path: Path) -> None:
    config, queue_dir = _prepared_queue(tmp_path)
    reports_dir = tmp_path / "reports"
    _create_sim_cluster(queue_dir, config)
    source_id = _register_source(tmp_path, queue_dir, config, "bostrom.txt", title="Bostrom Paper")
    add_source_to_cluster(queue_dir, config, cluster_id="CLUST-SIM-001", source_id=source_id, role="core_argument", relevance=5, priority=5)

    result = generate_cluster_triage_packet(
        queue_dir,
        reports_dir,
        config,
        cluster_id="CLUST-SIM-001",
        generated_at=datetime(2026, 5, 28, 12, 0, 0),
    )

    content = Path(result["prompt_packet_path"]).read_text(encoding="utf-8")
    assert "Evidence Cluster Triage Prompt Packet" in content
    assert "CLUST-SIM-001" in content
    assert "Bostrom Paper" in content
    assert "major objections" in content


def test_cluster_candidates_for_extraction_lists_high_priority_core_sources(tmp_path: Path) -> None:
    config, queue_dir = _prepared_queue(tmp_path)
    _create_sim_cluster(queue_dir, config)
    core = _register_source(tmp_path, queue_dir, config, "core.txt", title="Core")
    low = _register_source(tmp_path, queue_dir, config, "low.txt", title="Low")
    add_source_to_cluster(queue_dir, config, cluster_id="CLUST-SIM-001", source_id=core, role="core_argument", relevance=5, priority=2)
    add_source_to_cluster(queue_dir, config, cluster_id="CLUST-SIM-001", source_id=low, role="background", relevance=1, priority=1)

    result = cluster_candidates_for_extraction(queue_dir, config, cluster_id="CLUST-SIM-001")

    assert [row["source_id"] for row in result["rows"]] == [core]
    assert "generate-prompt-packet --source-id SRC0001" in result["rows"][0]["suggested_next_command"]


def test_validate_queues_includes_cluster_queues(tmp_path: Path) -> None:
    config, queue_dir = _prepared_queue(tmp_path)

    result = validate_queues(queue_dir, config)

    assert result["overall_status"] == "pass"
    assert "evidence_clusters" in result["required_files"]
    assert "source_cluster_members" in result["required_files"]


def test_queue_summary_includes_cluster_counts(tmp_path: Path) -> None:
    config, queue_dir = _prepared_queue(tmp_path)
    _create_sim_cluster(queue_dir, config)

    summary = queue_summary(queue_dir, config)

    assert summary["counts"]["evidence_clusters"] == 1
    assert summary["counts"]["source_cluster_members"] == 0


def _prepared_queue(tmp_path: Path) -> tuple[dict, Path]:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    init_queues(queue_dir, config)
    return config, queue_dir


def _create_sim_cluster(queue_dir: Path, config: dict) -> None:
    create_cluster(
        queue_dir,
        config,
        cluster_id="CLUST-SIM-001",
        title="Simulation Argument and Theological Implications",
        core_question="If simulated worlds are possible or likely, what follows?",
        hypotheses="CT; MT; PT; EC; PC; IS; MS; N",
        topic_tags="simulation argument; Bostrom; theology",
    )


def _register_source(
    tmp_path: Path,
    queue_dir: Path,
    config: dict,
    filename: str,
    *,
    title: str = "",
    source_type: str = "paper",
) -> str:
    source_path = tmp_path / filename
    return _register_path(queue_dir, config, source_path, title=title, source_type=source_type)


def _register_path(queue_dir: Path, config: dict, source_path: Path, *, title: str = "", source_type: str = "paper") -> str:
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(f"Source text for {source_path.name}.", encoding="utf-8")
    result = register_source(source_path, queue_dir, config, source_type=source_type, title=title)
    return result["source_id"]


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return next(csv.reader(handle))
