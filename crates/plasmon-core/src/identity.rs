//! Ed25519 machine identity. The node id is the hex public key.

use crate::{canonical, Error, Result};
use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use serde_json::Value;
use std::path::Path;

pub struct Identity {
    key: SigningKey,
}

impl Identity {
    pub fn generate() -> Self {
        let mut rng = rand::rngs::OsRng;
        Self {
            key: SigningKey::generate(&mut rng),
        }
    }

    pub fn from_seed(seed: &[u8]) -> Result<Self> {
        let bytes: [u8; 32] = seed
            .try_into()
            .map_err(|_| Error::Identity("seed must be 32 bytes".into()))?;
        Ok(Self {
            key: SigningKey::from_bytes(&bytes),
        })
    }

    pub fn load(path: &Path) -> Result<Self> {
        Self::from_seed(&std::fs::read(path)?)
    }

    /// Writes the 32-byte seed with mode 0600 on Unix.
    pub fn save(&self, path: &Path) -> Result<()> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let tmp = path.with_extension("key.tmp");
        std::fs::write(&tmp, self.key.to_bytes())?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&tmp, std::fs::Permissions::from_mode(0o600))?;
        }
        std::fs::rename(tmp, path)?;
        Ok(())
    }

    pub fn node_id(&self) -> String {
        hex::encode(self.key.verifying_key().to_bytes())
    }

    pub fn sign(&self, payload: &Value) -> Result<String> {
        let msg = canonical::dumps(payload)?;
        Ok(hex::encode(self.key.sign(&msg).to_bytes()))
    }
}

pub fn verify(node_id: &str, payload: &Value, signature_hex: &str) -> bool {
    let Ok(pk) = hex::decode(node_id) else {
        return false;
    };
    let Ok(pk): std::result::Result<[u8; 32], _> = pk.try_into() else {
        return false;
    };
    let Ok(key) = VerifyingKey::from_bytes(&pk) else {
        return false;
    };
    let Ok(sig) = hex::decode(signature_hex) else {
        return false;
    };
    let Ok(sig) = Signature::from_slice(&sig) else {
        return false;
    };
    let Ok(msg) = canonical::dumps(payload) else {
        return false;
    };
    key.verify(&msg, &sig).is_ok()
}

mod hex {
    pub fn encode(bytes: impl AsRef<[u8]>) -> String {
        bytes.as_ref().iter().map(|b| format!("{b:02x}")).collect()
    }

    pub fn decode(s: &str) -> Result<Vec<u8>, ()> {
        if !s.len().is_multiple_of(2) {
            return Err(());
        }
        (0..s.len())
            .step_by(2)
            .map(|i| u8::from_str_radix(&s[i..i + 2], 16).map_err(|_| ()))
            .collect()
    }
}
