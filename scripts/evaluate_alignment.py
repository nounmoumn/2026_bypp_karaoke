"""Evaluate line boundaries against independently listened-to references."""

import argparse
import csv
import json
import statistics
from pathlib import Path


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("prediction", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-partial", action="store_true",
                        help="Evaluate only manual_reviewed rows; never use for the final gate")
    args = parser.parse_args()

    prediction = json.loads(args.prediction.read_text(encoding="utf-8"))
    with args.reference.open(encoding="utf-8-sig", newline="") as stream:
        references = list(csv.DictReader(stream))
    if not references:
        parser.error("Reference CSV is empty")
    unreviewed = [row["line_id"] for row in references if row.get("timing_source") != "manual_reviewed"]
    if unreviewed and not args.allow_partial:
        parser.error("Every reference line must be marked manual_reviewed; candidates are not ground truth")
    if args.allow_partial:
        references = [row for row in references if row.get("timing_source") == "manual_reviewed"]
        if not references:
            parser.error("No manual_reviewed lines")
    pred_by_id = {row["lineId"]: row for row in prediction["lines"]}
    if len(pred_by_id) != len(prediction["lines"]):
        parser.error("Duplicate predicted line ID")
    if len({row["line_id"] for row in references}) != len(references):
        parser.error("Duplicate reference line ID")
    reference_ids = {row["line_id"] for row in references}
    if (not reference_ids.issubset(pred_by_id) or
            (not args.allow_partial and set(pred_by_id) != reference_ids)):
        parser.error("Prediction and reference line IDs differ")

    details = []
    for row in references:
        line_id = row["line_id"]
        expected_start = float(row["reference_start"])
        expected_end = float(row["reference_end"])
        if not 0 <= expected_start < expected_end <= args.duration:
            parser.error(f"Invalid reference bounds for {line_id}")
        predicted = pred_by_id[line_id]
        start, end = predicted.get("startSec"), predicted.get("endSec")
        valid = (start is not None and end is not None
                 and 0 <= start < end <= args.duration)
        details.append({"lineId": line_id, "valid": valid,
                        "startErrorSec": start - expected_start if valid else None,
                        "endErrorSec": end - expected_end if valid else None})

    starts = [abs(row["startErrorSec"]) for row in details if row["valid"]]
    ends = [abs(row["endErrorSec"]) for row in details if row["valid"]]
    total = len(details)
    report = {
        "provisionalPartial": args.allow_partial,
        "excludedUnreviewedLineIds": unreviewed,
        "referenceLines": total,
        "validLines": len(starts),
        "validRatio": len(starts) / total,
        "startWithin0_5SecAllLines": sum(error <= .5 for error in starts) / total,
        "endWithin0_7SecAllLines": sum(error <= .7 for error in ends) / total,
        "startAbsMedianSecValid": statistics.median(starts) if starts else None,
        "startAbsP90SecValid": percentile(starts, .9),
        "endAbsMedianSecValid": statistics.median(ends) if ends else None,
        "endAbsP90SecValid": percentile(ends, .9),
        "details": details,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "details"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
