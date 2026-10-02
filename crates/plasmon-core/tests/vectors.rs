use plasmon_core::{assignment, canonical, hashing, identity};
use serde_json::Value;

fn vectors() -> Value {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../python/tests/vectors/v1.json"
    );
    serde_json::from_str(&std::fs::read_to_string(path).expect("vectors file")).unwrap()
}

#[test]
fn canonical_matches_python() {
    for case in vectors()["canonical"].as_array().unwrap() {
        let got = String::from_utf8(canonical::dumps(&case["value"]).unwrap()).unwrap();
        assert_eq!(got, case["json"].as_str().unwrap());
    }
}

#[test]
fn canonical_rejects_floats() {
    assert!(canonical::dumps(&serde_json::json!({"loss": 0.5})).is_err());
}

#[test]
fn blake3_matches_python() {
    for case in vectors()["blake3"].as_array().unwrap() {
        assert_eq!(
            hashing::digest(case["input"].as_str().unwrap().as_bytes()),
            case["digest"]
        );
    }
}

#[test]
fn signatures_match_python() {
    for case in vectors()["sign"].as_array().unwrap() {
        let seed = hex_decode(case["seed"].as_str().unwrap());
        let ident = identity::Identity::from_seed(&seed).unwrap();
        assert_eq!(ident.node_id(), case["node_id"].as_str().unwrap());
        assert_eq!(
            ident.sign(&case["payload"]).unwrap(),
            case["signature"].as_str().unwrap()
        );
        assert!(identity::verify(
            case["node_id"].as_str().unwrap(),
            &case["payload"],
            case["signature"].as_str().unwrap()
        ));
        assert!(!identity::verify(
            case["node_id"].as_str().unwrap(),
            &serde_json::json!({"x": 1}),
            case["signature"].as_str().unwrap()
        ));
    }
}

#[test]
fn assignment_matches_python() {
    for case in vectors()["assignment"].as_array().unwrap() {
        let got = assignment::shard_index(
            case["seed"].as_str().unwrap(),
            case["round"].as_u64().unwrap(),
            case["node"].as_str().unwrap(),
            case["shards"].as_u64().unwrap(),
        );
        assert_eq!(got, case["index"].as_u64().unwrap());
    }
}

#[test]
fn identity_roundtrip_on_disk() {
    let dir = std::env::temp_dir().join(format!("plasmon-test-{}", std::process::id()));
    let path = dir.join("machine.key");
    let ident = identity::Identity::generate();
    ident.save(&path).unwrap();
    let back = identity::Identity::load(&path).unwrap();
    assert_eq!(ident.node_id(), back.node_id());
    std::fs::remove_dir_all(dir).unwrap();
}

fn hex_decode(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
        .collect()
}
