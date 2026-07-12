name: Bug report
description: Report something that is broken or does not match the spec
title: "[Bug]: "
labels: ["bug"]
body:
  - type: markdown
    attributes:
      value: |
        Thanks for taking the time to report a bug. The [spec](spec/party-network-poc-spec.md) defines expected behavior — please reference requirement IDs when you can.

  - type: textarea
    id: description
    attributes:
      label: What happened?
      description: A clear description of the bug.
      placeholder: Describe what went wrong.
    validations:
      required: true

  - type: textarea
    id: expected
    attributes:
      label: What did you expect?
      description: Expected behavior per the spec or acceptance walkthrough.
    validations:
      required: true

  - type: textarea
    id: reproduce
    attributes:
      label: Steps to reproduce
      description: Commands, API calls, or UI steps to reproduce the issue.
      placeholder: |
        1. Start Neo4j and the app
        2. POST /ingest with ...
        3. See error
    validations:
      required: true

  - type: input
    id: spec-ref
    attributes:
      label: Spec reference (optional)
      description: e.g. FR-2, NFR-4, section 8 step 5
      placeholder: FR-2

  - type: textarea
    id: environment
    attributes:
      label: Environment
      description: OS, Python/Node versions, Neo4j version, commit SHA.
      placeholder: macOS 15, Python 3.12.4, Neo4j 5.26, commit abc123
    validations:
      required: false

  - type: textarea
    id: logs
    attributes:
      label: Logs or screenshots
      description: Paste relevant logs. Do not include real PII.
    validations:
      required: false
