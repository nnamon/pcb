//! `cargo xtask test [--fast]`: runs the whole pcb test suite from a clean checkout and prints one summary.
//!
//! Layers (proposal, "Testing"): unit tests; the output contract; the import and route edge cases on synthetic
//! inputs; and each fixture in tests/fixtures run through import, route and zones, each result checked by its
//! independent oracle and each oracle by its mutation suite. `--fast` skips everything that runs Freerouting and
//! the mutation suites. Freerouting comes from PCB_FREEROUTING_JAR. Exit status 1 if any step fails.

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
}

fn tail(s: &str, n: usize) -> String {
    let lines: Vec<&str> = s.lines().filter(|l| !l.starts_with("Picked up JAVA_TOOL_OPTIONS")).collect();
    lines[lines.len().saturating_sub(n)..].join("\n")
}

impl Suite {
    /// Runs one command as a step: passes when it exits 0.
    fn run(&mut self, name: &str, prog: &str, args: &[&str]) -> bool {
        let t0 = Instant::now();
        eprintln!("-- {name}");
        let out = Command::new(prog).args(args).current_dir(&self.root).output();
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
    if args.first().map(|s| s.as_str()) != Some("test") {
        bail!("usage: cargo xtask test [--fast]");
    }
    let fast = args.iter().any(|a| a == "--fast");
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).parent().context("xtask sits in tools/pcb")?.to_path_buf();
    let work = root.join("target").join("xtask");
    let _ = std::fs::remove_dir_all(&work);
    std::fs::create_dir_all(&work)?;
    let jar = std::env::var("PCB_FREEROUTING_JAR").ok().map(PathBuf::from).filter(|p| p.exists());
    let mut s = Suite { root: root.clone(), work: work.clone(), pcb: root.join("target/release/pcb"), jar, fast, steps: vec![] };
    let t0 = Instant::now();

    // unit tests and the release binary every later step uses
    s.run("unit tests", "cargo", &["test", "--release", "--package", "pcb", "--quiet"]);
    if !s.run("build pcb", "cargo", &["build", "--release", "--package", "pcb", "--quiet"]) {
        return finish(&s, t0);
    }
    let pcb = s.pcb.to_string_lossy().to_string();
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
    s.py("output contract", "tests/cases/contract_cases.py", &[&pcb, &s.w("contract")]);
    s.py("kicad adapter", "tests/cases/adapter_cases.py", &[&s.w("adapter")]);
    s.py("import edge cases", "tests/cases/import_cases.py", &[&pcb, &s.w("import_cases")]);
    s.py("import orientation sweep", "tests/cases/orient_cases.py", &[&pcb, &s.w("orient_cases")]);
    // review 8's probes, kept as cases: edit, diff, init and status, the edit oracle's mutations, and move_footprint
    // against pcbnew's own move
    for (n, f) in [("review 8: edit probes", "edit_probes"), ("review 8: diff probes", "diff_probes"), ("review 8: project probes", "project_probes"), ("review 8: verify_edit mutations", "verify_edit_mutations"), ("review 8: move_footprint against pcbnew", "move_fp_vs_pcbnew")] {
        s.py(n, &format!("tests/review8/{f}.py"), &[&pcb, &s.w(&format!("review8_{f}"))]);
    }
    // review 9's cases: zone fills through the gate, the join rule, diff, the router's run choice (a stand-in java, no
    // Freerouting) and prewire with --rip
    s.py("review 9: zone gate cases", "tests/review9/zone_gate_cases.py", &[&pcb, &s.w("review9_zone")]);
    for (n, f) in [("review 9: join probes", "join_probes"), ("review 9: diff misses", "diff_misses"), ("review 9: route branches", "route_branches"), ("review 9: prewire probes", "prewire_probes")] {
        s.py(n, "tests/review9/expect_pass.py", &[&format!("tests/review9/{f}.py"), &pcb, &s.w(&format!("review9_{f}"))]);
    }
    // review 10's cases: zone pairing without uuids, joins through fills, diff on re-saves, prewire stubs
    s.py("review 10: gate, join, diff and prewire cases", "tests/review10/check.py", &[&pcb, &s.w("review10")]);
    s.py("review 11: gate markers, prewire stubs, diff on re-saves", "tests/review11/check.py", &[&pcb, &s.w("review11")]);
    s.py("review 12: markers, copper graphics, stubs at a shared pad", "tests/review12/check.py", &[&pcb, &s.w("review12")]);
    if s.py("edit edge cases", "tests/cases/edit_cases.py", &[&pcb, &s.w("edit_cases")]) {
        s.py("edit mutations", "tests/mutations/edit_mutations.py", &[&s.w("edit_cases")]);
        s.py("diff cases", "tests/cases/diff_cases.py", &[&pcb, &s.w("edit_cases"), &s.w("diff_cases")]);
    }
    s.py("zone cases", "tests/cases/zone_cases.py", &[&pcb, &s.w("zone_cases")]);
    s.py("check, gate and release cases", "tests/cases/release_cases.py", &[&pcb, &s.w("release_cases")]);
    s.py("review 13: zone probes", "tests/review13/check.py", &[&pcb, &s.w("review13")]);
    s.py("review 14: zone confirmation probes", "tests/review14/check.py", &[&pcb, &s.w("review14")]);
    match (&jar, s.fast) {
        (Some(j), false) => {
            let j = j.clone();
            s.py("route edge cases", "tests/cases/route_cases.py", &[&pcb, &j, &s.w("route_cases")]);
            s.py("review 8: route probes", "tests/review8/route_probes.py", &[&pcb, &j, &s.w("review8_route_probes")]);
        }
        _ => {
            s.skip("route edge cases", "--fast");
            s.skip("review 8: route probes", "--fast");
        }
    }

    // fixtures
    let fx_dir = root.join("tests/fixtures");
    let mut fixtures: Vec<_> = std::fs::read_dir(&fx_dir)?.filter_map(|e| e.ok()).map(|e| e.path()).filter(|p| p.join("fixture.toml").exists()).collect();
    fixtures.sort();
    for dir in fixtures {
        // a fixture that cannot even be read is a failed step, and the summary is still written
        if let Err(e) = fixture(&mut s, &dir, &pcb, jar.as_deref()) {
            s.steps.push(Step { name: format!("fixture {}", dir.display()), ok: false, seconds: 0.0, detail: format!("{e:#}") });
        }
    }
    finish(&s, t0)
}

fn fixture(s: &mut Suite, dir: &Path, pcb: &str, jar: Option<&str>) -> Result<()> {
    let fx: toml::Value = toml::from_str(&std::fs::read_to_string(dir.join("fixture.toml"))?)?;
    let name = fx["fixture"]["name"].as_str().context("fixture name")?.to_string();
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
        s.py(&format!("{name}: import mutations"), "tests/mutations/import_mutations.py", &[&cj, &board, &ftoml, &w("imut")]);
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
                s.py(&format!("{label}: route mutations"), "tests/mutations/route_mutations.py", &[&board, &out, &region, &targets, &allowed, &w("rmut")]);
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
                s.py(&format!("{name}: zone mutations"), "tests/mutations/zone_mutations.py", &[&base, &zoned, &ftoml, &w("zmut")]);
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
            s.py(&format!("{name}: release read-back mutations"), "tests/mutations/verify_mutations.py", &[&w("release_w/gerbers"), &format!("{rdir}/board.kicad_pcb"), &w("vmut")]);
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
