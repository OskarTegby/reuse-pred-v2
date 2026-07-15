import os
import sys

from scenario import (
    BIN_DIR, TRACE_PATHS,
    POLICIES, CONDITIONS, TRACE_KEYS, STATIC_FRAGMENTS, SCENARIO_MATRIX,
)


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


def unknown_scenario(scen):
    sys.stderr.write("unknown scenario '%s'\n" % scen)
    return None


def resolve_scenario(scen):
    parsed = parse_scenario(scen)
    if parsed is None:
        return unknown_scenario(scen)
    pol, cond, trc = parsed

    if trc not in TRACE_PATHS:
        return unknown_scenario(scen)

    binary, env_vars = resolve_binary_and_env(pol, cond)
    if binary is None:
        return unknown_scenario(scen)

    trace = os.environ.get("TRACE") or TRACE_PATHS[trc]
    bin_path = os.path.join(BIN_DIR, binary)
    return bin_path, trace, env_vars
