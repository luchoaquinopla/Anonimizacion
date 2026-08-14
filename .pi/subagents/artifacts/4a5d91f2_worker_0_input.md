# Task for worker

Implement ONLY PR 1 section 1.1 TRIANGULATE for OpenSpec change ingesta-pdf-clinicos in D:/proyectos/anonimizacion.

Current state: PR 1 RED and GREEN are complete. Existing Python code is under src/ingesta_clinica and all repository-owned names must be in Spanish per AGENTS.md. Strict boundaries: no actual PDF handling, UI, persistence, filesystem writes, logs of source content, network, database, OCR, queues, or brokers. Do not touch NUL or OpenSpec.

Follow TDD: first add tests that initially fail for these exact cases, run them to capture RED evidence, then minimally extend the domain model/policy to make them pass (GREEN within the triangulation task). Add tests for:
- incompatible unit for a field;
- malformed and truncated values;
- multiple candidates / ambiguity;
- legitimate absence of an optional field;
- assurance that every field explicitly maps to a known extraction state and none is silently omitted.

Keep output safe: tests must use synthetic non-identifying data and results must never preserve clinical values or source text. Prefer extending the existing domain contracts cleanly. Run .venv/Scripts/python.exe -m pytest after tests-first to prove final green; run git diff --check; use a no-index whitespace check for untracked files too; report changed-line estimate. Do not commit.

Return in Spanish: status, executive_summary, artifacts, next_recommended, risks, skill_resolution, changed files, commands/results, and explicit RED then GREEN evidence.

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