#!/usr/bin/env python3
"""
schedule.py — Project Nobi Arena
Deterministic match schedule generator for Season 1.

Generates the full 50-match schedule using a seeded PRNG. Anyone can
run this script to reproduce the exact schedule independently.

Algorithm:
  1. Load agent_registry.json (5 SN66 agents + 5 SN62 agents)
  2. Generate all 25 unique cross-subnet pairings (SN66 i vs SN62 j)
  3. Each pair gets 2 matches: one SN66-home, one SN62-home = 50 matchups
  4. Shuffle all 49 regular matchups using seeded PRNG
     Seed: SHA-256("s1|schedule|nobi-arena-v1")
  5. Assign match_id 1-49 to regular matches (1 per day)
  6. Match 50 = Championship Day (reserved — TBD post-season)

Usage:
  python schedule.py --season s1
  python schedule.py --season s1 --output schedule.json
  python schedule.py --season s1 --match 1
  python schedule.py --verify
"""

from __future__ import annotations  # Python 3.9 compat for type hints

import argparse
import hashlib
import json
import platform
import random
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEED_SUFFIX = "nobi-arena-v1"
DEFAULT_REGISTRY = Path(__file__).parent / "agent_registry.json"
CHAMPIONSHIP_MATCH_ID = 50


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def compute_schedule_seed(season_id: str) -> tuple[str, int]:
    """
    Compute the deterministic seed for schedule generation.

    The schedule seed is separate from the per-match task-draw seed,
    so schedule order and task selection are independently auditable.
    """
    seed_input = f"{season_id}|schedule|{SEED_SUFFIX}"
    digest = hashlib.sha256(seed_input.encode()).digest()
    seed_int = int.from_bytes(digest, "big")
    return seed_input, seed_int


def generate_matchups(sn66_agents: list[dict], sn62_agents: list[dict]) -> list[dict]:
    """
    Generate all 50 matchups (49 regular + 1 championship placeholder).

    For each of the 25 unique (SN66, SN62) pairs, we create 2 matches:
    - Match A: SN66 agent is home, SN62 agent is away
    - Match B: SN62 agent is home, SN66 agent is away
    This gives each pair a home and away match = 50 total.
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


def generate_schedule(season_id: str, registry: dict) -> list[dict]:
    """
    Generate the full 50-match schedule deterministically.

    Returns a list of 50 match dicts ordered by match_id (1-50).
    Match 50 is the Championship Day placeholder.
    """
    sn66 = registry["sn66_agents"]
    sn62 = registry["sn62_agents"]

    # Generate all 50 matchups (25 pairs × 2 home/away)
    all_matchups = generate_matchups(sn66, sn62)

    # We shuffle all 50 but only assign the first 49 to regular days.
    # The 50th slot is reserved for Championship Day (TBD by final standings).
    # As a result, one pair will appear only once in the regular season —
    # this is a known, accepted consequence of the Championship Day design.
    matchups_to_shuffle = all_matchups  # all 50; first 49 become regular matches

    seed_input, seed_int = compute_schedule_seed(season_id)
    rng = random.Random(seed_int)

    # Shuffle to determine order — this is the core deterministic step.
    # Anyone can verify by running with the same seed.
    # NOTE: record Python version — random.shuffle may vary across minor versions.
    shuffled = matchups_to_shuffle.copy()
    rng.shuffle(shuffled)

    # Assign match_id 1-49 to the first 49 shuffled matchups (regular season)
    schedule = []
    for i, matchup in enumerate(shuffled[:49], start=1):
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

    # Match 50: Championship Day — agents determined post-season by standings
    schedule.append({
        "match_id": CHAMPIONSHIP_MATCH_ID,
        "day": CHAMPIONSHIP_MATCH_ID,
        "agent_a": {"id": "TBD", "subnet": "SN66", "hotkey": None},
        "agent_b": {"id": "TBD", "subnet": "SN62", "hotkey": None},
        "home_subnet": "neutral",
        "away_subnet": "neutral",
        "draw_seed_input": f"{season_id}|{CHAMPIONSHIP_MATCH_ID}|{SEED_SUFFIX}",
        "championship": True,
        "note": "Championship Day. Agents: top-ranked SN66 vs top-ranked SN62 by final standings.",
    })

    return schedule


def build_schedule_output(season_id: str, registry: dict) -> dict:
    """Build the full schedule output dict including metadata."""
    seed_input, _ = compute_schedule_seed(season_id)
    schedule = generate_schedule(season_id, registry)
    return {
        "schema_version": "1.0",
        "season_id": season_id,
        "schedule_seed_input": seed_input,
        "schedule_seed_hex": hashlib.sha256(seed_input.encode()).hexdigest(),
        "python_version": platform.python_version(),
        "total_matches": len(schedule),
        "regular_matches": len([m for m in schedule if not m["championship"]]),
        "championship_match": CHAMPIONSHIP_MATCH_ID,
        "commit_reveal_note": (
            "OPERATIONAL REQUIREMENT: publish SHA-256(task_registry.json) to an "
            "immutable record (git tag / blockchain) BEFORE the season starts. "
            "At draw time, verify registry hash matches the commitment. "
            "Without this step, the seed provides determinism but not manipulation resistance."
        ),
        "matches": schedule,
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test(registry: dict) -> bool:
    """
    Run schedule self-tests. Returns True if all pass.

    Tests:
    1. Determinism: same registry + season → same schedule twice
    2. Exactly 49 regular matches + 1 championship = 50 total
    3. Every (SN66, SN62) pair appears exactly twice (once per home side)
    4. No duplicate (agent_a, agent_b, home_subnet) triplets
    5. match_ids are 1-50 with no gaps
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

    # Test 2: count
    regular = [m for m in matches if not m["championship"]]
    champ = [m for m in matches if m["championship"]]
    if len(regular) != 49 or len(champ) != 1:
        print(f"[FAIL] schedule: expected 49+1 matches, got {len(regular)}+{len(champ)}")
        all_passed = False
    else:
        print(f"[PASS] schedule: 49 regular + 1 championship")

    # Test 3: pair distribution
    # 49 regular matches from 50 matchups (25 pairs x2):
    # - 24 pairs appear twice (both home/away played in regular season)
    # - 1 pair appears once (its second slot became Championship Day)
    # No pair should appear 0 or 3+ times.
    pair_count: dict[tuple, int] = {}
    for m in regular:
        pair = tuple(sorted([m["agent_a"]["id"], m["agent_b"]["id"]]))
        pair_count[pair] = pair_count.get(pair, 0) + 1

    sn66_ids = [a["id"] for a in registry["sn66_agents"]]
    sn62_ids = [a["id"] for a in registry["sn62_agents"]]
    expected_pairs = {tuple(sorted([a, b])) for a in sn66_ids for b in sn62_ids}

    missing = expected_pairs - set(pair_count.keys())
    over = {p: c for p, c in pair_count.items() if c > 2}
    once_count = sum(1 for c in pair_count.values() if c == 1)
    twice_count = sum(1 for c in pair_count.values() if c == 2)

    if missing:
        print(f"[FAIL] schedule: pairs with 0 appearances: {missing}")
        all_passed = False
    elif over:
        print(f"[FAIL] schedule: pairs with >2 appearances: {over}")
        all_passed = False
    elif twice_count == 24 and once_count == 1:
        print(f"[PASS] schedule: 24 pairs x2 + 1 pair x1 = 49 regular matches")
    else:
        print(f"[FAIL] schedule: unexpected pair distribution (twice={twice_count}, once={once_count})")
        all_passed = False

    # Test 4: no duplicate triplets
    triplets = [
        (m["agent_a"]["id"], m["agent_b"]["id"], m["home_subnet"])
        for m in regular
    ]
    if len(triplets) != len(set(triplets)):
        print("[FAIL] schedule: duplicate (agent_a, agent_b, home_subnet) triplets")
        all_passed = False
    else:
        print("[PASS] schedule: no duplicate match triplets")

    # Test 5: match_ids are 1-50 with no gaps
    ids = sorted([m["match_id"] for m in matches])
    if ids != list(range(1, 51)):
        print(f"[FAIL] schedule: match_ids not 1-50: {ids}")
        all_passed = False
    else:
        print("[PASS] schedule: match_ids are 1-50 with no gaps")

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
                        help="Print details for a single match")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY,
                        help="Path to agent_registry.json")
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

    output = build_schedule_output(args.season, registry)

    if args.match is not None:
        if not 1 <= args.match <= 50:
            parser.error("--match must be between 1 and 50")
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
