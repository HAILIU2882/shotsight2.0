#!/usr/bin/env python3
"""Evaluate shot-event precision and recall when annotations are available."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ShotEvent:
    """One annotated or predicted shot release event."""

    timestamp_seconds: float
    event_id: str = ""


@dataclass(frozen=True, slots=True)
class ShotEventEvaluation:
    """Precision/recall comparison for release timestamps."""

    tolerance_seconds: float
    matches: tuple[tuple[ShotEvent, ShotEvent], ...]
    missed: tuple[ShotEvent, ...]
    extra: tuple[ShotEvent, ...]

    @property
    def precision(self) -> float:
        """Return release precision."""

        denominator = len(self.matches) + len(self.extra)
        return len(self.matches) / denominator if denominator else 1.0

    @property
    def recall(self) -> float:
        """Return release recall."""

        denominator = len(self.matches) + len(self.missed)
        return len(self.matches) / denominator if denominator else 1.0

    def to_json(self) -> dict[str, object]:
        """Return a stable JSON report."""

        return {
            "status": "evaluated",
            "tolerance_seconds": self.tolerance_seconds,
            "precision": self.precision,
            "recall": self.recall,
            "matches": [
                {
                    "expected_id": expected.event_id,
                    "predicted_id": predicted.event_id,
                    "expected_seconds": expected.timestamp_seconds,
                    "predicted_seconds": predicted.timestamp_seconds,
                    "error_seconds": abs(expected.timestamp_seconds - predicted.timestamp_seconds),
                }
                for expected, predicted in self.matches
            ],
            "missed_expected": [event.timestamp_seconds for event in self.missed],
            "extra_predicted": [event.timestamp_seconds for event in self.extra],
        }


def evaluate_events(
    expected: Iterable[ShotEvent],
    predicted: Iterable[ShotEvent],
    *,
    tolerance_seconds: float,
) -> ShotEventEvaluation:
    """Greedily match predicted release events to ground truth within tolerance."""

    expected_events = tuple(sorted(expected, key=lambda item: (item.timestamp_seconds, item.event_id)))
    unmatched_predictions = list(sorted(predicted, key=lambda item: (item.timestamp_seconds, item.event_id)))
    matches: list[tuple[ShotEvent, ShotEvent]] = []
    missed: list[ShotEvent] = []
    for expected_event in expected_events:
        candidates = [
            (abs(expected_event.timestamp_seconds - predicted_event.timestamp_seconds), index, predicted_event)
            for index, predicted_event in enumerate(unmatched_predictions)
            if abs(expected_event.timestamp_seconds - predicted_event.timestamp_seconds) <= tolerance_seconds
        ]
        if not candidates:
            missed.append(expected_event)
            continue
        _, index, predicted_event = min(candidates, key=lambda item: (item[0], item[2].timestamp_seconds))
        matches.append((expected_event, predicted_event))
        unmatched_predictions.pop(index)
    return ShotEventEvaluation(
        tolerance_seconds=tolerance_seconds,
        matches=tuple(matches),
        missed=tuple(missed),
        extra=tuple(unmatched_predictions),
    )


def load_events(path: Path) -> tuple[ShotEvent, ...]:
    """Load a JSON list or object containing shot events."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    records = _records(payload)
    return tuple(_event(record, index) for index, record in enumerate(records))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--tolerance-seconds", type=float, default=0.25)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.annotations is None or args.predictions is None:
        return _emit(
            {
                "status": "blocked",
                "reason": "Ground-truth annotations and prediction events are required for precision/recall.",
            },
            args.output,
        )
    if not args.annotations.exists():
        return _emit({"status": "blocked", "reason": f"Missing annotations file: {args.annotations}"}, args.output)
    if not args.predictions.exists():
        return _emit({"status": "blocked", "reason": f"Missing predictions file: {args.predictions}"}, args.output)
    report = evaluate_events(
        load_events(args.annotations),
        load_events(args.predictions),
        tolerance_seconds=args.tolerance_seconds,
    ).to_json()
    return _emit(report, args.output)


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        events = payload.get("events", payload.get("shots", payload.get("attempts", [])))
        records = events if isinstance(events, list) else []
    else:
        records = []
    result: list[dict[str, Any]] = []
    for record in records:
        if isinstance(record, dict):
            result.append(record)
    return result


def _event(record: dict[str, Any], index: int) -> ShotEvent:
    value = record.get("release_seconds", record.get("timestamp_seconds", record.get("time_seconds")))
    if not isinstance(value, int | float):
        raise ValueError(f"Shot event {index} is missing a numeric release timestamp")
    event_id = record.get("id", record.get("attempt_id", ""))
    return ShotEvent(float(value), event_id if isinstance(event_id, str) else "")


def _emit(report: dict[str, object], output: Path | None) -> int:
    payload = json.dumps(report, indent=2, sort_keys=True)
    print(payload)
    if output is not None:
        output.write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
