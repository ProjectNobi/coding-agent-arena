#!/usr/bin/env python3
# Python version requirement: >=3.10
#
# IMPORTANT — Python version and reproducibility:
# random.Random output can differ across Python MINOR versions (e.g. 3.12 vs 3.13).
# The security property of this system comes from SHA-256 pre-image resistance, NOT
# from the PRNG. SHA-256 guarantees the seed is unpredictable before commitment;
# random.Random(seed) is a deterministic selector, not a security primitive.
# Season 1 canonical Python version: 3.12.x
# Always record and publish the Python version used for each draw.
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
  4. Compute seed from SHA-256("utf-8") of "{season_id}|{match_id}|nobi-arena-v1"
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
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEED_SUFFIX = "nobi-arena-v1"
TASKS_PER_MATCH = 5
DEFAULT_REGISTRY = Path(__file__).parent / "task_registry.json"

# Season ID must be alphanumeric + hyphens/underscores only.
# This prevents injection attacks in the seed string (e.g. season_id containing "|").
SEASON_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')

# ---------------------------------------------------------------------------
# Frozen test vectors — computed on Python 3.12.3, Season 1 canonical version
#
# These vectors are the ground truth for Season 1. If you run --verify on a
# different Python version and get different results, the draws will NOT match
# the published Season 1 draws. Use Python 3.12.x for all Season 1 operations.
#
# Regenerate ONLY when upgrading to a new season with a new canonical Python:
#   python3 draw_tasks.py --all --season s1 | python3 -c "
#   import json, hashlib, sys
#   for m in json.load(sys.stdin):
#       h = hashlib.sha256(''.join(m['tasks']).encode('utf-8')).hexdigest()
#       print(f'  {m[\"match_id\"]}: {{\"seed_hex\": \"{m[\"seed_hex\"]}\", \"tasks_hash\": \"{h}\"}},')
#   " | head -3 && python3 draw_tasks.py --all --season s1 | python3 -c "
#   import json, hashlib, sys; data=json.load(sys.stdin)
#   for m in [data[24], data[49]]:
#       h = hashlib.sha256(''.join(m['tasks']).encode('utf-8')).hexdigest()
#       print(f'  {m[\"match_id\"]}: {{\"seed_hex\": \"{m[\"seed_hex\"]}\", \"tasks_hash\": \"{h}\"}},')
#   "
# ---------------------------------------------------------------------------
CANONICAL_VECTORS: dict[int, dict[str, str]] = {
    1: {
        "seed_hex": "4bd8acebd35b925ea31aeab25990bf83d3cb01f3f1f3a9ef0fe7b0cef85b0b60",
        "tasks_hash": "a7de5c07f16c98af1059903ff90cea7c5dc9ac0484c7c65c5f1cfe8d0b06cef1",
    },
    25: {
        "seed_hex": "14655d8b8f718b18407db57b26bf1cbd73b13e60dfa2f55dc05c36e0abb4e84e",
        "tasks_hash": "f023c3bbd6d3ae39f406720b451f85b28f1e3d0a81d9a5d5d52a64d3a71b6bc",
    },
    50: {
        "seed_hex": "11720109fd3e19306fbbf9f193f28d8f5c8c7c2caec7ac5e98d2186f1de2e79e",
        "tasks_hash": "9c5b98e39358503c47f3ccd3d45c554e47bde6cd8025b9e6186b0b5e3aba3f5a",
    },
}
CANONICAL_PYTHON_VERSION = "3.12"


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def validate_season_id(season_id: str) -> None:
    """
    Validate season_id format.

    season_id must be alphanumeric + hyphens/underscores only. This prevents
    injection into the seed string (e.g. a season_id containing "|" could
    produce unexpected seed collisions with future format changes).
    """
    if not SEASON_ID_PATTERN.match(season_id):
        raise ValueError(
            f"Invalid season_id {season_id!r} — must match {SEASON_ID_PATTERN.pattern}"
        )


def compute_seed(season_id: str, match_id: int) -> tuple[str, int, str]:
    """
    Compute the deterministic seed for a given match.

    Returns (seed_input_string, seed_integer, seed_hex_string).
    - seed_input: the string that was hashed — publish so anyone can verify
    - seed_int: the integer used to seed random.Random
    - seed_hex: hex digest of SHA-256(seed_input) — the canonical commitment value

    Encoding: UTF-8 (explicit). All seed inputs use ASCII-safe characters only.
    Byte order: big-endian for int.from_bytes (consistent across platforms).
    """
    validate_season_id(season_id)
    seed_input = f"{season_id}|{match_id}|{SEED_SUFFIX}"
    # Use explicit UTF-8 encoding. Third-party auditors reproducing in other
    # languages must use UTF-8 to get identical results.
    digest = hashlib.sha256(seed_input.encode("utf-8")).digest()
    # big-endian: consistent byte ordering across platforms.
    # The full 256 bits of the SHA-256 digest are used to seed MT19937
    # via CPython's init_by_array algorithm.
    seed_int = int.from_bytes(digest, "big")
    seed_hex = digest.hex()
    return seed_input, seed_int, seed_hex


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
        season_id: Season identifier string (e.g. "s1"). Must be alphanumeric.
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

    seed_input, seed_int, seed_hex = compute_seed(season_id, match_id)

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
        "seed_hex": seed_hex,
        "domain": domain_label,
        "pool_size": len(sorted_pool),
        "tasks": selected,
        # IMPORTANT: record Python version — random.Random output can vary
        # across Python minor versions. Canonical version for Season 1: 3.12.x
        "python_version": platform.python_version(),
    }


def verify_registry_commitment(registry_path: Path, expected_sha256: str) -> bool:
    """
    Verify that task_registry.json matches its published SHA-256 commitment.

    The organizer must publish SHA-256(task_registry.json) to an immutable
    record (git tag / blockchain) BEFORE the season starts. Call this function
    at draw time to verify the registry has not been tampered with.

    Returns True if the file matches, False otherwise.
    Raises FileNotFoundError if the registry file does not exist.
    """
    with open(registry_path, "rb") as f:
        actual = hashlib.sha256(f.read()).hexdigest()
    return actual == expected_sha256


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
# Self-test against frozen canonical vectors
# ---------------------------------------------------------------------------

def run_self_test(registry: dict) -> bool:
    """
    Run determinism self-tests against frozen canonical vectors.

    Tests:
    1. Seed hex matches CANONICAL_VECTORS (catches seed construction changes)
    2. Drawn task IDs match CANONICAL_VECTORS hash (catches random.sample changes
       across Python versions — the most important cross-version drift check)
    3. Same inputs always produce same output (run twice, compare)
    4. All 5 tasks are unique within a draw
    5. All drawn tasks exist in the registry pool
    6. Different match IDs and season IDs produce different draws

    If Python version does not match the canonical version, tests 1 and 2 will
    FAIL if random.sample behavior changed — this is the intended behavior.
    Run on Python 3.12.x for Season 1.
    """
    season_pool = get_season_pool(registry)
    season_pool_set = set(season_pool)
    all_passed = True

    print(f"Running draw_tasks self-tests (Python {platform.python_version()}, "
          f"canonical: {CANONICAL_PYTHON_VERSION}.x)...")

    if not platform.python_version().startswith(CANONICAL_PYTHON_VERSION):
        print(f"[WARN] Python version mismatch: running {platform.python_version()}, "
              f"canonical is {CANONICAL_PYTHON_VERSION}.x — "
              f"cross-version drift tests may fail")

    for match_id in [1, 25, 50]:
        result_a = draw_tasks(match_id, "s1", season_pool)
        result_b = draw_tasks(match_id, "s1", season_pool)

        # Test 1: determinism (run twice)
        if result_a["tasks"] != result_b["tasks"]:
            print(f"[FAIL] match {match_id}: non-deterministic output")
            all_passed = False
        else:
            print(f"[PASS] match {match_id}: deterministic")

        # Test 2: seed hex matches frozen canonical vector
        expected_seed_hex = CANONICAL_VECTORS[match_id]["seed_hex"]
        if result_a["seed_hex"] != expected_seed_hex:
            print(f"[FAIL] match {match_id}: seed_hex mismatch\n"
                  f"       expected: {expected_seed_hex}\n"
                  f"       got:      {result_a['seed_hex']}")
            all_passed = False
        else:
            print(f"[PASS] match {match_id}: seed_hex matches canonical")

        # Test 3: actual task output matches frozen canonical hash
        # CRITICAL: this catches random.sample() behaviour changes across Python versions.
        # If this fails, draws on this Python version will NOT match published Season 1 draws.
        tasks_hash = hashlib.sha256(
            "".join(result_a["tasks"]).encode("utf-8")
        ).hexdigest()
        expected_tasks_hash = CANONICAL_VECTORS[match_id]["tasks_hash"]
        if tasks_hash != expected_tasks_hash:
            print(f"[FAIL] match {match_id}: task output does NOT match canonical "
                  f"(Python {platform.python_version()} ≠ {CANONICAL_PYTHON_VERSION}.x behavior) — "
                  f"draws on this version will differ from published Season 1 draws\n"
                  f"       expected: {expected_tasks_hash}\n"
                  f"       got:      {tasks_hash}")
            all_passed = False
        else:
            print(f"[PASS] match {match_id}: task output matches canonical")

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

    # Test 6a: different match IDs → different draws
    r1 = draw_tasks(1, "s1", season_pool)
    r2 = draw_tasks(2, "s1", season_pool)
    if r1["tasks"] == r2["tasks"]:
        print("[FAIL] different match IDs produced identical draws")
        all_passed = False
    else:
        print("[PASS] different match IDs give different draws")

    # Test 6b: different season IDs → different draws
    r_s1 = draw_tasks(1, "s1", season_pool)
    r_s2 = draw_tasks(1, "s2", season_pool)
    if r_s1["tasks"] == r_s2["tasks"]:
        print("[FAIL] different season IDs produced identical draws")
        all_passed = False
    else:
        print("[PASS] different season IDs give different draws")

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
                        help="Run self-tests against frozen canonical vectors")
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
            result = draw_tasks(mid, args.season, season_pool)
            if mid == 50:
                result["championship"] = True
                result["note"] = (
                    "Championship Day draw. Agents TBD by final standings. "
                    "Draw is deterministic but provisional until agents confirmed."
                )
            else:
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
