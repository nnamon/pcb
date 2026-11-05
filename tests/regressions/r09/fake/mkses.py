"""mkses.py out.ses 'NET:LAYER:WIDTHmm:x,y;x,y;...' ... : a Specctra session with those wires (KiCad mm, y down)."""
import sys
out = sys.argv[1]
nets = {}
for spec in sys.argv[2:]:
    net, layer, w, pts = spec.split(":")
    nets.setdefault(net, []).append((layer, float(w), [tuple(map(float, p.split(","))) for p in pts.split(";")]))
s = ["(session x (routes (resolution um 10) (library_out) (network_out"]
for net, ws in nets.items():
    s.append(f"  (net {net}")
    for layer, w, pts in ws:
        s.append(f"    (wire (path {layer} {round(w*10000)} " + " ".join(f"{round(x*10000)} {round(-y*10000)}" for x, y in pts) + "))")
    s.append("  )")
s.append(")))")
open(out, "w").write("\n".join(s) + "\n")
