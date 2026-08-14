# Task for worker

Implement ONLY PR 1 section 1.2 RED for the OpenSpec change ingesta-pdf-clinicos in D:/proyectos/anonimizacion.

Current baseline is committed at e5dfe65. The user approved moving phase by phase. This is RED only: add tests and do NOT make production changes. Do not change OpenSpec, README, AGENTS.md, .gitignore, NUL, pyproject.toml, or existing production code. Do not process PDFs, add PDF libraries, UI, persistence, filesystem I/O, logging, network, database, OCR, queues, or brokers.

Create Spanish-named pytest tests using synthetic non-identifying text/blocks only, that define the future laboratory adapter contract for:
- classification of a laboratory document based on an explicit synthetic document structure rather than the current simple marker;
- ephemeral technical provenance with only allowable technical coordinates;
- conversion of parsed synthetic laboratory blocks into existing ResultadoExtraccion/ResolucionCampo contract;
- safe rejection for non-laboratory input;
- no retained source text or clinical values in public/intermediate results.

The tests must initially fail for a missing or insufficient future parser/contract, while existing tests remain unchanged. Run existing suite before test creation, then run the new tests and capture the expected RED failure. Do not implement GREEN. Run git diff --check and a no-index whitespace check for the new untracked test. No commit.

Return a concise Spanish envelope: status, executive_summary, artifacts, next_recommended, risks, skill_resolution, changed files, commands/results, explicit RED evidence.

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