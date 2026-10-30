"""Builder for small synthetic tscircuit circuit JSON files, used by cases/import_cases.py.

Adapted from the review 2 reviewer's generator (30 Oct 2026)."""
import json, math
class C:
    def __init__(s, w=40, h=30, cx=0, cy=0):
        s.d=[{"type":"pcb_board","pcb_board_id":"b","center":{"x":cx,"y":cy},"width":w,"height":h,"num_layers":2,"thickness":1.6,
              "outline":[{"x":cx-w/2,"y":cy-h/2},{"x":cx+w/2,"y":cy-h/2},{"x":cx+w/2,"y":cy+h/2},{"x":cx-w/2,"y":cy+h/2}]}]
        s.n=0
    def id(s,p): s.n+=1; return f"{p}_{s.n}"
    def comp(s, name, x, y, rot=0, layer="top", **kw):
        sc=s.id("sc"); pc=s.id("pc")
        s.d.append(dict({"type":"source_component","source_component_id":sc,"name":name,"ftype":"simple_chip"},**kw))
        s.d.append({"type":"pcb_component","pcb_component_id":pc,"source_component_id":sc,"center":{"x":x,"y":y},"rotation":rot,"layer":layer,"width":1,"height":1})
        return sc,pc
    def port(s, sc, pc, name, pin, x, y):
        sp=s.id("sp"); pp=s.id("pp")
        e={"type":"source_port","source_port_id":sp,"source_component_id":sc,"name":name}
        if pin is not None: e["pin_number"]=pin
        s.d.append(e)
        s.d.append({"type":"pcb_port","pcb_port_id":pp,"source_port_id":sp,"pcb_component_id":pc,"x":x,"y":y,"layers":["top"]})
        return sp,pp
    def pad(s, pc, pp, x, y, shape="rect", layer="top", **kw):
        e=dict({"type":"pcb_smtpad","pcb_smtpad_id":s.id("pad"),"pcb_component_id":pc,"pcb_port_id":pp,"x":x,"y":y,"shape":shape,"layer":layer},**kw)
        s.d.append(e); return e
    def net(s,name):
        i=s.id("sn"); s.d.append({"type":"source_net","source_net_id":i,"name":name}); return i
    def strace(s, ports=(), nets=()):
        i=s.id("st"); s.d.append({"type":"source_trace","source_trace_id":i,"connected_source_port_ids":list(ports),"connected_source_net_ids":list(nets)}); return i
    def add(s,e): s.d.append(e); return e
    def dump(s,p): json.dump(s.d,open(p,"w"))
def rot_yup(x,y,deg):
    a=math.radians(deg); return (x*math.cos(a)-y*math.sin(a), x*math.sin(a)+y*math.cos(a))
