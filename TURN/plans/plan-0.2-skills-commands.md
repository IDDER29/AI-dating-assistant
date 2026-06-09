# Plan 0.2 — Skills & Commands

**Builds:** Complete skill library + slash command set for the TURN dev workflow  
**Depends on:** Plan 0.1 complete (venv, uv, railway, tools all working)  
**Time:** ~20 minutes

---

## State Before
- 26 skills in `~/.claude/skills/` (from Plans 0/0.1)
- 5 custom slash commands in `.claude/commands/`
- No alirezarezvani/claude-skills installed
- No rmurphey/claude-setup commands installed

## State After
- ~50 skills in `~/.claude/skills/` (26 existing + ~24 new TURN-relevant ones)
- ~20 slash commands in `.claude/commands/`
- `/plugin` skill bundles installed (user action — requires Claude Code terminal)
- `AGENTS.md` present in project root

---

## Reality Check: What These Commands Actually Do

### `/plugin` commands — CANNOT be automated
```
/plugin marketplace add anthropics/skills
/plugin install document-skills@anthropic-agent-skills
/plugin install example-skills@anthropic-agent-skills
/plugin install engineering-skills@claude-code-skills
/plugin install engineering-advanced-skills@claude-code-skills
```
These are **Claude Code CLI slash commands**, not bash commands. They live inside the Claude Code terminal only.
- `anthropic-agent-skills` → 404 on npm. Does not exist as a public package.
- `claude-code-skills` → EXISTS on npm (v0.5.0) but is `rmurphey/claude-setup`, not a skill bundle.
- `/plugin marketplace` → Claude Code built-in, accesses Anthropic's internal skill registry.

**What to do:** Type these commands directly in the Claude Code terminal input. They may or may not succeed depending on whether your Claude Code installation has marketplace access. Treat as best-effort.

### Everything else — fully automatable

---

## Epic 1 — `/plugin` Marketplace Commands (USER ACTION)

Open the Claude Code terminal and type each of these. Do not run them in a shell.

```
/plugin marketplace add anthropics/skills
/plugin marketplace add alirezarezvani/claude-skills
/plugin install document-skills@anthropic-agent-skills
/plugin install example-skills@anthropic-agent-skills
```

**Verify:** `/plugin list` shows installed plugins.  
**If they fail:** Not blocking. All critical skills are installed via git clone in Epic 2.

---

## Epic 2 — alirezarezvani/claude-skills (automatable)

### Task 0.2.1 — Clone repo

```powershell
git clone https://github.com/alirezarezvani/claude-skills.git C:\Temp\claude-skills
```

### Task 0.2.2 — Flatten TURN-relevant skills to ~/.claude/skills/

The repo nests skills at `engineering/<category>/skills/<name>/SKILL.md`.
Only install skills that (a) don't already exist and (b) are relevant to TURN.

**Skills to install — TURN-relevant, not already present:**

| Skill | Why relevant to TURN |
|---|---|
| `api-design-reviewer` | Plan 8 FastAPI endpoint review |
| `api-test-suite-builder` | Plan 8 REST API test generation |
| `database-schema-designer` | Schema evolution guidance |
| `dependency-auditor` | Ongoing security checks |
| `env-secrets-manager` | Stripe/OpenAI/Telegram key management |
| `focused-fix` | Surgical bug fixes, no collateral damage |
| `llm-cost-optimizer` | Plan 9 multi-provider routing decisions |
| `llm-wiki` | LLM abstraction layer reference |
| `mcp-server-builder` | Build custom TURN MCP tools |
| `performance-profiler` | Bot response time, DB query analysis |
| `pr-review-expert` | Pre-merge code review |
| `release-manager` | Railway deployment workflow |
| `runbook-generator` | Production incident playbooks |
| `ship-gate` | Pre-deploy checklist |
| `sql-database-assistant` | SQLite query help, migration design |
| `spec-driven-workflow` | Plan → spec → tests → code discipline |
| `tech-debt-tracker` | Track shortcuts taken during MVP |
| `write-a-skill` | Create new TURN-specific skills |
| `karpathy-coder` | Enhanced version of our karpathy-guidelines |
| `grill-with-docs` | Grill-me variant that reads docs first |

**Skills to SKIP (already have equivalent):**
- `caveman`, `grill-me`, `handoff`, `security-guidance` — already installed

```powershell
# Flatten the relevant skills
$skills_to_install = @(
    "api-design-reviewer", "api-test-suite-builder", "database-schema-designer",
    "dependency-auditor", "env-secrets-manager", "focused-fix",
    "llm-cost-optimizer", "llm-wiki", "mcp-server-builder",
    "performance-profiler", "pr-review-expert", "release-manager",
    "runbook-generator", "ship-gate", "sql-database-assistant",
    "spec-driven-workflow", "tech-debt-tracker", "write-a-skill",
    "karpathy-coder", "grill-with-docs"
)

foreach ($skill in $skills_to_install) {
    # Skills are at: engineering/<category>/skills/<name>/SKILL.md
    $src = Get-ChildItem "C:\Temp\claude-skills\engineering" -Recurse -Filter "SKILL.md" |
           Where-Object { $_.Directory.Name -eq $skill } |
           Select-Object -First 1
    if ($src) {
        $dst = "C:\Users\developer\.claude\skills\$skill"
        if (-not (Test-Path $dst)) {
            Copy-Item $src.Directory.FullName $dst -Recurse
            Write-Host "Installed: $skill"
        } else {
            Write-Host "Skipped (exists): $skill"
        }
    } else {
        Write-Host "NOT FOUND: $skill"
    }
}
```

**Verify:** `Get-ChildItem ~/.claude/skills -Directory | Measure-Object` shows ~46+ skills.

---

## Epic 3 — rmurphey/claude-setup Commands (automatable)

### Task 0.2.3 — Clone and copy commands

```powershell
git clone https://github.com/rmurphey/claude-setup.git C:\Temp\claude-setup --depth=1
```

### Task 0.2.4 — Copy commands (skip conflicts with existing)

Commands from claude-setup to install:

| Command | What it does | Keep? |
|---|---|---|
| `commit.md` | Git commit workflow with analysis | ✅ New |
| `docs.md` | Documentation generation | ✅ New |
| `hygiene.md` | Code hygiene check | ✅ New |
| `maintainability.md` | Maintainability review | ✅ New |
| `next.md` | What to work on next | ✅ New |
| `push.md` | Pre-push workflow | ✅ New |
| `reflect.md` | Session reflection | ✅ New |
| `retrospective.md` | Sprint retrospective | ✅ New |
| `session-history.md` | Session summary | ✅ New |
| `tdd.md` | TDD workflow | ✅ New |
| `todo.md` | Todo management | ✅ New |
| `learn.md` | Learn from codebase | ✅ New |
| `monitor.md` | Monitor running processes | ✅ New |
| `docs-explain.md` | Explain code to docs | ✅ New |

```powershell
# Copy commands that don't conflict with existing ones
$existing = Get-ChildItem "C:\Users\developer\Documents\GitHub\TURN\turn_mvp\.claude\commands" |
            Select-Object -ExpandProperty BaseName

Get-ChildItem "C:\Temp\claude-setup\.claude\commands" -Filter "*.md" |
Where-Object { $_.BaseName -ne "README" } |
ForEach-Object {
    if ($existing -notcontains $_.BaseName) {
        Copy-Item $_.FullName "C:\Users\developer\Documents\GitHub\TURN\turn_mvp\.claude\commands\"
        Write-Host "Copied: $($_.Name)"
    } else {
        Write-Host "Skipped (exists): $($_.Name)"
    }
}
```

### Task 0.2.5 — Copy AGENTS.md

claude-setup ships an `AGENTS.md` explaining how to use Claude Code agents effectively. Copy it to the project root.

```powershell
Copy-Item "C:\Temp\claude-setup\AGENTS.md" `
    "C:\Users\developer\Documents\GitHub\TURN\turn_mvp\AGENTS.md"
```

---

## Epic 4 — npx claude-setup (semi-automated)

`npx claude-setup` is an interactive tool that:
1. Scans the project directory
2. Generates suggested command files based on what it finds
3. Asks if you want to add package.json scripts (say N)

It does NOT overwrite existing files.

```powershell
cd C:\Users\developer\Documents\GitHub\TURN\turn_mvp
npx claude-setup
# When prompted "Add package.json scripts?" → type N
```

**Note:** This may produce duplicate commands already copied in Epic 3. Review output and delete duplicates.

**Verify:** New command files appear in `.claude/commands/` that weren't there before.

---

## Epic 5 — Verification

```powershell
# Count total skills
$count = (Get-ChildItem "C:\Users\developer\.claude\skills" -Directory | Measure-Object).Count
Write-Host "Skills installed: $count"

# Count commands
$cmds = (Get-ChildItem "C:\Users\developer\Documents\GitHub\TURN\turn_mvp\.claude\commands" -Filter "*.md" | Measure-Object).Count
Write-Host "Commands installed: $cmds"

# Verify 3 specific new skills loaded correctly (have SKILL.md with frontmatter)
foreach ($skill in @("env-secrets-manager", "ship-gate", "llm-cost-optimizer")) {
    $path = "C:\Users\developer\.claude\skills\$skill\SKILL.md"
    if (Test-Path $path) {
        $first = Get-Content $path | Select-Object -First 1
        Write-Host "$skill`: $first"
    } else {
        Write-Host "MISSING: $skill"
    }
}
```

**Verify:** 
- Skills count ≥ 44
- Commands count ≥ 15
- Each sampled skill starts with `---` (valid YAML frontmatter)

---

## Acceptance Criteria

- [ ] `/plugin` commands attempted in Claude Code terminal (best-effort) — USER ACTION
- [x] 20/20 new skills from alirezarezvani installed, all have valid frontmatter
- [x] 14 commands from rmurphey/claude-setup copied to `.claude/commands/`
- [x] `AGENTS.md` present in `turn_mvp/`
- [ ] `npx claude-setup` run, output reviewed — USER ACTION (interactive)
- [x] All sampled SKILL.md files start with `---` (valid frontmatter)
- [x] Total skills: 46 — Total commands: 19

---

## What to Skip and Why

| Item | Reason |
|---|---|
| `chaos-engineering` skill | Not relevant for TURN MVP |
| `kubernetes-operator` skill | TURN deploys on Railway, not k8s |
| `helm-chart-builder` skill | Same |
| `terraform-patterns` skill | Not used |
| `docker-development` skill | Not in TURN stack |
| `demo-video` skill | Not a dev workflow tool |
| `full-page-screenshot` skill | Webapp-testing covers this |
| `agenthub` skill cluster | Complex multi-agent orchestration, not needed yet |
| `autoresearch-agent` cluster | Not needed for TURN build phase |
