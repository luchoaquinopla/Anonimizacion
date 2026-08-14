# Task for worker

Rewrite ONLY README.md at D:/proyectos/anonimizacion. Do not modify other files, do not commit or push.

User correction: README must document the PROJECT IN GENERAL, not merely the present implementation state. Write in Spanish and clearly separate:
1. project purpose: safe local-first ingestion, anonymization, and future preparation of clinical PDF-derived data;
2. guiding privacy principles and explicit boundaries;
3. target architecture: hexagonal architecture, domain/application/ports/adapters, why it fits this project vs monolith coupled to UI or infrastructure;
4. intended data flow from future local browser upload through transient extraction/anonymization/privacy validation to safe acknowledgement; make clear future persistence/ML require separate approval;
5. planned staged roadmap: current PR 1 core; future local UI; quality gating after approved corpus/inventory/thresholds; persistence only under separate approved proposal; ECG/echocardiography/ML as deferred capabilities;
6. repository structure: distinguish current source layout from OpenSpec planning artifacts and future capabilities;
7. development/testing command and realistic current status/limitations.

Do not promise clinical production readiness or real PDF processing. Preserve technical accuracy and explain decisions pedagogically. Run .venv/Scripts/python.exe -m pytest and whitespace check for README. Return concise Spanish envelope.

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