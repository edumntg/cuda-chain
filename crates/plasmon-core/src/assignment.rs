//! Deterministic shard assignment, identical to `plasmon.core.assignment`.

pub fn shard_index(job_seed: &str, round: u64, node_id: &str, num_shards: u64) -> u64 {
    assert!(num_shards > 0, "num_shards must be positive");
    let mut h = blake3::Hasher::new();
    h.update(job_seed.as_bytes());
    h.update(&round.to_le_bytes());
    h.update(node_id.as_bytes());
    let digest = h.finalize();
    let mut first = [0u8; 8];
    first.copy_from_slice(&digest.as_bytes()[..8]);
    u64::from_le_bytes(first) % num_shards
}
