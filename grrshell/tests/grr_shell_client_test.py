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
"""Unit tests for the Grr Shell client."""

# pylint: disable=wrong-import-order,ungrouped-imports
from concurrent import futures
import contextlib
import datetime
import io
import os
import sys
from unittest import mock
import unittest

from google.protobuf import text_format
from grr_api_client import api as grr_api
from grr_api_client import artifact
from grr_api_client import client
from grr_api_client import errors as grr_errors
from grr_api_client import flow
from grr_response_proto import artifact_pb2
from grr_response_proto import flows_pb2
from grr_response_proto import jobs_pb2
from grr_response_proto.api import client_pb2
from grr_response_proto.api import flow_pb2
from grrshell.lib import errors
from grrshell.lib import grr_shell_client
from absl import app
from absl import flags
from absl.testing import absltest
from absl.testing import parameterized


# `absltest.TestCase.create_tempdir()` requires that absl has parsed argv, but doing so when using unittest
# generates complaints that the following flags aren't defined. So, define them for absl.
flags.DEFINE_string('s', '', '')
flags.DEFINE_string('p', '', '')
app._run_init(sys.argv, app.parse_flags_with_usage)  # pylint: disable=protected-access



_TEST_GRR_URL = 'grr-url'
_TEST_GRR_USER = 'user'
_TEST_GRR_PASS = 'pass'
_TEST_CLIENT_FQDN = 'host.domain.com'
_TEST_CLIENT_GRR_ID = 'C.0000000000000001'
_TEST_CLIENT_GRR_ID = 'C.0000000000000001'

# pylint: disable=consider-using-with
# pylint: disable=line-too-long
_MOCK_DARWIN_CLIENT_PROTO_FILE = 'grrshell/tests/testdata/mock_client_darwin.textproto'
_MOCK_DARWIN_CLIENT = client.Client(data=text_format.Parse(
    open(_MOCK_DARWIN_CLIENT_PROTO_FILE, 'rb').read(),
    client_pb2.ApiClient()), context=True)

_MOCK_LINUX_CLIENT_PROTO_FILE = 'grrshell/tests/testdata/mock_client_linux.textproto'
_MOCK_LINUX_CLIENT = client.Client(data=text_format.Parse(
    open(_MOCK_LINUX_CLIENT_PROTO_FILE, 'rb').read(),
    client_pb2.ApiClient()), context=True)

_MOCK_WINDOWS_CLIENT_PROTO_FILE = 'grrshell/tests/testdata/mock_client_windows.textproto'
_MOCK_WINDOWS_CLIENT = client.Client(data=text_format.Parse(
    open(_MOCK_WINDOWS_CLIENT_PROTO_FILE, 'rb').read(),
    client_pb2.ApiClient()), context=True)

_MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_artifactcollector_allfile_running.textproto'
_MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING = flow.Flow(
    data=text_format.Parse(open(
        _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING_PROTO_FILE, 'rb').read(),
                           flow_pb2.ApiFlow()), context=mock.MagicMock())
_MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_TERMINATED_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_artifactcollector_allfile_terminated.textproto'
_MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_TERMINATED = flow.Flow(
    data=text_format.Parse(open(
        _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_TERMINATED_PROTO_FILE, 'rb').read(),
                           flow_pb2.ApiFlow()), context=mock.MagicMock())

_MOCK_APIFLOW_ARTEFACTCOLLECTOR_WINREGKEY_RUNNING_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_artifactcollector_windowsregkey_running.textproto'
_MOCK_APIFLOW_ARTEFACTCOLLECTOR_WINREGKEY_RUNNING = flow.Flow(
    data=text_format.Parse(open(
        _MOCK_APIFLOW_ARTEFACTCOLLECTOR_WINREGKEY_RUNNING_PROTO_FILE, 'rb').read(),
                           flow_pb2.ApiFlow()), context=mock.MagicMock())

_MOCK_APIFLOW_ARTEFACTCOLLECTOR_WMILOGICALDISKS_RUNNING_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_artifactcollector_wmilogicaldisks_running.textproto'
_MOCK_APIFLOW_ARTEFACTCOLLECTOR_WMILOGICALDISKS_RUNNING = flow.Flow(
    data=text_format.Parse(open(
        _MOCK_APIFLOW_ARTEFACTCOLLECTOR_WMILOGICALDISKS_RUNNING_PROTO_FILE, 'rb').read(),
                           flow_pb2.ApiFlow()), context=mock.MagicMock())

_MOCK_APIFLOW_CFF_HASH_RUNNING_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_clientfilefinder_hash_running.textproto'
_MOCK_APIFLOW_CFF_HASH_RUNNING = flow.Flow(data=text_format.Parse(
    open(_MOCK_APIFLOW_CFF_HASH_RUNNING_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiFlow()), context=mock.MagicMock())
_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_clientfilefinder_download_running.textproto'
_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING = flow.Flow(data=text_format.Parse(
    open(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiFlow()), context=mock.MagicMock())
_MOCK_APIFLOW_CFF_DOWNLOAD_TERMINATED_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_clientfilefinder_download_terminated.textproto'
_MOCK_APIFLOW_CFF_DOWNLOAD_TERMINATED = flow.Flow(data=text_format.Parse(
    open(_MOCK_APIFLOW_CFF_DOWNLOAD_TERMINATED_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiFlow()), context=mock.MagicMock())
_MOCK_APIFLOW_CFF_DOWNLOAD_ERROR_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_clientfilefinder_download_error.textproto'
_MOCK_APIFLOW_CFF_DOWNLOAD_ERROR = flow.Flow(data=text_format.Parse(
    open(_MOCK_APIFLOW_CFF_DOWNLOAD_ERROR_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiFlow()), context=mock.MagicMock())

_MOCK_CLIENTFILEFINDER_TERMINATED_DETAIL = """ClientFileFinder
\tCreator     creator
\tState       TERMINATED
\tStarted     1970-01-01T00:00:06Z
\tLast Active 1970-01-01T00:00:20Z
\tArgs:
\t            Action: DOWNLOAD
\t            Path: /remote/path"""

_MOCK_CLIENTFILEFINDER_ERROR_DETAIL = """ClientFileFinder
\tCreator     creator
\tState       ERROR
\tStarted     1970-01-01T00:00:25Z
\tLast Active 1970-01-01T00:00:30Z
\tArgs:
\t            Action: DOWNLOAD
\t            Path: /remote/path
\tError Details
\t\t"Test error\""""

_MOCK_TIMELINE_ERROR_DETAIL = """TimelineFlow
\tCreator     creator
\tState       ERROR
\tStarted     1970-01-01T00:00:16Z
\tLast Active 1970-01-01T00:00:32Z
\tArgs:
\t            root: 
\tError Details
\t\tThe timeline root directory not specified"""

_MOCK_TIMELINE_ERROR_STACKTRACE_DETAIL = """TimelineFlow
\tCreator     creator
\tState       ERROR
\tStarted     1970-01-01T00:00:17Z
\tLast Active 1970-01-01T00:00:33Z
\tArgs:
\t            root: /
\tError Details
\t\tStacktrace placeholder
\t\t  second line
\t\t    third line
\t\tfourth line"""

_MOCK_TIMELINE_ERROR_NOMESSAGE_DETAIL = """TimelineFlow
\tCreator     creator
\tState       ERROR
\tStarted     1970-01-01T00:00:18Z
\tLast Active 1970-01-01T00:00:34Z
\tArgs:
\t            root: /
\tError Details
\t\tMissing error message"""

_MOCK_APIFLOW_GETFILE_RUNNING_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_getfile_running.textproto'
_MOCK_APIFLOW_GETFILE_RUNNING = flow.Flow(data=text_format.Parse(
    open(_MOCK_APIFLOW_GETFILE_RUNNING_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiFlow()), context=mock.MagicMock())

_MOCK_APIFLOW_INTERROGATE_RUNNING_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_interrogate_running.textproto'
_MOCK_APIFLOW_INTERROGATE_RUNNING = flow.Flow(data=text_format.Parse(
    open(_MOCK_APIFLOW_INTERROGATE_RUNNING_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiFlow()), context=mock.MagicMock())

_MOCK_APIFLOW_TIMELINE_RUNNING_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_timeline_running.textproto'
_MOCK_APIFLOW_TIMELINE_RUNNING = flow.Flow(data=text_format.Parse(
    open(_MOCK_APIFLOW_TIMELINE_RUNNING_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiFlow()), context=mock.MagicMock())

_MOCK_APIFLOW_TIMELINE_ERROR_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_timeline_error.textproto'
_MOCK_APIFLOW_TIMELINE_ERROR = flow.Flow(data=text_format.Parse(
    open(_MOCK_APIFLOW_TIMELINE_ERROR_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiFlow()), context=mock.MagicMock())

_MOCK_APIFLOW_TIMELINE_ERROR_STACKTRACE_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_timeline_error_stacktrace.textproto'
_MOCK_APIFLOW_TIMELINE_ERROR_STACKTRACE = flow.Flow(data=text_format.Parse(
    open(_MOCK_APIFLOW_TIMELINE_ERROR_STACKTRACE_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiFlow()), context=mock.MagicMock())

_MOCK_APIFLOW_TIMELINE_ERROR_NOMESSAGE_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_timeline_error_nomessage.textproto'
_MOCK_APIFLOW_TIMELINE_ERROR_NOMESSAGE = flow.Flow(data=text_format.Parse(
    open(_MOCK_APIFLOW_TIMELINE_ERROR_NOMESSAGE_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiFlow()), context=mock.MagicMock())

_MOCK_APIFLOW_LISTFLOWS_PROTO_FILE = 'grrshell/tests/testdata/mock_apiflow_listflows.textproto'
_MOCK_APIFLOW_LISTFLOWS_FLOWS = text_format.Parse(
    open(_MOCK_APIFLOW_LISTFLOWS_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiListFlowsResult(),
)
_MOCK_APIFLOW_LISTFLOWS = [
    flow.Flow(data=item, context=mock.MagicMock())
    for item in _MOCK_APIFLOW_LISTFLOWS_FLOWS.items
]

_MOCK_HASH_LINUX_PROTO_FILE = 'grrshell/tests/testdata/mock_hash_linux.textproto'
_MOCK_HASH_LINUX_ENTRY = flow.FlowResult(data=text_format.Parse(
    open(_MOCK_HASH_LINUX_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiFlowResult()))
_EXPECTED_HASH_LINUX_RESULT = """/remote/file
    mode:           -rw-------
    inode:          2
    dev:            3
    st_nlink:       4
    st_uid:         5
    st_gid:         6
    st_size:        1024 (1.0 KiB)
    st_atime:       8 - 1970-01-01T00:00:08Z
    st_mtime:       9 - 1970-01-01T00:00:09Z
    st_ctime:       10 - 1970-01-01T00:00:10Z
    st_blocks:      11
    st_blksize:     12
    st_rdev:        13
    st_flags_osx:   14
    st_flags_linux: 15
    md5:            6d6435
    sha1:           73686131
    sha256:         736861323536"""

_MOCK_HASH_WINDOWS_PROTO_FILE = 'grrshell/tests/testdata/mock_hash_windows.textproto'
_MOCK_HASH_WINDOWS_ENTRY = flow.FlowResult(data=text_format.Parse(
    open(_MOCK_HASH_WINDOWS_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiFlowResult()))
_EXPECTED_HASH_WINDOWS_RESULT = """C:/Users/username/Downloads/Firefox Installer.exe
    mode:           -rw-------
    inode:          0
    dev:            0
    st_nlink:       1
    st_uid:         2
    st_gid:         3
    st_size:        398840 (389.5 KiB)
    st_atime:       8 - 1970-01-01T00:00:08Z
    st_mtime:       9 - 1970-01-01T00:00:09Z
    st_ctime:       10 - 1970-01-01T00:00:10Z
    st_blocks:      0
    st_blksize:     0
    st_rdev:        0
    st_flags_osx:   0
    st_flags_linux: 0
    md5:            6d6435
    sha1:           73686131
    sha256:         736861323536"""

_MOCK_HASH_WINDOWS_WITH_ADS_PROTO_FILE = 'grrshell/tests/testdata/mock_hash_windows_ads.textproto'
_MOCK_HASH_WINDOWS_WITH_ADS_ENTRY = flow.FlowResult(data=text_format.Parse(
    open(_MOCK_HASH_WINDOWS_WITH_ADS_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiFlowResult()))
_EXPECTED_HASH_WINDOWS_WITH_ADS_RESULT = """C:/Users/username/Downloads/Firefox Installer.exe
    mode:           -rw-------
    inode:          0
    dev:            0
    st_nlink:       1
    st_uid:         2
    st_gid:         3
    st_size:        398840 (389.5 KiB)
    st_atime:       8 - 1970-01-01T00:00:08Z
    st_mtime:       9 - 1970-01-01T00:00:09Z
    st_ctime:       10 - 1970-01-01T00:00:10Z
    st_blocks:      0
    st_blksize:     0
    st_rdev:        0
    st_flags_osx:   0
    st_flags_linux: 0
    md5:            6d6435
    sha1:           73686131
    sha256:         736861323536
    Zone.Identifier:
        [ZoneTransfer]
        ZoneId=3
        ReferrerUrl=https://www.mozilla.org/
        HostUrl=https://download-installer.cdn.mozilla.net/pub/firefox/releases/114.0.2/win32/en-US/Firefox%20Installer.exe"""

_EXPECTED_ZONE_IDENTIFIER = """    Zone.Identifier:
        [ZoneTransfer]
        ZoneId=3
        ReferrerUrl=https://www.mozilla.org/
        HostUrl=https://download-installer.cdn.mozilla.net/pub/firefox/releases/114.0.2/win32/en-US/Firefox%20Installer.exe"""

_MOCK_WINDOWS_ARTEFACT_REGVALUE_PROTO_FILE = 'grrshell/tests/testdata/mock_windows_registry_result.textproto'
_MOCK_WINDOWS_ARTEFACT_REGVALUE = flow.FlowResult(data=text_format.Parse(
    open(_MOCK_WINDOWS_ARTEFACT_REGVALUE_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiFlowResult()))

_EXPECTED_WINDOWS_REGVALUE_RESULT = """    /HKEY_LOCAL_MACHINE/SOFTWARE/Microsoft/Windows NT/CurrentVersion/InstallDate (REG_DWORD)
        integer: 12345"""

_MOCK_WINDOWS_ARTEFACT_VOLUME_C_PROTO_FILE = 'grrshell/tests/testdata/mock_volume_windows_c.textproto'
_MOCK_WINDOWS_ARTEFACT_VOLUME_C = flow.FlowResult(data=text_format.Parse(
    open(_MOCK_WINDOWS_ARTEFACT_VOLUME_C_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiFlowResult()))

_MOCK_WINDOWS_ARTEFACT_VOLUME_D_PROTO_FILE = 'grrshell/tests/testdata/mock_volume_windows_d.textproto'
_MOCK_WINDOWS_ARTEFACT_VOLUME_D = flow.FlowResult(data=text_format.Parse(
    open(_MOCK_WINDOWS_ARTEFACT_VOLUME_D_PROTO_FILE, 'rb').read(),
    flow_pb2.ApiFlowResult()))

_EXPECTED_WINDOWS_VOLUMES_RESULT = """Device ID - C:
    Name:                 C:
    Volume Name:          c_drive
    Volume Serial Number: 01234567
    Description:          Local Fixed Disk
    Drive Type:           DRIVE_FIXED
    File System:          NTFS
    Size:                 2047370850304 (1.9 TiB)
    Free Space:           1654566748160 (1.5 TiB) - 80.81%
Device ID - D:
    Name:                 D:
    Volume Name:          THUMBDRIVE
    Volume Serial Number: 98765432
    Description:          Removable Disk
    Drive Type:           DRIVE_REMOVABLE
    File System:          FAT32
    Size:                 8002781184 (7.5 GiB)
    Free Space:           8002740224 (7.5 GiB) - 100.0%"""

_MOCK_ZIP_DARWIN_CLIENTFILEFINDER_FILE = 'grrshell/tests/testdata/file_collect_darwin.zip'
_MOCK_ZIP_DARWIN_CLIENTFILEFINDER_DATA = open(
    _MOCK_ZIP_DARWIN_CLIENTFILEFINDER_FILE, 'rb').read()
_MOCK_ZIP_LINUX_CLIENTFILEFINDER_FILE = 'grrshell/tests/testdata/file_collect_linux.zip'
_MOCK_ZIP_LINUX_CLIENTFILEFINDER_DATA = open(
    _MOCK_ZIP_LINUX_CLIENTFILEFINDER_FILE, 'rb').read()
_MOCK_ZIP_WINDOWS_CLIENTFILEFINDER_FILE = 'grrshell/tests/testdata/file_collect_windows.zip'
_MOCK_ZIP_WINDOWS_CLIENTFILEFINDER_DATA = open(
    _MOCK_ZIP_WINDOWS_CLIENTFILEFINDER_FILE, 'rb').read()
_MOCK_ZIP_WINDOWS_CLIENTFILEFINDER_FAT32_FILE = 'grrshell/tests/testdata/file_collect_windows_fat32.zip'
_MOCK_ZIP_WINDOWS_CLIENTFILEFINDER_FAT32_DATA = open(
    _MOCK_ZIP_WINDOWS_CLIENTFILEFINDER_FAT32_FILE, 'rb').read()
_MOCK_ZIP_DARWIN_ARTIFACTCOLLECTORFLOW_FILE = 'grrshell/tests/testdata/artifact_collect_darwin.zip'
_MOCK_ZIP_DARWIN_ARTIFACTCOLLECTORFLOW_DATA = open(
    _MOCK_ZIP_DARWIN_ARTIFACTCOLLECTORFLOW_FILE, 'rb').read()
_MOCK_ZIP_LINUX_ARTIFACTCOLLECTORFLOW_FILE = 'grrshell/tests/testdata/artifact_collect_linux.zip'
_MOCK_ZIP_LINUX_ARTIFACTCOLLECTORFLOW_DATA = open(
    _MOCK_ZIP_LINUX_ARTIFACTCOLLECTORFLOW_FILE, 'rb').read()
_MOCK_ZIP_WINDOWS_ARTIFACTCOLLECTORFLOW_FILE = 'grrshell/tests/testdata/artifact_collect_windows.zip'
_MOCK_ZIP_WINDOWS_ARTIFACTCOLLECTORFLOW_DATA = open(
    _MOCK_ZIP_WINDOWS_ARTIFACTCOLLECTORFLOW_FILE, 'rb').read()
_MOCK_ZIP_WINDOWS_GETFILE_ADS_FILE = 'grrshell/tests/testdata/getfile_ads.zip'
_MOCK_ZIP_WINDOWS_GETFILE_ADS_DATA = open(
    _MOCK_ZIP_WINDOWS_GETFILE_ADS_FILE, 'rb').read()
_MOCK_ZIP_WINDOWS_GETFILE_ADS_EMPTY_FILE = 'grrshell/tests/testdata/getfile_ads_empty.zip'
_MOCK_ZIP_WINDOWS_GETFILE_ADS_EMPTY_DATA = open(
    _MOCK_ZIP_WINDOWS_GETFILE_ADS_EMPTY_FILE, 'rb').read()

_SAMPLE_TIMELINE_LINUX = 'grrshell/tests/testdata/sample_timeline_linux'
_SAMPLE_TIMELINE_WINDOWS = 'grrshell/tests/testdata/sample_timeline_windows'

_MAX_FILE_SIZE_1GB = 1024 * 1024 * 1024


# pylint: enable=line-too-long
def _BuildMockArtifactDescriptors() -> list[artifact.Artifact]:
  """Builds the mock artifact descriptors list, used by ListArtifacts."""
  artifactdescriptor_proto_files = (
      # go/keep-sorted start
      'grrshell/tests/testdata/mock_artifactdescriptor_all_artifactgroup.textproto',
      'grrshell/tests/testdata/mock_artifactdescriptor_all_file.textproto',
      'grrshell/tests/testdata/mock_artifactdescriptor_darwin_artifactfiles.textproto',
      'grrshell/tests/testdata/mock_artifactdescriptor_darwin_grraction.textproto',
      'grrshell/tests/testdata/mock_artifactdescriptor_linux_command.textproto',
      'grrshell/tests/testdata/mock_artifactdescriptor_linux_path.textproto',
      'grrshell/tests/testdata/mock_artifactdescriptor_mixed.textproto',
      'grrshell/tests/testdata/mock_artifactdescriptor_windows_regkey.textproto',
      'grrshell/tests/testdata/mock_artifactdescriptor_windows_regvalue.textproto'
      # go/keep-sorted end
  )
  to_return: list[artifact.Artifact] = []
  for proto_file in artifactdescriptor_proto_files:
    to_return.append(artifact.Artifact(data=text_format.Parse(
        open(proto_file, 'rb').read(),
        artifact_pb2.ArtifactDescriptor()), context=mock.MagicMock()))
  return to_return


def _MockGetFromFlowList(self) -> flow.Flow:
  """Based on the flows listed in _MOCK_APIFLOW_LISTFLOWS, return the one matching the Flow ID."""
  # TODO(ramoj): Use this method for all mocked calls to Flow.Get()
  for item in _MOCK_APIFLOW_LISTFLOWS_FLOWS.items:
    if self.data.flow_id == item.flow_id:
      return flow.Flow(data=item, context=mock.MagicMock())
  raise RuntimeError('Failure in mocking of Flow.Get() - Flow not found.')


# pylint: disable=protected-access
# pylint: enable=line-too-long


class GrrShellClientLinuxTest(parameterized.TestCase):
  """Unit tests for the Grr Shell client."""

  mock_grr_api: mock.Mock
  client: grr_shell_client.GRRShellClient

  @mock.patch.object(grr_api, 'InitHttp', autospec=True)
  def setUp(self, mock_InitHttp):  # pylint: disable=arguments-differ
    """Set up tests."""
    super().setUp()
    self.mock_grr_api = mock.Mock()
    mock_InitHttp.return_value = self.mock_grr_api
    self.mock_grr_api.Client.return_value.client_id = _TEST_CLIENT_GRR_ID
    self.mock_grr_api.Client.return_value.Get.return_value = _MOCK_LINUX_CLIENT
    self.mock_grr_api.SearchClients.return_value = [_MOCK_LINUX_CLIENT]
    self.mock_grr_api.ListArtifacts.return_value = (
        _BuildMockArtifactDescriptors())

    self.client = grr_shell_client.GRRShellClient(
        _TEST_GRR_URL, _TEST_GRR_USER, _TEST_GRR_PASS, _TEST_CLIENT_FQDN, _MAX_FILE_SIZE_1GB)
    self.client._pathspec_mapper['/'] = jobs_pb2.PathSpec.OS

  def test_Init(self):
    """Tests initialisation."""
    self.assertIsNotNone(self.client)

  def test_GetOS(self):
    """Tests the GetOS method."""
    self.assertEqual(self.client.GetOS(), 'Linux')

  @mock.patch.object(grr_api, 'InitHttp', autospec=True)
  def test_NoApproval(self, mock_InitHttp):  # pylint: disable=invalid-name
    """Tests no approval for the client is correctly handled."""
    mock_grr_api = mock.Mock()
    mock_InitHttp.return_value = mock_grr_api
    mock_grr_api.Client.return_value.client_id = _TEST_CLIENT_GRR_ID
    mock_grr_api.SearchClients.return_value = [_MOCK_LINUX_CLIENT]
    mock_grr_api.Client.return_value.VerifyAccess.side_effect = (
        grr_errors.AccessForbiddenError('No approval'))

    shell_client = grr_shell_client.GRRShellClient(
        _TEST_GRR_URL, _TEST_GRR_USER, _TEST_GRR_PASS, _TEST_CLIENT_FQDN, _MAX_FILE_SIZE_1GB)
    result = shell_client.CheckAccess()
    self.assertFalse(result)

  def test_CheckAccess(self):
    """Tests the CheckAccess method."""
    result = self.client.CheckAccess()
    self.assertTrue(result)

  @parameterized.named_parameters(
      ('no_duration', None, 0),
      ('with_duration', '25', 25),
  )
  @unittest.skip('Expiration duration not available in current public GRR API library version')
  def test_RequestAccessSuccess(self,
                                duration_input: str,
                                expected_duration: int):
    """Tests the RequestAccess method."""
    with (
        mock.patch('builtins.input') as mock_input,
        mock.patch.object(
            self.client._grr_client, 'CreateApproval') as mock_create_approval):
      mock_input.side_effect = ['reason', 'approver1,approver2', duration_input]
      mock_create_approval.return_value.data.requestor = 'requestor'
      mock_create_approval.return_value.data.id = 'request_id'

      with io.StringIO() as buf, contextlib.redirect_stdout(buf):
        result = self.client.RequestAccess()

        self.assertIn(
            'Approval URL: grr-url/v2/clients/'
            'C.0000000000000001/users/requestor/approvals/request_id',
            buf.getvalue())

      mock_create_approval.assert_called_once_with(
          reason='reason',
          notified_users=['approver1', 'approver2'],
          expiration_duration_days=expected_duration)
      mock_create_approval.return_value.WaitUntilValid.assert_called_once()
      self.assertTrue(result)

  @parameterized.named_parameters(
      ('negative_duration', '-5', 'Invalid duration: -5'),
      ('non_int_duration', 'asdf', 'Invalid duration: asdf'),
  )
  @unittest.skip('Expiration duration not available in current public GRR API library version')
  def test_RequestAccessFailure(self,
                                duration_input: str,
                                expected_message: str):
    """Tests the RequestAccess method failure methods."""
    with (
        mock.patch('builtins.input') as mock_input,
        mock.patch.object(
            self.client._grr_client, 'CreateApproval') as mock_create_approval):
      mock_input.side_effect = ['reason', 'approver1,approver2', duration_input]

      with io.StringIO() as buf, contextlib.redirect_stdout(buf):
        result = self.client.RequestAccess()

        self.assertIn(expected_message, buf.getvalue())

      mock_create_approval.assert_not_called()
      self.assertFalse(result)

  def test_Cleanup(self):
    """Tests destructor."""
    with mock.patch.object(self.client._collection_threads,
                           'shutdown') as mock_shutdown:
      self.client.WaitForBackgroundCompletions()
      mock_shutdown.assert_called_once()

  @mock.patch.object(grr_api, 'InitHttp', autospec=True)
  def test_InvalidClient(self, mock_InitHttp):  # pylint: disable=invalid-name
    """Tests an invalid client correctly fails."""
    mock_InitHttp.return_value = self.mock_grr_api
    self.mock_grr_api.SearchClients.return_value = []

    with self.assertRaisesRegex(
        errors.ClientNotFoundError,
        f'0 potential clients found with search {_TEST_CLIENT_FQDN}'):
      grr_shell_client.GRRShellClient(
          _TEST_GRR_URL, _TEST_GRR_USER, _TEST_GRR_PASS, _TEST_CLIENT_FQDN, _MAX_FILE_SIZE_1GB)

  def test_GetClientID(self):
    """Tests the GetClientID method."""
    result = self.client.GetClientID()
    self.assertEqual(result, _TEST_CLIENT_GRR_ID)

  def test_GetLastSeenTime(self):
    """Tests the GetLastSeenTime method."""
    with mock.patch.object(
        self.client._grr_client, 'Get', return_value=_MOCK_LINUX_CLIENT):
      self.client.StartBackgroundMonitors()
      result = self.client.GetLastSeenTime()
      self.assertEqual(result,
                       datetime.datetime(2023, 5, 24, 1, 24, 23, 783055,
                                         tzinfo=datetime.timezone.utc))

  @mock.patch('datetime.datetime', wraps=datetime.datetime)
  def test_GetLastTimelineCorrect(self, mock_dt):
    """Tests the GetLastTimeline method when there is a recent one."""
    with (mock.patch.object(self.client._grr_client,
                            'ListFlows',
                            return_value=_MOCK_APIFLOW_LISTFLOWS),
          mock.patch.object(flow.Flow, 'Get', new=_MockGetFromFlowList)):
      # "Now" is half of the staleness threshold past the epoch. All the flows
      # returned are at 1 second past the epoch, so they are not stale.
      mock_dt.now.return_value = datetime.datetime.fromtimestamp(
          grr_shell_client._STALE_TIMELINE_THRESHOLD.total_seconds() / 2,
          tz=datetime.timezone.utc)

      result = self.client.GetLastTimeline()

      self.assertStartsWith(result, 'CORRECT')

  @mock.patch('datetime.datetime', wraps=datetime.datetime)
  def test_GetLastTimelineNotFound(self, mock_dt):
    """Tests the GetLastTimeline method when there is no recent one."""
    with (mock.patch.object(self.client._grr_client,
                            'ListFlows',
                            return_value=_MOCK_APIFLOW_LISTFLOWS),
          mock.patch.object(flow.Flow, 'Get', new=_MockGetFromFlowList)):
      # "Now" is twice the staleness threshold past the epoch. All the flows
      # returned are at 1 second past the epoch, so they are stale.
      mock_dt.now.return_value = datetime.datetime.fromtimestamp(
          grr_shell_client._STALE_TIMELINE_THRESHOLD.total_seconds() * 2,
          tz=datetime.timezone.utc)

      result = self.client.GetLastTimeline()

      self.assertIsNone(result)

  @mock.patch('datetime.datetime', wraps=datetime.datetime)
  def test_GetLastTimelineOldAndNew(self, mock_dt):
    """Tests the GetLastTimeline method when there is one old and one new one."""
    with (mock.patch.object(self.client._grr_client,
                            'ListFlows',
                            return_value=_MOCK_APIFLOW_LISTFLOWS),
          mock.patch.object(flow.Flow, 'Get', new=_MockGetFromFlowList)):
      # "Now" is half of the staleness threshold past the epoch. All the flows
      # returned are at 1 second past the epoch, so they are not stale.
      mock_dt.now.return_value = datetime.datetime.fromtimestamp(
          grr_shell_client._STALE_TIMELINE_THRESHOLD.total_seconds() / 2,
          tz=datetime.timezone.utc)

      result = self.client.GetLastTimeline()

      self.assertEqual(result, 'CORRECT_LIN_2_SECOND')

  def test_CollectTimelineNew(self):
    """Tests the CollectTimeline method with no existing timeline specified."""
    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow,
          mock.patch('io.BytesIO') as mock_bytesio):
      mock_result_1 = mock.Mock()
      mock_result_1.timestamp = 1
      mock_result_2 = mock.Mock()
      mock_result_2.timestamp = 2
      mock_create_flow.return_value.ListResults.return_value = [mock_result_1]
      mock_create_flow.return_value.args.root = b'/'
      mock_bytesio.getvalue.return_value = open(
          _SAMPLE_TIMELINE_LINUX, 'rb').read()

      self.client.CollectTimeline()

      mock_create_flow_args.assert_called_once_with('TimelineFlow')
      mock_create_flow.assert_called_once_with(
          name='TimelineFlow', args=mock_create_flow_args.return_value)
      mock_create_flow.return_value.WaitUntilDone.assert_called_once()
      mock_create_flow.return_value.GetCollectedTimelineBody.assert_called_once()
      self.assertEqual(self.client.last_timeline_time, 1)
      self.assertDictEqual(self.client._pathspec_mapper._path_ps_map,
                           {'/': jobs_pb2.PathSpec.OS})

  def test_CollectTimelineExisting(self):
    """Tests the CollectTimeline method with a specified existing timeline."""
    with (mock.patch.object(self.client._grr_client, 'Flow') as mock_flow,
          mock.patch('io.BytesIO') as mock_bytesio):
      mock_flow.return_value.Get.return_value.ListResults.return_value = []
      mock_flow.return_value.Get.return_value.args.root = b'/'
      mock_bytesio.getvalue.return_value = open(
          _SAMPLE_TIMELINE_LINUX, 'rb').read()

      self.client.CollectTimeline(existing_timeline='ABCDE12345')

      mock_flow.assert_called_once_with('ABCDE12345')
      mock_flow.return_value.Get.assert_called_once()
      mock_flow.return_value.Get.return_value.WaitUntilDone.assert_called_once()
      mock_flow.return_value.Get.return_value.GetCollectedTimelineBody.assert_called_once()
      self.assertDictEqual(self.client._pathspec_mapper._path_ps_map,
                           {'/': jobs_pb2.PathSpec.OS})

  def test_CollectTimelinePath(self):
    """Tests the CollectTimeline method with a specified path."""
    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs',
                            return_value=mock.Mock()) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow',
                            return_value=mock.Mock()) as mock_create_flow,
          mock.patch('io.BytesIO') as mock_bytesio):
      mock_create_flow.return_value.ListResults.return_value = []
      mock_create_flow.return_value.args.root = b'/'
      mock_bytesio.getvalue.return_value = open(
          _SAMPLE_TIMELINE_LINUX, 'rb').read()

      self.client.CollectTimeline(path='/home/testuser/')

      mock_create_flow_args.assert_called_once_with('TimelineFlow')
      self.assertEqual(
          mock_create_flow_args.return_value.root, b'/home/testuser/'
      )
      mock_create_flow.assert_called_once_with(
          name='TimelineFlow', args=mock_create_flow_args.return_value)
      mock_create_flow.return_value.WaitUntilDone.assert_called_once()
      mock_create_flow.return_value.GetCollectedTimelineBody.assert_called_once()
      self.assertDictEqual(self.client._pathspec_mapper._path_ps_map,
                           {'/': jobs_pb2.PathSpec.OS})

  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  def test_FileInfo(self, mock_list_results, mock_wait_until_done):
    """Tests the FileInfo method."""
    mock_list_results.return_value = [_MOCK_HASH_LINUX_ENTRY]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow):
      mock_create_flow.return_value = _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING

      result = self.client.FileInfo('/remote/path')

      mock_create_flow_args.assert_called_once_with('ClientFileFinder')
      self.assertEqual(
          mock_create_flow_args.return_value.action.hash.max_size,
          _MAX_FILE_SIZE_1GB)
      mock_create_flow_args.return_value.paths.append.assert_called_once_with(
          '/remote/path')
      self.assertEqual(mock_create_flow_args.return_value.action.action_type,
                       flows_pb2.FileFinderAction.HASH)
      mock_create_flow.assert_called_once_with(
          name='ClientFileFinder', args=mock_create_flow_args.return_value)
      mock_wait_until_done.assert_called_once()

      self.assertEqual(result, _EXPECTED_HASH_LINUX_RESULT)

  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'GetFilesArchive')
  def test_CollectFiles(self,
                        mock_get_files_archive,
                        mock_list_results,
                        mock_wait_until_done,
                        mock_get):
    """Tests the CollectFile method."""
    mock_get.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_TERMINATED]
    mock_list_results.return_value = [_MOCK_HASH_LINUX_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_LINUX_CLIENTFILEFINDER_DATA]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow):
      mock_create_flow.return_value = _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING

      local_path = os.path.join(self.create_tempdir(), 'local_path')
      self.client.CollectFiles('/remote/path', local_path)

      mock_create_flow_args.assert_called_once_with('ClientFileFinder')
      self.assertEqual(
          mock_create_flow_args.return_value.action.download.max_size,
          _MAX_FILE_SIZE_1GB)
      self.assertEqual(mock_create_flow_args.return_value.pathtype,
                       jobs_pb2.PathSpec.OS)
      mock_create_flow_args.return_value.paths.append.assert_called_once_with(
          '/remote/path')
      mock_create_flow.assert_called_once_with(
          name='ClientFileFinder', args=mock_create_flow_args.return_value)
      mock_wait_until_done.assert_called_once()

      self.assertTrue(os.path.exists(  # sample zip contents
          os.path.join(local_path, 'home', 'ramoj', 'tmp', 'derp')))

  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'WaitUntilDone')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'ListResults')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'GetFilesArchive')
  def test_ScheduleAndDownloadArtefact(self,
                                       mock_get_files_archive,
                                       mock_list_results,
                                       mock_wait_until_done,
                                       mock_get):
    """Tests the ScheduleAndDownloadArtefact method."""
    mock_get.side_effect = [_MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_TERMINATED]
    mock_list_results.return_value = [_MOCK_HASH_LINUX_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_LINUX_ARTIFACTCOLLECTORFLOW_DATA]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow):
      mock_create_flow.return_value = (
          _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING)

      local_path = os.path.join(self.create_tempdir(), 'local_path')
      self.client.ScheduleAndDownloadArtefact('artifact_name', local_path)

      mock_create_flow_args.assert_called_once_with('ArtifactCollectorFlow')
      self.assertEqual(
          mock_create_flow_args.return_value.max_file_size,
          _MAX_FILE_SIZE_1GB)
      self.assertFalse(
          mock_create_flow_args.return_value.use_raw_filesystem_access)
      mock_create_flow_args.return_value.artifact_list.append.assert_called_once_with(
          'artifact_name')
      mock_create_flow.assert_called_once_with(
          name='ArtifactCollectorFlow', args=mock_create_flow_args.return_value)
      mock_wait_until_done.assert_called_once()

      self.assertTrue(os.path.exists(  # sample zip contents
          os.path.join(local_path, 'home', 'ramoj', 'tmp', 'derp')))

  @mock.patch.object(futures.Future, 'exception', return_value=False)
  @mock.patch.object(futures.Future, 'running')
  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'GetFilesArchive')
  def test_CollectFilesInBackground(self,
                                    mock_get_files_archive,
                                    mock_list_results,
                                    mock_wait_until_done,
                                    mock_get,
                                    mock_running,
                                    _):
    """Tests background collection of remote files."""
    mock_get.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING,
                            _MOCK_APIFLOW_CFF_DOWNLOAD_TERMINATED]
    mock_running.side_effect = [True, True, True, True, False, False]
    mock_list_results.return_value = [_MOCK_HASH_LINUX_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_LINUX_CLIENTFILEFINDER_DATA]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow):
      mock_create_flow.return_value = _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING
      local_path = os.path.join(self.create_tempdir(), 'local_path')

      running, total = self.client.GetRunningFlowCount()
      self.assertEqual(running, 0)
      self.assertEqual(total, 0)
      actual_states = self.client.GetBackgroundFlowsState()
      self.assertEqual(actual_states, 'No launched flows')

      self.client.CollectFilesInBackground('/remote/path', local_path)

      running, total = self.client.GetRunningFlowCount()
      self.assertEqual(running, 1)
      self.assertEqual(total, 1)
      actual_states = self.client.GetBackgroundFlowsState()
      self.assertEqual(
          actual_states,
          '\tCLIENTFILEFINDERRUNNINGFLOWID ClientFileFinder DOWNLOAD '
          '/remote/path RUNNING')

      running, total = self.client.GetRunningFlowCount()
      self.assertEqual(running, 1)
      self.assertEqual(total, 1)
      actual_states = self.client.GetBackgroundFlowsState()
      self.assertEqual(
          actual_states,
          '\tCLIENTFILEFINDERTERMINATEDFLOWID ClientFileFinder DOWNLOAD '
          '/remote/path DOWNLOADING')

      running, total = self.client.GetRunningFlowCount()
      self.assertEqual(running, 0)
      self.assertEqual(total, 1)
      actual_states = self.client.GetBackgroundFlowsState()
      self.assertEqual(
          actual_states,
          '\tCLIENTFILEFINDERTERMINATEDFLOWID ClientFileFinder DOWNLOAD '
          '/remote/path COMPLETE')

      mock_create_flow_args.assert_called_once_with('ClientFileFinder')
      mock_create_flow.assert_called_once_with(
          name='ClientFileFinder', args=mock_create_flow_args.return_value)
      mock_wait_until_done.assert_called_once()

      self.client._collection_threads.shutdown()

      self.assertTrue(os.path.exists(
          os.path.join(local_path, 'home', 'ramoj', 'tmp', 'derp')))
      self.assertFalse(os.path.exists(  # Temp dirs are cleaned up
          os.path.join(local_path,
                       ('C.0000000000000001_flow_ClientFileFinder_'
                        'CLIENTFILEFINDERRUNNINGFLOWID'))))
      self.assertIn('CLIENTFILEFINDERRUNNINGFLOWID',
                    self.client._flow_monitor._flows)
      self.assertEqual(
          self.client._flow_monitor._flows['CLIENTFILEFINDERRUNNINGFLOWID'],
          _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING)

  @mock.patch.object(futures.Future, 'exception', return_value=False)
  @mock.patch.object(futures.Future, 'running')
  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'WaitUntilDone')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'ListResults')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'GetFilesArchive')
  def test_CollectArtifactInBackground(self,
                                       mock_get_files_archive,
                                       mock_list_results,
                                       mock_wait_until_done,
                                       mock_get,
                                       mock_running,
                                       _):
    """Tests background collection of artifacts."""
    mock_get.side_effect = [_MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING,
                            _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_TERMINATED]
    mock_running.side_effect = [True, True, True, True, False, False]
    mock_list_results.return_value = [_MOCK_HASH_LINUX_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_LINUX_ARTIFACTCOLLECTORFLOW_DATA]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow):
      mock_create_flow.return_value = (
          _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING)
      local_path = os.path.join(self.create_tempdir(), 'local_path')

      running, total = self.client.GetRunningFlowCount()
      self.assertEqual(running, 0)
      self.assertEqual(total, 0)
      actual_states = self.client.GetBackgroundFlowsState()
      self.assertEqual(actual_states, 'No launched flows')

      self.client.CollectArtefact('AllOS_File', local_path)

      running, total = self.client.GetRunningFlowCount()
      self.assertEqual(running, 1)
      self.assertEqual(total, 1)
      actual_states = self.client.GetBackgroundFlowsState()
      self.assertEqual(
          actual_states,
          '\tARTIFACTCOLLECTORFLOWRUNNINGFLOWID ArtifactCollectorFlow '
          'AllOS_File RUNNING')

      running, total = self.client.GetRunningFlowCount()
      self.assertEqual(running, 1)
      self.assertEqual(total, 1)
      actual_states = self.client.GetBackgroundFlowsState()
      self.assertEqual(
          actual_states,
          '\tARTIFACTCOLLECTORFLOWTERMINATEDFLOWID ArtifactCollectorFlow '
          'AllOS_File DOWNLOADING')

      running, total = self.client.GetRunningFlowCount()
      self.assertEqual(running, 0)
      self.assertEqual(total, 1)
      actual_states = self.client.GetBackgroundFlowsState()
      self.assertEqual(
          actual_states,
          '\tARTIFACTCOLLECTORFLOWTERMINATEDFLOWID ArtifactCollectorFlow '
          'AllOS_File COMPLETE')

      mock_create_flow_args.assert_called_once_with('ArtifactCollectorFlow')
      mock_create_flow.assert_called_once_with(
          name='ArtifactCollectorFlow', args=mock_create_flow_args.return_value)
      mock_wait_until_done.assert_called_once()

      self.client._collection_threads.shutdown()

      self.assertTrue(os.path.exists(
          os.path.join(local_path, 'home', 'ramoj', 'tmp', 'derp')))
      self.assertFalse(os.path.exists(  # Temp dirs are cleaned up
          os.path.join(local_path,
                       ('C.0000000000000001_flow_ArtifactCollectorFlow_'
                        'ARTIFACTCOLLECTORFLOWRUNNINGFLOWID'))))
      self.assertIn('ARTIFACTCOLLECTORFLOWRUNNINGFLOWID',
                    self.client._flow_monitor._flows)
      self.assertEqual(
          self.client._flow_monitor._flows[
              'ARTIFACTCOLLECTORFLOWRUNNINGFLOWID'],
          _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING)

  def test_CollectFilesBadDirectory(self):
    """Tests collecting files fails when an invalid local path is used."""
    path = self.create_tempfile().full_path  # pylint: disable=no-member

    with self.assertRaisesRegex(FileExistsError, path):
      self.client.CollectFiles('/remote/path', path)

  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'GetFilesArchive')
  def test_SetMaxFileSize(self,
                          mock_get_files_archive,
                          mock_list_results,
                          _,
                          mock_get):
    """Tests the SetMaxFileSize method."""
    mock_get.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_TERMINATED]
    mock_list_results.return_value = [_MOCK_HASH_LINUX_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_LINUX_CLIENTFILEFINDER_DATA]

    self.client.SetMaxFilesize(1024)

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow):
      mock_create_flow.return_value = _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING

      local_path = os.path.join(self.create_tempdir(), 'local_path')
      self.client.CollectFiles('/remote/path', local_path)

      self.assertIn(
          'download',
          mock_create_flow_args.return_value.action.__dict__['_mock_children'])
      self.assertEqual(
          mock_create_flow_args.return_value.action.download.max_size, 1024)

  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'GetFilesArchive')
  def test_DefaultMaxFileSize(self,
                              mock_get_files_archive,
                              mock_list_results,
                              _,
                              mock_get):
    """Tests the SetMaxFileSize method with a default value."""
    mock_get.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_TERMINATED]
    mock_list_results.return_value = [_MOCK_HASH_LINUX_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_LINUX_CLIENTFILEFINDER_DATA]

    self.client.SetMaxFilesize(0)

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            )as mock_create_flow):
      mock_create_flow.return_value = _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING

      local_path = os.path.join(self.create_tempdir(), 'local_path')
      self.client.CollectFiles('/remote/path', local_path)

      self.assertNotIn(
          'download',
          mock_create_flow_args.return_value.action.__dict__['_mock_children'])

  def test_GetSupportedArtifacts(self):
    """Tests the GetSupportedArtifacts method."""
    self.mock_grr_api.ListArtifacts.return_value = (
        _BuildMockArtifactDescriptors())

    self.client._RetrieveSupportedArtefacts()
    self.assertCountEqual(
        self.client.GetSupportedArtefactNames(),
        ['AllOS_File', 'AllOS_ArtifactGroup', 'Linux_Command', 'Linux_Path',
         'Mixed'])

  @mock.patch.object(futures.Future, 'exception', return_value=False)
  @mock.patch.object(futures.Future, 'running')
  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'GetFilesArchive')
  def test_ExitWithRunningFlow(self,
                               mock_get_files_archive,
                               mock_list_results,
                               mock_wait_until_done,
                               mock_get,
                               mock_running,
                               _):
    """Tests shell client destructor with background flows still running."""
    mock_get.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING,
                            _MOCK_APIFLOW_CFF_DOWNLOAD_TERMINATED]
    mock_running.side_effect = [True, True, True]
    mock_list_results.return_value = [_MOCK_HASH_LINUX_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_LINUX_CLIENTFILEFINDER_DATA]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'),
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow):
      mock_create_flow.return_value = _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING
      local_path = os.path.join(self.create_tempdir(), 'local_path')

      self.client.CollectFilesInBackground('/remote/path', local_path)

      with io.StringIO() as buf, contextlib.redirect_stdout(buf):
        self.client.WaitForBackgroundCompletions()

        self.assertIn(
            'Waiting for collection threads CLIENTFILEFINDERRUNNINGFLOWID to '
            'finish (<CTRL+C> to force exit)\n',
            buf.getvalue())

      mock_wait_until_done.assert_called_once()
      self.assertTrue(os.path.exists(
          os.path.join(local_path, 'home', 'ramoj', 'tmp', 'derp')))

  @mock.patch.object(futures.Future, 'exception')
  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'GetFilesArchive')
  def test_ExitWithFlowError(self,
                             mock_get_files_archive,
                             mock_list_results,
                             _,
                             mock_get,
                             mock_exception):
    """Tests flow errors are presented on exit."""
    mock_get.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING,
                            _MOCK_APIFLOW_CFF_DOWNLOAD_TERMINATED]
    mock_list_results.return_value = [_MOCK_HASH_LINUX_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_LINUX_CLIENTFILEFINDER_DATA]
    mock_exception.return_value = RuntimeError('Test exception')

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'),
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow):
      mock_create_flow.return_value = _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING
      local_path = os.path.join(self.create_tempdir(), 'local_path')

      self.client.CollectFilesInBackground('/remote/path', local_path)
      self.client._collection_threads.shutdown()

      with io.StringIO() as buf, contextlib.redirect_stdout(buf):
        self.client.WaitForBackgroundCompletions()

        self.assertIn('CLIENTFILEFINDERRUNNINGFLOWID - Test exception',
                      buf.getvalue())

  def test_ListAllFlows(self):
    """Tests the ListAllFlows method."""
    with (mock.patch.object(self.client._grr_client, 'ListFlows'
                            ) as mock_listflows,
          mock.patch.object(self.client._flow_monitor._grr_client, 'Flow'
                            ) as mock_monitor_flow):
      mock_listflows.return_value = [
          _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING,
          _MOCK_APIFLOW_CFF_DOWNLOAD_TERMINATED,
          _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING,
          _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_TERMINATED,
          _MOCK_APIFLOW_GETFILE_RUNNING,
          _MOCK_APIFLOW_INTERROGATE_RUNNING,
          _MOCK_APIFLOW_TIMELINE_RUNNING]
      mock_monitor_flow.side_effect = [
          _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING,
          _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING,
          _MOCK_APIFLOW_GETFILE_RUNNING,
          _MOCK_APIFLOW_INTERROGATE_RUNNING,
          _MOCK_APIFLOW_TIMELINE_RUNNING]

      self.client._flow_monitor.StartMonitor()
      result = self.client.ListAllFlows(10)

      expected = """\tARTIFACTCOLLECTORFLOWTERMINATEDFLOWID 1970-01-01T00:00:09Z ArtifactCollectorFlow AllOS_File TERMINATED
\tARTIFACTCOLLECTORFLOWRUNNINGFLOWID 1970-01-01T00:00:08Z ArtifactCollectorFlow AllOS_File RUNNING
\tGETFILERUNNINGFLOWID 1970-01-01T00:00:07Z GetFile C:/Users/username/Downloads/Firefox Installer.exe:Zone.Identifier RUNNING
\tCLIENTFILEFINDERTERMINATEDFLOWID 1970-01-01T00:00:06Z ClientFileFinder DOWNLOAD /remote/path TERMINATED
\tCLIENTFILEFINDERRUNNINGFLOWID 1970-01-01T00:00:05Z ClientFileFinder DOWNLOAD /remote/path RUNNING
\tINTERROGATEFLOWID 1970-01-01T00:00:04Z Interrogate  RUNNING
\tTIMELINEFLOWID 1970-01-01T00:00:03Z TimelineFlow root: / RUNNING"""

      self.assertEqual(result, expected)

  def test_ListAllFlowsUncached(self):
    """Tests the ListAllFlows method when the flows are not yet cached."""
    with (mock.patch.object(self.client._grr_client, 'ListFlows'
                            ) as mock_listflows,
          mock.patch.object(self.client._flow_monitor, 'IsFlowCached'
                            ) as mock_isflowcached,
          mock.patch.object(self.client._flow_monitor._grr_client, 'Flow'
                            ) as mock_monitor_flow):
      mock_listflows.return_value = [_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING]
      mock_monitor_flow.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING]
      mock_isflowcached.return_value = False

      self.client._flow_monitor.StartMonitor()
      result = self.client.ListAllFlows(10)

      self.assertIn(
          '\tCLIENTFILEFINDERRUNNINGFLOWID 1970-01-01T00:00:05Z '
          'ClientFileFinder <UNCACHED FLOW ARGS> RUNNING', result)

  @parameterized.named_parameters(
      ('cff_success', _MOCK_APIFLOW_CFF_DOWNLOAD_TERMINATED,
       _MOCK_CLIENTFILEFINDER_TERMINATED_DETAIL),
      ('cff_failure', _MOCK_APIFLOW_CFF_DOWNLOAD_ERROR,
       _MOCK_CLIENTFILEFINDER_ERROR_DETAIL),
      ('timeline_failure', _MOCK_APIFLOW_TIMELINE_ERROR,
       _MOCK_TIMELINE_ERROR_DETAIL),
      ('timeline_failure_stacktrace', _MOCK_APIFLOW_TIMELINE_ERROR_STACKTRACE,
       _MOCK_TIMELINE_ERROR_STACKTRACE_DETAIL),
      ('timeline_failure_nomessage', _MOCK_APIFLOW_TIMELINE_ERROR_NOMESSAGE,
       _MOCK_TIMELINE_ERROR_NOMESSAGE_DETAIL))
  def test_Detail(self, mock_flow, expected_detail):
    """Tests the Detail method."""
    self.mock_grr_api.Client.return_value.Flow.return_value.Get.return_value = (
        mock_flow)

    result = self.client.FlowDetail(mock_flow.flow_id)
    self.assertEqual(result, expected_detail)

  def test_DetermineSourceForArtefact(self):
    """Tests determining the source type for a mixed type Artefact."""
    result = self.client._DetermineSourceForArtefact('Mixed')

    self.assertEqual(
        result, artifact_pb2.ArtifactSource.SourceType.FILE)


class GrrShellClientWindowsTest(parameterized.TestCase):
  """Windows specific tests for the GRR Shell Client class."""

  mock_grr_api: mock.Mock
  client: grr_shell_client.GRRShellClient

  @mock.patch.object(grr_api, 'InitHttp', autospec=True)
  def setUp(self, mock_InitHttp):  # pylint: disable=arguments-differ
    """Set up tests."""
    super().setUp()
    self.mock_grr_api = mock.Mock()
    mock_InitHttp.return_value = self.mock_grr_api
    self.mock_grr_api.Client.return_value.client_id = _TEST_CLIENT_GRR_ID
    self.mock_grr_api.Client.return_value.Get.return_value = (
        _MOCK_WINDOWS_CLIENT)
    self.mock_grr_api.Client.return_value.ListFlows.return_value = (
        _MOCK_APIFLOW_LISTFLOWS)
    self.mock_grr_api.SearchClients.return_value = [_MOCK_WINDOWS_CLIENT]
    self.mock_grr_api.ListArtifacts.return_value = (
        _BuildMockArtifactDescriptors())

    self.client = grr_shell_client.GRRShellClient(
        _TEST_GRR_URL, _TEST_GRR_USER, _TEST_GRR_PASS, _TEST_CLIENT_FQDN, _MAX_FILE_SIZE_1GB)

  def test_GetOS(self):
    """Tests the GetOS method."""
    self.assertEqual(self.client.GetOS(), 'Windows')

  @mock.patch('datetime.datetime', wraps=datetime.datetime)
  def test_GetLastTimelineWindowsRoot(self, mock_dt):
    """Tests the GetLastTimeline method when there is a Windows root."""
    with (mock.patch.object(self.client._grr_client,
                            'ListFlows',
                            return_value=_MOCK_APIFLOW_LISTFLOWS),
          mock.patch.object(flow.Flow, 'Get', new=_MockGetFromFlowList)):
      # "Now" is half of the staleness threshold past the epoch. All the flows
      # returned are at 1 second past the epoch, so they are not stale.
      mock_dt.now.return_value = datetime.datetime.fromtimestamp(
          grr_shell_client._STALE_TIMELINE_THRESHOLD.total_seconds() / 2,
          tz=datetime.timezone.utc)

      result = self.client.GetLastTimeline()
      self.assertEqual(result, 'CORRECT_WIN')

  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_GETFILE_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_GETFILE_RUNNING, 'ListResults')
  def test_FileInfo_NoADS(self,
                          mock_gf_list_results,
                          mock_gf_wait_until_done,
                          mock_ff_list_results,
                          mock_ff_wait_until_done):
    """Tests the FileInfo method, with attempting to collect an absent ADS."""
    mock_ff_list_results.return_value = [_MOCK_HASH_WINDOWS_ENTRY]
    mock_gf_list_results.return_value = []

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs',
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow',
                            ) as mock_create_flow):
      mock_create_flow.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING,
                                      _MOCK_APIFLOW_GETFILE_RUNNING]

      result = self.client.FileInfo(
          '/C:/Users/username/Downloads/Firefox Installer.exe',
          collect_ads=True)

      mock_create_flow_args.assert_called_once_with('ClientFileFinder')
      self.assertEqual(
          mock_create_flow_args.return_value.action.hash.max_size,
          _MAX_FILE_SIZE_1GB)
      mock_create_flow_args.return_value.paths.append.assert_called_once_with(
          'C:/Users/username/Downloads/Firefox Installer.exe')
      self.assertEqual(mock_create_flow_args.return_value.action.action_type,
                       flows_pb2.FileFinderAction.HASH)
      mock_create_flow.assert_has_calls([
          mock.call(
              name='ClientFileFinder', args=mock_create_flow_args.return_value),
          mock.call(
              name='MultiGetFile',
              args=flows_pb2.MultiGetFileArgs(
                  pathspecs=[jobs_pb2.PathSpec(
                      path='C:/Users/username/Downloads/Firefox Installer.exe',
                      pathtype=jobs_pb2.PathSpec.NTFS,
                      stream_name='Zone.Identifier')]))])
      mock_ff_wait_until_done.assert_called_once()
      mock_gf_wait_until_done.assert_called_once()

      self.assertEqual(result, _EXPECTED_HASH_WINDOWS_RESULT)

  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  def test_FileInfo_D_Drive(self,
                            mock_ff_list_results,
                            mock_ff_wait_until_done):
    """Tests CFF for a file on a Windows non-root drive uses OS PathSpec."""
    mock_ff_list_results.return_value = [_MOCK_HASH_WINDOWS_ENTRY]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs',
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow',
                            ) as mock_create_flow):
      mock_create_flow.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING]

      self.client.FileInfo('/D:/foo')

      mock_create_flow_args.assert_called_once_with('ClientFileFinder')
      mock_create_flow_args.return_value.paths.append.assert_called_once_with(
          'D:/foo')
      self.assertEqual(mock_create_flow_args.return_value.action.action_type,
                       flows_pb2.FileFinderAction.HASH)
      self.assertEqual(mock_create_flow_args.return_value.pathtype,
                       jobs_pb2.PathSpec.OS)
      mock_create_flow.assert_called_with(
          name='ClientFileFinder', args=mock_create_flow_args.return_value)
      mock_ff_wait_until_done.assert_called_once()

  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'GetFilesArchive')
  def test_CollectFiles_D_Drive(self,
                                mock_get_files_archive,
                                mock_list_results,
                                mock_wait_until_done,
                                mock_get):
    """Tests the CollectFile method for windows, non-NTFS volume, with a non-ascii directory name."""
    mock_get.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_TERMINATED]
    mock_list_results.return_value = [_MOCK_HASH_WINDOWS_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_WINDOWS_CLIENTFILEFINDER_FAT32_DATA]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow):
      mock_create_flow.return_value = _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING
      self.client._pathspec_mapper['D:/'] = jobs_pb2.PathSpec.OS

      local_path = os.path.join(self.create_tempdir(), 'local_path')
      self.client.CollectFiles('/D:/\xa0/bar', local_path)

      mock_create_flow_args.assert_called_once_with('ClientFileFinder')
      self.assertEqual(mock_create_flow_args.return_value.pathtype,
                       jobs_pb2.PathSpec.OS)
      self.assertTrue(
          mock_create_flow_args.return_value.use_raw_filesystem_access)

      mock_create_flow_args.return_value.paths.append.assert_called_once_with(
          'D:/\xa0/bar')
      mock_create_flow.assert_called_once_with(
          name='ClientFileFinder', args=mock_create_flow_args.return_value)
      mock_wait_until_done.assert_called_once()

      self.assertTrue(os.path.exists(
          os.path.join(local_path, 'D_', '\xa0', 'bar')))

  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  def test_FileInfo_wildcard(self, mock_list_results, mock_wait_until_done):
    """Tests the FileInfo method with a wildcard path."""
    mock_list_results.return_value = [_MOCK_HASH_WINDOWS_ENTRY]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow):
      mock_create_flow.return_value = _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING

      result = self.client.FileInfo('/C:/Users/username/Downloads/Firefox*')

      mock_create_flow_args.assert_called_once_with('ClientFileFinder')
      self.assertEqual(
          mock_create_flow_args.return_value.action.hash.max_size,
          _MAX_FILE_SIZE_1GB)
      mock_create_flow_args.return_value.paths.append.assert_called_once_with(
          'C:/Users/username/Downloads/Firefox*')
      self.assertEqual(mock_create_flow_args.return_value.action.action_type,
                       flows_pb2.FileFinderAction.HASH)
      mock_create_flow.assert_called_once_with(
          name='ClientFileFinder', args=mock_create_flow_args.return_value)
      mock_wait_until_done.assert_called_once()

      self.assertEqual(result, _EXPECTED_HASH_WINDOWS_RESULT)

  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_GETFILE_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_GETFILE_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_GETFILE_RUNNING, 'GetFilesArchive')
  def test_FileInfo_WithADS(self,
                            mock_gf_get_files_archive,
                            mock_gf_list_results,
                            mock_gf_wait_until_done,
                            mock_ff_list_results,
                            mock_ff_wait_until_done):
    """Tests the FileInfo method with a Zone.Identifier ADS present."""
    mock_ff_list_results.return_value = [_MOCK_HASH_WINDOWS_ENTRY]
    mock_gf_list_results.return_value = [_MOCK_HASH_WINDOWS_WITH_ADS_ENTRY]
    mock_gf_get_files_archive.return_value = [
        _MOCK_ZIP_WINDOWS_GETFILE_ADS_DATA]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs',
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow',
                            ) as mock_create_flow):
      mock_create_flow.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING,
                                      _MOCK_APIFLOW_GETFILE_RUNNING]

      result = self.client.FileInfo(
          'C:/Users/username/Downloads/Firefox Installer.exe',
          collect_ads=True)

      mock_create_flow_args.assert_called_once_with('ClientFileFinder')
      self.assertEqual(
          mock_create_flow_args.return_value.action.hash.max_size,
          _MAX_FILE_SIZE_1GB)
      mock_create_flow_args.return_value.paths.append.assert_called_once_with(
          'C:/Users/username/Downloads/Firefox Installer.exe')
      self.assertEqual(mock_create_flow_args.return_value.action.action_type,
                       flows_pb2.FileFinderAction.HASH)
      mock_create_flow.assert_has_calls([
          mock.call(
              name='ClientFileFinder', args=mock_create_flow_args.return_value),
          mock.call(
              name='MultiGetFile',
              args=flows_pb2.MultiGetFileArgs(
                  pathspecs=[jobs_pb2.PathSpec(
                      path='C:/Users/username/Downloads/Firefox Installer.exe',
                      pathtype=jobs_pb2.PathSpec.NTFS,
                      stream_name='Zone.Identifier')]))])
      mock_ff_wait_until_done.assert_called_once()
      mock_gf_wait_until_done.assert_called_once()
      mock_gf_get_files_archive.assert_called_once()

      self.assertEqual(result, _EXPECTED_HASH_WINDOWS_WITH_ADS_RESULT)

  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_GETFILE_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_GETFILE_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_GETFILE_RUNNING, 'GetFilesArchive')
  def test_FileInfo_WithEmptyADS(self,
                                 mock_gf_get_files_archive,
                                 mock_gf_list_results,
                                 mock_gf_wait_until_done,
                                 mock_ff_list_results,
                                 mock_ff_wait_until_done):
    """Tests the FileInfo method with a Zone.Identifier ADS present."""
    mock_ff_list_results.return_value = [_MOCK_HASH_WINDOWS_ENTRY]
    mock_gf_list_results.return_value = [_MOCK_HASH_WINDOWS_WITH_ADS_ENTRY]
    mock_gf_get_files_archive.return_value = [
        _MOCK_ZIP_WINDOWS_GETFILE_ADS_EMPTY_DATA]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs',
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow',
                            ) as mock_create_flow):
      mock_create_flow.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING,
                                      _MOCK_APIFLOW_GETFILE_RUNNING]

      result = self.client.FileInfo(
          'C:/Users/username/Downloads/Firefox Installer.exe',
          collect_ads=True)

      mock_create_flow_args.assert_called_once_with('ClientFileFinder')
      self.assertEqual(
          mock_create_flow_args.return_value.action.hash.max_size,
          _MAX_FILE_SIZE_1GB)
      mock_create_flow_args.return_value.paths.append.assert_called_once_with(
          'C:/Users/username/Downloads/Firefox Installer.exe')
      self.assertEqual(mock_create_flow_args.return_value.action.action_type,
                       flows_pb2.FileFinderAction.HASH)
      mock_create_flow.assert_has_calls([
          mock.call(
              name='ClientFileFinder', args=mock_create_flow_args.return_value),
          mock.call(
              name='MultiGetFile',
              args=flows_pb2.MultiGetFileArgs(
                  pathspecs=[jobs_pb2.PathSpec(
                      path='C:/Users/username/Downloads/Firefox Installer.exe',
                      pathtype=jobs_pb2.PathSpec.NTFS,
                      stream_name='Zone.Identifier')]))])
      mock_ff_wait_until_done.assert_called_once()
      mock_gf_wait_until_done.assert_called_once()
      mock_gf_get_files_archive.assert_called_once()

      self.assertEqual(result, _EXPECTED_HASH_WINDOWS_RESULT)

  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  def test_FileInfo_ClientFileFinderFailure(self,
                                            mock_ff_list_results,
                                            mock_ff_wait_until_done):
    """Tests a failure in ClientFileFinder in FileInfo is handled."""
    mock_ff_list_results.return_value = [_MOCK_HASH_WINDOWS_ENTRY]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'),
          mock.patch.object(self.client._grr_client, 'CreateFlow',
                            ) as mock_create_flow):
      mock_create_flow.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING]
      mock_ff_wait_until_done.side_effect = grr_errors.FlowFailedError(
          'test error')

      with io.StringIO() as buf, contextlib.redirect_stdout(buf):
        self.client.FileInfo(
            '/C:/Users/username/Downloads/Firefox Installer.exe')

        self.assertIn('HASH Flow collection CLIENTFILEFINDERRUNNINGFLOWID '
                      'failed: test error',
                      buf.getvalue())

  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_GETFILE_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_GETFILE_RUNNING, 'ListResults')
  def test_FileInfo_ADSFailure(self,
                               mock_gf_list_results,
                               mock_gf_wait_until_done,
                               mock_ff_list_results,
                               mock_ff_wait_until_done):
    """Tests a failure in collecting the ADS in FileInfo is handled."""
    mock_ff_list_results.return_value = [_MOCK_HASH_WINDOWS_ENTRY]
    mock_gf_list_results.return_value = [_MOCK_HASH_WINDOWS_WITH_ADS_ENTRY]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'),
          mock.patch.object(self.client._grr_client, 'CreateFlow',
                            ) as mock_create_flow):
      mock_create_flow.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING,
                                      _MOCK_APIFLOW_GETFILE_RUNNING]
      mock_gf_wait_until_done.side_effect = grr_errors.FlowFailedError(
          'test error')

      with io.StringIO() as buf, contextlib.redirect_stdout(buf):
        result = self.client.FileInfo(
            '/C:/Users/username/Downloads/Firefox Installer.exe',
            collect_ads=True)

        self.assertIn('ADS Flow collection GETFILERUNNINGFLOWID failed: '
                      'test error',
                      buf.getvalue())
        mock_ff_wait_until_done.assert_called_once()
        self.assertEqual(result, _EXPECTED_HASH_WINDOWS_RESULT)

  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'GetFilesArchive')
  def test_CollectFiles(self,
                        mock_get_files_archive,
                        mock_list_results,
                        mock_wait_until_done,
                        mock_get):
    """Tests the CollectFile method for a windows filesystem."""
    mock_get.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_TERMINATED]
    mock_list_results.return_value = [_MOCK_HASH_WINDOWS_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_WINDOWS_CLIENTFILEFINDER_DATA]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow):
      mock_create_flow.return_value = _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING
      self.client._pathspec_mapper['C:/'] = jobs_pb2.PathSpec.NTFS

      local_path = os.path.join(self.create_tempdir(), 'local_path')
      self.client.CollectFiles(
          '/C:/Users/username/Downloads/Firefox Installer.exe', local_path)

      mock_create_flow_args.assert_called_once_with('ClientFileFinder')
      self.assertEqual(mock_create_flow_args.return_value.pathtype,
                       jobs_pb2.PathSpec.NTFS)
      self.assertTrue(
          mock_create_flow_args.return_value.use_raw_filesystem_access)

      mock_create_flow_args.return_value.paths.append.assert_called_once_with(
          'C:/Users/username/Downloads/Firefox Installer.exe')
      mock_create_flow.assert_called_once_with(
          name='ClientFileFinder', args=mock_create_flow_args.return_value)
      mock_wait_until_done.assert_called_once()

      self.assertTrue(os.path.exists(
          os.path.join(local_path, 'volume', 'Users', 'username', 'Downloads',
                       'Firefox Installer.exe')))

  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'WaitUntilDone')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'ListResults')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'GetFilesArchive')
  def test_ScheduleAndDownloadArtefact(self,
                                       mock_get_files_archive,
                                       mock_list_results,
                                       mock_wait_until_done,
                                       mock_get):
    """Tests the ScheduleAndDownloadArtefact method for windows."""
    mock_get.side_effect = [_MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_TERMINATED]
    mock_list_results.return_value = [_MOCK_HASH_WINDOWS_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_WINDOWS_ARTIFACTCOLLECTORFLOW_DATA]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow):
      mock_create_flow.return_value = (
          _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING)

      local_path = os.path.join(self.create_tempdir(), 'local_path')
      self.client.ScheduleAndDownloadArtefact('artifact_name', local_path)

      mock_create_flow_args.assert_called_once_with('ArtifactCollectorFlow')
      self.assertEqual(
          mock_create_flow_args.return_value.max_file_size,
          _MAX_FILE_SIZE_1GB)
      self.assertTrue(
          mock_create_flow_args.return_value.use_raw_filesystem_access)
      mock_create_flow_args.return_value.artifact_list.append.assert_called_once_with(
          'artifact_name')
      mock_create_flow.assert_called_once_with(
          name='ArtifactCollectorFlow', args=mock_create_flow_args.return_value)
      mock_wait_until_done.assert_called_once()

      self.assertTrue(os.path.exists(
          os.path.join(local_path, 'volume', 'Users', 'username', 'Downloads',
                       'Firefox Installer.exe')))

  def test_CollectArtefactSynchronous(self):
    """Tests collecting a synchronous artefact."""
    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow):
      mock_create_flow.return_value.ListResults.return_value = [
          _MOCK_WINDOWS_ARTEFACT_REGVALUE]

      results = '\n'.join(self.client.CollectArtefact('Windows_RegKey', './'))

      mock_create_flow_args.assert_called_once()
      mock_create_flow.return_value.WaitUntilDone.assert_called_once()
      self.assertCountEqual(results, _EXPECTED_WINDOWS_REGVALUE_RESULT)

  @mock.patch.object(_MOCK_APIFLOW_GETFILE_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_GETFILE_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_GETFILE_RUNNING, 'GetFilesArchive')
  def test_Reattach_GetFile(self,
                            mock_get_files_archive,
                            mock_list_results,
                            mock_wait_until_done):
    """Tests reattaching a GetFile flow."""
    self.mock_grr_api.Client.return_value.Flow.return_value.Get.return_value = (
        _MOCK_APIFLOW_GETFILE_RUNNING)
    mock_list_results.return_value = [_MOCK_HASH_WINDOWS_WITH_ADS_ENTRY]
    mock_get_files_archive.return_value = [_MOCK_ZIP_WINDOWS_GETFILE_ADS_DATA]

    results = '\n'.join(self.client.ReattachFlow('GETFILERUNNINGFLOWID'))

    mock_wait_until_done.assert_called_once()
    self.assertEqual(results, _EXPECTED_ZONE_IDENTIFIER)

  @mock.patch.object(_MOCK_APIFLOW_CFF_HASH_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_HASH_RUNNING, 'ListResults')
  def test_Reattach_ClientFileFinder_Hash(self,
                                          mock_list_results,
                                          mock_wait_until_done):
    """Tests reattaching a ClientFileFinder HASH flow."""
    self.mock_grr_api.Client.return_value.Flow.return_value.Get.return_value = (
        _MOCK_APIFLOW_CFF_HASH_RUNNING)
    mock_list_results.return_value = [_MOCK_HASH_WINDOWS_ENTRY]

    results = '\n'.join(self.client.ReattachFlow(
        'CLIENTFILEFINDERHASHRUNNINGFLOWID'))
    mock_wait_until_done.assert_called_once()

    self.assertEqual(results, _EXPECTED_HASH_WINDOWS_RESULT)

  @mock.patch.object(futures.Future, 'exception', return_value=False)
  @mock.patch.object(futures.Future, 'running')
  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'GetFilesArchive')
  def test_Reattach_ClientFileFinder_Download(self,
                                              mock_get_files_archive,
                                              mock_list_results,
                                              mock_wait_until_done,
                                              mock_get,
                                              mock_running,
                                              _):
    """Tests reattaching a ClientFileFinder DOWNLOAD flow."""
    self.mock_grr_api.Client.return_value.Flow.return_value.Get.return_value = (
        _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING)
    mock_get.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING,
                            _MOCK_APIFLOW_CFF_DOWNLOAD_TERMINATED]
    mock_running.side_effect = [True, True, True, True, False, False]
    mock_list_results.return_value = [_MOCK_HASH_LINUX_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_WINDOWS_CLIENTFILEFINDER_DATA]

    local_path = os.path.join(self.create_tempdir(), 'C.0000000000000001')

    running, total = self.client.GetRunningFlowCount()
    self.assertEqual(running, 0)
    self.assertEqual(total, 0)
    actual_states = self.client.GetBackgroundFlowsState()
    self.assertEqual(actual_states, 'No launched flows')

    self.client.ReattachFlow('FLOWID', local_path)

    running, total = self.client.GetRunningFlowCount()
    self.assertEqual(running, 1)
    self.assertEqual(total, 1)
    actual_states = self.client.GetBackgroundFlowsState()
    self.assertEqual(
        actual_states,
        '\tCLIENTFILEFINDERRUNNINGFLOWID ClientFileFinder DOWNLOAD '
        '/remote/path RUNNING')

    running, total = self.client.GetRunningFlowCount()
    self.assertEqual(running, 1)
    self.assertEqual(total, 1)
    actual_states = self.client.GetBackgroundFlowsState()
    self.assertEqual(
        actual_states,
        '\tCLIENTFILEFINDERTERMINATEDFLOWID ClientFileFinder DOWNLOAD '
        '/remote/path DOWNLOADING')

    running, total = self.client.GetRunningFlowCount()
    self.assertEqual(running, 0)
    self.assertEqual(total, 1)
    actual_states = self.client.GetBackgroundFlowsState()
    self.assertEqual(
        actual_states,
        '\tCLIENTFILEFINDERTERMINATEDFLOWID ClientFileFinder DOWNLOAD '
        '/remote/path COMPLETE')

    self.client._collection_threads.shutdown()

    mock_wait_until_done.assert_called_once()
    self.assertTrue(os.path.exists(
        os.path.join(local_path, 'volume', 'Users', 'username', 'Downloads',
                     'Firefox Installer.exe')))

  @mock.patch.object(futures.Future, 'exception', return_value=False)
  @mock.patch.object(futures.Future, 'running')
  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'WaitUntilDone')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'ListResults')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'GetFilesArchive')
  def test_Reattach_ArtifactCollectorFlow(self,
                                          mock_get_files_archive,
                                          mock_list_results,
                                          mock_wait_until_done,
                                          mock_get,
                                          mock_running,
                                          _):
    """Tests reattaching an ArtifactCollectorFlow flow."""
    self.mock_grr_api.Client.return_value.Flow.return_value.Get.return_value = (
        _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING)
    mock_get.side_effect = [_MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING,
                            _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_TERMINATED]
    mock_running.side_effect = [True, True, True, True, False, False]
    mock_list_results.return_value = [_MOCK_HASH_WINDOWS_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_WINDOWS_ARTIFACTCOLLECTORFLOW_DATA]

    local_path = os.path.join(self.create_tempdir(), 'local_path')

    running, total = self.client.GetRunningFlowCount()
    self.assertEqual(running, 0)
    self.assertEqual(total, 0)
    actual_states = self.client.GetBackgroundFlowsState()
    self.assertEqual(actual_states, 'No launched flows')

    self.client.ReattachFlow('FLOWID', local_path)

    running, total = self.client.GetRunningFlowCount()
    self.assertEqual(running, 1)
    self.assertEqual(total, 1)
    actual_states = self.client.GetBackgroundFlowsState()
    self.assertEqual(
        actual_states,
        '\tARTIFACTCOLLECTORFLOWRUNNINGFLOWID ArtifactCollectorFlow '
        'AllOS_File RUNNING')

    running, total = self.client.GetRunningFlowCount()
    self.assertEqual(running, 1)
    self.assertEqual(total, 1)
    actual_states = self.client.GetBackgroundFlowsState()
    self.assertEqual(
        actual_states,
        '\tARTIFACTCOLLECTORFLOWTERMINATEDFLOWID ArtifactCollectorFlow '
        'AllOS_File DOWNLOADING')

    running, total = self.client.GetRunningFlowCount()
    self.assertEqual(running, 0)
    self.assertEqual(total, 1)
    actual_states = self.client.GetBackgroundFlowsState()
    self.assertEqual(
        actual_states,
        '\tARTIFACTCOLLECTORFLOWTERMINATEDFLOWID ArtifactCollectorFlow '
        'AllOS_File COMPLETE')

    self.client._collection_threads.shutdown()

    mock_wait_until_done.assert_called_once()
    self.assertTrue(os.path.exists(
        os.path.join(local_path, 'volume', 'Users', 'username', 'Downloads',
                     'Firefox Installer.exe')))

  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_WINREGKEY_RUNNING, 'WaitUntilDone')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_WINREGKEY_RUNNING, 'ListResults')
  def test_Reattach_SynchronousArtefact(self,
                                        mock_list_results,
                                        mock_wait_until_done):
    """Tests reattaching a synchronous ArtifactColector flow."""
    self.mock_grr_api.Client.return_value.Flow.return_value.Get.return_value = (
        _MOCK_APIFLOW_ARTEFACTCOLLECTOR_WINREGKEY_RUNNING)
    mock_list_results.return_value = [_MOCK_WINDOWS_ARTEFACT_REGVALUE]

    results = '\n'.join(self.client.ReattachFlow(
        'ARTIFACTCOLLECTORFLOWRUNNINGFLOWID'))
    mock_wait_until_done.assert_called_once()

    self.assertEqual(results, _EXPECTED_WINDOWS_REGVALUE_RESULT)

  def test_Reattach_InvalidFlow(self):
    """Tests attempting to resume an unsupported flow."""
    self.mock_grr_api.Client.return_value.Flow.return_value.Get.return_value = (
        _MOCK_APIFLOW_TIMELINE_RUNNING)

    with self.assertRaisesRegex(
        errors.NotResumeableFlowTypeError,
        'Flow TIMELINEFLOWID is of type TimelineFlow, not supported for '
        'resumption.'):
      self.client.ReattachFlow('TIMELINEFLOWID')

  @mock.patch.object(_MOCK_APIFLOW_GETFILE_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_GETFILE_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_GETFILE_RUNNING, 'GetFilesArchive')
  def test_Complete_GetFile(self,
                            mock_get_files_archive,
                            mock_list_results,
                            mock_wait_until_done):
    """Tests completing a GetFile flow."""
    self.mock_grr_api.Client.return_value.Flow.return_value.Get.return_value = (
        _MOCK_APIFLOW_GETFILE_RUNNING)
    mock_list_results.return_value = [_MOCK_HASH_WINDOWS_WITH_ADS_ENTRY]
    mock_get_files_archive.return_value = [_MOCK_ZIP_WINDOWS_GETFILE_ADS_DATA]

    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
      self.client.CompleteFlow('GETFILERUNNINGFLOWID', './')

      mock_wait_until_done.assert_called_once()
      self.assertIn(_EXPECTED_ZONE_IDENTIFIER, buf.getvalue())

  @mock.patch.object(_MOCK_APIFLOW_CFF_HASH_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_HASH_RUNNING, 'ListResults')
  def test_Complete_ClientFileFinder_Hash(self,
                                          mock_list_results,
                                          mock_wait_until_done):
    """Tests completing a ClientFileFinder HASH flow."""
    self.mock_grr_api.Client.return_value.Flow.return_value.Get.return_value = (
        _MOCK_APIFLOW_CFF_HASH_RUNNING)
    mock_list_results.return_value = [_MOCK_HASH_WINDOWS_ENTRY]

    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
      self.client.CompleteFlow('CLIENTFILEFINDERHASHRUNNINGFLOWID', './')

      mock_wait_until_done.assert_called_once()
      self.assertIn(_EXPECTED_HASH_WINDOWS_RESULT, buf.getvalue())

  @mock.patch.object(futures.Future, 'exception', return_value=False)
  @mock.patch.object(futures.Future, 'running')
  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'GetFilesArchive')
  def test_Complete_ClientFileFinder_Download(self,
                                              mock_get_files_archive,
                                              mock_list_results,
                                              mock_wait_until_done,
                                              mock_get,
                                              mock_running,
                                              _):
    """Tests completing a ClientFileFinder DOWNLOAD flow."""
    self.mock_grr_api.Client.return_value.Flow.return_value.Get.return_value = (
        _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING)
    mock_get.return_value = _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING
    mock_running.side_effect = False
    mock_list_results.return_value = [_MOCK_HASH_LINUX_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_WINDOWS_CLIENTFILEFINDER_DATA]

    local_path = os.path.join(self.create_tempdir(), 'C.0000000000000001')

    self.client.CompleteFlow('CLIENTFILEFINDERTERMINATEDFLOWID', local_path)

    mock_wait_until_done.assert_called_once()
    self.assertTrue(os.path.exists(
        os.path.join(local_path, 'volume', 'Users', 'username', 'Downloads',
                     'Firefox Installer.exe')))

  @mock.patch.object(futures.Future, 'exception', return_value=False)
  @mock.patch.object(futures.Future, 'running')
  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'WaitUntilDone')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'ListResults')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'GetFilesArchive')
  def test_Complete_ArtifactCollectorFlow(self,
                                          mock_get_files_archive,
                                          mock_list_results,
                                          mock_wait_until_done,
                                          mock_get,
                                          mock_running,
                                          _):
    """Tests completing an ArtifactCollectorFlow flow."""
    self.mock_grr_api.Client.return_value.Flow.return_value.Get.return_value = (
        _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING)
    mock_get.return_value = _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING
    mock_running.side_effect = False
    mock_list_results.return_value = [_MOCK_HASH_WINDOWS_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_WINDOWS_ARTIFACTCOLLECTORFLOW_DATA]

    local_path = os.path.join(self.create_tempdir(), 'local_path')

    self.client.CompleteFlow('ARTIFACTCOLLECTORFLOWRUNNINGFLOWID', local_path)

    mock_wait_until_done.assert_called_once()
    self.assertTrue(os.path.exists(
        os.path.join(local_path, 'volume', 'Users', 'username', 'Downloads',
                     'Firefox Installer.exe')))

  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_WINREGKEY_RUNNING, 'WaitUntilDone')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_WINREGKEY_RUNNING, 'ListResults')
  def test_Complete_SynchronousArtefact(self,
                                        mock_list_results,
                                        mock_wait_until_done):
    """Tests completing a synchronous ArtifactColector flow."""
    self.mock_grr_api.Client.return_value.Flow.return_value.Get.return_value = (
        _MOCK_APIFLOW_ARTEFACTCOLLECTOR_WINREGKEY_RUNNING)
    mock_list_results.return_value = [_MOCK_WINDOWS_ARTEFACT_REGVALUE]

    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
      self.client.CompleteFlow('ARTIFACTCOLLECTORFLOWRUNNINGFLOWID', './')

      mock_wait_until_done.assert_called_once()
      self.assertIn(_EXPECTED_WINDOWS_REGVALUE_RESULT, buf.getvalue())

  def test_Complete_InvalidFlow(self):
    """Tests attempting to complete an unsupported flow."""
    self.mock_grr_api.Client.return_value.Flow.return_value.Get.return_value = (
        _MOCK_APIFLOW_TIMELINE_RUNNING)

    with self.assertRaisesRegex(
        errors.NotResumeableFlowTypeError,
        'Flow TIMELINEFLOWID is of type TimelineFlow, not supported for '
        'resumption.'):
      self.client.CompleteFlow('TIMELINEFLOWID', './')

  def test_GetSupportedArtifacts(self):
    """Tests the GetSupportedArtifacts method."""
    self.mock_grr_api.ListArtifacts.return_value = (
        _BuildMockArtifactDescriptors())

    self.client._RetrieveSupportedArtefacts()
    self.assertCountEqual(
        self.client.GetSupportedArtefactNames(),
        ['AllOS_File', 'AllOS_ArtifactGroup', 'Windows_RegKey',
         'Windows_RegValue', 'Mixed'])

  @parameterized.named_parameters(
      ('root', '/', b'/'),
      ('c_drive', 'C:/', b'C:/'),
      ('c_preceding_slash', '/C:/', b'C:/')
  )
  def test_CollectTimelinePath(self, in_path, expected_path):
    """Tests the CollectTimeline method with a specified path."""
    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs',
                            return_value=mock.Mock()) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow',
                            return_value=mock.Mock()) as mock_create_flow,
          mock.patch('io.BytesIO') as mock_bytesio):
      mock_result = mock.Mock()
      mock_result.payload.filesystem_type = 'NTFS'
      mock_create_flow.return_value.ListResults.return_value = [mock_result]
      mock_create_flow.return_value.args.root = in_path.encode('utf-8')
      mock_bytesio.return_value.getvalue.return_value = open(
          _SAMPLE_TIMELINE_WINDOWS, 'rb').read()

      self.client.CollectTimeline(path=in_path)

      mock_create_flow_args.assert_called_once_with('TimelineFlow')
      self.assertEqual(
          mock_create_flow_args.return_value.root, expected_path)
      mock_create_flow.assert_called_once_with(
          name='TimelineFlow', args=mock_create_flow_args.return_value)
      mock_create_flow.return_value.WaitUntilDone.assert_called_once()
      mock_create_flow.return_value.GetCollectedTimelineBody.assert_called_once()
      self.assertDictEqual({'C:/': jobs_pb2.PathSpec.NTFS},
                           self.client._pathspec_mapper._path_ps_map)

  def test_DetermineSourceForArtefact(self):
    """Tests determining the source type for a mixed type Artefact."""
    result = self.client._DetermineSourceForArtefact('Mixed')

    self.assertEqual(
        result, artifact_pb2.ArtifactSource.SourceType.REGISTRY_VALUE)

  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_WMILOGICALDISKS_RUNNING, 'WaitUntilDone')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_WMILOGICALDISKS_RUNNING, 'ListResults')
  def test_DescribeVolumes(self,
                           mock_list_results,
                           mock_wait_until_done):
    """Tests the DescribeVolumes method."""
    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow):
      mock_create_flow.return_value = (
          _MOCK_APIFLOW_ARTEFACTCOLLECTOR_WMILOGICALDISKS_RUNNING)
      mock_list_results.return_value = [
          _MOCK_WINDOWS_ARTEFACT_VOLUME_C,
          _MOCK_WINDOWS_ARTEFACT_VOLUME_D]

      result = self.client.DescribeVolumes()

      mock_create_flow_args.assert_called_once_with('ArtifactCollectorFlow')
      mock_wait_until_done.assert_called_once()
      self.assertEqual(result, _EXPECTED_WINDOWS_VOLUMES_RESULT)


class GrrShellClientDarwinTest(parameterized.TestCase):
  """Dawin/MacOS specific tests for the GRR Shell Client class."""

  mock_grr_api: mock.Mock
  client: grr_shell_client.GRRShellClient

  @mock.patch.object(grr_api, 'InitHttp', autospec=True)
  def setUp(self, mock_InitHttp):  # pylint: disable=arguments-differ
    """Set up tests."""
    super().setUp()
    self.mock_grr_api = mock.Mock()
    mock_InitHttp.return_value = self.mock_grr_api
    self.mock_grr_api.Client.return_value.client_id = _TEST_CLIENT_GRR_ID
    self.mock_grr_api.Client.return_value.Get.return_value = _MOCK_DARWIN_CLIENT
    self.mock_grr_api.Client.return_value.ListFlows.return_value = (
        _MOCK_APIFLOW_LISTFLOWS)
    self.mock_grr_api.SearchClients.return_value = [_MOCK_DARWIN_CLIENT]
    self.mock_grr_api.ListArtifacts.return_value = (
        _BuildMockArtifactDescriptors())

    self.client = grr_shell_client.GRRShellClient(
        _TEST_GRR_URL, _TEST_GRR_USER, _TEST_GRR_PASS, _TEST_CLIENT_FQDN, _MAX_FILE_SIZE_1GB)
    self.client._pathspec_mapper['/'] = jobs_pb2.PathSpec.OS

  def test_GetOS(self):
    """Tests the GetOS method."""
    self.assertEqual(self.client.GetOS(), 'Darwin')

  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'WaitUntilDone')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'ListResults')
  @mock.patch.object(_MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING, 'GetFilesArchive')
  def test_CollectFiles(self,
                        mock_get_files_archive,
                        mock_list_results,
                        mock_wait_until_done,
                        mock_get):
    """Tests the CollectFile method."""
    mock_get.side_effect = [_MOCK_APIFLOW_CFF_DOWNLOAD_TERMINATED]
    mock_list_results.return_value = [_MOCK_HASH_LINUX_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_DARWIN_CLIENTFILEFINDER_DATA]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow):
      mock_create_flow.return_value = _MOCK_APIFLOW_CFF_DOWNLOAD_RUNNING

      local_path = os.path.join(self.create_tempdir(), 'local_path')
      self.client.CollectFiles('/remote/path', local_path)

      mock_create_flow_args.assert_called_once_with('ClientFileFinder')
      self.assertEqual(
          mock_create_flow_args.return_value.action.download.max_size,
          _MAX_FILE_SIZE_1GB)
      mock_create_flow.assert_called_once_with(
          name='ClientFileFinder', args=mock_create_flow_args.return_value)
      mock_wait_until_done.assert_called_once()

      self.assertTrue(os.path.exists(  # sample zip contents
          os.path.join(local_path, 'Users', 'username', 'file')))

  @mock.patch.object(flow.Flow, 'Get')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'WaitUntilDone')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'ListResults')
  @mock.patch.object(
      _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING, 'GetFilesArchive')
  def test_CollectArtifact(self,
                           mock_get_files_archive,
                           mock_list_results,
                           mock_wait_until_done,
                           mock_get):
    """Tests the CollectArtifact method."""
    mock_get.side_effect = [_MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_TERMINATED]
    mock_list_results.return_value = [_MOCK_HASH_LINUX_ENTRY]
    mock_get_files_archive.return_value = [
        _MOCK_ZIP_DARWIN_ARTIFACTCOLLECTORFLOW_DATA]

    with (mock.patch.object(self.client._grr_stubby.types, 'CreateFlowArgs'
                            ) as mock_create_flow_args,
          mock.patch.object(self.client._grr_client, 'CreateFlow'
                            ) as mock_create_flow):
      mock_create_flow.return_value = (
          _MOCK_APIFLOW_ARTEFACTCOLLECTOR_ALLFILE_RUNNING)

      local_path = os.path.join(self.create_tempdir(), 'local_path')
      self.client.ScheduleAndDownloadArtefact('artifact_name', local_path)

      mock_create_flow_args.assert_called_once_with('ArtifactCollectorFlow')
      self.assertEqual(
          mock_create_flow_args.return_value.max_file_size,
          _MAX_FILE_SIZE_1GB)
      self.assertFalse(
          mock_create_flow_args.return_value.use_raw_filesystem_access)
      mock_create_flow_args.return_value.artifact_list.append.assert_called_once_with(
          'artifact_name')
      mock_create_flow.assert_called_once_with(
          name='ArtifactCollectorFlow', args=mock_create_flow_args.return_value)
      mock_wait_until_done.assert_called_once()

      self.assertTrue(os.path.exists(  # sample zip contents
          os.path.join(local_path, 'Users', 'username', 'file')))

  def test_GetSupportedArtifacts(self):
    """Tests the GetSupportedArtifacts method."""
    self.mock_grr_api.ListArtifacts.return_value = (
        _BuildMockArtifactDescriptors())

    self.client._RetrieveSupportedArtefacts()
    self.assertCountEqual(
        self.client.GetSupportedArtefactNames(),
        ['AllOS_File', 'AllOS_ArtifactGroup', 'Darwin_GRRClientAction',
         'Darwin_ArtifactFiles', 'Mixed'])

  def test_DetermineSourceForArtefact(self):
    """Tests determining the source type for a mixed type Artefact."""
    result = self.client._DetermineSourceForArtefact('Mixed')

    self.assertEqual(
        result, artifact_pb2.ArtifactSource.SourceType.FILE)


class PathSpecMapperTest(parameterized.TestCase):
  """Tests the _PathSpecMapper class."""

  pathspecmapper_win = grr_shell_client._PathSpecMapper()
  pathspecmapper_lin = grr_shell_client._PathSpecMapper()

  def setUp(self):  # pylint: disable=arguments-differ
    """Set up tests."""
    super().setUp()
    self.pathspecmapper_win['C:/'] = jobs_pb2.PathSpec.NTFS
    self.pathspecmapper_win['D:/'] = jobs_pb2.PathSpec.OS

    self.pathspecmapper_lin['/'] = jobs_pb2.PathSpec.OS
    self.pathspecmapper_lin['/mnt/external'] = jobs_pb2.PathSpec.OS
    self.pathspecmapper_lin['/mnt/external_ntfs'] = jobs_pb2.PathSpec.NTFS

  def test_PathSpecMapper_SetItem(self):
    """Tests adding mappings to _PathSpecMapper.

    Mappings are added in setup(), this just tests they are as expected.
    """
    self.assertDictEqual(self.pathspecmapper_win._path_ps_map,
                         {'C:/': jobs_pb2.PathSpec.NTFS,
                          'D:/': jobs_pb2.PathSpec.OS})

    self.assertDictEqual(self.pathspecmapper_lin._path_ps_map,
                         {'/': jobs_pb2.PathSpec.OS,
                          '/mnt/external': jobs_pb2.PathSpec.OS,
                          '/mnt/external_ntfs': jobs_pb2.PathSpec.NTFS})

  @parameterized.named_parameters(
      ('c_drive', 'C:/file', jobs_pb2.PathSpec.NTFS),
      ('d_drive', 'D:/file', jobs_pb2.PathSpec.OS),
      ('e_drive', 'E:/file', jobs_pb2.PathSpec.OS),
  )
  def test_PathSpecmapper_win_GetItem(self, path, expected_value):
    """Tests getting a mapping from _PathSpecMapper - windows edition."""
    self.assertEqual(self.pathspecmapper_win[path], expected_value)

  @parameterized.named_parameters(
      ('root', '/home/file', jobs_pb2.PathSpec.OS),
      ('mapped_ext', '/mnt/external/file', jobs_pb2.PathSpec.OS),
      ('mapped_ntfs', '/mnt/external_ntfs/file', jobs_pb2.PathSpec.NTFS),
  )
  def test_PathSpecmapper_lin_GetItem(self, path, expected_value):
    """Tests getting a mapping from _PathSpecMapper - linux edition."""
    self.assertEqual(self.pathspecmapper_lin[path], expected_value)


if __name__ == '__main__':
  absltest.main()
