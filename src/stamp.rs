//! What the board was built from: each command that applies pcb.toml to the board (`zone`, `paste`, `art`) records
//! a hash of the settings and files it read in a text on the comments layer, `pcb:inputs:<command> <hash>`: KiCad
//! keeps such a text through a load and save, where it drops board properties without their project file. `pcb check` computes the
//! hashes again: settings changed in pcb.toml but never applied (a new version for a `{version}` label, a moved
//! label, a dropped paste rule) are a `stale` finding, so the gate cannot pass and release cannot run on a board
//! that does not carry what pcb.toml says (review 16, 25 and 29).

use crate::board::Board;
use crate::project::Loaded;
use crate::sexpr;
use anyhow::Result;
use sha2::{Digest, Sha256};
use std::path::Path;

pub const COMMANDS: &[&str] = &["zone", "paste", "art"];

fn key(cmd: &str) -> String {
    format!("pcb:inputs:{cmd}")
}

/// The hash of what `cmd` reads, or None when pcb.toml gives it nothing to do.
pub fn inputs(l: &Loaded, cmd: &str) -> Result<Option<String>> {
    let p = &l.project;
    let base = l.path.parent().unwrap_or(Path::new("."));
    let mut h = Sha256::new();
    let mut put = |label: &str, bytes: &[u8]| {
        h.update(label.as_bytes());
        h.update((bytes.len() as u64).to_le_bytes());
        h.update(bytes);
    };
    match cmd {
        "zone" => {
            if p.zone.is_empty() && p.keepout.is_empty() && p.pad_override.is_empty() && p.net_tie.is_empty() && p.stitch.is_empty() && !p.nets.values().any(|r| r.fill_grow_mm.is_some()) {
                return Ok(None);
            }
            let fills: Vec<(&String, Option<f64>, Option<u32>)> = p.nets.iter().filter(|(_, r)| r.fill_grow_mm.is_some() || r.fill_priority.is_some()).map(|(n, r)| (n, r.fill_grow_mm, r.fill_priority)).collect();
            put("zone", serde_json::to_string(&(&p.zone, &p.keepout, &p.pad_override, &p.net_tie, &p.fill, &p.stitch, &fills))?.as_bytes());
        }
        "paste" => {
            if p.paste.is_empty() {
                return Ok(None);
            }
            put("paste", serde_json::to_string(&(&p.paste, p.assembly.as_ref().and_then(|a| a.pin_in_paste.as_ref())))?.as_bytes());
        }
        "art" => {
            if p.art.is_empty() && p.text.is_empty() {
                return Ok(None);
            }
            put("art", serde_json::to_string(&(&p.art, &p.text))?.as_bytes());
            if p.text.iter().any(|t| t.text.contains("{version}")) {
                put("version", p.project.version.as_bytes());
            }
            let mut files: Vec<&String> = p.art.iter().map(|a| &a.file).chain(p.text.iter().map(|t| &t.font)).collect();
            files.sort();
            files.dedup();
            for f in files {
                // a missing file is the command's to refuse; here it only changes the hash
                put(f, &std::fs::read(base.join(f)).unwrap_or_default());
            }
        }
        _ => anyhow::bail!("no inputs for {cmd}"),
    }
    Ok(Some(format!("{:x}", h.finalize())[..16].to_string()))
}

/// The hash the board records for `cmd`.
pub fn read(b: &Board, cmd: &str) -> Option<String> {
    let k = format!("{} ", key(cmd));
    b.root.find_all("gr_text").find_map(|t| t.arg(1).and_then(|x| x.strip_prefix(&k)).map(String::from))
}

/// The board text with `cmd`'s hash recorded (replaced, removed with None, or added at the end).
pub fn write(src: &str, cmd: &str, hash: Option<&str>) -> Result<String> {
    let root = sexpr::parse(src)?;
    let k = format!("{} ", key(cmd));
    let mut e = sexpr::Edits::default();
    let old: Vec<&sexpr::Node> = root.find_all("gr_text").filter(|t| t.arg(1).is_some_and(|x| x.starts_with(&k))).collect();
    let i = COMMANDS.iter().position(|c| *c == cmd).unwrap_or(0) as f64;
    let text = hash.map(|h| {
        format!(
            "(gr_text {} (at 0 {}) (layer \"Cmts.User\") (uuid \"{}\") (effects (font (size 0.5 0.5) (thickness 0.08)) (justify left)))",
            sexpr::quote(&format!("{k}{h}")),
            sexpr::fmt_num(-2.0 - i),
            crate::zone::name_uuid(&key(cmd))
        )
    });
    // in place when there is one, so a run that changes nothing writes the same bytes
    if let (Some(t), [one]) = (&text, old.as_slice()) {
        e.replace(one.span, t.clone());
        return e.apply(src);
    }
    for o in &old {
        crate::route::remove(&mut e, src, o.span);
    }
    if hash.is_some() {
        // after the setup, where no command adds or removes items, so later runs leave it in place
        match root.find("setup") {
            Some(st) => e.insert(st.span.1, format!("\n\t{}", text.unwrap_or_default())),
            None => e.insert(root.span.1 - 1, format!("\t{}\n", text.unwrap_or_default())),
        }
    } else if old.is_empty() {
        return Ok(src.to_string());
    }
    e.apply(src)
}

/// Commands whose recorded inputs differ from pcb.toml's, with why.
pub fn stale(l: &Loaded, b: &Board) -> Result<Vec<(String, String)>> {
    let mut v = vec![];
    for cmd in COMMANDS {
        let want = inputs(l, cmd)?;
        let have = read(b, cmd);
        if want != have {
            let why = match (&want, &have) {
                (Some(_), None) => format!("pcb {cmd} has not been run on this board since pcb.toml gave it work"),
                (None, Some(_)) => format!("pcb.toml no longer gives pcb {cmd} anything to do, but the board still carries what it made; run pcb {cmd} again"),
                _ => format!("pcb.toml's settings for pcb {cmd}, or a file they name, changed after it last ran; run pcb {cmd} again"),
            };
            v.push((cmd.to_string(), why));
        }
    }
    Ok(v)
}

#[cfg(test)]
mod tests {
    #[test]
    fn writes_and_replaces() {
        let src = "(kicad_pcb (version 20260206)\n\t(setup (pad_to_mask_clearance 0))\n)\n";
        let a = super::write(src, "art", Some("abc")).unwrap();
        assert!(a.contains("(gr_text \"pcb:inputs:art abc\""), "{a}");
        assert_eq!(super::read(&crate::board::Board::from_str(a.clone()).unwrap(), "art").as_deref(), Some("abc"));
        let b = super::write(&a, "art", Some("def")).unwrap();
        assert!(b.contains("art def") && !b.contains("art abc"), "{b}");
        let c = super::write(&b, "art", None).unwrap();
        assert!(!c.contains("pcb:inputs"), "{c}");
    }
}
