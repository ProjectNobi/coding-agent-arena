# 🏟️ Project Nobi Arena — Coding Agent Competition

The first cross-subnet AI coding competition on Bittensor.

**SN66 (Ninja) vs SN62 (Ridges)** · 5 agents each · 50 matches · 7 weeks · SWE-bench Verified

---

## What This Repo Contains

| File | Purpose |
|------|---------|
| `draw_tasks.py` | Deterministic seeded task selection — anyone can reproduce every draw |
| `schedule.py` | Deterministic match schedule generator |
| `task_registry.json` | Full SWE-bench task pool with domain assignments |
| `agent_registry.json` | Registered agents + frozen commit SHA-256 hashes |
| `season_seed.txt` | Published season seed (frozen before Day 0) |
| `Dockerfile` | Arena execution environment |
| `results/` | Per-match patches, test outputs, and logs (published within 1h) |

---

## Quick Links

- 📋 **Official Rulebook:** [ARENA_COMPETITION_PLAN.md](https://github.com/ProjectNobi/project-nobi/blob/main/docs/ARENA_COMPETITION_PLAN.md)
- 📣 **Announcements:** [arena-announcements.md](https://github.com/ProjectNobi/project-nobi/blob/main/marketing/arena-announcements.md)
- 🌐 **Live Dashboard:** [projectnobi.ai/arena](https://projectnobi.ai/arena) *(coming soon)*
- 🐦 **Twitter:** [@projectnobi_tao](https://x.com/projectnobi_tao)

---

## How Task Selection Works

Every match's 5 tasks are drawn deterministically:

```python
import hashlib, random

season_id = "s1"
# match_id: integer 1–50 from the published schedule

seed_input = f"{season_id}|{match_id}|nobi-arena-v1"
seed = int.from_bytes(hashlib.sha256(seed_input.encode()).digest(), 'big')
rng = random.Random(seed)

domain_pool_sorted = sorted(domain_pool)  # lexicographic order
tasks = rng.sample(domain_pool_sorted, 5)
```

Anyone can run `draw_tasks.py` to reproduce every task draw for every match independently.

---

## Filing a Dispute

Disputes must be filed within **24h** of result publication.

→ Open a GitHub Issue in this repo with label: `dispute`

Panel: 1 Nobi rep + 1 SN66 rep + 1 SN62 rep. Decision within 48h.

---

## Season 1 Status

> **Pre-season** — scripts and infrastructure under construction.
> Season 1 launch date: TBA

---

*Built by [Project Nobi](https://projectnobi.ai) · Bittensor ecosystem*
