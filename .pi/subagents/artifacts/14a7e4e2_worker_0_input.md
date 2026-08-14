# Task for worker

Create ONLY README.md at the repository root D:/proyectos/anonimizacion. Do not modify any existing file and do not commit or push.

Write in Spanish, for the current state of the project, with a practical and accurate explanation of:
- purpose and explicit non-goals of the current local/ephemeral laboratory core;
- folder and file structure, including src/ingesta_clinica/dominio, aplicacion/puertos, adaptadores/salida, composicion.py, tests, pyproject.toml, openspec, and .venv;
- data/dependency flow and the dependency-inversion boundary;
- why hexagonal architecture was selected for this project rather than a monolithic/UI-coupled design or direct infrastructure dependencies;
- current limitations: synthetic markers only, no real PDF parsing, UI, persistence, external network, database, clinical corpus or production clinical claims;
- how to run tests with .venv/Scripts/python.exe -m pytest.

Follow AGENTS.md: Spanish repository-facing names and prose. Explain exactly what exists; do not promise functionality that is not implemented. Do not mention NUL or PI harness artifacts. Return concise Spanish result envelope and run git diff --check. Include skill path below.

## Skills to load before work
C:\Users\lucho\.config\opencode\skills\cognitive-doc-design\SKILL.md

## Acceptance Contract
Acceptance level: attested
Completion is not accepted from prose alone. End with a structured acceptance report.

Criteria:
- criterion-1: Return concrete findings with file paths and severity when applicable

Required evidence: review-findings, residual-risks

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