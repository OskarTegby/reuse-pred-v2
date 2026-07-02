# Logic for interpreting the data in scenario.py: the scenario naming
# scheme and the SCENARIO_MATRIX/STATIC_FRAGMENTS lookup. Has scenario/
# policy knowledge, so it can't live in fileutils.py; it's logic, not
# data, so it can't live in scenario.py either.

from scenario import POLICIES, CONDITIONS, TRACE_KEYS, STATIC_FRAGMENTS, SCENARIO_MATRIX


def list_scenarios():
    out = []
    for p in POLICIES:
        for c in CONDITIONS:
            for t in TRACE_KEYS:
                out.append(p + "_" + c + "_" + t)
    return out


def parse_scenario(scen):
    parts = scen.split("_")
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


def resolve_fragment(frag):
    return frag if isinstance(frag, dict) else STATIC_FRAGMENTS[frag]


def resolve_binary_and_env(pol, cond):
    entry = SCENARIO_MATRIX.get(pol, {}).get(cond)
    if entry is None:
        return None, None
    binary, fragments = entry
    env = {}
    for frag in fragments:
        env.update(resolve_fragment(frag))
    return binary, env
