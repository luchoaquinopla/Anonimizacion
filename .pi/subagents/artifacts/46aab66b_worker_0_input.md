# Task for worker

Implement ONLY PR 1 phase GREEN for the OpenSpec change ingesta-pdf-clinicos in D:/proyectos/anonimizacion.

Prerequisites already proven: Python + pytest; tests are intentionally RED and import the absent ingesta_clinica package. Implement the MINIMUM production code under src/ingesta_clinica necessary to make the existing three RED test files pass. Do not change tests except if an unavoidable bug in their contract is found; explain any such change. Do not edit OpenSpec. Do not touch NUL. Do not implement a real PDF library/extraction, UI, persistence, temporary files, logs containing source data, OCR, network access, database, queues, or brokers.

Implement exact Spanish owned identifiers and module names matching current test placeholders. Third-party/standard library API names may remain as required. Create only the needed package/init files and modules. Must provide:
- exhaustive extraction statuses and explicit field resolutions;
- ephemeral extraction result/provenance representation;
- an input-port boundary whose public result contains only approval, technical codes, and counts;
- policy rejecting residual PII/PHI, incomplete privacy controls, and unverifiable required fields;
- in-memory laboratory adapter for synthetic content only, with safe non-laboratory rejection and minimal numeric-only technical provenance;
- privacy validator whose public safe output exposes only approval, codes, counts.

Run the local venv test command .venv/Scripts/python.exe -m pytest and prove GREEN. Run git diff --check and report diff stat. Keep changes below the PR review budget; do not commit.

Return a Spanish envelope: status, executive_summary, artifacts, next_recommended, risks, skill_resolution, changed files, commands/results.

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