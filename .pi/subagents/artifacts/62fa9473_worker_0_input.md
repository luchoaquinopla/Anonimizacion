# Task for worker

Implement ONLY PR 1 section 1.2 REFACTOR for OpenSpec change ingesta-pdf-clinicos in D:/proyectos/anonimizacion.

Current state: section 1.2 RED/GREEN/TRIANGULATE complete; suite has 25 passing tests. User approved REFACTOR. Refactor only the synthetic laboratory mapping behind AdaptadorFamiliaLaboratorio for clarity, cohesion, and maintainability. Preserve every existing behavior, public contract, safe rejection code, technical provenance constraint, and Spanish-owned naming. Do not change tests unless strictly needed to preserve existing behavior; do not expand scope.

Confirm architecture constraints: domain and application must not depend on any PDF library, and application must not import the concrete adapter. Do not add PDF handling, libraries, UI, persistence, filesystem I/O, source-content logging, network, database, OCR, queues, brokers, clinical data. Do not touch OpenSpec, README, AGENTS.md, .gitignore, pyproject.toml, or NUL. No commit.

Run full .venv/Scripts/python.exe -m pytest before and after. Run git diff --check and targeted no-index whitespace checks. Report the PR 1 changed-line estimate and flag if it approaches/exceeds 400. Return concise Spanish envelope: status, executive_summary, artifacts, next_recommended, risks, skill_resolution, changed files, commands/results.

## Skills to load before work
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