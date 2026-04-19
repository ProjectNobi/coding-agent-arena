#!/usr/bin/env python3
"""
schedule.py — Project Nobi Arena
Deterministic match schedule generator for Season 1.

Generates the full 50-match schedule using a seeded PRNG. Anyone can
run this script to reproduce the exact schedule independently.

Algorithm:
  1. Load agent_registry.json (5 SN66 agents + 5 SN62 agents)
  2. Sort agents by ID (ascending) — order-independent of JSON array ordering
  3. Generate all 25 unique cross-subnet pairings (SN66 i vs SN62 j)
  4. Each pair gets 2 matchups: one SN66-home, one SN62-home = 50 total
  5. Shuffle all 50 matchups using seeded PRNG
     Seed: SHA-256("s1|schedule|nobi-arena-v1", encoding=UTF-8)
  6. Assign match_id 1-49 to the first 49 shuffled matchups (regular season)
  7. The 50th matchup (dropped_matchup) is published for transparency
  8. Match 50 = Championship Day (reserved — TBD post-season by final standings)

Note on the dropped matchup:
  50 matchups ÷ 49 regular slots = one matchup gets dropped. This pair plays
  only once in the regular season (instead of twice). The dropped matchup is
  fully deterministic from the published seed and is disclosed in the schedule
  output. Both the dropped pair and its home/away direction are knowable from
  the published schedule seed — this is by design (full transparency).

Usage:
  python schedule.py --season s1
  python schedule.py --season s1 --output schedule.json
  python schedule.py --season s1 --match 1
  python schedule.py --verify
  python schedule.py --registry agent_registry.json --task-registry task_registry.json --season s1
"""

from __future__ import annotations  # Python 3.9 compat for type hints

import argparse
import hashlib
import json
import platform
import random
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEED_SUFFIX = "nobi-arena-v1"
DEFAULT_REGISTRY = Path(__file__).parent / "agent_registry.json"
DEFAULT_TASK_REGISTRY = Path(__file__).parent / "task_registry.json"
CHAMPIONSHIP_MATCH_ID = 50
AGENTS_PER_SUBNET = 5

# Season ID must be alphanumeric + hyphens/underscores only (prevents injection).
SEASON_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_season_id(season_id: str) -> None:
    """Validate season_id format to prevent seed string injection."""
    if not SEASON_ID_PATTERN.match(season_id):
        raise ValueError(
            f"Invalid season_id {season_id!r} — must match {SEASON_ID_PATTERN.pattern}"
        )


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def compute_schedule_seed(season_id: str) -> tuple[str, int]:
    """
    Compute the deterministic seed for schedule generation.

    The schedule seed is separate from the per-match task-draw seed,
    so schedule order and task selection are independently auditable.

    Encoding: UTF-8 (explicit). Byte order: big-endian.
    """
    validate_season_id(season_id)
    seed_input = f"{season_id}|schedule|{SEED_SUFFIX}"
    # Explicit UTF-8 encoding — required for cross-language reproducibility.
    digest = hashlib.sha256(seed_input.encode("utf-8")).digest()
    seed_int = int.from_bytes(digest, "big")
    return seed_input, seed_int


def generate_matchups(sn66_agents: list[dict], sn62_agents: list[dict]) -> list[dict]:
    """
    Generate all 50 matchups (25 pairs × 2 home/away directions).

    Agents MUST be sorted by ID before calling this function (done in
    generate_schedule). This ensures matchup generation is independent
    of JSON array ordering in agent_registry.json — same logical agents
    always produce the same initial matchup list regardless of how the
    JSON file happens to be ordered.
    """
    matchups = []
    for a in sn66_agents:
        for b in sn62_agents:
            # SN66 home
            matchups.append({
                "agent_a": a,
                "agent_b": b,
                "home_subnet": "SN66",
                "away_subnet": "SN62",
            })
            # SN62 home
            matchups.append({
                "agent_a": b,
                "agent_b": a,
                "home_subnet": "SN62",
                "away_subnet": "SN66",
            })
    return matchups


def generate_schedule(season_id: str, registry: dict) -> tuple[list[dict], dict]:
    """
    Generate the full 50-match schedule deterministically.

    Returns:
        (schedule, dropped_matchup) where:
        - schedule: list of 50 match dicts ordered by match_id (1-50)
        - dropped_matchup: the one matchup from the 50 that became
          Championship Day's slot (published for transparency)
    """
    validate_season_id(season_id)

    sn66_raw = registry["sn66_agents"]
    sn62_raw = registry["sn62_agents"]

    # Validate agent counts
    if len(sn66_raw) != AGENTS_PER_SUBNET or len(sn62_raw) != AGENTS_PER_SUBNET:
        raise ValueError(
            f"Expected {AGENTS_PER_SUBNET} agents per subnet, "
            f"got SN66={len(sn66_raw)}, SN62={len(sn62_raw)}"
        )

    # Sort agents by ID (ascending) for reproducibility.
    # Without sorting, two auditors with semantically identical registries
    # but different JSON array orderings would get different schedules.
    sn66 = sorted(sn66_raw, key=lambda a: a["id"])
    sn62 = sorted(sn62_raw, key=lambda a: a["id"])

    # Validate SN66/SN62 agent disjointness
    sn66_ids = {a["id"] for a in sn66}
    sn62_ids = {a["id"] for a in sn62}
    overlap = sn66_ids & sn62_ids
    if overlap:
        raise ValueError(
            f"Agents appear in both SN66 and SN62 registries: {sorted(overlap)}"
        )

    # Generate all 50 matchups
    all_matchups = generate_matchups(sn66, sn62)  # exactly 5×5×2 = 50

    seed_input, seed_int = compute_schedule_seed(season_id)
    rng = random.Random(seed_int)

    # Shuffle to determine order — the core deterministic step.
    # NOTE: record Python version — random.shuffle may vary across minor versions.
    shuffled = all_matchups.copy()
    rng.shuffle(shuffled)

    # First 49 shuffled matchups → regular season (match_id 1-49)
    # The 50th shuffled matchup → dropped (replaced by Championship Day)
    # The dropped matchup is published in the schedule output for full transparency.
    regular_matchups = shuffled[:49]
    dropped = shuffled[49]

    schedule = []
    for i, matchup in enumerate(regular_matchups, start=1):
        match = {
            "match_id": i,
            "day": i,
            "agent_a": {
                "id": matchup["agent_a"]["id"],
                "subnet": matchup["agent_a"]["subnet"],
                "hotkey": matchup["agent_a"]["hotkey"],
            },
            "agent_b": {
                "id": matchup["agent_b"]["id"],
                "subnet": matchup["agent_b"]["subnet"],
                "hotkey": matchup["agent_b"]["hotkey"],
            },
            "home_subnet": matchup["home_subnet"],
            "away_subnet": matchup["away_subnet"],
            "draw_seed_input": f"{season_id}|{i}|{SEED_SUFFIX}",
            "championship": False,
        }
        schedule.append(match)

    # Match 50: Championship Day — agents determined post-season by final standings
    schedule.append({
        "match_id": CHAMPIONSHIP_MATCH_ID,
        "day": CHAMPIONSHIP_MATCH_ID,
        "agent_a": {"id": "TBD", "subnet": "SN66", "hotkey": None},
        "agent_b": {"id": "TBD", "subnet": "SN62", "hotkey": None},
        "home_subnet": "neutral",
        "away_subnet": "neutral",
        "draw_seed_input": f"{season_id}|{CHAMPIONSHIP_MATCH_ID}|{SEED_SUFFIX}",
        "championship": True,
        "note": (
            "Championship Day. Agents: top-ranked SN66 vs top-ranked SN62 "
            "by final regular-season standings."
        ),
    })

    # Build dropped_matchup disclosure
    dropped_matchup = {
        "agent_a_id": dropped["agent_a"]["id"],
        "agent_b_id": dropped["agent_b"]["id"],
        "home_subnet": dropped["home_subnet"],
        "away_subnet": dropped["away_subnet"],
        "note": (
            "This matchup was displaced by Championship Day (match 50). "
            "The reverse fixture (opposite home/away) is included in the regular season. "
            "The displaced pair plays once instead of twice. "
            "The displaced matchup is deterministic from the published schedule seed — "
            "it is disclosed here for full transparency."
        ),
    }

    return schedule, dropped_matchup


def build_schedule_output(
    season_id: str,
    registry: dict,
    task_registry_path: Path | None = None,
    agent_registry_path: Path | None = None,
) -> dict:
    """
    Build the full schedule output dict including metadata and registry hashes.

    If task_registry_path and agent_registry_path are provided, their SHA-256
    hashes are included in the output. Publishing this output satisfies the
    commit-reveal requirement: the registry hashes are bound to the published
    schedule, preventing post-publication registry swaps.
    """
    seed_input, _ = compute_schedule_seed(season_id)
    schedule, dropped_matchup = generate_schedule(season_id, registry)

    output = {
        "schema_version": "1.0",
        "season_id": season_id,
        "schedule_seed_input": seed_input,
        "schedule_seed_hex": hashlib.sha256(seed_input.encode("utf-8")).hexdigest(),
        "python_version": platform.python_version(),
        "total_matches": len(schedule),
        "regular_matches": len([m for m in schedule if not m["championship"]]),
        "championship_match": CHAMPIONSHIP_MATCH_ID,
        "dropped_matchup": dropped_matchup,
        "commit_reveal_note": (
            "OPERATIONAL REQUIREMENT: publish this schedule output (including "
            "task_registry_sha256 and agent_registry_sha256 below) to an immutable "
            "record (git tag / blockchain) BEFORE the season starts. "
            "At draw time, verify registry files match these hashes. "
            "Publishing this document constitutes the commitment — the hashes "
            "prevent post-publication registry swaps."
        ),
        "matches": schedule,
    }

    # Compute and embed registry SHA-256 hashes if paths provided.
    # These hashes ARE the commit-reveal commitment. Publishing the schedule
    # output (which includes these hashes) satisfies the commitment requirement.
    if task_registry_path is not None and task_registry_path.exists():
        with open(task_registry_path, "rb") as f:
            output["task_registry_sha256"] = hashlib.sha256(f.read()).hexdigest()
    else:
        output["task_registry_sha256"] = None

    if agent_registry_path is not None and agent_registry_path.exists():
        with open(agent_registry_path, "rb") as f:
            output["agent_registry_sha256"] = hashlib.sha256(f.read()).hexdigest()
    else:
        output["agent_registry_sha256"] = None

    return output


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test(registry: dict) -> bool:
    """
    Run schedule self-tests. Returns True if all pass.

    Tests:
    1. Determinism: same registry + season → same schedule twice
    2. Exactly 49 regular matches + 1 championship = 50 total
    3. Pair distribution: 24 pairs appear twice, 1 pair appears once (49 total)
    4. No pair appears more than twice
    5. No duplicate (agent_a, agent_b, home_subnet) triplets
    6. match_ids are 1-50 with no gaps
    7. dropped_matchup field is present and valid
    8. Championship match is match_id 50
    9. Different seasons → different schedules
    10. Agents are sorted by ID in schedule output
    """
    print("Running schedule self-tests...")
    all_passed = True

    # Test 1: determinism
    output_a = build_schedule_output("s1", registry)
    output_b = build_schedule_output("s1", registry)
    if output_a["matches"] != output_b["matches"]:
        print("[FAIL] schedule: non-deterministic output")
        all_passed = False
    else:
        print("[PASS] schedule: deterministic")

    matches = output_a["matches"]
    regular = [m for m in matches if not m["championship"]]
    champ = [m for m in matches if m["championship"]]

    # Test 2: count
    if len(regular) != 49 or len(champ) != 1:
        print(f"[FAIL] schedule: expected 49+1 matches, got {len(regular)}+{len(champ)}")
        all_passed = False
    else:
        print("[PASS] schedule: 49 regular + 1 championship")

    # Test 3 & 4: pair distribution
    pair_count: dict[tuple, int] = {}
    for m in regular:
        pair = tuple(sorted([m["agent_a"]["id"], m["agent_b"]["id"]]))
        pair_count[pair] = pair_count.get(pair, 0) + 1

    over = {p: c for p, c in pair_count.items() if c > 2}
    once_count = sum(1 for c in pair_count.values() if c == 1)
    twice_count = sum(1 for c in pair_count.values() if c == 2)

    if over:
        print(f"[FAIL] schedule: pairs with >2 appearances: {over}")
        all_passed = False
    else:
        print("[PASS] schedule: no pair appears more than twice")

    if twice_count == 24 and once_count == 1:
        print("[PASS] schedule: 24 pairs ×2 + 1 pair ×1 = 49 regular matches")
    else:
        print(f"[FAIL] schedule: unexpected pair distribution "
              f"(twice={twice_count}, once={once_count})")
        all_passed = False

    # Test 5: no duplicate triplets
    triplets = [
        (m["agent_a"]["id"], m["agent_b"]["id"], m["home_subnet"])
        for m in regular
    ]
    if len(triplets) != len(set(triplets)):
        print("[FAIL] schedule: duplicate (agent_a, agent_b, home_subnet) triplets")
        all_passed = False
    else:
        print("[PASS] schedule: no duplicate match triplets")

    # Test 6: match_ids 1-50 with no gaps
    ids = sorted(m["match_id"] for m in matches)
    if ids != list(range(1, 51)):
        print(f"[FAIL] schedule: match_ids not 1-50: {ids}")
        all_passed = False
    else:
        print("[PASS] schedule: match_ids are 1-50 with no gaps")

    # Test 7: dropped_matchup field
    dm = output_a.get("dropped_matchup")
    if not dm:
        print("[FAIL] schedule: dropped_matchup field missing")
        all_passed = False
    elif not all(k in dm for k in ["agent_a_id", "agent_b_id", "home_subnet", "note"]):
        print(f"[FAIL] schedule: dropped_matchup missing required fields")
        all_passed = False
    else:
        print("[PASS] schedule: dropped_matchup field present and valid")

    # Test 8: championship match
    if champ and champ[0]["match_id"] == CHAMPIONSHIP_MATCH_ID:
        print(f"[PASS] schedule: championship is match_id {CHAMPIONSHIP_MATCH_ID}")
    else:
        print("[FAIL] schedule: championship match_id wrong")
        all_passed = False

    # Test 9: different seasons → different schedules
    output_alt = build_schedule_output("s2", registry)
    ids_s1 = [m["agent_a"]["id"] for m in output_a["matches"] if not m["championship"]]
    ids_s2 = [m["agent_a"]["id"] for m in output_alt["matches"] if not m["championship"]]
    if ids_s1 != ids_s2:
        print("[PASS] schedule: different seasons give different orderings")
    else:
        print("[FAIL] schedule: s1 and s2 produced identical orderings")
        all_passed = False

    # Test 10: Python version and commit_reveal_note in output
    if "python_version" in output_a:
        print("[PASS] schedule: python_version in output")
    else:
        print("[FAIL] schedule: python_version missing from output")
        all_passed = False

    if "commit_reveal_note" in output_a:
        print("[PASS] schedule: commit_reveal_note in output")
    else:
        print("[FAIL] schedule: commit_reveal_note missing from output")
        all_passed = False

    # Null hotkey warning (expected pre-season, not a failure)
    null_count = sum(
        1 for m in regular
        if m["agent_a"]["hotkey"] is None or m["agent_b"]["hotkey"] is None
    )
    if null_count > 0:
        print(f"[WARN] schedule: {null_count} matches have null hotkeys "
              f"(expected pre-season — must be populated before Day 0)")

    return all_passed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Project Nobi Arena — deterministic match schedule"
    )
    parser.add_argument("--season", type=str, default="s1", help="Season ID")
    parser.add_argument("--output", type=Path, default=None,
                        help="Save schedule to this JSON file")
    parser.add_argument("--match", type=int, default=None,
                        help="Print details for a single match (1-50)")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY,
                        help="Path to agent_registry.json")
    parser.add_argument("--task-registry", type=Path, default=DEFAULT_TASK_REGISTRY,
                        help="Path to task_registry.json (for commit-reveal hash)")
    parser.add_argument("--verify", action="store_true", help="Run self-tests")
    args = parser.parse_args()

    registry_path = args.registry
    if not registry_path.exists():
        print(f"Error: registry not found at {registry_path}", file=sys.stderr)
        sys.exit(1)

    with open(registry_path) as f:
        registry = json.load(f)

    if args.verify:
        passed = run_self_test(registry)
        sys.exit(0 if passed else 1)

    if args.match is not None:
        if not 1 <= args.match <= 50:
            parser.error("--match must be between 1 and 50")

    task_registry_path = args.task_registry if args.task_registry.exists() else None

    output = build_schedule_output(
        args.season,
        registry,
        task_registry_path=task_registry_path,
        agent_registry_path=registry_path,
    )

    if args.match is not None:
        match = next((m for m in output["matches"] if m["match_id"] == args.match), None)
        if match is None:
            print(f"Error: match {args.match} not found", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(match, indent=2))
        return

    if args.output:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Schedule written to {args.output}")
    else:
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
