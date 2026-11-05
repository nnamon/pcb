"""Checks one command's output against the output contract: the JSON validates against schemas/<command>.json
(which includes schemas/envelope.json), and the exit code matches the outcome (0 done, 1 rejected, 2 refused,
3 failed). Used by every case script, so each run of the suite checks the contract too."""
import json
import os

import jsonschema
from referencing import Registry, Resource

SCHEMAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "schemas")
EXIT = {"done": 0, "rejected": 1, "refused": 2, "failed": 3}


def _registry():
    reg = Registry()
    for f in os.listdir(SCHEMAS):
        doc = json.load(open(os.path.join(SCHEMAS, f)))
        reg = reg.with_resource(doc["$id"], Resource.from_contents(doc))
    return reg


_REG = _registry()


def check(stdout, exit_code):
    """Returns (parsed object, list of problems)."""
    try:
        d = json.loads(stdout)
    except ValueError:
        return None, [f"not one JSON object: {stdout[-200:]!r}"]
    problems = []
    schema_id = d.get("schema", "")
    name = schema_id.split("/")[1] + ".json" if schema_id.count("/") == 2 else None
    if not name or not os.path.exists(os.path.join(SCHEMAS, name)):
        return d, [f"no schema file for {schema_id!r}"]
    schema = json.load(open(os.path.join(SCHEMAS, name)))
    v = jsonschema.Draft202012Validator(schema, registry=_REG)
    problems += [f"schema: {e.message} at {list(e.path)}" for e in v.iter_errors(d)]
    want = EXIT.get(d.get("outcome"))
    if want is not None and want != exit_code:
        problems.append(f"exit code {exit_code} for outcome {d.get('outcome')} (want {want})")
    return d, problems
