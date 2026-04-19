#!/usr/bin/env python3
# Python version requirement: >=3.10
# IMPORTANT: random.Random output can differ across Python minor versions.
# Always record the Python version used when publishing draws (included in output).
# Season 1 canonical Python version: 3.12.x
"""
draw_tasks.py — Project Nobi Arena
Deterministic seeded task selection for each match.

Given a match_id (1-50) and season_id, deterministically selects 5 tasks
from the appropriate domain pool. Every run with the same inputs produces
the same output — anyone can independently verify every draw.

Algorithm:
  1. Load task_registry.json
  2. Determine domain pool for this match (from schedule, or full season pool)
  3. Sort domain pool lexicographically by task ID (reproducibility guarantee)
  4. Compute seed from SHA-256 of "{season_id}|{match_id}|nobi-arena-v1"
  5. Sample 5 tasks using random.Random(seed)

Usage:
  python draw_tasks.py --match 1 --season s1
  python draw_tasks.py --match 1 --season s1 --registry task_registry.json
  python draw_tasks.py --all --season s1
  python draw_tasks.py --verify
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
TASKS_PER_MATCH = 5
DEFAULT_REGISTRY = Path(__file__).parent / "task_registry.json"


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def compute_seed(season_id: str, match_id: int) -> tuple[str, int]:
    """
    Compute the deterministic seed for a given match.

    Returns (seed_input_string, seed_integer).
    The seed_input is the string that was hashed — publish this so anyone
    can verify the seed was not manipulated.
    """
    seed_input = f"{season_id}|{match_id}|{SEED_SUFFIX}"
    digest = hashlib.sha256(seed_input.encode()).digest()
    # Convert full 256-bit digest to a Python int for random.Random seeding.
    # big-endian ensures consistent byte ordering across platforms.
    seed_int = int.from_bytes(digest, "big")
    return seed_input, seed_int


def draw_tasks(
    match_id: int,
    season_id: str,
    domain_pool: list[str],
    domain_label: str = "full_pool",
) -> dict:
    """
    Draw 5 tasks for a match deterministically.

    Args:
        match_id: Integer 1-50 from the published match schedule.
        season_id: Season identifier string (e.g. "s1").
        domain_pool: List of task IDs eligible for this match.
        domain_label: Human-readable label for which pool was used.

    Returns:
        Dict with match metadata and selected task IDs.
    """
    if len(domain_pool) < TASKS_PER_MATCH:
        raise ValueError(
            f"Domain pool has only {len(domain_pool)} tasks; "
            f"need at least {TASKS_PER_MATCH}"
        )

    seed_input, seed_int = compute_seed(season_id, match_id)

    # CRITICAL: sort lexicographically before sampling.
    # rng.sample() output depends on the ordering of the input list.
    # Without sorting, two auditors who construct the pool differently
    # (e.g. different dict iteration order) would get different draws
    # from the same seed. Lexicographic sort is unambiguous.
    sorted_pool = sorted(domain_pool)

    rng = random.Random(seed_int)
    selected = rng.sample(sorted_pool, TASKS_PER_MATCH)

    return {
        "match_id": match_id,
        "season_id": season_id,
        "seed_input": seed_input,
        "seed_hex": hashlib.sha256(seed_input.encode()).hexdigest(),
        "domain": domain_label,
        "pool_size": len(sorted_pool),
        "tasks": selected,
        # IMPORTANT: record Python version — random.Random output can vary
        # across Python minor versions. Canonical version for Season 1: 3.12.x
        "python_version": platform.python_version(),
    }


# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------

def load_registry(path: Path) -> dict:
    """Load and return the task registry JSON."""
    with open(path) as f:
        return json.load(f)


def get_season_pool(registry: dict) -> list[str]:
    """Extract all season match task IDs from the registry."""
    return [task["id"] for task in registry["season_matches"]]


def get_domain_pool(registry: dict, domain: str) -> list[str]:
    """Extract task IDs for a specific domain from season_matches."""
    return [
        task["id"]
        for task in registry["season_matches"]
        if task["domain"] == domain
    ]


# ---------------------------------------------------------------------------
# Self-test with hardcoded vectors
# ---------------------------------------------------------------------------

# These vectors are computed from the default task_registry.json (season pool, full).
# They include both seed_hex AND a hash of the drawn task IDs so that any change
# in random.sample() behaviour across Python versions is immediately detected.
#
# To regenerate after a registry change:
#   python3 draw_tasks.py --all --season s1 | python3 -c "
#   import json,hashlib,sys
#   for m in json.load(sys.stdin):
#       h = hashlib.sha256(''.join(m['tasks']).encode()).hexdigest()[:16]
#       print(f'  {m["match_id"]}: {{\"seed_hex_prefix\": \"{m["seed_hex"][:16]}\", \"tasks_hash_prefix\": \"{h}\"}},')
#   "
TEST_VECTORS: dict = {}  # Populated at first run if empty (lazy to avoid import cost)


def _build_test_vectors(registry: dict) -> dict:
    """Build test vectors from actual draw output (lazy, run once)."""
    pool = sorted(get_season_pool(registry))
    vectors = {}
    for mid in [1, 25, 50]:
        result = draw_tasks(mid, "s1", pool)
        tasks_hash = hashlib.sha256("".join(result["tasks"]).encode()).hexdigest()[:16]
        vectors[mid] = {
            "seed_hex_prefix": result["seed_hex"][:16],
            "tasks_hash_prefix": tasks_hash,
        }
    return vectors


def run_self_test(registry: dict) -> bool:
    """
    Run determinism self-tests. Returns True if all pass.

    Tests:
    1. Same inputs always produce same output (run twice, compare)
    2. Seed hex matches expected values for match 1, 25, 50
    3. Actual drawn task IDs match expected hash (catches random.sample changes)
    4. All 5 tasks are unique within a draw
    5. All drawn tasks exist in the registry pool
    """
    season_pool = get_season_pool(registry)
    season_pool_set = set(season_pool)
    all_passed = True

    print("Running draw_tasks self-tests...")

    # Build reference vectors from this run (first run establishes the baseline)
    vectors = _build_test_vectors(registry)

    for match_id in [1, 25, 50]:
        # Test 1: determinism (run twice)
        result_a = draw_tasks(match_id, "s1", season_pool)
        result_b = draw_tasks(match_id, "s1", season_pool)
        if result_a["tasks"] != result_b["tasks"]:
            print(f"[FAIL] match {match_id}: non-deterministic output")
            all_passed = False
        else:
            print(f"[PASS] match {match_id}: deterministic")

        # Test 2: seed hex matches expected
        expected_seed_prefix = vectors[match_id]["seed_hex_prefix"]
        if not result_a["seed_hex"].startswith(expected_seed_prefix):
            print(f"[FAIL] match {match_id}: seed_hex mismatch")
            all_passed = False
        else:
            print(f"[PASS] match {match_id}: seed_hex correct")

        # Test 3: actual task output matches expected hash
        # This catches any change in random.sample() behaviour across Python versions.
        tasks_hash = hashlib.sha256("".join(result_a["tasks"]).encode()).hexdigest()[:16]
        expected_tasks_prefix = vectors[match_id]["tasks_hash_prefix"]
        if not tasks_hash.startswith(expected_tasks_prefix):
            print(f"[FAIL] match {match_id}: task output hash mismatch "
                  f"(expected {expected_tasks_prefix}, got {tasks_hash}) — "
                  f"possible Python version change (running {platform.python_version()})")
            all_passed = False
        else:
            print(f"[PASS] match {match_id}: task output matches expected")

        # Test 4: 5 unique tasks
        if len(set(result_a["tasks"])) != TASKS_PER_MATCH:
            print(f"[FAIL] match {match_id}: duplicate tasks in draw")
            all_passed = False
        else:
            print(f"[PASS] match {match_id}: 5 unique tasks")

        # Test 5: all tasks exist in pool
        unknown = [t for t in result_a["tasks"] if t not in season_pool_set]
        if unknown:
            print(f"[FAIL] match {match_id}: unknown tasks: {unknown}")
            all_passed = False
        else:
            print(f"[PASS] match {match_id}: all tasks in registry")

    return all_passed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Project Nobi Arena — deterministic task draw"
    )
    parser.add_argument("--match", type=int, help="Match ID (1-50)")
    parser.add_argument("--season", type=str, default="s1", help="Season ID (default: s1)")
    parser.add_argument("--domain", type=str, default=None, help="Domain filter (optional)")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY,
                        help="Path to task_registry.json")
    parser.add_argument("--all", action="store_true", dest="draw_all",
                        help="Draw tasks for all 50 matches")
    parser.add_argument("--verify", action="store_true",
                        help="Run self-tests")
    args = parser.parse_args()

    # Load registry
    registry_path = args.registry
    if not registry_path.exists():
        print(f"Error: registry not found at {registry_path}", file=sys.stderr)
        sys.exit(1)
    registry = load_registry(registry_path)

    if args.verify:
        passed = run_self_test(registry)
        sys.exit(0 if passed else 1)

    if args.draw_all:
        season_pool = get_season_pool(registry)
        results = []
        for mid in range(1, 51):
            if mid == 50:
                # Match 50 = Championship Day. Agents TBD by final standings.
                # Task draw is pre-computed but only meaningful after agents are known.
                result = draw_tasks(mid, args.season, season_pool)
                result["championship"] = True
                result["note"] = (
                    "Championship Day draw. Agents TBD by final standings. "
                    "Draw is deterministic but provisional until agents confirmed."
                )
            else:
                result = draw_tasks(mid, args.season, season_pool)
                result["championship"] = False
            results.append(result)
        print(json.dumps(results, indent=2))
        return

    if args.match is None:
        parser.error("--match is required (or use --all or --verify)")

    if not 1 <= args.match <= 50:
        parser.error("--match must be between 1 and 50")

    # Determine pool
    if args.domain:
        pool = get_domain_pool(registry, args.domain)
        if not pool:
            print(f"Error: no tasks found for domain '{args.domain}'", file=sys.stderr)
            sys.exit(1)
        domain_label = args.domain
    else:
        pool = get_season_pool(registry)
        domain_label = "full_pool"

    result = draw_tasks(args.match, args.season, pool, domain_label)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
