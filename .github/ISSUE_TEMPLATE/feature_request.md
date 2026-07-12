name: Feature request
description: Suggest a new capability or spec change
title: "[Feature]: "
labels: ["enhancement"]
body:
  - type: markdown
    attributes:
      value: |
        Feature requests should align with POC goals in the spec. Check [non-goals](spec/party-network-poc-spec.md#3-non-goals-explicitly-out-of-scope) before proposing production-scale or security hardening work.

  - type: textarea
    id: problem
    attributes:
      label: Problem or opportunity
      description: What problem does this solve? Who benefits?
    validations:
      required: true

  - type: textarea
    id: proposal
    attributes:
      label: Proposed solution
      description: Describe the change at a high level.
    validations:
      required: true

  - type: dropdown
    id: scope
    attributes:
      label: Scope
      description: Does this fit the POC or belong post-POC?
      options:
        - POC scope (in spec goals)
        - Spec clarification only
        - Post-POC / open item
    validations:
      required: true

  - type: textarea
    id: acceptance
    attributes:
      label: Acceptance criteria
      description: How would we know this is done? Reference demo steps or FR/NFR IDs if possible.
    validations:
      required: false

  - type: checkboxes
    id: spec-update
    attributes:
      label: Spec impact
      options:
        - label: This requires updating spec/party-network-poc-spec.md
          required: false
        - label: This requires updating test data or acceptance fixtures
          required: false
