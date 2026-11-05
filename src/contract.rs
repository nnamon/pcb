//! The output contract every command keeps (proposal, "Output contract for agents").
//!
//! With `--json` a command prints exactly one object:
//! `{schema, ok, outcome, written?, warnings[], error?, data}`, and exits with
//! 0 `done` (did what was asked; nothing got worse), 1 `rejected` (ran, the result made something worse, the board
//! is untouched), 2 `refused` (input or precondition the command does not take; nothing ran), 3 `failed` (an outside
//! tool crashed or timed out). Errors and warnings carry stable codes, listed in `docs/codes.md`.

use serde::Serialize;
use std::fmt;

#[derive(Serialize, Clone, Debug, PartialEq)]
pub struct Warning {
    pub code: String,
    pub message: String,
}

pub fn warn(code: &str, message: impl Into<String>) -> Warning {
    Warning { code: code.to_string(), message: message.into() }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Outcome {
    Done,
    Rejected,
    Refused,
    Failed,
}

impl Outcome {
    pub fn name(self) -> &'static str {
        match self {
            Outcome::Done => "done",
            Outcome::Rejected => "rejected",
            Outcome::Refused => "refused",
            Outcome::Failed => "failed",
        }
    }
    pub fn exit_code(self) -> i32 {
        match self {
            Outcome::Done => 0,
            Outcome::Rejected => 1,
            Outcome::Refused => 2,
            Outcome::Failed => 3,
        }
    }
}

/// An error with a stable code and the outcome it stands for.
#[derive(Debug)]
pub struct CodedError {
    pub outcome: Outcome,
    pub code: String,
    pub message: String,
}

impl fmt::Display for CodedError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for CodedError {}

/// Input or a precondition the command does not take.
pub fn refused(code: &str, message: impl Into<String>) -> anyhow::Error {
    anyhow::Error::new(CodedError { outcome: Outcome::Refused, code: code.to_string(), message: message.into() })
}

/// An outside tool (KiCad, Freerouting, the file system) crashed or timed out.
pub fn failed(code: &str, message: impl Into<String>) -> anyhow::Error {
    anyhow::Error::new(CodedError { outcome: Outcome::Failed, code: code.to_string(), message: message.into() })
}

/// The outcome and code of any error: a coded one says itself; an I/O error is a failure; anything else is a
/// refusal of the input.
pub fn classify(e: &anyhow::Error) -> (Outcome, String) {
    for cause in e.chain() {
        if let Some(c) = cause.downcast_ref::<CodedError>() {
            return (c.outcome, c.code.clone());
        }
        if cause.downcast_ref::<std::io::Error>().is_some() {
            return (Outcome::Failed, "io".to_string());
        }
    }
    (Outcome::Refused, "refused".to_string())
}

pub fn envelope(
    command: &str,
    outcome: Outcome,
    written: Option<&str>,
    warnings: &[Warning],
    error: Option<(&str, &str)>,
    data: serde_json::Value,
) -> serde_json::Value {
    let mut v = serde_json::json!({
        "schema": format!("pcb/{command}/1"),
        "ok": outcome == Outcome::Done,
        "outcome": outcome.name(),
        "warnings": warnings,
        "data": data,
    });
    if let Some(w) = written {
        v["written"] = serde_json::json!(w);
    }
    if let Some((code, message)) = error {
        v["error"] = serde_json::json!({ "code": code, "message": message });
    }
    v
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classify_codes() {
        let e = refused("arc-unsupported", "arcs");
        assert_eq!(classify(&e), (Outcome::Refused, "arc-unsupported".to_string()));
        let e = failed("freerouting-timeout", "slow").context("routing");
        assert_eq!(classify(&e), (Outcome::Failed, "freerouting-timeout".to_string()));
        let io: anyhow::Error = std::io::Error::new(std::io::ErrorKind::NotFound, "x").into();
        assert_eq!(classify(&io).0, Outcome::Failed);
        assert_eq!(classify(&anyhow::anyhow!("plain")).0, Outcome::Refused);
    }

    #[test]
    fn envelope_fields() {
        let v = envelope("route", Outcome::Rejected, Some("b.rejected.kicad_pcb"), &[warn("still-open", "VBUS_F")], None, serde_json::json!({}));
        assert_eq!(v["schema"], "pcb/route/1");
        assert_eq!(v["ok"], false);
        assert_eq!(v["outcome"], "rejected");
        assert_eq!(v["written"], "b.rejected.kicad_pcb");
        assert_eq!(v["warnings"][0]["code"], "still-open");
        assert_eq!(Outcome::Rejected.exit_code(), 1);
    }
}
