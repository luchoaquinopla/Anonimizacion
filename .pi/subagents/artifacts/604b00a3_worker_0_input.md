# Task for worker

Modify ONLY the test bootstrap created for PR 1 RED in D:/proyectos/anonimizacion. Do not install pytest. Do not create production modules. Do not modify OpenSpec or NUL.

User explicitly requests Spanish names for test files and test functions. Rename these files:
- tests/test_ingestion_contracts.py -> tests/test_contratos_ingesta.py
- tests/test_laboratory_adapter_contract.py -> tests/test_contrato_adaptador_laboratorio.py
- tests/test_privacy_contract.py -> tests/test_contrato_privacidad.py

Rename every test function in these files to clear Spanish snake_case names. Keep intended production imports/contracts unchanged (they are API placeholders and no production code exists). Preserve synthetic, non-identifying data and intentional RED failure. Ensure pytest discovery still matches the renamed filenames. No commits and no dependency installation. Run git diff --check only. Return a concise Spanish envelope with changed files and command result.

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