# Copyright 2023 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""GRR Flow Args parsing functions."""


from typing import Any
from grr_response_proto import flows_pb2
from grr_response_proto import timeline_pb2
from grr_api_client import flow


def _FileFinderArgsParse(args: Any, allow_multiline: bool) -> list[str]:
  ff_args = flows_pb2.FileFinderArgs.FromString(args.value)
  action = flows_pb2.FileFinderAction.Action.Name(ff_args.action.action_type)
  if allow_multiline:
    lines = [f'Action: {action}']
    for p in ff_args.paths:
      lines.append(f'Path: {p}')
    return lines
  if len(ff_args.paths) == 1:
    return [f'{action} {ff_args.paths[0]}']
  return [f'{action} <MULTIPLE PATHS>']


def _TimelineArgsParse(args: Any, _allow_multiline: bool) -> list[str]:
  return [f'root: {timeline_pb2.TimelineArgs.FromString(args.value).root.decode("utf-8")}']


def _ArtifactCollectorFlowArgsParse(args: Any, allow_multiline: bool) -> list[str]:
  artefacts = flows_pb2.ArtifactCollectorFlowArgs.FromString(args.value).artifact_list
  if allow_multiline:
    return [f'Artefact: {a}' for a in artefacts]
  if len(artefacts) == 1:
    return [artefacts[0]]
  return ['<MULTIPLE ARTEFACTS>']


def _GetFileArgsParse(args: Any, _allow_multiline: bool) -> list[str]:
  args = flows_pb2.GetFileArgs.FromString(args.value)
  param = args.pathspec.path
  if args.pathspec.stream_name:
    param = f'{param}:{args.pathspec.stream_name}'
  return [param]


_FLOW_ARGS_PARSING_FUNCTIONS = {
    'grr.FileFinderArgs': _FileFinderArgsParse,
    'grr.GetFileArgs': _GetFileArgsParse,
    'grr.TimelineArgs': _TimelineArgsParse,
    'grr.ArtifactCollectorFlowArgs': _ArtifactCollectorFlowArgsParse,
}


def Parse(flow_handle: flow.Flow, multiline: bool = False) -> list[str]:
  """Parse out flow args from a flow object.

  Args:
    flow_handle: The flow to extract runtime args from.
    multiline: True if the context allows for multiple lines, False if result
      should only be a single line.

  Returns:
    The argument for the flow.
  """
  typename = flow_handle.data.args.TypeName()
  if typename in _FLOW_ARGS_PARSING_FUNCTIONS:
    return _FLOW_ARGS_PARSING_FUNCTIONS[typename](flow_handle.data.args, multiline)
  return ['<UNSUPPORTED FLOW TYPE>']
