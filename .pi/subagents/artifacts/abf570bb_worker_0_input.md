# Task for worker

Implement ONLY PR 1 phase RED for the approved OpenSpec change ingesta-pdf-clinicos in D:/proyectos/anonimizacion.

Authoritative scope: Python + pytest. This is RED, not GREEN: write tests and the minimum test-project bootstrap only. Do NOT implement production contracts, types, privacy logic, PDF extraction, UI, persistence, or any behavior that makes these tests pass. The intended final test run MUST fail because the production module/contract does not yet exist; record that as successful RED evidence.

Use the PR 1 task lines 1.1 RED, 1.2 RED, and 1.3 RED in openspec/changes/ingesta-pdf-clinicos/tasks.md. Tests must use only synthetic, non-identifying values. Specify expected contracts for exhaustive extraction states, field resolution, rejection when residual PII/PHI or incomplete controls exist, laboratory classification, ephemeral provenance, and permitted safe technical output. Keep all tests intentionally failing for missing production implementation. Add only files necessary for pytest discovery/configuration and tests. Do not edit OpenSpec artifacts, do not commit, and do not install unrelated dependencies.

Before finishing, run the exact test command and report the expected failure. Also run git diff --check. Return Spanish envelope: status, executive_summary, artifacts, next_recommended, risks, skill_resolution, changed files, commands/results.

## Skills to load before work
C:\Users\lucho\.config\opencode\skills\work-unit-commits\SKILL.md

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