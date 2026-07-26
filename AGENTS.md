# Agents — Ko-Stream (CodeProject2)

Orchestration brain lives in the Obsidian vault; this repo holds the code.

| Path | Role |
|------|------|
| **Code** | `C:\Users\Kosov\.cursor\Repositories\CodeProject2` |
| **Vault** | `C:\Users\Kosov\OneDrive\Documents\ObsidianVaults\CodingProjekt1\CodingProjekt` |
| **GitHub** | https://github.com/KosovarM/Ko-Stream |

## Roles

| Skill | Role | Code? |
|-------|------|-------|
| *(this chat)* | Project Leader | Orchestration (+ trivial fixes) |
| `@cp1-research` | Research | No |
| `@cp1-architect` | Architect | Specs only |
| `@cp1-coder` | Coder | Yes |
| `@cp1-tester` | Tester | Tests only |
| `@cp1-critic` | Critic | No |
| `@cp1-documenter` | Documenter | Docs / vault only |

Skills may live under CodeProject1 `.cursor/skills/cp1-*` until mirrored here. Roster detail: vault `30 Agents.md`.

## Standing rule — vault sync on publish

**Whenever an agent creates a git commit and publishes/pushes to remote**, also update the vault:

1. `90 Changelog.md` — dated entry for what shipped.
2. Any affected project/agent notes (`21 Codebase — Ko-Stream`, `10 Project`, `00 Start`, `30 Agents/*`, `70 Documentation/*` as needed).

Commit without push → vault optional. **Commit + push → vault required** (same turn or Documenter handoff). Cursor rule: `.cursor/rules/vault-sync-on-publish.mdc`.

## Typical flow

```
Leader → Research? → Architect? → Coder → Tester → Critic → Documenter
```

After **commit + push**: Documenter (or the publishing agent) updates the vault before ending the turn.

## Model efficiency

Vault: `30 Agents/Model efficiency.md` — light models for small/clear tasks; heavy only when needed. Briefs set `Model tier: light | standard | heavy`.

## Cursor locations

- Rules: `.cursor/rules/`
- Skills: prefer `@cp1-*` (see vault `30 Agents.md`); media library import/maintain → `@kostream-media` (`.cursor/skills/kostream-media/`)
