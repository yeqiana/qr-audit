# Measuring QR preprocessing strategy contributions

A strategy's raw success count is not its marginal value. Individual file contribution, whole-family removal loss and paired-image contribution are separate measures.

## File-level metrics

Let \(S_i^F\) be the set of physical image IDs decoded by strategy \(i\), using at least one selected decoder.

- Ordered new success: \(|S_i^F - \cup_{j<i} S_j^F|\).
- Repeated success: \(|S_i^F \cap \cup_{j<i} S_j^F|\).
- Individual exclusive contribution: \(|S_i^F - \cup_{j\ne i} S_j^F|\).
- File family-removal loss: \(|\cup_i S_i^F - \cup_{i\notin G} S_i^F|\).

## Pair-level metrics

A pair is identified by a stable `pair_id` derived from both `group_id` and the normalized pair key. Therefore, `sample.png` in group A cannot collide with `sample.png` in group B.

Only unambiguous `PAIRED` entries are included in pair-level denominators. Single-directory, missing-side, left-only, right-only and ambiguous pairs remain visible in reports but are not silently forced into a two-sided pair.

Let \(S_i^P\) be the set of eligible pair IDs for which at least one file on either side was decoded by strategy \(i\).

- Ordered new pair success: \(|S_i^P - \cup_{j<i} S_j^P|\).
- Repeated pair success: \(|S_i^P \cap \cup_{j<i} S_j^P|\).
- Individual exclusive pair contribution: \(|S_i^P - \cup_{j\ne i} S_j^P|\).
- Pair family-removal loss: \(|\cup_i S_i^P - \cup_{i\notin G} S_i^P|\).

File and pair values must be reported separately. For example, if strategy A decodes only the left image and strategy B decodes only the right image, removing A loses one successful file but may lose zero successful pairs because B still makes that pair successful.

## Worked counterexample

Assume two groups. Each has a left and right image with the same pair key:

| Group | Left | Right |
| --- | --- | --- |
| A | Strategy A succeeds | Strategy B succeeds |
| B | Strategy A succeeds | Strategy B succeeds |

There are four successful files and two successful pairs. Removing A loses two successful files, but zero successful pairs. This is why pair success cannot be inferred by summing file-level loss.

## Multi-QR and payload comparison

Payload comparison is an order-independent set comparison over identities. Each identity includes algorithm, data scope and hash value. Two hashes with different scopes are not comparable. Hash-only records are accepted only when scope and algorithm are explicit.

Multiple distinct QR symbols in one image form a payload set; their mere multiplicity is not a conflict. Different payload sets across retries of the same logical combination are contradictory evidence and block contribution validation. Different successful strategies/decoders can be counted for recall while the image is separately flagged for manual review if their payload sets disagree.

## Completeness and provenance gate

Contribution metrics are valid only when:

- the v2 manifest, attempts and frozen strategy registry agree;
- every attempt belongs to the same run and matches the image identity and input SHA-256;
- retry IDs/indexes and status fields are valid;
- every expected image × strategy × decoder logical combination has an execution or explicit eligible skip;
- early stop, missing implementations, unavailable decoders, unresolved errors and retry payload contradictions are absent;
- before/after input snapshots are stable;
- inventory, strategy registry and source-file fingerprints are verified.

A structural PASS with unverified provenance is not a complete contribution audit. Incomplete exclusive contribution and family-removal loss must be `NA_INCOMPLETE`, never zero.

Use wall-clock decoder duration for executed attempts, report arithmetic mean and nearest-rank P95, and retain transform duration separately. A zero individual exclusive count does not justify removing an entire family.
