#!/usr/bin/env python3
"""Evaluate make/miss accuracy and uncertainty calibration when labels are available."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAKE_MISS_OUTCOMES = {"MADE", "MISSED"}
ALL_OUTCOMES = {"MADE", "MISSED", "UNCERTAIN"}


@dataclass(frozen=True, slots=True)
class OutcomeLabel:
    """One ground-truth make/miss label."""

    attempt_id: str
    outcome: str


@dataclass(frozen=True, slots=True)
class OutcomePrediction:
    """One automatic outcome prediction."""

    attempt_id: str
    outcome: str
    confidence: float


@dataclass(frozen=True, slots=True)
class OutcomeEvaluation:
    """Make/miss accuracy and confidence calibration summary."""

    labels: tuple[OutcomeLabel, ...]
    predictions: tuple[OutcomePrediction, ...]

    def to_json(self) -> dict[str, object]:
        """Return a stable JSON report."""

        prediction_by_id = {item.attempt_id: item for item in self.predictions}
        matched = tuple(
            (label, prediction_by_id[label.attempt_id]) for label in self.labels if label.attempt_id in prediction_by_id
        )
        missing_predictions = tuple(label for label in self.labels if label.attempt_id not in prediction_by_id)
        label_ids = {label.attempt_id for label in self.labels}
        extra_predictions = tuple(
            prediction for prediction in self.predictions if prediction.attempt_id not in label_ids
        )
        certain = tuple(
            (label, prediction) for label, prediction in matched if prediction.outcome in MAKE_MISS_OUTCOMES
        )
        uncertain = tuple((label, prediction) for label, prediction in matched if prediction.outcome == "UNCERTAIN")
        correct = tuple((label, prediction) for label, prediction in certain if label.outcome == prediction.outcome)
        incorrect = tuple((label, prediction) for label, prediction in certain if label.outcome != prediction.outcome)
        return {
            "status": "evaluated",
            "labeled_attempts": len(self.labels),
            "matched_attempts": len(matched),
            "certain_predictions": len(certain),
            "uncertain_predictions": len(uncertain),
            "missing_predictions": [item.attempt_id for item in missing_predictions],
            "extra_predictions": [item.attempt_id for item in extra_predictions],
            "make_miss_accuracy": len(correct) / len(certain) if certain else 0.0,
            "certain_coverage": len(certain) / len(matched) if matched else 0.0,
            "uncertainty_rate": len(uncertain) / len(matched) if matched else 0.0,
            "mean_confidence_correct": _mean(prediction.confidence for _, prediction in correct),
            "mean_confidence_incorrect": _mean(prediction.confidence for _, prediction in incorrect),
            "calibration_bins": _calibration_bins(certain),
        }


def evaluate(labels: Iterable[OutcomeLabel], predictions: Iterable[OutcomePrediction]) -> OutcomeEvaluation:
    """Build an outcome evaluation from labels and predictions."""

    return OutcomeEvaluation(
        labels=tuple(sorted(labels, key=lambda item: item.attempt_id)),
        predictions=tuple(sorted(predictions, key=lambda item: item.attempt_id)),
    )


def load_labels(path: Path) -> tuple[OutcomeLabel, ...]:
    """Load ground-truth make/miss labels from JSON."""

    records = _records(json.loads(path.read_text(encoding="utf-8")))
    return tuple(_label(record, index) for index, record in enumerate(records))


def load_predictions(path: Path) -> tuple[OutcomePrediction, ...]:
    """Load automatic outcome predictions from JSON."""

    records = _records(json.loads(path.read_text(encoding="utf-8")))
    return tuple(_prediction(record, index) for index, record in enumerate(records))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.labels is None or args.predictions is None:
        return _emit(
            {
                "status": "blocked",
                "reason": "Ground-truth make/miss labels and automatic predictions are required.",
            },
            args.output,
        )
    if not args.labels.exists():
        return _emit({"status": "blocked", "reason": f"Missing labels file: {args.labels}"}, args.output)
    if not args.predictions.exists():
        return _emit({"status": "blocked", "reason": f"Missing predictions file: {args.predictions}"}, args.output)
    report = evaluate(load_labels(args.labels), load_predictions(args.predictions)).to_json()
    return _emit(report, args.output)


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        values = payload.get("attempts", payload.get("shots", payload.get("labels", payload.get("predictions", []))))
        records = values if isinstance(values, list) else []
    else:
        records = []
    return [record for record in records if isinstance(record, dict)]


def _label(record: dict[str, Any], index: int) -> OutcomeLabel:
    attempt_id = _attempt_id(record, index)
    outcome = _outcome(record, index)
    if outcome not in MAKE_MISS_OUTCOMES:
        raise ValueError(f"Label {index} must be MADE or MISSED")
    return OutcomeLabel(attempt_id, outcome)


def _prediction(record: dict[str, Any], index: int) -> OutcomePrediction:
    attempt_id = _attempt_id(record, index)
    outcome = _outcome(record, index)
    if outcome not in ALL_OUTCOMES:
        raise ValueError(f"Prediction {index} must be MADE, MISSED, or UNCERTAIN")
    confidence_value = record.get("confidence", record.get("outcome_confidence", 0.0))
    if isinstance(confidence_value, bool) or not isinstance(confidence_value, int | float):
        raise ValueError(f"Prediction {index} is missing a numeric confidence")
    confidence = float(confidence_value)
    if not 0 <= confidence <= 1:
        raise ValueError(f"Prediction {index} confidence must be between zero and one")
    return OutcomePrediction(attempt_id, outcome, confidence)


def _attempt_id(record: dict[str, Any], index: int) -> str:
    value = record.get("attempt_id", record.get("id"))
    if isinstance(value, str) and value:
        return value
    return f"row-{index}"


def _outcome(record: dict[str, Any], index: int) -> str:
    value = record.get("outcome", record.get("automatic_outcome"))
    if not isinstance(value, str):
        raise ValueError(f"Record {index} is missing an outcome")
    return value.upper()


def _mean(values: Iterable[float]) -> float:
    items = tuple(values)
    return sum(items) / len(items) if items else 0.0


def _calibration_bins(pairs: Iterable[tuple[OutcomeLabel, OutcomePrediction]]) -> list[dict[str, object]]:
    bins = ((0.0, 0.5), (0.5, 0.7), (0.7, 0.85), (0.85, 1.0000001))
    items = tuple(pairs)
    result: list[dict[str, object]] = []
    for lower, upper in bins:
        bucket = tuple((label, prediction) for label, prediction in items if lower <= prediction.confidence < upper)
        result.append(
            {
                "confidence_min": lower,
                "confidence_max": min(1.0, upper),
                "count": len(bucket),
                "mean_confidence": _mean(prediction.confidence for _, prediction in bucket),
                "accuracy": (
                    sum(1 for label, prediction in bucket if label.outcome == prediction.outcome) / len(bucket)
                    if bucket
                    else 0.0
                ),
            }
        )
    return result


def _emit(report: dict[str, object], output: Path | None) -> int:
    payload = json.dumps(report, indent=2, sort_keys=True)
    print(payload)
    if output is not None:
        output.write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
