"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    metrics = pr.get("metrics") or {}

    # 1. metric values that compare False against every threshold
    for k, v in metrics.items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (NaN/inf compares False against any threshold)")

    # 2. graders that crashed, or whose result went missing
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), first: {pr['evaluator_failures'][0]}")
    rows = pr.get("rows") or []
    for m in graded:
        bad = [r for r in rows if not isinstance(r.get(m), bool)]
        if bad:
            problems.append(f"{len(bad)} row(s) with no boolean value for graded metric {m} "
                            f"(first {bad[0].get('item_id')}@{bad[0].get('seed')}: {bad[0].get(m)!r})")

    # 3. row coverage: every (item, seed) exactly once, and the same set as the baseline
    man, bman = pr.get("manifest") or {}, base.get("manifest") or {}
    pairs = [(r.get("item_id"), r.get("seed")) for r in rows]
    if len(set(pairs)) != len(pairs):
        problems.append(f"{len(pairs) - len(set(pairs))} duplicated (item, seed) row(s)")
    try:
        want = int(man.get("items")) * len(man.get("seeds") or [])
    except (TypeError, ValueError):
        want = None
    if want is None or len(rows) != want:
        problems.append(f"{len(rows)} rows, manifest says {man.get('items')} items x {len(man.get('seeds') or [])} seeds")
    for key in ("items", "seeds"):
        if man.get(key) != bman.get(key):
            problems.append(f"manifest {key} {man.get(key)!r} differs from the baseline's {bman.get(key)!r}")
    base_pairs = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    if set(pairs) != base_pairs:
        miss, extra = base_pairs - set(pairs), set(pairs) - base_pairs
        problems.append(f"(item, seed) set differs from the baseline: {len(miss)} missing, {len(extra)} extra")

    # 4. slice tags must be the baseline's (relabelling an item out of a slice hides it)
    base_slices = {r.get("item_id"): sorted(r.get("slices") or []) for r in base.get("rows") or []}
    moved = sorted({str(r.get("item_id")) for r in rows if r.get("item_id") in base_slices
                    and sorted(r.get("slices") or []) != base_slices[r.get("item_id")]})
    if moved:
        problems.append(f"slice tags differ from the baseline for {len(moved)} item(s), e.g. {moved[0]}")

    # 5. reported metrics must be what the rows say (a hand-edited number is not a measurement)
    if rows and not problems:
        try:
            recomputed = aggregate(rows, [m for m in graded if m in rows[0]], k_values=spec.get("pass_k", []))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            recomputed = {}
        for k, v in recomputed.items():
            if k in metrics and not _close(metrics[k], v):
                problems.append(f"metric {k} reported {metrics[k]!r} but the rows give {v!r}")

    # 6. ratchet: on the same eval set, thresholds only get stricter
    if base_spec is not None:
        problems += ratchet_check(spec, base_spec,
                                  same_eval_set=man.get("eval_set_sha") == bman.get("eval_set_sha"))
    return problems


def _close(a, b) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return a == b
    return math.isfinite(a) and abs(a - b) <= 1e-4


def _looser(th: dict, bth: dict) -> list[str]:
    out = []
    for key in ("max", "max_increase"):
        if key in bth and (key not in th or th[key] > bth[key]):
            out.append(f"{key} {bth[key]} -> {th.get(key, 'removed')}")
    if "min" in bth and ("min" not in th or th["min"] < bth["min"]):
        out.append(f"min {bth['min']} -> {th.get('min', 'removed')}")
    if bth.get("no_significant_drop") and not th.get("no_significant_drop"):
        out.append("no_significant_drop dropped")
    return out


def ratchet_check(spec: dict, base_spec: dict, *, same_eval_set: bool = True) -> list[str]:
    """Thresholds may only get stricter while the eval-set version stays the same. Renaming the
    version without changing the eval set does not reset the ratchet."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        if same_eval_set or spec.get("eval_set") == base_spec.get("eval_set"):
            return [f"RATCHET eval_set_version {base_spec.get('eval_set_version')!r} -> "
                    f"{spec.get('eval_set_version')!r} but the eval set itself did not change"]
        return []
    problems = []
    cur = {m["id"]: m for m in spec.get("metrics", [])}
    for bm in base_spec.get("metrics", []):
        m = cur.get(bm["id"])
        if m is None:
            problems.append(f"RATCHET metric {bm['id']} removed")
            continue
        if bm.get("blocking") and not m.get("blocking"):
            problems.append(f"RATCHET metric {bm['id']} no longer blocking")
        problems += [f"RATCHET metric {bm['id']} {x}"
                     for x in _looser(m.get("threshold") or {}, bm.get("threshold") or {})]
    cur_sl = {(x.get("name"), x.get("metric")): x for x in spec.get("slices") or []}
    for bs in base_spec.get("slices") or []:
        key = (bs.get("name"), bs.get("metric"))
        sl = cur_sl.get(key)
        if sl is None:
            problems.append(f"RATCHET slice {key[0]}/{key[1]} removed")
            continue
        if bs.get("blocking") and not sl.get("blocking"):
            problems.append(f"RATCHET slice {key[0]}/{key[1]} no longer blocking")
        problems += [f"RATCHET slice {key[0]}/{key[1]} {x}" for x in _looser(sl, bs)]
    cur_rr = {x.get("metric"): x for x in spec.get("row_regressions") or []}
    for br in base_spec.get("row_regressions") or []:
        rr = cur_rr.get(br.get("metric"))
        if rr is None:
            problems.append(f"RATCHET row_regressions/{br.get('metric')} removed")
            continue
        if br.get("blocking") and not rr.get("blocking"):
            problems.append(f"RATCHET row_regressions/{br.get('metric')} no longer blocking")
        if rr.get("max", 0) > br.get("max", 0):
            problems.append(f"RATCHET row_regressions/{br.get('metric')} max {br.get('max', 0)} -> {rr.get('max', 0)}")
    for key in ("seeds", "pass_k", "bootstrap", "eval_set", "labels", "adversarial_pack"):
        if base_spec.get(key) != spec.get(key):
            problems.append(f"RATCHET {key} changed {base_spec.get(key)!r} -> {spec.get(key)!r}")
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict, note = "fail", "slice empty in PR"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if "max" in sl and val > sl["max"]:
                verdict = "fail"
            if sl.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}] n={len(keys)}"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        label = "ok" if verdict == "ok" else ("BLOCK" if sl.get("blocking") else "warn")
        lines.append(f"  {sid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    if spec.get("row_regressions"):
        rb, rl = row_regression_check(pr, base, spec)
        blocked += rb
        lines += rl
    return blocked, lines


def row_regression_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """Trials that passed on main and fail on the PR, matched on (item, seed).
    Only meaningful when the A/A noise band is 0 (deterministic MockLLM, same seeds): then a flip is
    a real regression even when the aggregate is unchanged -- e.g. a bug moved from one seed to
    another, or an override that no longer leaves a trace event. With a real LLM, replace max: 0
    by a tolerance taken from the A/A run, or drop the check."""
    blocked, lines = [], []
    safety = {m["id"] for m in spec.get("metrics", []) if m.get("kind") == "safety"}
    base_rows = {(r.get("item_id"), r.get("seed")): r for r in base.get("rows") or []}
    for rr in spec.get("row_regressions") or []:
        metric = rr["metric"]
        good = (lambda v: v is False) if metric in safety else (lambda v: v is True)
        flips = sorted(f"{r['item_id']}@{r['seed']}" for r in pr.get("rows") or []
                       if (r.get("item_id"), r.get("seed")) in base_rows
                       and good(base_rows[(r.get("item_id"), r.get("seed"))].get(metric)) and not good(r.get(metric)))
        rid = f"rows:{metric}"
        fail = len(flips) > rr.get("max", 0)
        if fail and rr.get("blocking"):
            blocked.append(rid)
        label = "ok" if not fail else ("BLOCK" if rr.get("blocking") else "warn")
        note = f"new failures: {', '.join(flips[:4])}{' …' if len(flips) > 4 else ''}" if flips else ""
        lines.append(f"  {rid:<22} {len(flips)!s:<8} {json.dumps({'max': rr.get('max', 0)}):<40} {note:<28} {label}")
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
