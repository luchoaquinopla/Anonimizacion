# Task for worker

Update ONLY OpenSpec planning artifacts for change ingesta-pdf-clinicos in D:/proyectos/anonimizacion. Do not implement code, do not modify tests, do not commit or push.

Explicit user delivery decision: close the current first reviewable delivery now because the implemented core plus synthetic laboratory adapter is approximately 357 changed lines, near the 400-line budget. Move PR 1 section 1.3 privacy and operational limits into the next chained PR/delivery. Preserve the actual completed state accurately: 1.1 and 1.2 have completed RED/GREEN/TRIANGULATE/REFACTOR; 1.3 is not started. Reconcile only the relevant delivery/task planning language in proposal.md, design.md, tasks.md as needed. Do not falsely mark code or tests complete beyond that. Keep Spanish OpenSpec style and traceability. Run git diff --check. Return Spanish envelope with exact artifacts and changed summary.

## Skills to load before work
C:\Users\lucho\.config\opencode\skills\cognitive-doc-design\SKILL.md
C:\Users\lucho\.config\opencode\skills\work-unit-commits\SKILL.md

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