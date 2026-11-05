//! `cargo xtask test [--fast] [--only WORD] [--list]`: runs the pcb test suite from a clean checkout and prints one
//! summary.
//!
//! Order (proposal, "Testing"): unit tests; `pcb doctor`; the edge cases listed in tests/cases/steps.toml; each
//! fixture in tests/fixtures (a folder with a fixture.toml) through its import, route, edit, zone, release or M4 flow,
//! each result checked by its independent oracle and each oracle by its mutation suite; then the cases marked
//! `after_fixtures`, which read a fixture's flow. `--fast` skips everything that runs Freerouting and the mutation suites. `--only`
//! runs the steps whose id, folder or `covers` is WORD (a fixture by its name, or all with `fixtures`); `--list`
//! prints what covers each command. Freerouting comes from PCB_FREEROUTING_JAR. Exit status 1 if any step fails.
//!
//! A step that passed is not run again while its key is unchanged (DESIGN.md, "Test method"): the keys live in
//! target/xtask-cache and the work folders persist. `--full` clears both and runs everything.

use anyhow::{Context, Result, bail};
use serde_json::json;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Instant;

struct Step {
    name: String,
    ok: bool,
    seconds: f64,
    detail: String,
}

struct Suite {
    root: PathBuf,
    work: PathBuf,
    pcb: PathBuf,
    jar: Option<PathBuf>,
    fast: bool,
    steps: Vec<Step>,
    /// ids of the scripted steps that passed, for `after`
    passed: std::collections::HashSet<String>,
    /// fixture name to its project folder, for each fixture flow that ran to the end, for `{flow:<name>}`
    flows: std::collections::HashMap<String, String>,
    /// target/xtask-cache: one file per step that passed, holding the key it passed with
    cache: PathBuf,
    /// this run's key for each scripted step, so a step's key can include the keys of the steps it needs
    keys: std::collections::HashMap<String, String>,
    /// the hash of the release binary
    pcb_key: String,
}

/// The SHA-256 of files and folders (every file below, in path order) and extra strings.
fn key_of(root: &Path, paths: &[PathBuf], extra: &[&str]) -> String {
    use sha2::{Digest, Sha256};
    fn walk(p: &Path, out: &mut Vec<PathBuf>) {
        if p.is_dir() {
            let mut es: Vec<_> = std::fs::read_dir(p).into_iter().flatten().filter_map(|e| e.ok()).map(|e| e.path()).filter(|q| q.file_name().is_some_and(|n| n != "__pycache__")).collect();
            es.sort();
            for e in es {
                walk(&e, out);
            }
        } else if p.is_file() {
            out.push(p.to_path_buf());
        }
    }
    let mut files = vec![];
    for p in paths {
        walk(p, &mut files);
    }
    let mut h = Sha256::new();
    for f in files {
        h.update(f.strip_prefix(root).unwrap_or(&f).to_string_lossy().as_bytes());
        h.update(std::fs::read(&f).unwrap_or_default());
    }
    for e in extra {
        h.update(e.as_bytes());
    }
    h.finalize().iter().map(|b| format!("{b:02x}")).collect()
}

impl Suite {
    /// True when `name` passed before with this key; the step is then recorded as cached and not run.
    fn cached(&mut self, name: &str, key: &str) -> bool {
        let f = self.cache.join(slug(name));
        if std::fs::read_to_string(&f).is_ok_and(|k| k == key) {
            eprintln!("-- {name}: cached");
            self.steps.push(Step { name: format!("{name} (cached)"), ok: true, seconds: 0.0, detail: String::new() });
            return true;
        }
        false
    }

    fn remember(&self, name: &str, key: &str) {
        let _ = std::fs::write(self.cache.join(slug(name)), key);
    }

    /// A mutation suite, whose result depends only on its files: the script, the oracles and its inputs (every
    /// argument but the last, which is its work folder). It tests an oracle, not pcb, so it is not re-run while the
    /// files it damages and the oracle are unchanged.
    fn py_cached(&mut self, name: &str, script: &str, args: &[&str]) -> bool {
        let mut paths = vec![self.root.join(script), self.root.join("tests/oracles"), self.root.join("tests/lib")];
        paths.extend(args[..args.len().saturating_sub(1)].iter().map(PathBuf::from).filter(|p| p.exists()));
        let key = key_of(&self.root, &paths, &[]);
        if self.cached(name, &key) {
            return true;
        }
        let ok = self.py(name, script, args);
        if ok {
            self.remember(name, &key);
        }
        ok
    }
}

fn slug(name: &str) -> String {
    name.chars().map(|c| if c.is_ascii_alphanumeric() { c } else { '_' }).collect()
}

fn tail(s: &str, n: usize) -> String {
    let lines: Vec<&str> = s.lines().filter(|l| !l.starts_with("Picked up JAVA_TOOL_OPTIONS")).collect();
    lines[lines.len().saturating_sub(n)..].join("\n")
}

impl Suite {
    /// Runs one command as a step: passes when it exits 0.
    fn run(&mut self, name: &str, prog: &str, args: &[&str]) -> bool {
        self.run_env(name, prog, args, &[])
    }

    fn run_env(&mut self, name: &str, prog: &str, args: &[&str], env: &[(String, String)]) -> bool {
        let t0 = Instant::now();
        eprintln!("-- {name}");
        let out = Command::new(prog).args(args).envs(env.iter().map(|(k, v)| (k, v))).current_dir(&self.root).output();
        let (ok, detail) = match out {
            Ok(o) => {
                let text = String::from_utf8_lossy(&o.stdout).to_string() + &String::from_utf8_lossy(&o.stderr);
                (o.status.success(), tail(&text, if o.status.success() { 3 } else { 40 }))
            }
            Err(e) => (false, format!("could not start {prog}: {e}")),
        };
        eprintln!("   {} ({:.0} s)", if ok { "ok" } else { "FAILED" }, t0.elapsed().as_secs_f64());
        if !ok {
            eprintln!("{}", detail.lines().map(|l| format!("   | {l}")).collect::<Vec<_>>().join("\n"));
        }
        self.steps.push(Step { name: name.to_string(), ok, seconds: t0.elapsed().as_secs_f64(), detail });
        ok
    }

    fn skip(&mut self, name: &str, why: &str) {
        eprintln!("-- {name}: skipped ({why})");
        self.steps.push(Step { name: format!("{name} (skipped: {why})"), ok: true, seconds: 0.0, detail: String::new() });
    }

    fn py(&mut self, name: &str, script: &str, args: &[&str]) -> bool {
        let mut a = vec![script];
        a.extend_from_slice(args);
        self.run(name, "python3", &a)
    }

    fn w(&self, p: &str) -> String {
        self.work.join(p).to_string_lossy().to_string()
    }
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let usage = "usage: cargo xtask test [--fast] [--full] [--only WORD] [--list]";
    if args.first().map(|s| s.as_str()) != Some("test") {
        bail!(usage);
    }
    let fast = args.iter().any(|a| a == "--fast");
    let only = match args.iter().position(|a| a == "--only") {
        Some(i) => Some(args.get(i + 1).cloned().context(usage)?),
        None => None,
    };
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).parent().context("xtask sits in tools/pcb")?.to_path_buf();
    if args.iter().any(|a| a == "--list") {
        let cases = load_specs(&root.join("tests/cases/steps.toml"))?;
        list(&cases.iter().collect::<Vec<_>>());
        return Ok(());
    }
    let work = root.join("target").join("xtask");
    let cache = root.join("target").join("xtask-cache");
    // work folders persist between runs, so a cached step's output is still there for the steps after it; --full
    // starts clean
    let full = args.iter().any(|a| a == "--full");
    if full {
        let _ = std::fs::remove_dir_all(&work);
        let _ = std::fs::remove_dir_all(&cache);
    }
    std::fs::create_dir_all(&work)?;
    std::fs::create_dir_all(&cache)?;
    let jar = std::env::var("PCB_FREEROUTING_JAR").ok().map(PathBuf::from).filter(|p| p.exists());
    let mut s = Suite { root: root.clone(), work: work.clone(), pcb: root.join("target/release/pcb"), jar, fast, steps: vec![], passed: Default::default(), flows: Default::default(), cache, keys: Default::default(), pcb_key: String::new() };
    let t0 = Instant::now();

    // unit tests and the release binary every later step uses
    s.run("unit tests", "cargo", &["test", "--release", "--package", "pcb", "--quiet"]);
    if !s.run("build pcb", "cargo", &["build", "--release", "--package", "pcb", "--quiet"]) {
        return finish(&s, t0);
    }
    let pcb = s.pcb.to_string_lossy().to_string();
    s.pcb_key = key_of(&root, &[s.pcb.clone()], &[]);
    let jar = s.jar.as_ref().map(|p| p.to_string_lossy().to_string());
    if !s.fast && jar.is_none() {
        s.steps.push(Step { name: "freerouting jar".into(), ok: false, seconds: 0.0, detail: "PCB_FREEROUTING_JAR must name the Freerouting 2.5.0 jar (or use --fast)".into() });
        return finish(&s, t0);
    }

    // the pinned tools first: nothing else means anything on other versions
    let doctor_work = s.w("doctor");
    let mut dargs = vec!["--json", "doctor", "--work", &doctor_work];
    let jar_s = jar.clone().unwrap_or_default();
    if jar.is_some() {
        dargs.extend(["--freerouting", jar_s.as_str()]);
    }
    if !s.run("pcb doctor", &pcb, &dargs) {
        return finish(&s, t0);
    }
    // the edge cases, then the fixtures, then the cases that read a fixture's flow
    let (late, cases): (Vec<Spec>, Vec<Spec>) = load_specs(&root.join("tests/cases/steps.toml"))?.into_iter().partition(|sp| sp.late);
    run_specs(&mut s, &cases, &pcb, jar.as_deref(), only.as_deref());
    let fx_dir = root.join("tests/fixtures");
    let mut fixtures: Vec<_> = std::fs::read_dir(&fx_dir)?.filter_map(|e| e.ok()).map(|e| e.path()).filter(|p| p.join("fixture.toml").exists()).collect();
    fixtures.sort();
    for dir in fixtures {
        let fname = dir.file_name().unwrap_or_default().to_string_lossy().to_string();
        if only.as_deref().is_some_and(|o| o != "fixtures" && o != fname) {
            continue;
        }
        // the whole fixture is skipped while the binary, the fixture, the shared checks and this runner are unchanged
        let paths = [dir.clone(), root.join("tests/oracles"), root.join("tests/mutations"), root.join("tests/lib"), root.join("xtask/src/main.rs")];
        let key = key_of(&root, &paths, &[&s.pcb_key, jar.as_deref().unwrap_or(""), if s.fast { "fast" } else { "" }]);
        let label = format!("fixture {fname}");
        let project = work.join(&fname).join("project");
        if s.cached(&label, &key) {
            if project.join("release").exists() {
                s.flows.insert(fname.clone(), project.to_string_lossy().to_string());
            }
            continue;
        }
        let _ = std::fs::remove_dir_all(work.join(&fname));
        let before = s.steps.iter().filter(|x| !x.ok).count();
        // a fixture that cannot even be read is a failed step, and the summary is still written
        if let Err(e) = fixture(&mut s, &dir, &pcb, jar.as_deref()) {
            s.steps.push(Step { name: format!("fixture {}", dir.display()), ok: false, seconds: 0.0, detail: format!("{e:#}") });
        }
        if s.steps.iter().filter(|x| !x.ok).count() == before && !s.fast {
            s.remember(&label, &key);
        }
    }
    run_specs(&mut s, &late, &pcb, jar.as_deref(), only.as_deref());
    finish(&s, t0)
}

/// One scripted step from a `steps.toml` (format: tests/cases/steps.toml).
struct Spec {
    id: String,
    name: String,
    run: Vec<String>,
    covers: Vec<String>,
    needs: Vec<String>,
    after: Option<String>,
    env: Vec<(String, String)>,
    group: String,
    /// runs after the fixtures, because it reads a fixture's flow
    late: bool,
}

fn load_specs(path: &Path) -> Result<Vec<Spec>> {
    let v: toml::Value = toml::from_str(&std::fs::read_to_string(path).with_context(|| format!("{}", path.display()))?).with_context(|| format!("{}", path.display()))?;
    let group = path.parent().and_then(|p| p.file_name()).unwrap_or_default().to_string_lossy().to_string();
    let strs = |t: &toml::Value, k: &str| -> Vec<String> { t.get(k).and_then(|x| x.as_array()).into_iter().flatten().filter_map(|x| x.as_str().map(String::from)).collect() };
    let mut out = vec![];
    for t in v.get("step").and_then(|x| x.as_array()).into_iter().flatten() {
        let get = |k: &str| t.get(k).and_then(|x| x.as_str()).map(String::from);
        let id = get("id").with_context(|| format!("{}: a step without an id", path.display()))?;
        let env = t.get("env").and_then(|x| x.as_table()).into_iter().flatten().map(|(k, x)| (k.clone(), x.as_str().unwrap_or_default().to_string())).collect();
        out.push(Spec { name: get("name").unwrap_or_else(|| id.clone()), run: strs(t, "run"), covers: strs(t, "covers"), needs: strs(t, "needs"), after: get("after"), env, group: group.clone(), late: t.get("after_fixtures").and_then(|x| x.as_bool()).unwrap_or(false), id });
    }
    Ok(out)
}

/// A step is selected by `--only` when the word is its id, its folder or one of what it covers.
fn selected(sp: &Spec, only: Option<&str>) -> bool {
    only.is_none_or(|o| sp.id == o || sp.group == o || sp.covers.iter().any(|c| c == o))
}

fn run_specs(s: &mut Suite, specs: &[Spec], pcb: &str, jar: Option<&str>, only: Option<&str>) {
    for sp in specs.iter().filter(|sp| selected(sp, only)) {
        if sp.needs.iter().any(|n| n == "freerouting") && (s.fast || jar.is_none()) {
            s.skip(&sp.name, "--fast");
            continue;
        }
        if let Some(a) = &sp.after {
            if !s.passed.contains(a) {
                s.skip(&sp.name, &format!("needs {a}, which did not pass"));
                continue;
            }
        }
        let fill = |a: &str| -> Option<String> {
            let mut a = a.replace("{pcb}", pcb).replace("{jar}", jar.unwrap_or("")).replace("{work}", &s.w(&sp.id));
            while let Some(i) = a.find("{work:") {
                let j = a[i..].find('}')? + i;
                a = format!("{}{}{}", &a[..i], s.w(&a[i + 6..j]), &a[j + 1..]);
            }
            while let Some(i) = a.find("{flow:") {
                let j = a[i..].find('}')? + i;
                a = format!("{}{}{}", &a[..i], s.flows.get(&a[i + 6..j])?, &a[j + 1..]);
            }
            Some(a)
        };
        let args: Vec<String> = sp.run.iter().map(|a| fill(a).unwrap_or_default()).collect();
        // an env value naming a flow that did not run is left out: the probes then run that flow themselves
        let env: Vec<(String, String)> = sp.env.iter().filter_map(|(k, v)| fill(v).map(|v| (k.clone(), v))).collect();
        // the key: the step's scripts, the shared
        // test files, the binary, the Freerouting jar, and the keys of the steps whose work it reads
        let mut paths: Vec<PathBuf> = sp.run.iter().map(|a| s.root.join(a)).filter(|p| p.is_file()).collect();
        paths.extend(["tests/lib", "tests/oracles", "tests/mutations", "tests/fixtures"].map(|p| s.root.join(p)));
        let deps: Vec<String> = sp.run.iter().chain(sp.env.iter().map(|(_, v)| v)).flat_map(|a| a.match_indices("{work:").map(|(i, _)| a[i + 6..].split('}').next().unwrap_or("").to_string()).collect::<Vec<_>>()).chain(sp.after.clone()).map(|d| s.keys.get(&d).cloned().unwrap_or_default()).collect();
        let mut extra: Vec<&str> = vec![&s.pcb_key, jar.unwrap_or("")];
        extra.extend(sp.run.iter().map(|x| x.as_str()));
        extra.extend(sp.env.iter().flat_map(|(k, v)| [k.as_str(), v.as_str()]));
        extra.extend(deps.iter().map(|x| x.as_str()));
        let key = key_of(&s.root, &paths, &extra);
        s.keys.insert(sp.id.clone(), key.clone());
        if s.cached(&sp.name, &key) {
            s.passed.insert(sp.id.clone());
            continue;
        }
        let _ = std::fs::remove_dir_all(s.w(&sp.id));
        let a: Vec<&str> = args.iter().map(|x| x.as_str()).collect();
        if s.run_env(&sp.name, "python3", &a, &env) {
            s.passed.insert(sp.id.clone());
            s.remember(&sp.name, &key);
        }
    }
}

fn list(specs: &[&Spec]) {
    let mut by: std::collections::BTreeMap<&str, Vec<String>> = Default::default();
    for sp in specs {
        for c in &sp.covers {
            by.entry(c).or_default().push(format!("{}/{}", sp.group, sp.id));
        }
    }
    for (c, ids) in by {
        println!("{c}: {}", ids.join(", "));
    }
    println!("fixtures (tests/fixtures/*/fixture.toml): import, route, edit, zone, check, release and the M4 flow, by what each fixture lists");
}

fn fixture(s: &mut Suite, dir: &Path, pcb: &str, jar: Option<&str>) -> Result<()> {
    let fx: toml::Value = toml::from_str(&std::fs::read_to_string(dir.join("fixture.toml"))?)?;
    let name = fx["fixture"]["name"].as_str().context("fixture name")?.to_string();
    if fx.get("flow").is_some() {
        return flow(s, dir, &fx, &name, pcb, jar);
    }
    let ftoml = dir.join("fixture.toml").to_string_lossy().to_string();
    let cj = dir.join(fx["fixture"]["circuit_json"].as_str().context("circuit_json")?).to_string_lossy().to_string();
    let wd = s.work.join(&name);
    std::fs::create_dir_all(&wd)?;
    let board = wd.join("board.kicad_pcb").to_string_lossy().to_string();
    let w = |p: &str| wd.join(p).to_string_lossy().to_string();

    // import
    let layers = fx["fixture"].get("layers").and_then(|v| v.as_integer()).unwrap_or(2).to_string();
    let allow: Vec<&str> = fx.get("import").and_then(|i| i.get("allow_cross_net")).and_then(|v| v.as_array()).map(|a| a.iter().filter_map(|x| x.as_str()).collect()).unwrap_or_default();
    let allow = allow.join(",");
    if !s.run(&format!("{name}: import"), pcb, &["--json", "import-tscircuit", &cj, "--layers", &layers, "--allow-cross-net", &allow, "-o", &board]) {
        return Ok(());
    }
    s.py(&format!("{name}: verify_import"), "tests/oracles/verify_import.py", &[&cj, &board, &ftoml]);
    if s.fast {
        s.skip(&format!("{name}: import mutations"), "--fast");
    } else {
        s.py_cached(&format!("{name}: import mutations"), "tests/mutations/import_mutations.py", &[&cj, &board, &ftoml, &w("imut")]);
    }

    // route cases
    let mut mutated = false;
    for case in fx.get("route").and_then(|r| r.as_array()).cloned().unwrap_or_default() {
        let cname = case["name"].as_str().context("route case name")?.to_string();
        let label = format!("{name}: route {cname}");
        let (Some(jar), false) = (jar, s.fast) else {
            s.skip(&label, "--fast");
            continue;
        };
        let list = |k: &str| case.get(k).and_then(|v| v.as_array()).map(|a| a.iter().filter_map(|x| x.as_str()).collect::<Vec<_>>().join(",")).unwrap_or_default();
        let region = case["region"].as_array().context("region")?.iter().map(|v| v.as_float().or_else(|| v.as_integer().map(|i| i as f64)).unwrap_or(0.0).to_string()).collect::<Vec<_>>().join(",");
        let out = w(&format!("{cname}.kicad_pcb"));
        let mut args = vec!["--json".to_string(), "route".into(), board.clone(), "--region".into(), region.clone(), "--freerouting".into(), jar.into(), "--work".into(), w(&format!("{cname}_w")), "-o".into(), out.clone()];
        if !list("nets").is_empty() {
            args.extend(["--nets".into(), list("nets")]);
        }
        if !list("rip").is_empty() {
            args.extend(["--rip".into(), list("rip")]);
        }
        let t0 = Instant::now();
        eprintln!("-- {label}");
        let before = std::fs::read(&board)?;
        let o = Command::new(pcb).args(&args).output()?;
        let v: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap_or(json!({}));
        let want = case.get("expect").and_then(|x| x.as_str()).unwrap_or("done");
        let mut problems = vec![];
        let cp = contract_problems(&s.root, &o)?;
        if cp != "[]" {
            problems.push(format!("output contract: {cp}"));
        }
        if std::fs::read(&board)? != before {
            problems.push("the input board changed".into());
        }
        if want == "done" && !Path::new(&out).exists() {
            problems.push("done, but no output written".into());
        }
        if v["outcome"] != want {
            problems.push(format!("outcome {} (want {want}): {}", v["outcome"], v["error"]));
        }
        let open: Vec<String> = v["data"]["still_open"].as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default();
        let want_open: Vec<String> = list("still_open").split(',').filter(|x| !x.is_empty()).map(String::from).collect();
        if open != want_open {
            problems.push(format!("still open {open:?} (want {want_open:?})"));
        }
        if let Some(a) = case.get("attempt_used").and_then(|x| x.as_integer()) {
            if v["data"]["attempt_used"].as_i64() != Some(a) {
                problems.push(format!("attempt_used {} (want {a}): {}", v["data"]["attempt_used"], v["data"]["attempts"]));
            }
        }
        let ok = problems.is_empty();
        eprintln!("   {} ({:.0} s)", if ok { "ok" } else { "FAILED" }, t0.elapsed().as_secs_f64());
        s.steps.push(Step { name: label.clone(), ok, seconds: t0.elapsed().as_secs_f64(), detail: problems.join("; ") });
        if ok && want == "done" && Path::new(&out).exists() {
            let mut allowed = list("nets");
            if !list("rip").is_empty() {
                allowed = format!("{allowed},{}", list("rip"));
            }
            let targets = list("targets");
            s.py(&format!("{label}: verify_route"), "tests/oracles/verify_route.py", &[&board, &out, &region, &targets, &allowed]);
            if !mutated && !targets.is_empty() && v["data"]["added_segments"].as_u64().unwrap_or(0) > 0 {
                mutated = true;
                s.py_cached(&format!("{label}: route mutations"), "tests/mutations/route_mutations.py", &[&board, &out, &region, &targets, &allowed, &w("rmut")]);
            }
        }
    }

    // edit cases: the gate and target rules on the real board
    for case in fx.get("edit").and_then(|r| r.as_array()).cloned().unwrap_or_default() {
        let cname = case["name"].as_str().context("edit case name")?.to_string();
        let label = format!("{name}: edit {cname}");
        let t0 = Instant::now();
        let ops = w(&format!("edit_{cname}.json"));
        std::fs::write(&ops, case["ops"].as_str().context("edit case ops")?)?;
        let out = w(&format!("edit_{cname}.kicad_pcb"));
        let _ = std::fs::remove_file(&out);
        let before = std::fs::read(&board)?;
        let o = Command::new(pcb).args(["--json", "edit", &board, "--ops", &ops, "--work", &w(&format!("edit_{cname}_w")), "-o", &out]).output()?;
        let v: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap_or(json!({}));
        let want = case.get("expect").and_then(|x| x.as_str()).unwrap_or("done");
        let mut problems = vec![];
        let cp = contract_problems(&s.root, &o)?;
        if cp != "[]" {
            problems.push(format!("output contract: {cp}"));
        }
        if std::fs::read(&board)? != before {
            problems.push("the input board changed".to_string());
        }
        if v["outcome"] != want {
            problems.push(format!("outcome {} (want {want}): {} {}", v["outcome"], v["error"], v["data"]["regressions"]));
        }
        if let Some(c) = case.get("code").and_then(|x| x.as_str()) {
            if v["error"]["code"] != c {
                problems.push(format!("code {} (want {c})", v["error"]["code"]));
            }
        }
        let got: Vec<String> = v["data"]["regressions"].as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default();
        for r in case.get("regressions").and_then(|x| x.as_array()).cloned().unwrap_or_default() {
            let r = r.as_str().unwrap_or_default();
            if !got.iter().any(|g| g.starts_with(&format!("{r}:"))) {
                problems.push(format!("regression {r} not reported: {got:?}"));
            }
        }
        if want != "done" && Path::new(&out).exists() {
            problems.push("a refused or rejected edit wrote the output".into());
        }
        let ok = problems.is_empty();
        s.steps.push(Step { name: label.clone(), ok, seconds: t0.elapsed().as_secs_f64(), detail: problems.join("; ") });
        if ok && want == "done" {
            s.py(&format!("{label}: verify_edit"), "tests/oracles/verify_edit.py", &[&board, &ops, &out]);
        }
    }

    // zones: `pcb zone` runs with the fixture's pcb.toml beside a copy of the imported board, twice: the second run, on
    // the zoned board, must write the same bytes
    if fx.get("zones").is_some() {
        let zdir = w("zone");
        std::fs::create_dir_all(&zdir)?;
        let zb = format!("{zdir}/board.kicad_pcb");
        std::fs::copy(&board, &zb)?;
        std::fs::copy(Path::new(&board).with_extension("kicad_pro"), Path::new(&zb).with_extension("kicad_pro"))?;
        std::fs::copy(dir.join("pcb.toml"), format!("{zdir}/pcb.toml")).context("a fixture with [zones] needs pcb.toml")?;
        let base = w("base.kicad_pcb");
        let zoned = w("zoned.kicad_pcb");
        std::fs::copy(Path::new(&board).with_extension("kicad_pro"), Path::new(&base).with_extension("kicad_pro"))?;
        let save = format!("import pcbnew; b = pcbnew.LoadBoard({board:?}); b.Save({base:?})");
        let zwork = w("zone_work");
        if s.run(&format!("{name}: zones base (KiCad save)"), "python3", &["-c", &save]) && s.run(&format!("{name}: pcb zone"), pcb, &["zone", "--project", &zdir, "-o", &zoned, "--work", &zwork]) {
            s.py(&format!("{name}: verify_zones"), "tests/oracles/verify_zones.py", &[&base, &zoned, &ftoml]);
            // second run on the zoned board
            let again = w("zone_again");
            std::fs::create_dir_all(&again)?;
            std::fs::copy(&zoned, format!("{again}/board.kicad_pcb"))?;
            std::fs::copy(Path::new(&board).with_extension("kicad_pro"), format!("{again}/board.kicad_pro"))?;
            std::fs::copy(dir.join("pcb.toml"), format!("{again}/pcb.toml"))?;
            let zoned2 = w("zoned_again.kicad_pcb");
            let t0 = Instant::now();
            let ran = Command::new(pcb).args(["zone", "--project", &again, "-o", &zoned2, "--work", &w("zone_work2")]).output()?;
            let same = ran.status.success() && std::fs::read(&zoned2).ok() == std::fs::read(&zoned).ok();
            s.steps.push(Step { name: format!("{name}: pcb zone again (same bytes)"), ok: same, seconds: t0.elapsed().as_secs_f64(), detail: if same { String::new() } else { String::from_utf8_lossy(&ran.stdout).chars().take(400).collect() } });
            // pcb check on the zoned board finds exactly what the fixture lists (M3 gate: the badge through pcb check)
            if let Some(want) = fx.get("check").and_then(|c| c.get("findings")).and_then(|v| v.as_array()) {
                let want: std::collections::BTreeSet<String> = want.iter().filter_map(|x| x.as_str().map(String::from)).collect();
                let t0 = Instant::now();
                let o = Command::new(pcb).args(["--json", "check", "--project", &again, "--work", &w("check_work")]).output()?;
                let v: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap_or(json!({}));
                let got: std::collections::BTreeSet<String> = v["data"]["findings"].as_array().into_iter().flatten().map(|f| format!("{} {}", f["check"].as_str().unwrap_or(""), f["item"].as_str().unwrap_or(""))).collect();
                let cp = contract_problems(&s.root, &o)?;
                let ok = got == want && cp == "[]";
                let detail = if ok { String::new() } else { format!("only found: {:?}; only listed: {:?}; contract {cp}; {}", got.difference(&want).collect::<Vec<_>>(), want.difference(&got).collect::<Vec<_>>(), v["error"]) };
                s.steps.push(Step { name: format!("{name}: pcb check finds what the fixture lists"), ok, seconds: t0.elapsed().as_secs_f64(), detail });
            }
            if s.fast {
                s.skip(&format!("{name}: zone mutations"), "--fast");
            } else {
                s.py_cached(&format!("{name}: zone mutations"), "tests/mutations/zone_mutations.py", &[&base, &zoned, &ftoml, &w("zmut")]);
            }
        }
    }
    // the release flow (M3): pcb.toml and its folders beside a copy of the imported board, each step written back in
    // place, then release, compared with the files that were ordered
    if let Some(r) = fx.get("release") {
        let rdir = w("release_project");
        if Path::new(&rdir).exists() {
            std::fs::remove_dir_all(&rdir)?;
        }
        std::fs::create_dir_all(&rdir)?;
        std::fs::copy(&board, format!("{rdir}/board.kicad_pcb"))?;
        std::fs::copy(Path::new(&board).with_extension("kicad_pro"), format!("{rdir}/board.kicad_pro"))?;
        std::fs::copy(dir.join("pcb.toml"), format!("{rdir}/pcb.toml"))?;
        for a in r.get("assets").and_then(|v| v.as_array()).into_iter().flatten().filter_map(|v| v.as_str()) {
            let to = Path::new(&rdir).join(a);
            std::fs::create_dir_all(&to)?;
            for e in std::fs::read_dir(dir.join(a))? {
                let e = e?;
                std::fs::copy(e.path(), to.join(e.file_name()))?;
            }
        }
        let mut ok = true;
        for step in r.get("steps").and_then(|v| v.as_array()).into_iter().flatten().filter_map(|v| v.as_str()) {
            let wdir = w(&format!("release_{}_w", step.replace(' ', "_")));
            let mut args: Vec<&str> = vec!["--json"];
            args.extend(step.split_whitespace());
            args.extend(["--project", &rdir, "--work", &wdir]);
            ok = ok && s.run(&format!("{name}: release flow: pcb {step}"), pcb, &args);
        }
        let out = w("release");
        if Path::new(&out).exists() {
            std::fs::remove_dir_all(&out)?;
        }
        if ok && s.run(&format!("{name}: pcb release"), pcb, &["--json", "release", "--project", &rdir, "-o", &out, "--work", &w("release_w")]) {
            let p: toml::Value = toml::from_str(&std::fs::read_to_string(dir.join("pcb.toml"))?)?;
            let (pn, pv) = (p["project"]["name"].as_str().unwrap_or(""), p["project"]["version"].as_str().unwrap_or(""));
            let f = |k: &str| r.get(k).and_then(|v| v.as_str()).map(|v| dir.join(v).to_string_lossy().to_string()).unwrap_or_default();
            let zip = format!("{out}/{pn}_v{pv}_gerbers.zip");
            s.run(&format!("{name}: compare-gerbers with the ordered files"), pcb, &["--json", "compare-gerbers", &zip, &f("golden_gerbers"), "--explain", &f("explain"), "--board", &format!("{rdir}/board.kicad_pcb"), "--work", &w("compare_w")]);
            s.py(&format!("{name}: verify_release"), "tests/oracles/verify_release.py", &[&out, &f("golden_bom"), &f("golden_cpl"), pn, pv]);
            s.py_cached(&format!("{name}: release read-back mutations"), "tests/mutations/verify_mutations.py", &[&w("release_w/gerbers"), &format!("{rdir}/board.kicad_pcb"), &w("vmut")]);
        }
    }
    Ok(())
}

/// A project's own flow (M4): a copy of the fixture folder, each `[flow] steps` command run on it in turn (`{p}` the
/// copy, `{w}` a work folder per step), then the oracles: the board against the netlist and JLCPCB's footprints, the
/// release against the golden BOM and CPL, the read-back's mutations, the drawing against the board and CPL.
fn flow(s: &mut Suite, dir: &Path, fx: &toml::Value, name: &str, pcb: &str, jar: Option<&str>) -> Result<()> {
    let f = &fx["flow"];
    let wd = s.work.join(name);
    if wd.exists() {
        std::fs::remove_dir_all(&wd)?;
    }
    let p = wd.join("project");
    std::fs::create_dir_all(&p)?;
    copy_dir(dir, &p)?;
    let ps = p.to_string_lossy().to_string();
    let mut ok = true;
    for (i, step) in f["steps"].as_array().into_iter().flatten().filter_map(|v| v.as_str()).enumerate() {
        if !ok {
            break;
        }
        if step.starts_with("route ") && jar.is_none() {
            s.skip(&format!("{name}: pcb {step}"), "no Freerouting (--fast)");
            return Ok(());
        }
        let w = wd.join(format!("w{i}")).to_string_lossy().to_string();
        let line = step.replace("{p}", &ps).replace("{w}", &w);
        let mut args: Vec<&str> = vec!["--json"];
        args.extend(line.split_whitespace());
        let short = step.split_whitespace().take(2).collect::<Vec<_>>().join(" ");
        ok = s.run(&format!("{name}: pcb {short}"), pcb, &args);
    }
    if !ok {
        return Ok(());
    }
    s.flows.insert(name.to_string(), ps.clone());
    let net = wd.join("netlist.net").to_string_lossy().to_string();
    let sch = p.join("schematic/paddle-keyer.kicad_sch");
    let _ = Command::new("kicad-cli").args(["sch", "export", "netlist", "--format", "kicadsexpr", "-o", &net]).arg(&sch).output();
    let board = p.join("board.kicad_pcb").to_string_lossy().to_string();
    s.py(&format!("{name}: verify_sync"), "tests/oracles/verify_sync.py", &[&board, &net, &format!("{ps}/parts"), &format!("{ps}/pcb.toml")]);
    let pt: toml::Value = toml::from_str(&std::fs::read_to_string(p.join("pcb.toml"))?)?;
    let (pn, pv) = (pt["project"]["name"].as_str().unwrap_or(""), pt["project"]["version"].as_str().unwrap_or(""));
    let g = |k: &str| f.get(k).and_then(|v| v.as_str()).map(|v| dir.join(v).to_string_lossy().to_string()).unwrap_or_default();
    let rel = format!("{ps}/release");
    s.py(&format!("{name}: verify_release against v1.0.0's BOM and CPL"), "tests/oracles/verify_release.py", &[&rel, &g("golden_bom"), &g("golden_cpl"), pn, pv]);
    s.py(&format!("{name}: holes, paste and mask against v1.0.0's Gerbers"), "tests/oracles/verify_against_v1.py", &[&format!("{rel}/{pn}_v{pv}_gerbers.zip"), &dir.join("../paddle_keyer_v1/golden/paddle-keyer_v1.0.0_gerbers.zip").to_string_lossy()]);
    s.py_cached(&format!("{name}: release read-back mutations"), "tests/mutations/verify_mutations.py", &[&wd.join(format!("w{}/gerbers", 9)).to_string_lossy(), &board, &wd.join("vmut").to_string_lossy()]);
    s.py(&format!("{name}: verify_drawing"), "tests/oracles/verify_drawing.py", &[&format!("{ps}/drawings"), &board, &format!("{rel}/{pn}_v{pv}_CPL.csv")]);
    Ok(())
}

fn copy_dir(from: &Path, to: &Path) -> Result<()> {
    for e in std::fs::read_dir(from)? {
        let e = e?;
        let t = to.join(e.file_name());
        if e.file_type()?.is_dir() {
            std::fs::create_dir_all(&t)?;
            copy_dir(&e.path(), &t)?;
        } else {
            std::fs::copy(e.path(), &t)?;
        }
    }
    Ok(())
}

/// The output-contract checker's problems with one command's output, as JSON (`[]` when none).
fn contract_problems(root: &Path, o: &std::process::Output) -> Result<String> {
    let c = Command::new("python3")
        .args(["-c", "import sys, json; sys.path.insert(0, 'tests/lib'); from contract_check import check; d, p = check(sys.stdin.read(), int(sys.argv[1])); print(json.dumps(p))", &o.status.code().unwrap_or(-1).to_string()])
        .current_dir(root)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .spawn()
        .and_then(|mut c| {
            use std::io::Write;
            c.stdin.take().unwrap().write_all(&o.stdout)?;
            c.wait_with_output()
        })?;
    Ok(String::from_utf8_lossy(&c.stdout).trim().to_string())
}

fn finish(s: &Suite, t0: Instant) -> Result<()> {
    let failed: Vec<&Step> = s.steps.iter().filter(|x| !x.ok).collect();
    let summary = json!({
        "ok": failed.is_empty(),
        "fast": s.fast,
        "seconds": t0.elapsed().as_secs_f64(),
        "steps": s.steps.iter().map(|x| json!({ "name": x.name, "ok": x.ok, "seconds": (x.seconds * 10.0).round() / 10.0, "detail": x.detail })).collect::<Vec<_>>(),
    });
    std::fs::write(s.work.join("summary.json"), serde_json::to_string_pretty(&summary)?)?;
    eprintln!("\n{} of {} steps passed in {:.0} s; summary in {}", s.steps.len() - failed.len(), s.steps.len(), t0.elapsed().as_secs_f64(), s.work.join("summary.json").display());
    for f in &failed {
        eprintln!("FAILED: {}", f.name);
    }
    if !failed.is_empty() {
        std::process::exit(1);
    }
    Ok(())
}
