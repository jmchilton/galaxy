#!/usr/bin/env cwl-runner
class: ExpressionTool
requirements:
  - class: InlineJavascriptRequirement
cwlVersion: v1.2
inputs:
  parameter:
    type:
      type: record
      fields:
        - name: name
          type: string
        - name: count
          type: int
outputs:
  output: string
expression: "$({'output': inputs.parameter.name})"
