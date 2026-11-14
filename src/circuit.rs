//! Circuit checks over the netlist, run by `pcb check` as check `circuit`: faults a schematic can carry through ERC
//! and DRC and that stop a board working. Each is a rule of thumb that reads reference prefixes, pin names and net
//! names, so each finding can be waived with the reason it does not apply.
//!
//! - **decoupling:** a supply pin of an IC (reference `U` or `IC`) on a net with no capacitor to ground.
//! - **usb-cc:** a USB-C receptacle's CC1 or CC2 with neither a resistor nor a controller on it, the two tied
//!   together, or a pull-down that is not 5.1 kΩ. Without its own 5.1 kΩ on each, a USB-C source supplies no power.
//! - **i2c-pullup:** an I2C net (SDA or SCL by pin or net name) with no resistor to a supply.
//! - **crystal-load:** a crystal (reference `Y`) terminal with no capacitor to ground.
//! - **led-resistor:** a two-pin LED with no resistor on either terminal.
//!
//! Source: the comparison with Copper's design review (14 Nov 2026), which lists these among the faults agents
//! leave in schematics.

use crate::netlist::{Comp, Netlist};
use std::collections::{BTreeMap, BTreeSet};

pub struct Fault {
    /// `<kind> <reference> [<net or pin>]`: what a waiver names.
    pub item: String,
    pub message: String,
}

fn prefix(reference: &str) -> &str {
    let end = reference.find(|c: char| !c.is_ascii_alphabetic()).unwrap_or(reference.len());
    &reference[..end]
}

fn is(c: &str, kinds: &[&str]) -> bool {
    kinds.iter().any(|k| prefix(c).eq_ignore_ascii_case(k))
}

/// The tokens of a pin or net name: runs of letters and digits, upper case.
fn tokens(name: &str) -> Vec<String> {
    name.to_ascii_uppercase().split(|c: char| !c.is_ascii_alphanumeric()).filter(|t| !t.is_empty()).map(String::from).collect()
}

/// A net's own name: the last part of a hierarchical path (`/sensors/SDA` is `SDA`).
fn leaf(net: &str) -> &str {
    net.rsplit('/').next().unwrap_or(net)
}

pub fn is_ground(net: &str) -> bool {
    tokens(leaf(net)).iter().any(|t| t.contains("GND") || matches!(t.as_str(), "VSS" | "VSSA" | "VSSD" | "0V" | "EARTH"))
}

/// A supply by its name: `+3V3`, `VCC`, `VBUS`, `5V` and the like.
fn rail_name(net: &str) -> bool {
    let n = leaf(net);
    if n.starts_with('+') {
        return true;
    }
    let t = tokens(n);
    // an enable, a detect or a sense line of a supply is a signal
    if t.iter().any(|x| matches!(x.as_str(), "EN" | "DET" | "SENSE" | "GOOD" | "OK" | "PG" | "FLT" | "FAULT")) {
        return false;
    }
    t.iter().any(|t| {
        let volts = |t: &str| {
            let d: String = t.chars().filter(|c| c.is_ascii_digit()).collect();
            !d.is_empty() && t.contains('V') && t.chars().all(|c| c.is_ascii_digit() || c == 'V')
        };
        volts(t) || ["VCC", "VDD", "VBUS", "VBAT", "VIN", "VSYS", "VOUT", "AVDD", "DVDD", "VDDA", "VDDIO", "VREF"].iter().any(|k| t.starts_with(k))
    })
}

/// A supply pin by its name, for netlists that give no pin type. `VIN` is left out: `VIN+` and `VINP` are an
/// amplifier's inputs.
fn supply_pin(function: &str) -> bool {
    tokens(function).iter().any(|t| ["VCC", "VDD", "AVDD", "DVDD", "VDDA", "VDDIO", "VBAT", "IOVDD", "VCCIO"].iter().any(|k| t.starts_with(k)))
}

/// Ohms from a resistor's value: `5.1k`, `5k1`, `5.1 kΩ`, `5100`, `4R7`, `0R`.
pub fn ohms(value: &str) -> Option<f64> {
    let mut words = value.split_whitespace();
    let mut v = words.next()?.to_string();
    // "5.1 kΩ": the unit is its own word
    if let Some(w) = words.next()
        && w.chars().next().is_some_and(|c| matches!(c, 'R' | 'r' | 'k' | 'K' | 'M' | 'm' | '\u{2126}' | '\u{3a9}')) {
        v.push_str(w);
    }
    let lower = v.to_lowercase();
    for unit in ["ohms", "ohm", "ω"] {
        if lower.ends_with(unit) {
            v.truncate(v.len() - v.chars().rev().take(unit.chars().count()).map(char::len_utf8).sum::<usize>());
            break;
        }
    }
    let mult = |c: char| match c {
        'R' | 'r' => Some(1.0),
        'k' | 'K' => Some(1e3),
        'M' => Some(1e6),
        'm' => Some(1e-3),
        _ => None,
    };
    if let Some(i) = v.find(|c: char| mult(c).is_some()) {
        let m = mult(v[i..].chars().next()?)?;
        let (a, b) = (&v[..i], &v[i + 1..]);
        if a.is_empty() && b.is_empty() {
            return None;
        }
        // 5k1 is 5.1k; 5.1k has nothing after the letter
        let num: f64 = if b.is_empty() { a.parse().ok()? } else { format!("{}.{}", if a.is_empty() { "0" } else { a }, b).parse().ok()? };
        return Some(num * m);
    }
    v.parse().ok()
}

/// An IC's supply net and the capacitors on it that go to ground: what a decoupling loop is measured between.
pub struct Decap {
    pub ic: String,
    pub net: String,
    /// The IC's pins on the supply net.
    pub ic_pins: Vec<String>,
    /// The IC's pins on ground nets, as (pin, net).
    pub ground_pins: Vec<(String, String)>,
    /// (capacitor, its pin on the supply net, its pin on ground, the ground net).
    pub caps: Vec<(String, String, String, String)>,
}

/// Every IC supply net with a capacitor to ground on the net itself, by the `decoupling` rule's reading of the
/// netlist.
pub fn decoupling_pairs(n: &Netlist) -> Vec<Decap> {
    let mut pins: BTreeMap<&str, Vec<(&str, &str, &str, &str)>> = BTreeMap::new();
    for net in &n.nets {
        for x in &net.nodes {
            pins.entry(x.reference.as_str()).or_default().push((&x.pin, &x.function, &x.pintype, &net.name));
        }
    }
    let mut out = vec![];
    for c in n.comps.iter().filter(|c| is(&c.reference, &["U", "IC"])) {
        let Some(ps) = pins.get(c.reference.as_str()) else { continue };
        let supply: BTreeSet<&str> = ps.iter().filter(|q| (q.2 == "power_in" || (q.2.is_empty() || q.2 == "passive") && supply_pin(q.1)) && !is_ground(q.3)).map(|q| q.3).collect();
        let ground_pins: Vec<(String, String)> = ps.iter().filter(|q| is_ground(q.3)).map(|q| (q.0.to_string(), q.3.to_string())).collect();
        for net in supply {
            let caps: Vec<(String, String, String, String)> = pins
                .iter()
                .filter(|(r, v)| is(r, &["C"]) && v.len() == 2 && v.iter().any(|q| q.3 == net) && v.iter().any(|q| is_ground(q.3)))
                .map(|(r, v)| {
                    let (s, g) = (v.iter().find(|q| q.3 == net).unwrap(), v.iter().find(|q| is_ground(q.3)).unwrap());
                    (r.to_string(), s.0.to_string(), g.0.to_string(), g.3.to_string())
                })
                .collect();
            if !caps.is_empty() {
                out.push(Decap { ic: c.reference.clone(), net: net.to_string(), ic_pins: ps.iter().filter(|q| q.3 == net).map(|q| q.0.to_string()).collect(), ground_pins: ground_pins.clone(), caps });
            }
        }
    }
    out
}

pub fn run(n: &Netlist) -> Vec<Fault> {
    let comp: BTreeMap<&str, &Comp> = n.comps.iter().map(|c| (c.reference.as_str(), c)).collect();
    // the pins of each part, as (pin, function, pintype, net); a net with one pin connects nothing
    let mut pins: BTreeMap<&str, Vec<(&str, &str, &str, &str)>> = BTreeMap::new();
    let mut members: BTreeMap<&str, Vec<(&str, &str)>> = BTreeMap::new();
    for net in &n.nets {
        for x in &net.nodes {
            pins.entry(x.reference.as_str()).or_default().push((&x.pin, &x.function, &x.pintype, &net.name));
            members.entry(net.name.as_str()).or_default().push((&x.reference, &x.pin));
        }
    }
    let empty = vec![];
    let on = |net: &str| members.get(net).unwrap_or(&empty);
    // the nets at the other pins of a two-pin part, seen from one net
    let other_nets = |reference: &str, net: &str| -> Vec<&str> { pins.get(reference).map(|v| v.iter().filter(|q| q.3 != net).map(|q| q.3).collect()).unwrap_or_default() };
    let is_rail = |net: &str| rail_name(net) || on(net).iter().any(|(r, p)| pins.get(r).is_some_and(|v| v.iter().any(|q| q.0 == *p && (q.2 == "power_in" || q.2 == "power_out"))));
    // parts of a kind on a net whose other pin is on a net the test takes
    let bridged = |net: &str, kinds: &[&str], to: &dyn Fn(&str) -> bool| -> Vec<&str> {
        let mut v: Vec<&str> = on(net).iter().filter(|(r, _)| is(r, kinds) && other_nets(r, net).iter().any(|o| to(o))).map(|(r, _)| *r).collect();
        v.sort();
        v.dedup();
        v
    };
    let single = |net: &str| on(net).len() <= 1;
    // the nets one series part away: through a ferrite bead, an inductor, or a resistor (any, or only a link of
    // 1 Ω or less)
    let through = |net: &str, any_resistor: bool| -> Vec<&str> {
        on(net)
            .iter()
            .filter(|(r, _)| pins.get(r).is_some_and(|v| v.len() == 2) && (is(r, &["FB", "L"]) || is(r, &["R"]) && (any_resistor || comp.get(r).and_then(|c| ohms(&c.value)).is_some_and(|o| o <= 1.0))))
            .flat_map(|(r, _)| other_nets(r, net))
            .collect()
    };
    let mut out = vec![];
    let mut add = |kind: &str, reference: &str, rest: &str, message: String| {
        out.push(Fault { item: format!("{kind} {reference}{}{rest}", if rest.is_empty() { "" } else { " " }), message })
    };

    for c in &n.comps {
        let r = c.reference.as_str();
        let Some(ps) = pins.get(r) else { continue };

        // decoupling
        if is(r, &["U", "IC"]) {
            let nets: BTreeSet<&str> = ps.iter().filter(|q| (q.2 == "power_in" || (q.2.is_empty() || q.2 == "passive") && supply_pin(q.1)) && !is_ground(q.3) && !single(q.3)).map(|q| q.3).collect();
            for net in nets {
                // the capacitor may sit on the far side of a bead or a 0 Ω link
                if bridged(net, &["C"], &is_ground).is_empty() && !through(net, false).iter().any(|far| !bridged(far, &["C"], &is_ground).is_empty()) {
                    add("decoupling", r, net, format!("{r} is supplied from {net}, which has no capacitor to ground; add a decoupling capacitor at its supply pin"));
                }
            }
        }

        // a USB-C receptacle's configuration pins
        if is(r, &["J", "P", "CN", "USB", "USBC", "X"]) {
            // the pin's name, or its first word: a schematic made from JLCPCB's symbols names pins `CC1_A5`
            // `CC2_EN` and `CC1101_GDO` are not configuration pins: the other words may only be pin numbers
            let cc_name = |f: &str| {
                let t = tokens(f);
                let pin_number = |x: &str| x.len() >= 2 && x.starts_with(['A', 'B']) && x[1..].chars().all(|c| c.is_ascii_digit());
                let cc: Vec<&String> = t.iter().filter(|x| *x == "CC1" || *x == "CC2").collect();
                (cc.len() == 1 && t.iter().all(|x| x == cc[0] || pin_number(x))).then(|| cc[0].clone())
            };
            let cc: Vec<(String, &str)> = ps.iter().filter_map(|q| Some((cc_name(q.1)?, q.3))).collect();
            let names: BTreeSet<String> = cc.iter().map(|q| q.0.clone()).collect();
            if names.len() == 2 {
                let nets: BTreeSet<&str> = cc.iter().map(|q| q.1).collect();
                if nets.len() == 1 && !single(nets.iter().next().unwrap()) {
                    add("usb-cc", r, "", format!("{r}'s CC1 and CC2 are tied together on {}; each needs its own 5.1 kΩ to ground, or a cable with an e-marker pulls both low and the source supplies nothing", nets.iter().next().unwrap()));
                } else {
                    for (name, net) in nets.iter().map(|net| (cc.iter().find(|q| q.1 == *net).unwrap().0.as_str(), *net)) {
                        // a controller on the net, or behind one series resistor
                        let has_ic = |x: &str| on(x).iter().any(|(o, _)| is(o, &["U", "IC", "Q"]));
                        let controller = has_ic(net) || through(net, true).iter().any(|far| !is_ground(far) && has_ic(far));
                        let down = bridged(net, &["R"], &is_ground);
                        let up = bridged(net, &["R"], &is_rail);
                        if controller || !up.is_empty() {
                            continue;
                        }
                        if down.is_empty() {
                            add("usb-cc", r, name, format!("{r}'s {name} has no 5.1 kΩ to ground and no controller on it; a USB-C source supplies no power to a device that does not pull CC down"));
                        } else if let Some(bad) = down.iter().find(|d| comp.get(*d).and_then(|x| ohms(&x.value)).is_some_and(|o| (o - 5100.0).abs() > 5100.0 * 0.06)) {
                            add("usb-cc", r, name, format!("{r}'s {name} is pulled down by {bad} ({}); a device's pull-down is 5.1 kΩ", comp[bad].value));
                        }
                    }
                }
            }
        }

        // a crystal's load capacitors
        if is(r, &["Y"]) {
            let powered = ps.iter().any(|q| q.2 == "power_in" || q.2 == "output" || q.2 == "power_out" || is_rail(q.3) && !is_ground(q.3));
            let nets: BTreeSet<&str> = ps.iter().filter(|q| !is_ground(q.3) && !single(q.3)).map(|q| q.3).collect();
            if !powered && nets.len() == 2 {
                let bare: Vec<&str> = nets.into_iter().filter(|net| bridged(net, &["C"], &is_ground).is_empty()).collect();
                if !bare.is_empty() {
                    add("crystal-load", r, "", format!("crystal {r} has no load capacitor to ground on {}; without both it starts off frequency or not at all, unless the IC has them inside", bare.join(" and ")));
                }
            }
        }

        // an LED's series resistor: on a terminal that is neither ground nor a supply, where a resistor there is
        // in the LED's path. A resistor elsewhere on ground or the rail says nothing.
        let led = is(r, &["LED"]) || is(r, &["D"]) && (tokens(&c.value).iter().any(|t| t == "LED") || tokens(&c.footprint).iter().any(|t| t.starts_with("LED")));
        if led && ps.len() == 2 && ps.iter().all(|q| !single(q.3)) {
            let limited = ps.iter().any(|q| !is_ground(q.3) && !is_rail(q.3) && on(q.3).iter().any(|(o, _)| is(o, &["R", "RN"])));
            if !limited {
                add("led-resistor", r, "", format!("LED {r} has no resistor in series on either terminal ({} and {}); add one, or waive it if a constant-current driver feeds it", ps[0].3, ps[1].3));
            }
        }
    }

    // I2C pull-ups, once per net
    let i2c = |name: &str| {
        let t = tokens(name);
        let line = |x: &str| x.starts_with("SDA") && x[3..].chars().all(|c| c.is_ascii_digit()) || x.starts_with("SCL") && x[3..].chars().all(|c| c.is_ascii_digit());
        let bus = |x: &str| x.starts_with("I2C") || x.starts_with("TWI") || x.chars().all(|c| c.is_ascii_digit());
        t.iter().any(|x| line(x)) && t.iter().all(|x| line(x) || bus(x))
    };
    for net in &n.nets {
        if net.nodes.len() < 2 || is_ground(&net.name) {
            continue;
        }
        let by_pin = net.nodes.iter().filter(|x| is(&x.reference, &["U", "IC", "J", "P", "CN"]) && i2c(&x.function)).count();
        // by its own name a net is I2C when any word of it is SDA or SCL (`SENSOR_SDA`, `/bus/SCL1`)
        let line_word = |x: &str| (x.starts_with("SDA") || x.starts_with("SCL")) && x[3..].chars().all(|c| c.is_ascii_digit());
        if by_pin == 0 && !tokens(leaf(&net.name)).iter().any(|x| line_word(x)) {
            continue;
        }
        if bridged(&net.name, &["R", "RN"], &|o| is_rail(o) && !is_ground(o)).is_empty() {
            let at = net.nodes.iter().find(|x| is(&x.reference, &["U", "IC"])).unwrap_or(&net.nodes[0]);
            add("i2c-pullup", &at.reference, &net.name, format!("I2C net {} has no pull-up resistor to a supply; the bus idles low and no device answers, unless a module on it carries the pull-ups", net.name));
        }
    }
    out.sort_by(|a, b| a.item.cmp(&b.item));
    out.dedup_by(|a, b| a.item == b.item);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A netlist from `(ref, value)` parts and `net: [(ref, pin, function, pintype)]`.
    fn nl(comps: &[(&str, &str)], nets: &[(&str, &[(&str, &str, &str, &str)])]) -> Netlist {
        let q = |s: &str| format!("{s:?}");
        let mut t = String::from("(export (components");
        for (r, v) in comps {
            t += &format!(" (comp (ref {}) (value {}) (footprint \"x:y\"))", q(r), q(v));
        }
        t += ") (nets";
        for (name, nodes) in nets {
            t += &format!(" (net (name {})", q(name));
            for (r, p, f, k) in *nodes {
                t += &format!(" (node (ref {}) (pin {}) (pinfunction {}) (pintype {}))", q(r), q(p), q(f), q(k));
            }
            t += ")";
        }
        t += "))";
        crate::netlist::parse(&t).unwrap()
    }

    fn items(n: &Netlist) -> Vec<String> {
        run(n).into_iter().map(|f| f.item).collect()
    }

    #[test]
    fn resistor_values() {
        assert_eq!(ohms("5.1k"), Some(5100.0));
        assert_eq!(ohms("5k1"), Some(5100.0));
        assert_eq!(ohms("5.1kΩ"), Some(5100.0));
        assert_eq!(ohms("4R7"), Some(4.7));
        assert_eq!(ohms("330"), Some(330.0));
        assert_eq!(ohms("10K 1%"), Some(10000.0));
        assert_eq!(ohms("DNP"), None);
        // review 22, 2
        assert_eq!(ohms("5.1 kΩ"), Some(5100.0));
        assert_eq!(ohms("5.1 k"), Some(5100.0));
        assert_eq!(ohms("0R"), Some(0.0));
        assert_eq!(ohms("2m"), Some(0.002));
        assert_eq!(ohms("100 ohm"), Some(100.0));
        assert_eq!(ohms(""), None);
    }

    #[test]
    fn names() {
        assert!(is_ground("GND") && is_ground("/AGND") && is_ground("VSS") && !is_ground("VSENSE"));
        assert!(rail_name("+3V3") && rail_name("VBUS") && rail_name("3V3") && rail_name("/5V") && !rail_name("SDA") && !rail_name("V"));
        // review 22, 6: a sheet's name is not the net's, and an enable or a detect line is not a supply
        assert!(!rail_name("/pwr/LED_K") && !rail_name("PWR_EN") && !rail_name("VBUS_DET") && rail_name("/pwr/VBUS") && is_ground("/pwr/GND") && !is_ground("/gnd_sense/X"));
    }

    #[test]
    fn decoupling_needs_a_capacitor_to_ground() {
        let bad = nl(&[("U1", "MCU"), ("R1", "10k")], &[("+3V3", &[("U1", "1", "VDD", "power_in"), ("R1", "1", "", "passive")]), ("GND", &[("U1", "2", "VSS", "power_in"), ("R1", "2", "", "passive")])]);
        assert_eq!(items(&bad), ["decoupling U1 +3V3"]);
        let good = nl(&[("U1", "MCU"), ("C1", "100n")], &[("+3V3", &[("U1", "1", "VDD", "power_in"), ("C1", "1", "", "passive")]), ("GND", &[("U1", "2", "VSS", "power_in"), ("C1", "2", "", "passive")])]);
        assert!(items(&good).is_empty());
        // no pin type: the pin's name says supply
        let named = nl(&[("U1", "MCU"), ("R1", "10k")], &[("N1", &[("U1", "1", "VDD", "passive"), ("R1", "1", "", "passive")]), ("GND", &[("U1", "2", "GND", "passive"), ("R1", "2", "", "passive")])]);
        assert_eq!(items(&named), ["decoupling U1 N1"]);
    }

    #[test]
    fn usb_c_configuration_pins() {
        let gnd: (&str, &[(&str, &str, &str, &str)]) = ("GND", &[("J1", "A1", "GND", "passive"), ("R1", "2", "", "passive"), ("R2", "2", "", "passive")]);
        let good = nl(&[("J1", "USB-C"), ("R1", "5.1k"), ("R2", "5k1")], &[("CC1", &[("J1", "A5", "CC1", "passive"), ("R1", "1", "", "passive")]), ("CC2", &[("J1", "B5", "CC2", "passive"), ("R2", "1", "", "passive")]), gnd]);
        assert!(items(&good).is_empty(), "{:?}", items(&good));
        let open = nl(&[("J1", "USB-C"), ("R1", "5.1k"), ("R2", "5.1k"), ("R3", "1k")], &[("CC1", &[("J1", "A5", "CC1", "passive"), ("R1", "1", "", "passive")]), ("CC2", &[("J1", "B5", "CC2", "passive"), ("R3", "1", "", "passive")]), ("X", &[("R3", "2", "", "passive"), ("R2", "1", "", "passive")]), gnd]);
        assert_eq!(items(&open), ["usb-cc J1 CC2"]);
        let tied = nl(&[("J1", "USB-C"), ("R1", "5.1k")], &[("CC", &[("J1", "A5", "CC1", "passive"), ("J1", "B5", "CC2", "passive"), ("R1", "1", "", "passive")]), gnd]);
        assert_eq!(items(&tied), ["usb-cc J1"]);
        let wrong = nl(&[("J1", "USB-C"), ("R1", "10k"), ("R2", "5.1k")], &[("CC1", &[("J1", "A5", "CC1", "passive"), ("R1", "1", "", "passive")]), ("CC2", &[("J1", "B5", "CC2", "passive"), ("R2", "1", "", "passive")]), gnd]);
        assert_eq!(items(&wrong), ["usb-cc J1 CC1"]);
        // pin names with the pin number after them, as a schematic from JLCPCB's symbols has
        let suffixed = nl(&[("J1", "USB-C"), ("R1", "10k"), ("R2", "5.1k")], &[("CC1", &[("J1", "A5", "CC1_A5", "passive"), ("R1", "1", "", "passive")]), ("CC2", &[("J1", "B5", "CC2_B5", "passive"), ("R2", "1", "", "passive")]), gnd]);
        assert_eq!(items(&suffixed), ["usb-cc J1 CC1"]);
        // review 23, 13: an enable named after a CC line is not one
        let enables = nl(&[("J1", "hdr"), ("R1", "10k"), ("R2", "10k")], &[("A", &[("J1", "1", "CC1_EN", "passive"), ("R1", "1", "", "passive")]), ("B", &[("J1", "2", "CC2_EN", "passive"), ("R2", "1", "", "passive")]), gnd]);
        assert!(items(&enables).is_empty(), "{:?}", items(&enables));
        let controller = nl(&[("J1", "USB-C"), ("U1", "PD")], &[("CC1", &[("J1", "A5", "CC1", "passive"), ("U1", "1", "CC1", "bidirectional")]), ("CC2", &[("J1", "B5", "CC2", "passive"), ("U1", "2", "CC2", "bidirectional")])]);
        assert!(items(&controller).is_empty());
    }

    #[test]
    fn i2c_needs_a_pull_up() {
        let rail: (&str, &[(&str, &str, &str, &str)]) = ("+3V3", &[("R1", "2", "", "passive"), ("C1", "1", "", "passive"), ("U1", "9", "VDD", "power_in")]);
        let gnd: (&str, &[(&str, &str, &str, &str)]) = ("GND", &[("C1", "2", "", "passive"), ("U1", "8", "GND", "power_in")]);
        let bad = nl(&[("U1", "MCU"), ("U2", "sensor"), ("R1", "10k"), ("C1", "100n")], &[("SDA", &[("U1", "1", "PB7", "bidirectional"), ("U2", "1", "SDA", "bidirectional")]), rail, gnd]);
        assert_eq!(items(&bad), ["i2c-pullup U1 SDA"]);
        let good = nl(&[("U1", "MCU"), ("U2", "sensor"), ("R1", "4.7k"), ("C1", "100n")], &[("SDA", &[("U1", "1", "PB7", "bidirectional"), ("U2", "1", "SDA", "bidirectional"), ("R1", "1", "", "passive")]), rail, gnd]);
        assert!(items(&good).is_empty(), "{:?}", items(&good));
        // a pin that can be SDA among other things is not an I2C net by that alone
        let gpio = nl(&[("U1", "MCU"), ("U2", "x"), ("R1", "1k"), ("C1", "100n")], &[("LED_EN", &[("U1", "1", "GPIO4/I2C0_SDA/UART1_TX", "bidirectional"), ("U2", "1", "EN", "input")]), rail, gnd]);
        assert!(items(&gpio).is_empty(), "{:?}", items(&gpio));
    }

    #[test]
    fn crystal_and_led() {
        let gnd: (&str, &[(&str, &str, &str, &str)]) = ("GND", &[("C1", "2", "", "passive"), ("U1", "8", "GND", "power_in"), ("D1", "1", "K", "passive")]);
        let n = nl(
            &[("Y1", "12MHz"), ("C1", "15p"), ("U1", "MCU"), ("D1", "LED red")],
            &[("XI", &[("Y1", "1", "", "passive"), ("C1", "1", "", "passive"), ("U1", "1", "XI", "input")]), ("XO", &[("Y1", "2", "", "passive"), ("U1", "2", "XO", "output")]), ("IO", &[("D1", "2", "A", "passive"), ("U1", "3", "PA1", "bidirectional")]), gnd],
        );
        assert_eq!(items(&n), ["crystal-load Y1", "led-resistor D1"]);
    }

    // review 22, 1: a resistor elsewhere on ground does not stand in for the LED's own
    #[test]
    fn led_resistor_must_be_in_its_path() {
        let rail: (&str, &[(&str, &str, &str, &str)]) = ("+3V3", &[("U1", "9", "VDD", "power_in"), ("C1", "1", "", "passive"), ("D2", "2", "A", "passive")]);
        let n = nl(
            &[("U1", "MCU"), ("C1", "100n"), ("D1", "LED"), ("D2", "LED"), ("R1", "5.1k"), ("R2", "330")],
            &[
                ("IO", &[("D1", "2", "A", "passive"), ("U1", "3", "PA1", "bidirectional")]),
                ("GND", &[("D1", "1", "K", "passive"), ("R1", "2", "", "passive"), ("C1", "2", "", "passive"), ("U1", "8", "GND", "power_in"), ("R2", "2", "", "passive")]),
                ("CC", &[("R1", "1", "", "passive"), ("U1", "4", "PA2", "bidirectional")]),
                ("D2K", &[("D2", "1", "K", "passive"), ("R2", "1", "", "passive")]),
                rail,
            ],
        );
        assert_eq!(items(&n), ["led-resistor D1"]);
    }

    // review 22, 4 and 5: a controller behind a series resistor; an amplifier's VIN+; a capacitor behind a bead
    #[test]
    fn series_parts_and_input_pins() {
        let n = nl(
            &[("J1", "USB-C"), ("R1", "22"), ("R2", "22"), ("U1", "PD"), ("U2", "amp"), ("FB1", "600R"), ("C1", "100n"), ("R3", "0.01")],
            &[
                ("CC1", &[("J1", "A5", "CC1", "passive"), ("R1", "1", "", "passive")]),
                ("CC2", &[("J1", "B5", "CC2", "passive"), ("R2", "1", "", "passive")]),
                ("C1U", &[("R1", "2", "", "passive"), ("U1", "1", "CC1", "passive")]),
                ("C2U", &[("R2", "2", "", "passive"), ("U1", "2", "CC2", "passive")]),
                ("SHUNT_P", &[("U2", "1", "VIN+", "passive"), ("R3", "1", "", "passive")]),
                ("SHUNT_N", &[("U2", "2", "VIN-", "passive"), ("R3", "2", "", "passive")]),
                ("VA", &[("U2", "3", "VDD", "passive"), ("FB1", "2", "", "passive")]),
                ("+3V3", &[("FB1", "1", "", "passive"), ("C1", "1", "", "passive")]),
                ("GND", &[("C1", "2", "", "passive"), ("U2", "4", "GND", "passive"), ("U1", "3", "GND", "passive")]),
            ],
        );
        assert!(items(&n).is_empty(), "{:?}", items(&n));
    }

    // review 22, 6
    #[test]
    fn i2c_by_net_name() {
        let n = nl(&[("U1", "MCU"), ("J1", "hdr"), ("R1", "10k")], &[("/sensors/SENSOR_SDA", &[("U1", "1", "PB7", "bidirectional"), ("J1", "1", "1", "passive")]), ("GND", &[("U1", "2", "GND", "passive"), ("R1", "1", "", "passive")]), ("X", &[("R1", "2", "", "passive"), ("J1", "2", "2", "passive")])]);
        assert_eq!(items(&n), ["i2c-pullup U1 /sensors/SENSOR_SDA"]);
    }
}
