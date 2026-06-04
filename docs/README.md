# Project Documentation — AI Dating Assistant

This folder is the single source of truth for all documentation, analysis, and outputs produced about this project. Every document lives here. Nothing is duplicated outside this folder.

## Structure

```
docs/
├── README.md                  ← this index (always update when adding a file)
├── overview.md                ← product concept, goals, target users
├── analysis/                  ← research, audits, evaluations
└── architecture/              ← system design, flow diagrams, module breakdown
└── decisions/                 ← reasoning behind key design or technical choices
```

## Index

| File | Type | Description | Last updated |
|------|------|-------------|--------------|
| [IMPROVEMENT-BLUEPRINT.md](IMPROVEMENT-BLUEPRINT.md) | **Execution plan** | 33 issues, 7 epics, 24 tasks with step-by-step implementation, dependencies, and 4-week roadmap | 2026-06-04 |
| [SYNTHESIS.md](SYNTHESIS.md) | **Final synthesis** | Unified mental model, design philosophy, strengths/weaknesses, system classification, final truth | 2026-06-04 |
| [TECHNICAL-REFERENCE.md](TECHNICAL-REFERENCE.md) | **Master reference** | Complete technical documentation — start here | 2026-06-04 |
| [overview.md](overview.md) | Concept | Product purpose, problem, users, value | 2026-06-04 |
| [architecture/codebase-map.md](architecture/codebase-map.md) | Architecture | Full module map, data flow, state fields, config knobs | 2026-06-04 |
| [architecture/system-architecture.md](architecture/system-architecture.md) | Architecture | Component map, both pipelines, AI integration, concurrency, patterns, weaknesses | 2026-06-04 |
| [analysis/component-deep-dive.md](analysis/component-deep-dive.md) | Analysis | Per-module deep dive: internals, design rationale, connections, trade-offs | 2026-06-04 |
| [analysis/engineering-decisions.md](analysis/engineering-decisions.md) | Analysis | 15 key engineering decisions: rationale, trade-offs, risks, quality verdict | 2026-06-04 |
| [analysis/dependencies-and-boundaries.md](analysis/dependencies-and-boundaries.md) | Analysis | All external dependencies, risk matrix, removal impact, system boundary definition | 2026-06-04 |
| [analysis/data-model.md](analysis/data-model.md) | Analysis | Full data model: entities, ERD, lifecycles, consistency rules, bottlenecks | 2026-06-04 |
| [analysis/runtime-behavior.md](analysis/runtime-behavior.md) | Analysis | 13 runtime flows traced step by step: boot, profiles, conversations, debounce, crash recovery | 2026-06-04 |
| [analysis/failure-analysis.md](analysis/failure-analysis.md) | Analysis | All failure modes: error handlers, silent failures, race conditions, dangerous assumptions, missing guards | 2026-06-04 |
| [analysis/security-analysis.md](analysis/security-analysis.md) | Analysis | Full security review: auth, access control, data protection, prompt injection, behavioral boundaries, threat model | 2026-06-04 |
| [analysis/performance-scalability.md](analysis/performance-scalability.md) | Analysis | Operation cost inventory, bottlenecks, latency budget, caching audit, scale behavior, optimization roadmap | 2026-06-04 |
| [analysis/vision-vs-reality.md](analysis/vision-vs-reality.md) | Analysis | Vision vs implementation comparison: feature alignment, gaps, over-engineering, gap analysis | 2026-06-04 |
| [analysis/architectural-critique.md](analysis/architectural-critique.md) | Analysis | Staff-engineer critique: design flaws, coupling failures, concrete refactoring proposals, alternative architecture | 2026-06-04 |
| [analysis/product-gaps.md](analysis/product-gaps.md) | **Gap register** | 24 product gaps, each linked to source documents, classified by severity, prioritized by impact | 2026-06-04 |

## Principles

- Update an existing document instead of creating a new one whenever content overlaps.
- All future outputs (analyses, reports, architecture notes, decisions) go into the relevant subfolder.
- Keep this index table current — add a row for every new file created.
- Preserve history inside documents with dated `## Update — YYYY-MM-DD` sections rather than overwriting.
