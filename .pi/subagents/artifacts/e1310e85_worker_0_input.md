# Task for worker

Implement ONLY PR 1 section 1.1 REFACTOR for OpenSpec change ingesta-pdf-clinicos in D:/proyectos/anonimizacion.

Current state: RED, GREEN and TRIANGULATE are complete; .venv/Scripts/python.exe -m pytest currently passes. User approved the immediate REFACTOR phase. Refactor for strict hexagonal architecture: application must not import an adapter implementation directly. Define a Spanish-named outbound port/protocol/abstraction owned by the application or domain boundary, make PuertoEntradaIngesta depend only on it, and inject the concrete AdaptadorFamiliaLaboratorio at composition/use time. Preserve all public behavior and tests. Add narrowly scoped tests only if required to prove dependency inversion; otherwise do not expand test scope.

Do not implement actual PDF handling, UI, persistence, filesystem writes, logging of source contents, networking, databases, OCR, queues or brokers. Do not touch OpenSpec or NUL. Maintain all repository-owned names in Spanish as AGENTS.md requires. Do not commit.

Run the full pytest suite before and after refactor; run git diff --check and no-index whitespace checks for untracked source/test files. Estimate accumulated PR 1 changed lines and clearly flag if review budget is exceeded. Return Spanish envelope: status, executive_summary, artifacts, next_recommended, risks, skill_resolution, changed files, commands/results.

## Skills to load before work
C:\Users\lucho\.config\opencode\skills\work-unit-commits\SKILL.md

If important discoveries or decisions occur, save them to Engram with project anonimizacion before returning.

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