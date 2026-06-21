from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import evaluate_outcome_classification as outcome_evaluator
from scripts import evaluate_shot_lifecycle as lifecycle_evaluator
from scripts.match_shot_predictions import Attempt, export_predictions, load_attempts, match_attempts


def test_timestamp_matcher_maximizes_matches_before_timestamp_error() -> None:
    expected = (Attempt("expected-a", 0.2), Attempt("expected-b", 0.4))
    predicted = (Attempt("predicted-a", 0.0), Attempt("predicted-b", 0.3))

    result = match_attempts(expected, predicted, tolerance_seconds=0.21)
    reversed_result = match_attempts(tuple(reversed(expected)), tuple(reversed(predicted)), tolerance_seconds=0.21)

    assert [(left.attempt_id, right.attempt_id) for left, right in result.matches] == [
        ("expected-a", "predicted-a"),
        ("expected-b", "predicted-b"),
    ]
    assert reversed_result == result
    assert result.missed == ()
    assert result.extra == ()


def test_matcher_rejects_invalid_tolerance() -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        match_attempts((), (), tolerance_seconds=float("nan"))


def test_lifecycle_zero_predictions_does_not_report_perfect_precision() -> None:
    report = lifecycle_evaluator.evaluate_events(
        (lifecycle_evaluator.ShotEvent(1.0, "shot-001"),),
        (),
        tolerance_seconds=0.25,
    ).to_json()

    assert report["precision"] is None
    assert report["precision_defined"] is False
    assert report["recall"] == 0.0
    assert report["recall_defined"] is True
    assert json.loads(json.dumps(report))["precision"] is None


def test_lifecycle_empty_inputs_use_documented_perfect_agreement_convention() -> None:
    report = lifecycle_evaluator.evaluate_events((), (), tolerance_seconds=0.25).to_json()

    assert report["precision"] == 1.0
    assert report["precision_defined"] is True
    assert report["recall"] == 1.0
    assert report["recall_defined"] is True


def test_lifecycle_prediction_without_truth_has_undefined_recall() -> None:
    report = lifecycle_evaluator.evaluate_events(
        (),
        (lifecycle_evaluator.ShotEvent(1.0, "prediction-001"),),
        tolerance_seconds=0.25,
    ).to_json()

    assert report["precision"] == 0.0
    assert report["precision_defined"] is True
    assert report["recall"] is None
    assert report["recall_defined"] is False


def test_outcome_accuracy_is_unavailable_without_matched_certain_predictions() -> None:
    report = outcome_evaluator.evaluate(
        (outcome_evaluator.OutcomeLabel("shot-001", "MADE"),),
        (),
    ).to_json()

    assert report["matched_attempts"] == 0
    assert report["make_miss_accuracy"] is None
    assert report["make_miss_accuracy_defined"] is False
    assert report["certain_coverage"] is None
    assert report["certain_coverage_defined"] is False
    assert report["uncertainty_rate"] is None
    assert report["uncertainty_rate_defined"] is False
    assert json.loads(json.dumps(report))["make_miss_accuracy"] is None


def test_outcome_accuracy_is_unavailable_when_all_matched_predictions_are_uncertain() -> None:
    report = outcome_evaluator.evaluate(
        (outcome_evaluator.OutcomeLabel("shot-001", "MADE"),),
        (outcome_evaluator.OutcomePrediction("shot-001", "UNCERTAIN", 0.4),),
    ).to_json()

    assert report["matched_attempts"] == 1
    assert report["make_miss_accuracy"] is None
    assert report["make_miss_accuracy_defined"] is False
    assert report["certain_coverage"] == 0.0
    assert report["certain_coverage_defined"] is True
    assert report["uncertainty_rate"] == 1.0
    assert report["uncertainty_rate_defined"] is True


def test_export_schema_drives_both_evaluators_and_excludes_unobservable(tmp_path: Path) -> None:
    annotation_path = tmp_path / "annotations.json"
    automatic_path = tmp_path / "automatic.json"
    export_path = tmp_path / "predictions.json"
    annotation_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "attempts": [
                    {"attempt_id": "shot-001", "release_seconds": 1.0, "outcome": "MADE"},
                    {"attempt_id": "shot-002", "release_seconds": 2.0, "outcome": "UNOBSERVABLE"},
                    {"attempt_id": "shot-003", "release_seconds": 3.0, "outcome": "MISSED"},
                ],
            }
        ),
        encoding="utf-8",
    )
    automatic_path.write_text(
        json.dumps(
            {
                "attempts": [
                    {
                        "id": "automatic-a",
                        "release_seconds": 1.05,
                        "automatic_outcome": "MADE",
                        "confidence": {"score": 0.9},
                    },
                    {
                        "id": "automatic-b",
                        "release_seconds": 2.1,
                        "automatic_outcome": "UNCERTAIN",
                        "confidence": 0.4,
                    },
                    {
                        "id": "automatic-extra",
                        "release_seconds": 4.0,
                        "automatic_outcome": "MISSED",
                        "confidence": 0.8,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    exported = export_predictions(
        load_attempts(annotation_path, predictions=False),
        load_attempts(automatic_path, predictions=True),
        tolerance_seconds=0.2,
        run_id="synthetic-run",
    )
    export_path.write_text(json.dumps(exported), encoding="utf-8")

    lifecycle_report = lifecycle_evaluator.evaluate_events(
        lifecycle_evaluator.load_events(annotation_path),
        lifecycle_evaluator.load_events(export_path),
        tolerance_seconds=0.2,
    ).to_json()
    assert lifecycle_report["ground_truth_releases"] == 3
    assert lifecycle_report["predicted_releases"] == 3
    assert lifecycle_report["matched_releases"] == 2

    outcome_report = outcome_evaluator.evaluate(
        outcome_evaluator.load_labels(annotation_path),
        outcome_evaluator.load_predictions(export_path),
    ).to_json()
    assert outcome_report["labeled_attempts"] == 3
    assert outcome_report["outcome_evaluable_attempts"] == 2
    assert outcome_report["excluded_unobservable_attempts"] == 1
    assert outcome_report["excluded_unobservable_attempt_ids"] == ["shot-002"]
    assert outcome_report["matched_attempts"] == 1
    assert outcome_report["missing_predictions"] == ["shot-003"]
    assert outcome_report["extra_predictions"] == ["extra:automatic-extra"]
    assert outcome_report["make_miss_accuracy"] == 1.0
