# Task for worker

Implement ONLY PR 1 section 1.2 GREEN for OpenSpec change ingesta-pdf-clinicos in D:/proyectos/anonimizacion.

Current state: section 1.2 RED is complete. tests/test_contrato_bloques_laboratorio.py has 5 intentional failing tests because AdaptadorFamiliaLaboratorio lacks extraer_bloques. Implement the MINIMUM production code needed to make that existing contract pass. Do not change tests unless an actual contract defect makes it unavoidable, and explain it. Do not edit OpenSpec, README, AGENTS.md, .gitignore, pyproject.toml, or NUL. Do not add a PDF library or process PDFs. No UI, persistence, filesystem I/O, source-content logging, network, database, OCR, queues, brokers, or clinical data.

Keep all repository-owned identifiers Spanish. The adapter must process synthetic text/blocks in memory only, classify the agreed explicit synthetic document structure, produce only technical numeric provenance, map blocks into existing ResultadoExtraccion/ResolucionCampo without retaining original text or values, and reject non-laboratory content safely. Preserve the hexagonal boundary: do not make application depend on the adapter.

Run .venv/Scripts/python.exe -m pytest before and after the change, git diff --check, no-index whitespace checks for new/untracked files, and report changed-line estimate. Do not commit.

Return a concise Spanish envelope: status, executive_summary, artifacts, next_recommended, risks, skill_resolution, changed files, commands/results, explicit GREEN evidence.

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