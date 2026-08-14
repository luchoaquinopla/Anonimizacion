# Task for worker

Implement the approved PR 1 RED environment setup in D:/proyectos/anonimizacion. User explicitly approved installing pytest and gave an explicit repository convention: every repository-facing file name, test name, code identifier (functions, variables, constants, classes, modules/packages), comments, and future code must be written in Spanish unless a third-party API requires otherwise.

Perform these bounded changes only:
1. Update AGENTS.md in Spanish to record that explicit naming convention, including the third-party API exception.
2. Update the Python test bootstrap so pytest is a development/test dependency in pyproject.toml, without adding production/PDF dependencies.
3. Update the current RED tests under tests/ so ALL repository-owned Python identifiers and all intended production module/API placeholders are Spanish. Rename package references from clinical_ingestion to ingesta_clinica and use Spanish module/class/function/constant names. Keep pytest and standard-library external names unchanged. Tests must remain intentional RED because src/ingesta_clinica must not be created.
4. Create an ignored project-local .venv and install pytest into it. Do not install globally. Do not create production source code.

Do NOT delete or modify NUL: it is an unexpected artifact requiring separate user authorization. Do not modify OpenSpec. Do not commit.

Run .venv/Scripts/python.exe -m pytest (or the correct local Windows venv interpreter) and demonstrate expected RED failure due to absent ingesta_clinica. Run git diff --check. Report exact results in Spanish with status, executive_summary, artifacts, next_recommended, risks, skill_resolution, changed files, commands/results.

## Skills to load before work
C:\Users\lucho\.config\opencode\skills\work-unit-commits\SKILL.md

If important decisions or discoveries occur, save them to Engram with project anonimizacion before returning.

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