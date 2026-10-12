"""Duplicate-note pairs from `eno tiling --json` as chipsocket receipts, and the truth they wait for.

`tiling.py` scores every note pair by embedding cosine and sorts them into
`error_pairs` (>= error_threshold, 0.90) and `review_pairs` (>= threshold,
0.80). The two numbers have no recorded origin and no human verdict on a
review pair is stored anywhere. This script turns one tiling report into:

    data/labels/tiling-receipts.jsonl  one receipt per pair; member `tiling:cosine`
                                       carries the score, its value is the band it was put in
    data/labels/tiling-truth.jsonl     EMPTY until someone reviews: {"key": "<a>|<b>", "truth": true|false}
                                       (true = the two notes are duplicates)

    eno tiling --json > /tmp/tiling.json && python3 scripts/socket_labels.py /tmp/tiling.json
    uv run --project ~/Projects/chipsocket chipsocket cuts data/labels/tiling-receipts.jsonl \
        --truth data/labels/tiling-truth.jsonl --key input.pair --scorer tiling:cosine \
        --width 0.05 --min-n 20 --min-bucket 5
"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "labels"


def main(report_path: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rep = json.loads(Path(report_path).read_text())
    n = 0
    with (OUT / "tiling-receipts.jsonl").open("w") as fh:
        for band in ("error_pairs", "review_pairs"):
            for p in rep.get(band) or []:
                a, b = sorted((p["path_a"], p["path_b"]))
                member = "code:tiling:cosine@sha256:tiling"
                fh.write(json.dumps({
                    "schema": "chip.socket-receipt/v0alpha1", "socket": "eno.duplicate_note",
                    "answeredBy": member,
                    "input": {"pair": f"{a}|{b}", "a": a, "b": b},
                    "attempts": [{"member": member, "trigger": "primary", "outcome": "value",
                                  "value": band.removesuffix("_pairs"), "score": float(p["score"])}],
                    "shadows": [],
                }) + "\n")
                n += 1
    truth = OUT / "tiling-truth.jsonl"
    if not truth.exists():
        truth.write_text("")
    print(f"{n} pairs; truth rows: {sum(1 for _ in open(truth))}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "-")
