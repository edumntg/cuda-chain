# Protocol, version 1

This document specifies the data formats that the coordinator, the trainers and the
CLI exchange. Python (`plasmon.core`) is the reference implementation. Rust
(`plasmon-core`) must produce the same bytes. The file
`python/tests/vectors/v1.json` holds test vectors for both.

## 1. Identity

- Each machine has one Ed25519 key pair.
- The node id is the public key as 64 lowercase hex characters.
- The private seed is 32 bytes in `machine.key`, file mode 0600.
- A signature is 64 bytes as 128 lowercase hex characters.
- A signature covers the canonical JSON of a payload (section 2).

## 2. Canonical JSON

Signed payloads use canonical JSON:

- Keys are sorted by Unicode code point.
- There is no whitespace between tokens.
- Strings are UTF-8. Only `"`, `\` and control characters are escaped.
- Allowed values: string, integer in the signed 64-bit range, boolean, null, array, object.
- Floats are not allowed. Put decimal values in strings or scale them to integers.

Example: the object `{"b": 1, "a": [true, null, "ñ"]}` serializes to
`{"a":[true,null,"ñ"],"b":1}`.

## 3. Content addressing

- A blob id is the BLAKE3 digest of the blob bytes, as 64 lowercase hex characters.
- The blob store keys blobs by blob id. A blob is immutable.
- A party verifies the digest after download. A mismatch is an error.

## 4. Shard assignment

The shard for one trainer in one round is:

```
index = u64_le(blake3(job_seed || u64_le(round) || node_id)[0:8]) mod num_shards
```

- `job_seed` and `node_id` are UTF-8 strings.
- `round` is a 64-bit little-endian integer.
- The result is deterministic. Any party can recompute it.

## 5. Δ frame

A Δ frame carries one trainer's compressed pseudo-gradient for one round.

| Field | Size | Value |
|---|---|---|
| magic | 4 bytes | `PLSM` |
| version | 1 byte | `1` |
| kind | 1 byte | `1` sparse top-k, `2` dense |
| reserved | 2 bytes | `0` |
| header length | 8 bytes, little endian | byte length of the header |
| header | header length | JSON, UTF-8 |
| payload | rest | tensor data |

Header fields: `job`, `round`, `node`, `theta` (blob id of the weights the trainer
started from), `samples`, `meta` (free JSON, for example losses), `tensors`.

Each entry in `tensors` has `name`, `shape`, `numel`, `val_offset`, `val_len`, and for
sparse tensors `idx_offset` and `idx_len`. Offsets are relative to the start of the
payload.

- Sparse values: `uint32` little-endian indices, then `float16` values.
- Dense values: `float16` values in row-major order.
- The frame id is the BLAKE3 digest of the complete frame.

A receiver rejects a frame when: the magic or the version is wrong, the header does not
fit, an offset points outside the payload, or an index is not smaller than `numel`.

## 6. Commit and reveal

1. The trainer computes the frame and its frame id.
2. The trainer sends a commit: `{"job", "round", "node", "blob": frame id}` with a
   signature. The coordinator stores the commit and the time.
3. The trainer uploads the frame to the blob store.
4. The coordinator verifies the digest, matches it to the commit and marks the update as
   revealed.

A trainer cannot change an update after the commit. A trainer that reveals a frame with
a different id gets no credit for the round.
