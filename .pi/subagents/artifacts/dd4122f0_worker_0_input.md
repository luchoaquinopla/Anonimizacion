# Task for worker

Implement ONLY PR 1 section 1.2 TRIANGULATE for OpenSpec change ingesta-pdf-clinicos in D:/proyectos/anonimizacion.

Current state: 1.2 RED and GREEN are complete, suite has 21 passing tests. User approved TRIANGULATE 1.2. Follow TDD: add tests first and run them to capture RED evidence, then minimally extend only the laboratory synthetic adapter and its contracts as needed to reach GREEN. Do not modify OpenSpec, README, AGENTS.md, .gitignore, pyproject.toml or NUL. Do not add PDF libraries or parse real PDFs; no UI, persistence, filesystem I/O, logging source content, network, database, OCR, queues, brokers, or clinical data.

Add synthetic non-identifying cases for: variable block/row order, incomplete tables including laboratory header with no result rows (must define a safe explicit result rather than silently accepting empty extraction), two conflicting candidates for the same field, and preservation of only permitted technical provenance. Tests and all owned identifiers must be Spanish. Ensure no text source or values survive in output. Preserve strict hexagonal direction: no application import of concrete adapter.

Run baseline tests before change; run targeted new tests to prove RED; then full .venv/Scripts/python.exe -m pytest to prove GREEN. Run git diff --check and no-index whitespace validation for task-owned untracked files. Report changed-line estimate. No commit.

Return Spanish envelope: status, executive_summary, artifacts, next_recommended, risks, skill_resolution, changed files, commands/results, explicit RED and GREEN evidence.

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