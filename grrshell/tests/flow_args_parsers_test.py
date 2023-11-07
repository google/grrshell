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
"""Unit tests for GRR Flow Args parsing functions."""

from unittest import mock

from absl.testing import absltest
from absl.testing import parameterized

from grr_api_client import flow
from grr_response_proto.api import flow_pb2
from google.protobuf import text_format

from grrshell.lib import flow_args_parsers


# pylint: disable=consider-using-with
_MOCK_APIFLOW_ARTEFACTCOLLECTOR_SINGLE_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_artifactcollector_allfile_running.textproto'
_MOCK_APIFLOW_ARTEFACTCOLLECTOR_SINGLE = flow.Flow(
    data=text_format.Parse(open(_MOCK_APIFLOW_ARTEFACTCOLLECTOR_SINGLE_PROTO_FILE, 'rb').read().decode('utf-8'), flow_pb2.ApiFlow()),
    context=mock.MagicMock())
_MOCK_APIFLOW_ARTEFACT_SINGLE_EXPECTED_SINGLE = ['AllOS_File']
_MOCK_APIFLOW_ARTEFACT_SINGLE_EXPECTED_MULTI = ['Artefact: AllOS_File']

_MOCK_APIFLOW_ARTEFACTCOLLECTOR_MULTIPLE_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_artifactcollector_multiple.textproto'
_MOCK_APIFLOW_ARTEFACTCOLLECTOR_MULTIPLE = flow.Flow(
    data=text_format.Parse(open(_MOCK_APIFLOW_ARTEFACTCOLLECTOR_MULTIPLE_PROTO_FILE, 'rb').read().decode('utf-8'), flow_pb2.ApiFlow()),
    context=mock.MagicMock())
_MOCK_APIFLOW_ARTEFACT_MULTIPLE_EXPECTED_SINGLE = ['<MULTIPLE ARTEFACTS>']
_MOCK_APIFLOW_ARTEFACT_MULTIPLE_EXPECTED_MULTI = ['Artefact: AllOS_File', 'Artefact: AllOS_ArtifactGroup']

_MOCK_APIFLOW_CFF_HASH_SINGLE_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_clientfilefinder_hash_running.textproto'
_MOCK_APIFLOW_CFF_HASH_SINGLE = flow.Flow(
    data=text_format.Parse(open(_MOCK_APIFLOW_CFF_HASH_SINGLE_PROTO_FILE, 'rb').read().decode('utf-8'), flow_pb2.ApiFlow()),
    context=mock.MagicMock())
_MOCK_APIFLOW_CFF_HASH_SINGLE_EXPECTED_SINGLE = ['HASH C:/Users/ramoj/Downloads/Firefox Installer.exe']
_MOCK_APIFLOW_CFF_HASH_SINGLE_EXPECTED_MULTI = ['Action: HASH', 'Path: C:/Users/ramoj/Downloads/Firefox Installer.exe']

_MOCK_APIFLOW_CFF_HASH_MULTIPLE_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_clientfilefinder_multiple.textproto'
_MOCK_APIFLOW_CFF_HASH_MULTIPLE = flow.Flow(
    data=text_format.Parse(open(_MOCK_APIFLOW_CFF_HASH_MULTIPLE_PROTO_FILE, 'rb').read().decode('utf-8'), flow_pb2.ApiFlow()),
    context=mock.MagicMock())
_MOCK_APIFLOW_CFF_HASH_MULTIPLE_EXPECTED_SINGLE = ['HASH <MULTIPLE PATHS>']
_MOCK_APIFLOW_CFF_HASH_MULTIPLE_EXPECTED_MULTI = [
  'Action: HASH', 'Path: C:/Users/ramoj/Downloads/Firefox Installer.exe', 'Path: C:/Users/ramoj/Downloads/notepad++.exe']

_MOCK_APIFLOW_TIMELINE_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_timeline_running.textproto'
_MOCK_APIFLOW_TIMELINE = flow.Flow(
    data=text_format.Parse(open(_MOCK_APIFLOW_TIMELINE_PROTO_FILE, 'rb').read().decode('utf-8'), flow_pb2.ApiFlow()),
    context=mock.MagicMock())
_MOCK_APIFLOW_TIMELINE_EXPECTED = ['root: /']

_MOCK_APIFLOW_GETFILE_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_getfile_running.textproto'
_MOCK_APIFLOW_GETFILE = flow.Flow(
    data=text_format.Parse(open(_MOCK_APIFLOW_GETFILE_PROTO_FILE, 'rb').read().decode('utf-8'), flow_pb2.ApiFlow()),
    context=mock.MagicMock())
_MOCK_APIFLOW_GETFILE_EXPECTED = ['C:/Users/username/Downloads/Firefox Installer.exe:Zone.Identifier']

_MOCK_APIFLOW_INTERROGATE_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_interrogate_running.textproto'
_MOCK_APIFLOW_INTERROGATE = flow.Flow(
    data=text_format.Parse(open(_MOCK_APIFLOW_INTERROGATE_PROTO_FILE, 'rb').read().decode('utf-8'), flow_pb2.ApiFlow()),
    context=mock.MagicMock())
_MOCK_APIFLOW_INTERROGATE_EXPECTED = ['<UNSUPPORTED FLOW TYPE>']
# pylint: enable=consider-using-with


class FlowArgsParsersTest(parameterized.TestCase):
  """Unit tests for GRR Flow Args parsing functions."""

  @parameterized.named_parameters(
      ('artefact_single_singleline', _MOCK_APIFLOW_ARTEFACTCOLLECTOR_SINGLE, False, _MOCK_APIFLOW_ARTEFACT_SINGLE_EXPECTED_SINGLE),
      ('artefact_single_multiline', _MOCK_APIFLOW_ARTEFACTCOLLECTOR_SINGLE, True, _MOCK_APIFLOW_ARTEFACT_SINGLE_EXPECTED_MULTI),
      ('artefact_multiple_singleline', _MOCK_APIFLOW_ARTEFACTCOLLECTOR_MULTIPLE, False, _MOCK_APIFLOW_ARTEFACT_MULTIPLE_EXPECTED_SINGLE),
      ('artefact_multiple_multiline', _MOCK_APIFLOW_ARTEFACTCOLLECTOR_MULTIPLE, True, _MOCK_APIFLOW_ARTEFACT_MULTIPLE_EXPECTED_MULTI),
      ('cff_single_singleline', _MOCK_APIFLOW_CFF_HASH_SINGLE, False, _MOCK_APIFLOW_CFF_HASH_SINGLE_EXPECTED_SINGLE),
      ('cff_single_multiline', _MOCK_APIFLOW_CFF_HASH_SINGLE, True, _MOCK_APIFLOW_CFF_HASH_SINGLE_EXPECTED_MULTI),
      ('cff_multiple_singleline', _MOCK_APIFLOW_CFF_HASH_MULTIPLE, False, _MOCK_APIFLOW_CFF_HASH_MULTIPLE_EXPECTED_SINGLE),
      ('cff_multiple_multiline', _MOCK_APIFLOW_CFF_HASH_MULTIPLE, True, _MOCK_APIFLOW_CFF_HASH_MULTIPLE_EXPECTED_MULTI),
      ('timeline_singleline', _MOCK_APIFLOW_TIMELINE, False, _MOCK_APIFLOW_TIMELINE_EXPECTED),
      ('timeline_multiline', _MOCK_APIFLOW_TIMELINE, True, _MOCK_APIFLOW_TIMELINE_EXPECTED),
      ('getfile_singleline', _MOCK_APIFLOW_GETFILE, False, _MOCK_APIFLOW_GETFILE_EXPECTED),
      ('getfile_multiline', _MOCK_APIFLOW_GETFILE, True, _MOCK_APIFLOW_GETFILE_EXPECTED),
      ('interrogate_singleline', _MOCK_APIFLOW_INTERROGATE, False, _MOCK_APIFLOW_INTERROGATE_EXPECTED),
      ('interrogate_multiline', _MOCK_APIFLOW_INTERROGATE, True, _MOCK_APIFLOW_INTERROGATE_EXPECTED),
  )
  def test_Parse(self, flow_handle: flow.Flow, multiline: bool, expected_output: list[str]):
    """Tests the Parse function in flow_args_parsers."""
    output = flow_args_parsers.Parse(flow_handle, multiline)
    self.assertEqual(output, expected_output)

if __name__ == '__main__':
  absltest.main()