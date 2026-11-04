"""Edge cases for `pcb import-tscircuit`: each builds a small circuit JSON, runs the importer, and checks the
outcome it must have (done, or refused with a message naming the problem). Every case the importer accepts is
then checked by tests/oracles/verify_import.py, which must pass. The cases come from reviews 1 and 2.

Usage: python3 import_cases.py pcb-binary workdir
Prints one JSON summary; exit 1 on any failure.
"""
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "lib"))
from circuit import C  # noqa: E402
from contract_check import check  # noqa: E402

def base():
    c=C()
    sa,pa=c.comp("R1",-5,0,0,"top",resistance=1000)
    s1,p1=c.port(sa,pa,"pin1",1,-5.5,0); c.pad(pa,p1,-5.5,0,width=0.5,height=0.5)
    s2,p2=c.port(sa,pa,"pin2",2,-4.5,0); c.pad(pa,p2,-4.5,0,width=0.5,height=0.5)
    sb,pb=c.comp("R2",5,0,0,"top",resistance=1000)
    s3,p3=c.port(sb,pb,"pin1",1,4.5,0); c.pad(pb,p3,4.5,0,width=0.5,height=0.5)
    s4,p4=c.port(sb,pb,"pin2",2,5.5,0); c.pad(pb,p4,5.5,0,width=0.5,height=0.5)
    return c,dict(s1=s1,s2=s2,s3=s3,s4=s4,p1=p1,p2=p2,p3=p3,p4=p4)
def wire(x,y,l="top",w=0.2): return {"route_type":"wire","x":x,"y":y,"width":w,"layer":l}
cases={}
def case(f): cases[f.__name__]=f; return f
@case
def s2_port_to_port():
    c,i=base(); c.strace(ports=[i["s2"],i["s3"]]); return c
@case
def s2_port_two_nets():
    c,i=base(); a=c.net("A"); b=c.net("B"); c.strace([i["s2"]],[a]); c.strace([i["s2"]],[b]); return c
@case
def s2_chain_two_nets():
    # A - R1.2 ; R1.2 - R2.1 ; R2.1 - B : short through port-to-port
    c,i=base(); a=c.net("A"); b=c.net("B"); c.strace([i["s2"]],[a]); c.strace([i["s2"],i["s3"]]); c.strace([i["s3"]],[b]); return c
@case
def s3_trace_no_netname_srctrace():
    c,i=base(); a=c.net("A"); st=c.strace([i["s2"],i["s3"]],[a])
    c.add({"type":"pcb_trace","pcb_trace_id":"t1","source_trace_id":st,"route":[wire(-4.5,0),wire(4.5,0)]}); return c
@case
def s3_trace_no_netname_ports():
    c,i=base(); a=c.net("A"); c.strace([i["s2"],i["s3"]],[a])
    c.add({"type":"pcb_trace","pcb_trace_id":"t1","start_pcb_port_id":i["p2"],"end_pcb_port_id":i["p3"],"route":[wire(-4.5,0),wire(4.5,0)]}); return c
@case
def s3_trace_geometry_only():
    c,i=base(); a=c.net("A"); c.strace([i["s2"],i["s3"]],[a])
    c.add({"type":"pcb_trace","pcb_trace_id":"t1","route":[wire(-4.5,0),wire(4.5,0)]}); return c
@case
def s3_via_no_netname():
    c,i=base(); a=c.net("A"); c.strace([i["s2"],i["s3"]],[a])
    c.add({"type":"pcb_trace","pcb_trace_id":"t1","net_name":"A","route":[wire(-4.5,0),wire(0,0)]})
    c.add({"type":"pcb_trace","pcb_trace_id":"t2","net_name":"A","route":[wire(0,0,"bottom"),wire(4.5,0,"bottom")]})
    c.add({"type":"pcb_via","pcb_via_id":"v1","x":0,"y":0,"outer_diameter":0.6,"hole_diameter":0.3,"from_layer":"top","to_layer":"bottom"}); return c
@case
def s3_wrong_netname():
    # trace net_name B, but geometrically joins pads on net A
    c,i=base(); a=c.net("A"); c.strace([i["s2"],i["s3"]],[a]); c.net("B")
    c.add({"type":"pcb_trace","pcb_trace_id":"t1","net_name":"B","route":[wire(-4.5,0),wire(4.5,0)]}); return c
@case
def s4_route_via_no_pcb_via():
    c,i=base(); a=c.net("A"); c.strace([i["s2"],i["s3"]],[a])
    c.add({"type":"pcb_trace","pcb_trace_id":"t1","net_name":"A","route":[wire(-4.5,0),{"route_type":"via","x":0,"y":0,"from_layer":"top","to_layer":"bottom"},wire(4.5,0,"bottom")]}); return c
@case
def s4_route_via_no_to_layer():
    c,i=base(); a=c.net("A"); c.strace([i["s2"],i["s3"]],[a])
    c.add({"type":"pcb_trace","pcb_trace_id":"t1","net_name":"A","route":[wire(-4.5,0),{"route_type":"via","x":0,"y":0},wire(4.5,0,"bottom")]}); return c
@case
def s4_route_via_wrong_from():
    c,i=base(); a=c.net("A"); c.strace([i["s2"],i["s3"]],[a])
    c.add({"type":"pcb_trace","pcb_trace_id":"t1","net_name":"A","route":[wire(-4.5,0),{"route_type":"via","x":0,"y":0,"from_layer":"bottom","to_layer":"top"},wire(4.5,0,"bottom")]}); return c
@case
def s4_layer_change():
    c,i=base(); a=c.net("A"); c.strace([i["s2"],i["s3"]],[a])
    c.add({"type":"pcb_trace","pcb_trace_id":"t1","net_name":"A","route":[wire(-4.5,0),wire(0,0,"bottom"),wire(4.5,0,"bottom")]}); return c
@case
def s5_lpoly():
    c,i=base(); sa,pa=c.comp("J1",0,5,90)
    sp,pp=c.port(sa,pa,"pin1",1,0.2,5.2)
    c.pad(pa,pp,0,0,"polygon",points=[{"x":0,"y":5},{"x":2,"y":5},{"x":2,"y":6},{"x":1,"y":6},{"x":1,"y":7},{"x":0,"y":7}]); return c
@case
def s5_lpoly_port_outside():
    c,i=base(); sa,pa=c.comp("J1",0,5,0)
    sp,pp=c.port(sa,pa,"pin1",1,1.5,6.5)
    c.pad(pa,pp,0,0,"polygon",points=[{"x":0,"y":5},{"x":2,"y":5},{"x":2,"y":6},{"x":1,"y":6},{"x":1,"y":7},{"x":0,"y":7}]); return c
@case
def s6_cutout():
    c,i=base(); c.add({"type":"pcb_cutout","shape":"rect","center":{"x":0,"y":0},"width":1,"height":1}); return c
@case
def s6_keepout():
    c,i=base(); c.add({"type":"pcb_keepout","shape":"rect","center":{"x":0,"y":0},"width":1,"height":1}); return c
@case
def s6_trace_error():
    c,i=base(); c.add({"type":"pcb_trace_error","message":"could not route R1.pin2 to R2.pin1"}); return c
@case
def s6_copper_text():
    c,i=base(); c.add({"type":"pcb_copper_text","text":"X","anchor_position":{"x":0,"y":0},"layer":"top"}); return c
@case
def s6_hole_offset():
    c,i=base(); sa,pa=c.comp("J1",0,5,0); sp,pp=c.port(sa,pa,"pin1",1,0,5)
    c.add({"type":"pcb_plated_hole","pcb_component_id":pa,"pcb_port_id":pp,"shape":"circle","x":0,"y":5,"outer_diameter":1.6,"hole_diameter":0.8,"hole_offset_x":0.2}); return c
@case
def s6_pill_bad_radius():
    c,i=base(); sa,pa=c.comp("J1",0,5,0); sp,pp=c.port(sa,pa,"pin1",1,0,5)
    c.pad(pa,pp,0,5,"pill",width=1,height=2,radius=0.2); return c
@case
def s6_roundrect():
    c,i=base(); sa,pa=c.comp("J1",0,5,0); sp,pp=c.port(sa,pa,"pin1",1,0,5)
    c.pad(pa,pp,0,5,"rect",width=1,height=2,corner_radius=0.25); return c
@case
def s6_rotated_rect():
    c,i=base(); sa,pa=c.comp("J1",0,5,0); sp,pp=c.port(sa,pa,"pin1",1,0,5)
    c.pad(pa,pp,0,5,"rotated_rect",width=1,height=2,ccw_rotation=45); return c
@case
def s6_rect_ccw_rotation():
    c,i=base(); sa,pa=c.comp("J1",0,5,0); sp,pp=c.port(sa,pa,"pin1",1,0,5)
    c.pad(pa,pp,0,5,"rect",width=1,height=2,ccw_rotation=90); return c
@case
def s6_courtyard_circle():
    c,i=base(); c.add({"type":"pcb_courtyard_circle","pcb_component_id":"pc_2","center":{"x":0,"y":0},"radius":1}); return c
@case
def s6_npth_pill_in_comp():
    c,i=base(); c.add({"type":"pcb_hole","pcb_component_id":"pc_2","hole_shape":"pill","x":0,"y":0,"hole_width":1,"hole_height":2}); return c
@case
def s6_npth_board_pill():
    c,i=base(); c.add({"type":"pcb_hole","hole_shape":"pill","x":0,"y":0,"hole_width":1,"hole_height":2}); return c
@case
def s6_npth_board_oval():
    c,i=base(); c.add({"type":"pcb_hole","hole_shape":"oval","x":0,"y":0,"hole_width":1,"hole_height":2}); return c
@case
def s6_board_circle_hole_shape_missing():
    c,i=base(); c.add({"type":"pcb_hole","x":0,"y":0,"hole_diameter":1}); return c
@case
def s7_no_number():
    c,i=base(); sa,pa=c.comp("J1",0,5,0)
    sp,pp=c.port(sa,pa,"",None,0,5); c.pad(pa,pp,0,5,width=1,height=1); return c
@case
def s7_pad_no_port():
    c,i=base(); sa,pa=c.comp("J1",0,5,0)
    c.add({"type":"pcb_smtpad","pcb_component_id":pa,"x":0,"y":5,"shape":"rect","width":1,"height":1,"layer":"top"}); return c
@case
def s7_dup_numbers():
    c,i=base(); sa,pa=c.comp("J1",0,5,0)
    sp,pp=c.port(sa,pa,"A",1,0,5); c.pad(pa,pp,0,5,width=1,height=1)
    sp,pp=c.port(sa,pa,"B",1,1,5); c.pad(pa,pp,1,5,width=1,height=1); return c
@case
def n2_blind_via():
    c,i=base(); c.add({"type":"pcb_via","pcb_via_id":"v","x":0,"y":0,"outer_diameter":0.6,"hole_diameter":0.3,"from_layer":"top","to_layer":"inner1","net_name":"X"}); return c
@case
def n2_blind_via_layers_only():
    c,i=base(); a=c.net("A"); c.strace([i["s2"],i["s3"]],[a]); c.add({"type":"pcb_via","pcb_via_id":"v","x":0,"y":0,"outer_diameter":0.6,"hole_diameter":0.3,"layers":["top","inner1"],"net_name":"A"}); return c
@case
def n6_lib_chars():
    c,i=base(); c.d=[e for e in c.d]; 
    for e in c.d:
        if e["type"]=="source_component" and e["name"]=="R1": e["manufacturer_part_number"]='A:B/C"D\\E E{F}<G>|H*?'
    return c
@case
def n7_values():
    c,i=base()
    for e in c.d:
        if e["type"]=="source_component" and e["name"]=="R1": e["resistance"]=999.9999
        if e["type"]=="source_component" and e["name"]=="R2": del e["resistance"]; e["capacitance"]=4.7e-12
    return c
@case
def n5_closed_outline():
    c,i=base(); o=c.d[0]["outline"]; o.append(dict(o[0])); return c
@case
def n4_offcentre():
    c,i=base(); c.d[0]["center"]={"x":100,"y":50}
    for p in c.d[0]["outline"]: p["x"]+=100; p["y"]+=50
    return c
@case
def name_escape():
    c,i=base(); a=c.net('N"ET (x)\\'); c.strace([i["s2"],i["s3"]],[a]); return c

# M3 (paddle-keyer): a part's internal connection, a router's net name the circuit lacks, silkscreen
def two_holes_one_pin(c, joined):
    # a USB-C shell: hole EH1 is pin 1, and a second hole for the same pin has no pin number, only the hint
    sa,pa=c.comp("J1",0,5,0); g=c.net("G"); out=[]
    for k,x in enumerate((0,3)):
        sp,pp=c.port(sa,pa,"EH1" if k==0 else "pin1_internal_1",1 if k==0 else None,x,5)
        hints=["EH1","pin1","1"] if k==0 else ["pin1_internal_1","pin1","1"]
        c.add({"type":"pcb_plated_hole","pcb_component_id":pa,"pcb_port_id":pp,"shape":"circle","x":x,"y":5,"outer_diameter":1.6,"hole_diameter":0.8,"port_hints":hints})
        out.append(sp)
    c.strace([out[0]],[g])
    if joined: c.add({"type":"source_component_internal_connection","source_component_internal_connection_id":"ic1","source_component_id":sa,"source_port_ids":out})
    return c
@case
def m3_internal_connection():
    c,i=base(); return two_holes_one_pin(c, True)
@case
def m3_internal_connection_missing():
    c,i=base(); return two_holes_one_pin(c, False)
@case
def m3_foreign_net_name():
    c,i=base(); a=c.net("A"); c.strace([i["s2"],i["s3"]],[a])
    c.add({"type":"pcb_trace","pcb_trace_id":"t1","net_name":"Net-(R1","route":[wire(-4.5,0),wire(0,0)]})
    c.add({"type":"pcb_trace","pcb_trace_id":"t2","net_name":"Net-(R1","route":[wire(0,0,"bottom"),wire(4.5,0,"bottom")]})
    c.add({"type":"pcb_via","pcb_via_id":"v1","net_name":"Net-(R1","x":0,"y":0,"outer_diameter":0.6,"hole_diameter":0.3,"from_layer":"top","to_layer":"bottom"}); return c
@case
def m3_foreign_net_two_nets():
    c,i=base(); a=c.net("A"); b=c.net("B"); c.strace([i["s2"]],[a]); c.strace([i["s3"]],[b])
    c.add({"type":"pcb_trace","pcb_trace_id":"t1","net_name":"Net-(R1","route":[wire(-4.5,0),wire(4.5,0)]}); return c
@case
def m3_silkscreen():
    c,i=base()
    pa=[e for e in c.d if e["type"]=="pcb_component"][0]["pcb_component_id"]
    c.add({"type":"pcb_silkscreen_path","pcb_silkscreen_path_id":"sp1","pcb_component_id":pa,"layer":"top","route":[{"x":-6,"y":1},{"x":-4,"y":1},{"x":-4,"y":-1}],"stroke_width":0.15})
    c.add({"type":"pcb_silkscreen_circle","pcb_silkscreen_circle_id":"sc1","pcb_component_id":pa,"layer":"top","center":{"x":-6,"y":-1},"radius":0.2,"stroke_width":0.15})
    c.add({"type":"pcb_silkscreen_path","pcb_silkscreen_path_id":"sp2","layer":"bottom","route":[{"x":0,"y":10},{"x":5,"y":10}],"stroke_width":0.2}); return c


# case -> (outcome, words the refusal must contain)
EXPECT = {
    's2_port_to_port': ('done', None),
    's2_port_two_nets': ('refused', 'joined'),
    's2_chain_two_nets': ('refused', 'joined'),
    's3_trace_no_netname_srctrace': ('done', None),
    's3_trace_no_netname_ports': ('done', None),
    's3_trace_geometry_only': ('refused', 'has no net'),
    's3_via_no_netname': ('done', None),
    's3_wrong_netname': ('refused', 'a short'),
    's4_route_via_no_pcb_via': ('done', None),
    's4_route_via_no_to_layer': ('refused', 'to_layer'),
    's4_route_via_wrong_from': ('refused', 'comes from'),
    's4_layer_change': ('refused', 'without a via'),
    's5_lpoly': ('done', None),
    's5_lpoly_port_outside': ('refused', 'inside polygon'),
    's6_cutout': ('refused', 'not handled'),
    's6_keepout': ('refused', 'not handled'),
    's6_trace_error': ('refused', 'pcb_trace_error'),
    's6_copper_text': ('refused', 'not handled'),
    's6_hole_offset': ('refused', 'hole_offset'),
    's6_pill_bad_radius': ('refused', 'radius'),
    's6_roundrect': ('done', None),
    's6_rotated_rect': ('refused', 'rotated_rect'),
    's6_rect_ccw_rotation': ('refused', 'ccw_rotation'),
    's6_courtyard_circle': ('refused', 'not handled'),
    's6_npth_pill_in_comp': ('refused', 'NPTH'),
    's6_npth_board_pill': ('refused', 'not handled'),
    's6_npth_board_oval': ('refused', 'not handled'),
    's6_board_circle_hole_shape_missing': ('refused', 'no hole_shape'),
    's7_no_number': ('refused', 'no number'),
    's7_pad_no_port': ('done', None),
    's7_dup_numbers': ('refused', 'two pads numbered'),
    'n2_blind_via': ('refused', 'only through vias'),
    'n2_blind_via_layers_only': ('refused', 'only through vias'),
    'n6_lib_chars': ('done', None),
    'n7_values': ('done', None),
    'n5_closed_outline': ('done', None),
    'n4_offcentre': ('done', None),
    'name_escape': ('done', None),
    'm3_internal_connection': ('done', None),
    'm3_internal_connection_missing': ('refused', 'two pads numbered'),
    'm3_foreign_net_name': ('done', None),
    'm3_foreign_net_two_nets': ('refused', 'a short'),
    'm3_silkscreen': ('done', None),
}
# what a done case's board must also hold, as (text that must appear, count)
HOLDS = {
    'm3_internal_connection': [('(pad "1" thru_hole', 2), ('(net "G")', 2)],
    'm3_foreign_net_name': [('(net "A")', 5), ('Net-(R1', 0)],
    'm3_silkscreen': [('(type solid)) (layer "F.SilkS")', 2), ('(fp_circle', 1), ('(layer "B.SilkS")', 1)],
}
WARNS = {'m3_foreign_net_name': 'net-renamed'}

if __name__ == "__main__":
    pcb, work = sys.argv[1:3]
    os.makedirs(work, exist_ok=True)
    assert set(EXPECT) == set(cases), set(EXPECT) ^ set(cases)
    results = {}
    for name, f in cases.items():
        cj = os.path.join(work, name + ".json")
        out = os.path.join(work, name + ".kicad_pcb")
        f().dump(cj)
        r = subprocess.run([pcb, "--json", "import-tscircuit", cj, "-o", out], capture_output=True, text=True)
        want, words = EXPECT[name]
        d, problems = check(r.stdout, r.returncode)
        if problems:
            results[name] = "output contract: " + "; ".join(problems)
            continue
        got = d["outcome"]
        msg = d.get("error", {}).get("message", "")
        if got != want:
            results[name] = f"expected {want}, got {got}: {msg}"
        elif words and words not in msg:
            results[name] = f"refused, but the message does not say {words!r}: {msg}"
        elif got == "done":
            v = subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_import.py"), cj, out], capture_output=True, text=True)
            results[name] = "ok" if v.returncode == 0 else f"verify_import failed: {v.stdout[-400:]}{v.stderr[-300:]}"
            text = open(out).read()
            for needle, count in HOLDS.get(name, []):
                if text.count(needle) != count:
                    results[name] = f"the board holds {needle!r} {text.count(needle)} times, expected {count}"
            if name in WARNS and not any(w.get("code") == WARNS[name] for w in d.get("warnings", [])):
                results[name] = f"no {WARNS[name]} warning"
        else:
            results[name] = "ok"
    bad = {k: v for k, v in results.items() if v != "ok"}
    print(json.dumps({"ok": not bad, "cases": len(results), "failed": bad}, indent=1))
    sys.exit(0 if not bad else 1)
