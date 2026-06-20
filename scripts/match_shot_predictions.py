#!/usr/bin/env python3
"""Match automatic shot predictions to human releases and export evaluator input."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, cast

AUTOMATIC_OUTCOMES = frozenset({"MADE", "MISSED", "UNCERTAIN"})
GROUND_TRUTH_OUTCOMES = frozenset({"MADE", "MISSED", "UNOBSERVABLE"})


@dataclass(frozen=True, slots=True)
class Attempt:
    """Minimal attempt record needed for timestamp matching."""

    attempt_id: str
    release_seconds: float
    outcome: str | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class MatchResult:
    """One-to-one release matching result."""

    matches: tuple[tuple[Attempt, Attempt], ...]
    missed: tuple[Attempt, ...]
    extra: tuple[Attempt, ...]


def match_attempts(
    expected: tuple[Attempt, ...],
    predicted: tuple[Attempt, ...],
    *,
    tolerance_seconds: float,
) -> MatchResult:
    """Maximize one-to-one matches, then minimize total timestamp error."""

    if not math.isfinite(tolerance_seconds) or tolerance_seconds < 0:
        raise ValueError("tolerance_seconds must be finite and non-negative")
    expected_items = tuple(sorted(expected, key=lambda item: (item.release_seconds, item.attempt_id)))
    predicted_items = tuple(sorted(predicted, key=lambda item: (item.release_seconds, item.attempt_id)))

    @cache
    def solve(expected_index: int, predicted_index: int) -> tuple[int, float, tuple[tuple[int, int], ...]]:
        if expected_index == len(expected_items) or predicted_index == len(predicted_items):
            return (0, 0.0, ())
        options = [solve(expected_index + 1, predicted_index), solve(expected_index, predicted_index + 1)]
        error = abs(expected_items[expected_index].release_seconds - predicted_items[predicted_index].release_seconds)
        if error <= tolerance_seconds:
            count, total_error, pairs = solve(expected_index + 1, predicted_index + 1)
            options.append((count + 1, total_error + error, ((expected_index, predicted_index), *pairs)))
        return min(options, key=lambda item: (-item[0], item[1], item[2]))

    _, _, index_pairs = solve(0, 0)
    matched_expected = {expected_index for expected_index, _ in index_pairs}
    matched_predicted = {predicted_index for _, predicted_index in index_pairs}
    return MatchResult(
        matches=tuple(
            (expected_items[expected_index], predicted_items[predicted_index])
            for expected_index, predicted_index in index_pairs
        ),
        missed=tuple(item for index, item in enumerate(expected_items) if index not in matched_expected),
        extra=tuple(item for index, item in enumerate(predicted_items) if index not in matched_predicted),
    )


def load_attempts(path: Path, *, predictions: bool) -> tuple[Attempt, ...]:
    """Load human or automatic attempts from a supported JSON object/list."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        values = payload.get("attempts", payload.get("shots", payload.get("predictions", [])))
        records = values if isinstance(values, list) else []
    else:
        records = []
    attempts: list[Attempt] = []
    seen_ids: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        attempt_id = _attempt_id(record, index)
        if attempt_id in seen_ids:
            raise ValueError(f"Duplicate attempt_id: {attempt_id}")
        seen_ids.add(attempt_id)
        release_seconds = _release_seconds(record, index)
        outcome = _outcome(record, index, predictions=predictions)
        confidence = _confidence(record, index) if predictions else None
        attempts.append(Attempt(attempt_id, release_seconds, outcome, confidence))
    return tuple(attempts)


def export_predictions(
    expected: tuple[Attempt, ...],
    predicted: tuple[Attempt, ...],
    *,
    tolerance_seconds: float,
    run_id: str = "",
) -> dict[str, object]:
    """Export matched predictions while retaining missed and extra events."""

    result = match_attempts(expected, predicted, tolerance_seconds=tolerance_seconds)
    exported: list[dict[str, object]] = []
    for ground_truth, automatic in result.matches:
        exported.append(
            {
                "attempt_id": ground_truth.attempt_id,
                "source_attempt_id": automatic.attempt_id,
                "release_seconds": automatic.release_seconds,
                "expected_release_seconds": ground_truth.release_seconds,
                "timestamp_error_seconds": abs(automatic.release_seconds - ground_truth.release_seconds),
                "automatic_outcome": automatic.outcome,
                "confidence": automatic.confidence,
                "match_status": "MATCHED",
            }
        )
    for automatic in result.extra:
        exported.append(
            {
                "attempt_id": f"extra:{automatic.attempt_id}",
                "source_attempt_id": automatic.attempt_id,
                "release_seconds": automatic.release_seconds,
                "automatic_outcome": automatic.outcome,
                "confidence": automatic.confidence,
                "match_status": "EXTRA",
            }
        )
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "matching": {
            "tolerance_seconds": tolerance_seconds,
            "matched_count": len(result.matches),
            "missed_count": len(result.missed),
            "extra_count": len(result.extra),
        },
        "attempts": sorted(
            exported,
            key=lambda item: (cast(float, item["release_seconds"]), cast(str, item["attempt_id"])),
        ),
        "unmatched_ground_truth": [
            {
                "attempt_id": item.attempt_id,
                "release_seconds": item.release_seconds,
                "outcome": item.outcome,
                "match_status": "MISSED",
            }
            for item in result.missed
        ],
    }


def main() -> int:
    """Match two JSON files and write a schema-compatible prediction file."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--automatic-attempts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tolerance-seconds", type=float, default=0.25)
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()
    try:
        document = export_predictions(
            load_attempts(args.annotations, predictions=False),
            load_attempts(args.automatic_attempts, predictions=True),
            tolerance_seconds=args.tolerance_seconds,
            run_id=args.run_id,
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(document["matching"], indent=2, sort_keys=True))
    return 0


def _attempt_id(record: dict[str, Any], index: int) -> str:
    value = record.get("attempt_id", record.get("id"))
    if not isinstance(value, str) or not value:
        raise ValueError(f"Attempt {index} is missing a non-empty attempt_id")
    return value


def _release_seconds(record: dict[str, Any], index: int) -> float:
    value = record.get("release_seconds", record.get("timestamp_seconds", record.get("time_seconds")))
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"Attempt {index} is missing numeric release_seconds")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"Attempt {index} release_seconds must be finite and non-negative")
    return result


def _outcome(record: dict[str, Any], index: int, *, predictions: bool) -> str:
    value = record.get("automatic_outcome", record.get("outcome"))
    if not isinstance(value, str):
        kind = "automatic outcome" if predictions else "ground-truth outcome"
        raise ValueError(f"Attempt {index} is missing a {kind}")
    outcome = value.upper()
    valid_outcomes = AUTOMATIC_OUTCOMES if predictions else GROUND_TRUTH_OUTCOMES
    if outcome not in valid_outcomes:
        choices = "MADE, MISSED, or UNCERTAIN" if predictions else "MADE, MISSED, or UNOBSERVABLE"
        raise ValueError(f"Attempt {index} outcome must be {choices}")
    return outcome


def _confidence(record: dict[str, Any], index: int) -> float:
    value = record.get("confidence", record.get("outcome_confidence"))
    if isinstance(value, dict):
        value = value.get("score")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"Attempt {index} is missing numeric confidence")
    confidence = float(value)
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError(f"Attempt {index} confidence must be between zero and one")
    return confidence


if __name__ == "__main__":
    raise SystemExit(main())
