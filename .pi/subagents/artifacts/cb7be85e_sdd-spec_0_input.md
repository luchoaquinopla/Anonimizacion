# Task for sdd-spec

Execute exactly the SDD spec phase for existing change `ingesta-pdf-clinicos`, updating delta specs to be consistent with the newly approved proposal.

## Approved scope
Build a local-only browser UI that supports drag-and-drop of multiple sample PDFs. Each file is processed synchronously, entirely in memory, and all data is discarded before completing. Reply only after the complete batch with received/processed counts and safe technical per-file outcome codes. Never display clinical data, anonymized values, extracted text, PDF names, PII/PHI, or detailed diagnostics in the UI. No persistence, temporary files, logs containing content, network exposure, authentication, queue/broker, future source selection, APIs, folder watchers, hospital-system integration, or ML feature persistence.

Add a decoupled inbound port for the ingestion use case, so a future source adapter can call it without changing extraction/privacy/domain. Do not choose frameworks or mechanisms for future sources. Retain current privacy, extraction quality, and discard constraints.

## Files and workflow context
- Read AGENTS.md, openspec/config.yaml, proposal.md, existing four spec files, design.md, tasks.md.
- Update only the relevant files under `openspec/changes/ingesta-pdf-clinicos/specs/`. Add a `carga-manual-local` spec if the capability needs a separate delta spec; remove or reframe scopes which now conflict (especially any present persistence/ML output obligations).
- Specs must be Spanish, use requirements/scenarios with DADO/CUANDO/ENTONCES and preserve the project convention explaining RFC terms.
- Do not modify proposal, design, tasks, code, config, or commit.
- Save meaningful outcome to Engram if available; failure to reach Engram must be reported, not block the file artifact.

Return: status, executive_summary, artifacts, next_recommended, risks, skill_resolution.

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