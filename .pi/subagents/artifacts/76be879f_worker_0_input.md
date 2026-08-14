# Task for worker

Act as the fallback SDD planning writer because the package sdd-design agent is unusable in this runtime (unavailable glob tool). Execute ONLY planning reconciliation for existing OpenSpec change ingesta-pdf-clinicos in D:/proyectos/anonimizacion; do NOT implement application code.

User-approved decisions:
1. First implementable increment: local browser UI + laboratory PDFs only; in-memory extraction and anonymization; no persistence, no ECG, no echocardiography.
2. Delivery: chained PRs, each designed to stay within roughly 400 changed lines.

Edit ONLY proposal.md, design.md, and tasks.md below the change root. Reconcile their scope into a coherent staged plan: first slice as approved; future ECG, echocardiography, persistence, quality evaluation, and ML datasets clearly deferred and gated by their approvals; eliminate PostgreSQL/queue claims from the first slice; and split work into reviewable chained increments. Preserve Spanish OpenSpec conventions and strict-TDD tasks. Do not commit or run unrelated work.

Return in Spanish: status, executive_summary, artifacts, next_recommended, risks, skill_resolution.

## Skills to load before work
C:\Users\lucho\.config\opencode\skills\cognitive-doc-design\SKILL.md

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