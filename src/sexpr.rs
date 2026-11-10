//! KiCad S-expressions with source spans.
//!
//! Every node keeps the byte range it came from, so the file can be edited by splicing new text into those ranges.
//! An unedited file is written back byte for byte, and a hand edit made in KiCad survives any edit `pcb` makes
//! elsewhere in the file.

use anyhow::{Result, bail};

#[derive(Debug, Clone)]
pub enum Kind {
    List(Vec<Node>),
    /// An atom, quoted ("strings") or bare.
    Atom { text: String },
}

#[derive(Debug, Clone)]
pub struct Node {
    pub kind: Kind,
    /// Byte range in the source, `start..end`.
    pub span: (usize, usize),
}

impl Node {
    pub fn items(&self) -> &[Node] {
        match &self.kind {
            Kind::List(v) => v,
            Kind::Atom { .. } => &[],
        }
    }

    pub fn atom(&self) -> Option<&str> {
        match &self.kind {
            Kind::Atom { text, .. } => Some(text),
            Kind::List(_) => None,
        }
    }

    /// The first atom of a list: `(footprint ...)` gives "footprint".
    pub fn head(&self) -> Option<&str> {
        self.items().first().and_then(|n| n.atom())
    }

    pub fn is(&self, name: &str) -> bool {
        self.head() == Some(name)
    }

    /// The first child list with this head.
    pub fn find(&self, name: &str) -> Option<&Node> {
        self.items().iter().find(|n| n.is(name))
    }

    pub fn find_all<'a>(&'a self, name: &'a str) -> impl Iterator<Item = &'a Node> + 'a {
        self.items().iter().filter(move |n| n.is(name))
    }

    /// The atom at position `i` (0 is the head).
    pub fn arg(&self, i: usize) -> Option<&str> {
        self.items().get(i).and_then(|n| n.atom())
    }

    pub fn num(&self, i: usize) -> Option<f64> {
        self.arg(i).and_then(|s| s.parse().ok())
    }

    /// Atom arguments after the head, for flags such as `(layers "F.Cu" "F.Paste")` or `locked`.
    pub fn args(&self) -> Vec<&str> {
        self.items().iter().skip(1).filter_map(|n| n.atom()).collect()
    }
}

pub fn parse(src: &str) -> Result<Node> {
    let b = src.as_bytes();
    let mut i = 0;
    skip_ws(b, &mut i);
    let n = parse_node(src, b, &mut i)?;
    Ok(n)
}

fn skip_ws(b: &[u8], i: &mut usize) {
    while *i < b.len() && (b[*i] as char).is_ascii_whitespace() {
        *i += 1;
    }
}

fn parse_node(src: &str, b: &[u8], i: &mut usize) -> Result<Node> {
    skip_ws(b, i);
    if *i >= b.len() {
        bail!("unexpected end of file");
    }
    let start = *i;
    match b[*i] {
        b'(' => {
            *i += 1;
            let mut items = Vec::new();
            loop {
                skip_ws(b, i);
                if *i >= b.len() {
                    bail!("unclosed list starting at byte {start}");
                }
                if b[*i] == b')' {
                    *i += 1;
                    break;
                }
                items.push(parse_node(src, b, i)?);
            }
            Ok(Node { kind: Kind::List(items), span: (start, *i) })
        }
        b')' => bail!("unexpected ')' at byte {start}"),
        b'"' => {
            *i += 1;
            let mut text = String::new();
            loop {
                if *i >= b.len() {
                    bail!("unclosed string at byte {start}");
                }
                match b[*i] {
                    b'\\' if *i + 1 < b.len() => {
                        let c = b[*i + 1];
                        text.push(match c {
                            b'n' => '\n',
                            b't' => '\t',
                            other => other as char,
                        });
                        *i += 2;
                    }
                    b'"' => {
                        *i += 1;
                        break;
                    }
                    _ => {
                        // copy one UTF-8 character
                        let ch = src[*i..].chars().next().unwrap();
                        text.push(ch);
                        *i += ch.len_utf8();
                    }
                }
            }
            Ok(Node { kind: Kind::Atom { text }, span: (start, *i) })
        }
        _ => {
            while *i < b.len() && !(b[*i] as char).is_ascii_whitespace() && b[*i] != b'(' && b[*i] != b')' {
                *i += 1;
            }
            Ok(Node { kind: Kind::Atom { text: src[start..*i].to_string() }, span: (start, *i) })
        }
    }
}

/// Quote a string the way KiCad writes it.
pub fn quote(s: &str) -> String {
    let mut o = String::with_capacity(s.len() + 2);
    o.push('"');
    for c in s.chars() {
        match c {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            '\n' => o.push_str("\\n"),
            _ => o.push(c),
        }
    }
    o.push('"');
    o
}

/// A number the way KiCad 7 writes it: shortest form, no trailing zeros, at most 6 decimals.
pub fn fmt_num(v: f64) -> String {
    let mut s = format!("{:.6}", v);
    if s.contains('.') {
        while s.ends_with('0') {
            s.pop();
        }
        if s.ends_with('.') {
            s.pop();
        }
    }
    if s == "-0" { "0".into() } else { s }
}

/// Pending edits to a source text: byte ranges replaced by new text, applied together.
#[derive(Default, Clone)]
pub struct Edits {
    ops: Vec<(usize, usize, String)>,
}

impl Edits {
    pub fn replace(&mut self, span: (usize, usize), text: impl Into<String>) {
        self.ops.push((span.0, span.1, text.into()));
    }

    /// Insert before byte `at`.
    pub fn insert(&mut self, at: usize, text: impl Into<String>) {
        self.ops.push((at, at, text.into()));
    }

    /// Apply to `src`. Overlapping edits are an error.
    pub fn apply(mut self, src: &str) -> Result<String> {
        self.ops.sort_by_key(|o| (o.0, o.1));
        let mut out = String::with_capacity(src.len());
        let mut pos = 0;
        for (s, e, t) in &self.ops {
            if *s < pos {
                bail!("overlapping edits at byte {s}");
            }
            out.push_str(&src[pos..*s]);
            out.push_str(t);
            pos = *e;
        }
        out.push_str(&src[pos..]);
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_and_keeps_spans() {
        let s = "(kicad_pcb (version 20221018) (net 1 \"A b\") (at 1.5 -2))";
        let n = parse(s).unwrap();
        assert!(n.is("kicad_pcb"));
        assert_eq!(n.find("version").unwrap().num(1), Some(20221018.0));
        let net = n.find("net").unwrap();
        assert_eq!(net.arg(2), Some("A b"));
        assert_eq!(&s[net.span.0..net.span.1], "(net 1 \"A b\")");
    }

    #[test]
    fn edits_splice() {
        let s = "(a (b 1) (c 2))";
        let n = parse(s).unwrap();
        let mut e = Edits::default();
        e.replace(n.find("b").unwrap().span, "(b 9)");
        assert_eq!(e.apply(s).unwrap(), "(a (b 9) (c 2))");
    }

    #[test]
    fn numbers() {
        assert_eq!(fmt_num(1.5), "1.5");
        assert_eq!(fmt_num(2.0), "2");
        assert_eq!(fmt_num(-0.0000001), "0");
        assert_eq!(fmt_num(0.1234567), "0.123457");
    }
}
