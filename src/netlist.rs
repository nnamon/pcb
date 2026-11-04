//! The circuit as KiCad exports it: a netlist (`kicadsexpr`), read from a `.net` file or exported from a
//! `.kicad_sch` by `kicad-cli sch export netlist`.

use crate::contract::{failed, refused};
use crate::sexpr;
use anyhow::Result;
use std::collections::BTreeMap;
use std::path::Path;

#[derive(Debug, Clone, serde::Serialize)]
pub struct Comp {
    pub reference: String,
    pub value: String,
    /// The symbol's Footprint field (`LIB:NAME`), empty when it has none.
    pub footprint: String,
    /// Other fields (LCSC, DNP and so on), by name.
    pub fields: BTreeMap<String, String>,
}

impl Comp {
    /// The footprint attributes the schematic's flags ask for: `dnp` (not fitted: out of the BOM and CPL too) and
    /// `exclude_from_bom` (review 19, 49).
    pub fn flags(&self) -> Vec<&'static str> {
        // a flag KiCad writes has no value; a field the designer made says yes or no (review 20, 60)
        let has = |k: &str| {
            self.fields.iter().any(|(f, v)| {
                f.eq_ignore_ascii_case(k) && matches!(v.trim().to_ascii_lowercase().as_str(), "" | "yes" | "y" | "true" | "1" | "x" | "dnp")
            })
        };
        let mut v = vec![];
        if has("dnp") {
            v.extend(["exclude_from_pos_files", "exclude_from_bom", "dnp"]);
        } else if has("exclude_from_bom") {
            v.push("exclude_from_bom");
        }
        v
    }

    /// The LCSC code, from a field named LCSC (any case) or "LCSC Part #".
    pub fn lcsc(&self) -> Option<String> {
        self.fields.iter().find(|(k, _)| {
            let k = k.to_ascii_uppercase();
            k == "LCSC" || k == "LCSC PART #" || k == "LCSC PART"
        }).map(|(_, v)| v.trim().to_string()).filter(|v| !v.is_empty())
    }
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct Node {
    pub reference: String,
    pub pin: String,
    /// The symbol's pin name, as KiCad gives it (`pinfunction`), empty when the pin has none.
    pub function: String,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct Net {
    pub name: String,
    pub nodes: Vec<Node>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct Netlist {
    pub comps: Vec<Comp>,
    pub nets: Vec<Net>,
}

impl Netlist {
    /// The net each pin is on, by (reference, pin).
    pub fn pin_nets(&self) -> BTreeMap<(String, String), String> {
        let mut m = BTreeMap::new();
        for n in &self.nets {
            for x in &n.nodes {
                m.insert((x.reference.clone(), x.pin.clone()), n.name.clone());
            }
        }
        m
    }

    /// A net with one pin connects nothing: KiCad names such a pin's net `unconnected-(...)` or `Net-(...)`.
    pub fn is_single(&self, net: &str) -> bool {
        self.nets.iter().find(|n| n.name == net).map(|n| n.nodes.len() <= 1).unwrap_or(true)
    }
}

/// Read the netlist a project names: a `.net` file as it is, a `.kicad_sch` through kicad-cli into `work`.
pub fn load(path: &Path, work: &Path) -> Result<Netlist> {
    if !path.exists() {
        return Err(refused("config", format!("{}: no such netlist or schematic", path.display())));
    }
    let text = if path.extension().and_then(|e| e.to_str()) == Some("kicad_sch") {
        std::fs::create_dir_all(work).map_err(|e| failed("io", format!("{}: {e}", work.display())))?;
        let out = work.join("netlist.net");
        let r = std::process::Command::new("kicad-cli")
            .args(["sch", "export", "netlist", "--format", "kicadsexpr", "-o"])
            .arg(&out)
            .arg(path)
            .output()
            .map_err(|e| failed("kicad-cli", format!("running kicad-cli: {e}")))?;
        if !r.status.success() || !out.exists() {
            return Err(failed("kicad-cli", format!("kicad-cli could not export the netlist of {}: {}", path.display(), String::from_utf8_lossy(&r.stderr).trim())));
        }
        std::fs::read_to_string(&out)?
    } else {
        std::fs::read_to_string(path).map_err(|e| failed("io", format!("{}: {e}", path.display())))?
    };
    parse(&text).map_err(|e| refused("netlist", format!("{}: {e}", path.display())))
}

pub fn parse(text: &str) -> Result<Netlist> {
    let root = sexpr::parse(text)?;
    if !root.is("export") {
        anyhow::bail!("not a KiCad netlist (no export list)");
    }
    let s = |n: &sexpr::Node, k: &str| n.find(k).and_then(|x| x.arg(1)).unwrap_or("").to_string();
    let mut comps = vec![];
    if let Some(cs) = root.find("components") {
        for c in cs.find_all("comp") {
            let mut fields = BTreeMap::new();
            if let Some(fs) = c.find("fields") {
                for f in fs.find_all("field") {
                    if let Some(nm) = f.find("name").and_then(|x| x.arg(1)) {
                        let v = f.arg(2).unwrap_or("").to_string();
                        fields.insert(nm.to_string(), v);
                    }
                }
            }
            for p in c.find_all("property") {
                // a flag (dnp, exclude_from_bom) is a property with no value
                if let Some(k) = p.find("name").and_then(|x| x.arg(1)) {
                    let v = p.find("value").and_then(|x| x.arg(1)).unwrap_or("");
                    fields.entry(k.to_string()).or_insert_with(|| v.to_string());
                }
            }
            let reference = s(c, "ref");
            if reference.is_empty() {
                anyhow::bail!("a component has no reference");
            }
            comps.push(Comp { reference, value: s(c, "value"), footprint: s(c, "footprint"), fields });
        }
    }
    let mut seen = std::collections::BTreeSet::new();
    for c in &comps {
        if !seen.insert(c.reference.clone()) {
            anyhow::bail!("two components are {}; annotate the schematic", c.reference);
        }
        if c.reference.contains('?') {
            anyhow::bail!("{} is not annotated", c.reference);
        }
    }
    let mut nets = vec![];
    if let Some(ns) = root.find("nets") {
        for n in ns.find_all("net") {
            let nodes = n.find_all("node").map(|x| Node { reference: s(x, "ref"), pin: s(x, "pin"), function: s(x, "pinfunction") }).collect();
            nets.push(Net { name: s(n, "name"), nodes });
        }
    }
    Ok(Netlist { comps, nets })
}

#[cfg(test)]
mod tests {
    #[test]
    fn reads_comps_and_nets() {
        let t = r#"(export (version "E")
  (components
    (comp (ref "U3") (value "XC6206") (footprint "pcb:C5446")
      (fields (field (name "Footprint") "pcb:C5446") (field (name "LCSC") "C5446"))))
  (nets
    (net (code "1") (name "GND") (class "Default") (node (ref "U3") (pin "1") (pinfunction "VSS") (pintype "power_in")))))"#;
        let n = super::parse(t).unwrap();
        assert_eq!(n.comps[0].lcsc().as_deref(), Some("C5446"));
        assert_eq!(n.nets[0].nodes[0].function, "VSS");
    }

    #[test]
    fn refuses_duplicates() {
        let t = r#"(export (components (comp (ref "R1")) (comp (ref "R1"))) (nets))"#;
        assert!(super::parse(t).is_err());
    }
}
