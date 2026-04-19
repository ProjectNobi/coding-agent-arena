#!/usr/bin/env python3
"""
verify_all.py — Project Nobi Arena
Master verification script. Imports and calls the real module functions
(not inline reimplementations) to avoid drift between verifier and code.

Usage:
  python verify_all.py

Exit code 0 = all checks passed.
Exit code 1 = one or more checks failed.
"""

import hashlib
import json
import platform
import sys
from pathlib import Path

# Add parent dir to path so we can import the arena modules directly.
# This ensures the verifier tests the ACTUAL code, not a stale inline copy.
sys.path.insert(0, str(Path(__file__).parent))

import draw_tasks as dt
import schedule as sc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS = "[PASS]"
FAIL = "[FAIL]"
results: list[tuple[bool, str]] = []


def check(passed: bool, label: str, detail: str = "") -> bool:
    """Record a check result and print it."""
    tag = PASS if passed else FAIL
    msg = f"{tag} {label}"
    if not passed and detail:
        msg += f"\n       → {detail}"
    print(msg)
    results.append((passed, label))
    return passed


# ---------------------------------------------------------------------------
# 1. draw_tasks — uses real module functions
# ---------------------------------------------------------------------------

def verify_draw_tasks(registry: dict) -> None:
    """Verify draw_tasks determinism and correctness using the real module."""
    print("\n── draw_tasks.py ──")

    season_pool = dt.get_season_pool(registry)

    for mid in [1, 25, 50]:
        # Determinism
        r1 = dt.draw_tasks(mid, "s1", season_pool)
        r2 = dt.draw_tasks(mid, "s1", season_pool)
        check(r1["tasks"] == r2["tasks"], f"draw match {mid}: deterministic")

        # 5 unique tasks
        check(len(set(r1["tasks"])) == dt.TASKS_PER_MATCH,
              f"draw match {mid}: {dt.TASKS_PER_MATCH} unique tasks",
              f"got {len(set(r1['tasks']))}")

        # All tasks in registry
        pool_set = set(season_pool)
        unknown = [t for t in r1["tasks"] if t not in pool_set]
        check(len(unknown) == 0, f"draw match {mid}: all tasks in registry",
              f"unknown: {unknown}")

        # Seed hex format (SHA-256 hex = 64 chars)
        check(len(r1["seed_hex"]) == 64, f"draw match {mid}: seed_hex is 64-char hex")

        # Python version recorded in output
        check("python_version" in r1, f"draw match {mid}: python_version in output")

    # Different matches → different draws
    r1 = dt.draw_tasks(1, "s1", season_pool)
    r2 = dt.draw_tasks(2, "s1", season_pool)
    check(r1["tasks"] != r2["tasks"], "draw: different matches give different tasks")

    # Different seasons → different draws
    r_s1 = dt.draw_tasks(1, "s1", season_pool)
    r_s2 = dt.draw_tasks(1, "s2", season_pool)
    check(r_s1["tasks"] != r_s2["tasks"], "draw: different seasons give different tasks")

    # Championship match flagged
    champ_results = []
    all_results = []
    for mid in range(1, 51):
        result = dt.draw_tasks(mid, "s1", season_pool)
        all_results.append(result)
        if mid == 50:
            champ_results.append(result)
    check(len(all_results) == 50, "draw --all: 50 results produced")

    # Canonical vectors are defined and complete
    check(len(dt.CANONICAL_VECTORS) == 3, "draw_tasks: 3 canonical vectors defined")
    for mid in [1, 25, 50]:
        check(
            mid in dt.CANONICAL_VECTORS
            and "seed_hex" in dt.CANONICAL_VECTORS[mid]
            and "tasks_hash" in dt.CANONICAL_VECTORS[mid]
            and len(dt.CANONICAL_VECTORS[mid]["seed_hex"]) == 64,
            f"draw_tasks: canonical vector for match {mid} is complete"
        )


# ---------------------------------------------------------------------------
# 2. schedule — uses real module functions
# ---------------------------------------------------------------------------

def verify_schedule(agent_registry: dict) -> None:
    """Verify schedule determinism and correctness using the real module."""
    print("\n── schedule.py ──")

    # Determinism
    o1 = sc.build_schedule_output("s1", agent_registry)
    o2 = sc.build_schedule_output("s1", agent_registry)
    check(o1["matches"] == o2["matches"], "schedule: deterministic")

    # dropped_matchup field
    dm = o1.get("dropped_matchup")
    check(dm is not None, "schedule: dropped_matchup field present")
    if dm:
        check(
            all(k in dm for k in ["agent_a_id", "agent_b_id", "home_subnet", "note"]),
            "schedule: dropped_matchup has all required fields",
            f"keys present: {list(dm.keys())}"
        )

    # Registry hash fields present (None is valid pre-season)
    check("task_registry_sha256" in o1, "schedule: task_registry_sha256 field present")
    check("agent_registry_sha256" in o1, "schedule: agent_registry_sha256 field present")

    matches = o1["matches"]
    regular = [m for m in matches if not m["championship"]]
    champ = [m for m in matches if m["championship"]]

    check(len(regular) == 49, "schedule: 49 regular matches", f"got {len(regular)}")
    check(len(champ) == 1, "schedule: 1 championship match", f"got {len(champ)}")
    check(champ[0]["match_id"] == sc.CHAMPIONSHIP_MATCH_ID,
          f"schedule: championship is match_id {sc.CHAMPIONSHIP_MATCH_ID}")

    # SN66/SN62 agent disjointness
    sn66_ids = {a["id"] for a in agent_registry["sn66_agents"]}
    sn62_ids = {a["id"] for a in agent_registry["sn62_agents"]}
    check(
        len(sn66_ids & sn62_ids) == 0,
        "schedule: SN66 and SN62 agent IDs are disjoint",
        f"overlap: {sn66_ids & sn62_ids}"
    )

    # Pair distribution: 24×2 + 1×1 = 49 regular matches
    pair_count: dict[tuple, int] = {}
    for m in regular:
        a, b = m["agent_a"]["id"], m["agent_b"]["id"]
        pair = tuple(sorted([a, b]))
        pair_count[pair] = pair_count.get(pair, 0) + 1

    over = {p: c for p, c in pair_count.items() if c > 2}
    once_count = sum(1 for c in pair_count.values() if c == 1)
    twice_count = sum(1 for c in pair_count.values() if c == 2)
    check(len(over) == 0, "schedule: no pair appears more than twice", f"over: {over}")
    check(twice_count == 24 and once_count == 1,
          "schedule: 24 pairs x2 + 1 pair x1 = 49 regular matches",
          f"twice={twice_count}, once={once_count}")

    # No duplicate triplets
    triplets = [(m["agent_a"]["id"], m["agent_b"]["id"], m["home_subnet"]) for m in regular]
    check(len(triplets) == len(set(triplets)), "schedule: no duplicate match triplets")

    # match_ids 1-50 with no gaps
    ids = sorted(m["match_id"] for m in matches)
    check(ids == list(range(1, 51)), "schedule: match_ids are 1-50 with no gaps",
          f"got: {ids}")

    # Python version in output
    check("python_version" in o1, "schedule: python_version in output")

    # commit-reveal note present
    check("commit_reveal_note" in o1, "schedule: commit_reveal_note in output")

    # Null hotkeys: warn if agents have null hotkeys (not a failure — pre-season expected)
    null_hotkeys = [m["agent_a"]["id"] for m in regular if m["agent_a"]["hotkey"] is None]
    if null_hotkeys:
        print(f"[WARN] schedule: {len(null_hotkeys)} matches have null hotkeys "
              f"(expected pre-season — must be populated before Day 0)")

    # Different seasons → different schedules
    o_alt = sc.build_schedule_output("s2", agent_registry)
    check(
        [m["agent_a"]["id"] for m in o1["matches"] if not m["championship"]] !=
        [m["agent_a"]["id"] for m in o_alt["matches"] if not m["championship"]],
        "schedule: different seasons give different orderings"
    )


# ---------------------------------------------------------------------------
# 3. task_registry.json — schema and disjoint check
# ---------------------------------------------------------------------------

def verify_task_registry(registry: dict) -> None:
    """Verify task_registry.json schema and pool isolation."""
    print("\n── task_registry.json ──")

    required = ["schema_version", "note", "pools_are_disjoint", "meta",
                "season_matches", "qualifier", "reserve", "holdout"]
    for field in required:
        check(field in registry, f"task_registry: field '{field}' present")

    meta = registry.get("meta", {})
    season = registry.get("season_matches", [])
    qualifier = registry.get("qualifier", [])
    reserve = registry.get("reserve", [])
    holdout = registry.get("holdout", [])

    # Count checks
    check(len(season) == meta.get("season_matches_count"),
          f"task_registry: season_matches count = {meta.get('season_matches_count')}",
          f"actual: {len(season)}")
    check(len(qualifier) == meta.get("qualifier_count"),
          f"task_registry: qualifier count = {meta.get('qualifier_count')}",
          f"actual: {len(qualifier)}")
    check(len(reserve) == meta.get("reserve_count"),
          f"task_registry: reserve count = {meta.get('reserve_count')}",
          f"actual: {len(reserve)}")
    check(len(holdout) == meta.get("holdout_count"),
          f"task_registry: holdout count = {meta.get('holdout_count')}",
          f"actual: {len(holdout)}")

    total = len(season) + len(qualifier) + len(reserve) + len(holdout)
    check(total == meta.get("total_tasks"),
          f"task_registry: total = {meta.get('total_tasks')}",
          f"actual: {total}")

    # Extract all IDs — handle both object and string entries
    def extract_id(entry) -> str:
        return entry["id"] if isinstance(entry, dict) else entry

    season_ids = {extract_id(t) for t in season}
    qualifier_ids = {extract_id(t) for t in qualifier}
    reserve_ids = {extract_id(t) for t in reserve}
    holdout_ids = {extract_id(t) for t in holdout}

    # CRITICAL disjoint checks — a task in two pools = competitive advantage
    overlaps = [
        ("season ∩ qualifier", season_ids & qualifier_ids),
        ("season ∩ reserve",   season_ids & reserve_ids),
        ("season ∩ holdout",   season_ids & holdout_ids),
        ("qualifier ∩ reserve",qualifier_ids & reserve_ids),
        ("qualifier ∩ holdout",qualifier_ids & holdout_ids),
        ("reserve ∩ holdout",  reserve_ids & holdout_ids),
    ]
    for label, overlap in overlaps:
        check(len(overlap) == 0, f"task_registry: disjoint {label}",
              f"{len(overlap)} duplicates: {list(overlap)[:3]}")

    all_ids = list(season_ids) + list(qualifier_ids) + list(reserve_ids) + list(holdout_ids)
    check(len(all_ids) == len(set(all_ids)), "task_registry: all IDs globally unique")

    # Schema checks on season_matches
    season_fields_ok = all(
        isinstance(t, dict) and "id" in t and "domain" in t and "difficulty" in t
        for t in season
    )
    check(season_fields_ok, "task_registry: season_matches have id/domain/difficulty")

    # Schema checks on qualifier
    qualifier_fields_ok = all(
        isinstance(t, dict) and "id" in t and "domain" in t for t in qualifier
    )
    check(qualifier_fields_ok, "task_registry: qualifier entries have id/domain")

    # Valid domains
    valid_domains = {"django", "scikit-learn", "matplotlib", "sympy",
                     "pytest", "requests", "flask", "pandas"}
    bad_domains = {t["domain"] for t in season if t["domain"] not in valid_domains}
    check(len(bad_domains) == 0, "task_registry: all domains valid",
          f"unknown: {bad_domains}")

    # Check pools_are_disjoint flag is consistent with reality
    actual_disjoint = all(len(overlap) == 0 for _, overlap in overlaps)
    check(registry.get("pools_are_disjoint") == actual_disjoint,
          "task_registry: pools_are_disjoint flag matches reality",
          f"flag={registry.get('pools_are_disjoint')}, actual={actual_disjoint}")


# ---------------------------------------------------------------------------
# 4. agent_registry.json — schema check
# ---------------------------------------------------------------------------

def verify_agent_registry(agent_registry: dict) -> None:
    """Verify agent_registry.json schema."""
    print("\n── agent_registry.json ──")

    required = ["schema_version", "season", "selection_method", "sn66_agents", "sn62_agents"]
    for field in required:
        check(field in agent_registry, f"agent_registry: field '{field}' present")

    sn66 = agent_registry.get("sn66_agents", [])
    sn62 = agent_registry.get("sn62_agents", [])

    check(len(sn66) == 5, "agent_registry: 5 SN66 agent slots", f"got {len(sn66)}")
    check(len(sn62) == 5, "agent_registry: 5 SN62 agent slots", f"got {len(sn62)}")

    agent_fields = ["id", "subnet", "slot", "hotkey", "commit_sha256",
                    "repo_url", "model_manifest", "registered_at", "status"]
    for agent in sn66 + sn62:
        missing_fields = [f for f in agent_fields if f not in agent]
        check(len(missing_fields) == 0,
              f"agent_registry: agent {agent.get('id')} has all fields",
              f"missing: {missing_fields}")

    all_ids = [a["id"] for a in sn66 + sn62]
    check(len(all_ids) == len(set(all_ids)), "agent_registry: all agent IDs unique")

    sn66_slots = sorted(a["slot"] for a in sn66)
    sn62_slots = sorted(a["slot"] for a in sn62)
    check(sn66_slots == [1, 2, 3, 4, 5], "agent_registry: SN66 slots 1-5")
    check(sn62_slots == [1, 2, 3, 4, 5], "agent_registry: SN62 slots 1-5")

    # Warn if hotkeys are null (expected pre-season)
    null_hotkeys = [a["id"] for a in sn66 + sn62 if a["hotkey"] is None]
    if null_hotkeys:
        print(f"[WARN] agent_registry: {len(null_hotkeys)} agents have null hotkeys "
              f"(expected pre-season — must be populated before Week -1 Friday)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"Project Nobi Arena — Verification Suite")
    print(f"Python {platform.python_version()} on {platform.system()}")
    print("=" * 50)

    base = Path(__file__).parent

    task_registry_path = base / "task_registry.json"
    agent_registry_path = base / "agent_registry.json"

    errors = []
    for p in [task_registry_path, agent_registry_path]:
        if not p.exists():
            errors.append(f"Missing: {p}")
    if errors:
        for e in errors:
            print(f"[FAIL] {e}")
        sys.exit(1)

    with open(task_registry_path) as f:
        task_registry = json.load(f)
    with open(agent_registry_path) as f:
        agent_registry = json.load(f)

    verify_draw_tasks(task_registry)
    verify_schedule(agent_registry)
    verify_task_registry(task_registry)
    verify_agent_registry(agent_registry)

    total = len(results)
    passed = sum(1 for ok, _ in results if ok)
    failed = total - passed

    print(f"\n{'='*50}")
    if failed == 0:
        print(f"✅ All {total} checks passed.")
    else:
        print(f"❌ {failed}/{total} checks failed — see above.")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
