#!/usr/bin/env cwl-runner

class: ExpressionTool
requirements:
  - class: InlineJavascriptRequirement
cwlVersion: v1.2

inputs:
  parameter:
    type: double

outputs:
  output: double

expression: "$({'output': inputs.parameter})"
