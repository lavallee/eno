# Socket labels: duplicate notes

The decision: are two notes duplicates (`tiling.py`)? Cosine on embeddings,
`>= 0.90` is an error, `0.80–0.90` goes to review, below is dropped; neither
number has a recorded origin, and no review verdict is stored.

`scripts/socket_labels.py` turns an `eno tiling --json` report into
`data/labels/tiling-receipts.jsonl` (score = cosine, value = the band) and an
empty `data/labels/tiling-truth.jsonl` to fill in by review
(`{"key": "<a>|<b>", "truth": true|false}`). The eno service was not running on
2026-10-12 so no real report was converted; the converter is smoke-tested on a
two-pair report. Once ~20 review pairs are labelled, `chipsocket cuts`
(scorer `tiling:cosine`, width 0.05) says where 0.80 and 0.90 should be.
