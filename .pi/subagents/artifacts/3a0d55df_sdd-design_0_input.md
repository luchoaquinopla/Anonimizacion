# Task for sdd-design

Execute ONLY the planning-reconciliation phase for existing OpenSpec change ingesta-pdf-clinicos in D:/proyectos/anonimizacion; do NOT implement application code.

The user explicitly chose:
- First implementable increment: local browser UI + laboratory PDFs only; in-memory extraction and anonymization; no persistence, no ECG, no echocardiography.
- Delivery: chained PRs, each designed to stay within roughly 400 changed lines.

Reconcile the inconsistent planning artifacts so they establish one coherent scope. Edit only:
- openspec/changes/ingesta-pdf-clinicos/proposal.md
- openspec/changes/ingesta-pdf-clinicos/design.md
- openspec/changes/ingesta-pdf-clinicos/tasks.md

Keep future ECG, echocardiography, persistence, quality evaluation, and ML datasets explicitly out of the first increment, as deferred work with their required approvals. Replace stale PostgreSQL/queue architecture with the local ephemeral first-increment design. Break implementation work into chained, reviewable increments. Preserve Spanish OpenSpec language and existing strict-TDD task convention. Do not claim tests ran or implementation completed. Do not commit.

Return in Spanish exactly this result envelope: status, executive_summary, artifacts, next_recommended, risks, skill_resolution.

## Skills to load before work
C:\Users\lucho\.config\opencode\skills\cognitive-doc-design\SKILL.md

If you make important discoveries or decisions, save them to Engram with project anonimizacion before returning.

## Acceptance Contract
Acceptance level: checked
Completion is not accepted from prose alone. End with a structured acceptance report.

Criteria:
- criterion-1: Implement the requested change without widening scope

Required evidence: changed-files, tests-added, commands-run, residual-risks, no-staged-files

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