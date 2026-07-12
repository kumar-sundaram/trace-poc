name: Question
description: Ask about the spec, architecture, or contribution process
title: "[Question]: "
labels: ["question"]
body:
  - type: markdown
    attributes:
      value: |
        For contribution process questions, see [CONTRIBUTING.md](../CONTRIBUTING.md). For security concerns, see [SECURITY.md](../SECURITY.md) — do not use this template for vulnerabilities.

  - type: textarea
    id: question
    attributes:
      label: Your question
      description: What would you like clarified?
    validations:
      required: true

  - type: textarea
    id: context
    attributes:
      label: Context
      description: What you have read or tried so far.
    validations:
      required: false
