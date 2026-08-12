# Task for sdd-proposal

Amend the existing OpenSpec proposal ONLY for change `ingesta-pdf-clinicos` to add the user-approved first delivery shape.

User decision: implement option 1. Provide a local-only, browser-based manual upload adapter where the user drag-and-drops multiple sample PDFs. Each PDF is processed synchronously and entirely in memory before the response. The UI returns only a batch acknowledgement after all files finish, e.g. received/processed counts and safe per-file technical outcome codes. It must never persist PDFs, raw extracted text, PII/PHI, temp files, logs with contents, queue payloads, or results. It does not expose anonymized clinical data in this first UI.

Architecture intent: add/retain an inbound port so future adapters (folder watcher, authenticated API, hospital system or queue) can supply the same ingestion use case without changing domain extraction/anonymous validation. Do not choose any future source, broker, auth provider, framework, or storage. Retain all existing hard privacy constraints and state that the browser UI is local only, not network exposed.

Read AGENTS.md, config, and existing proposal. Modify only `openspec/changes/ingesta-pdf-clinicos/proposal.md`; Spanish artifact language. Do not modify specs/design/tasks or create code. Do not commit. Save the significant decision to Engram. Return: status, executive_summary, artifacts, next_recommended, risks, skill_resolution.

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