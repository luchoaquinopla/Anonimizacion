# Task for sdd-tasks

Execute exactly the ready SDD phase `sdd-tasks` for change `ingesta-pdf-clinicos`.

## Authoritative status
- change root: `openspec/changes/ingesta-pdf-clinicos`
- proposal, 4 specs, and design: present
- tasks: missing
- action context: repo-local at `D:/proyectos/anonimizacion`, safe
- exact ready phase: sdd-tasks
- apply/verify/sync/archive: blocked pending tasks

## Session decisions
- Interactive SDD; this is the one approved phase.
- Store artifacts in both OpenSpec and Engram.
- One PR default; 400 changed-line review budget.

## Work
Read AGENTS.md and all existing proposal, four specs, and design. Create only `openspec/changes/ingesta-pdf-clinicos/tasks.md` in Spanish. Follow `openspec/config.yaml`: group by phase and use hierarchical numbering; keep each task feasible in one session. Create a practical first increment: local, in-memory lab-PDF spike with no persistence, then deliberately-gated expansion. Explicitly distinguish implementation tasks from blocking business/clinical decisions. Forecast review workload; do not invent missing corpus, thresholds, source, broker, or pseudonymization approval. Do not create application code, dependencies, test fixtures, or commits.

## Skills to load before work
- `C:\Users\lucho\.config\opencode\skills\work-unit-commits\SKILL.md`

Save a concise significant decision/discovery to Engram before returning. Return the SDD Result Contract: status, executive_summary, artifacts, next_recommended, risks, skill_resolution.

## Acceptance Contract
Acceptance level: attested
Completion is not accepted from prose alone. End with a structured acceptance report.

Criteria:
- criterion-1: Return a concise result and residual risks when applicable

Required evidence: manual-notes, residual-risks

Finish with a fenced JSON block tagged `acceptance-report` in this shape:
Use empty arrays when no items apply; array fields contain strings unless object entries are shown.
`criteriaSatisfied[].status` must be exactly one of: satisfied, not-satisfied, not-applicable.
`commandsRun[].result` must be exactly one of: passed, failed, not-run.
`manualNotes` and `notes` are optional strings; an empty string means no note and does not satisfy `manual-notes` evidence.
```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "specific proof"
    }
  ],
  "changedFiles": [
    "src/file.ts"
  ],
  "testsAddedOrUpdated": [
    "test/file.test.ts"
  ],
  "commandsRun": [
    {
      "command": "command",
      "result": "passed",
      "summary": "short result"
    }
  ],
  "validationOutput": [
    "validation output or concise summary"
  ],
  "residualRisks": [
    "none"
  ],
  "noStagedFiles": true,
  "diffSummary": "short description of the diff",
  "reviewFindings": [
    "blocker: file.ts:12 - issue found, or no blockers"
  ],
  "manualNotes": "anything else the parent should know"
}
```