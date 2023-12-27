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
"""Unit tests for the Grr Shell REPL driver."""

# pylint: disable=wrong-import-order
import contextlib
import datetime
import io
import sys
from unittest import mock

import prompt_toolkit

from grr_api_client import api as grr_api
from grrshell.lib import errors
from grrshell.lib import grr_shell_client
from grrshell.lib import grr_shell_emulated_fs
from grrshell.lib import grr_shell_repl
from absl.testing import absltest
from absl.testing import parameterized


_SAMPLE_TIMELINE_LINUX = 'grrshell/tests/testdata/sample_timeline_linux'
_SAMPLE_TIMELINE_WINDOWS = 'grrshell/tests/testdata/sample_timeline_windows'

_COMMANDS = ('help', 'ls', 'pwd', 'cd', 'refresh', 'info', 'collect', 'find',
             'flows', 'exit', 'set', 'artefact', 'clear', 'resume', 'detail')
_ALIASES = ('h', '?', 'hash', 'quit')
_ARTIFACT_NAMES = ['first', 'second', 'third', 'fourth']

_CLIENT_ID = 'C.0000000000000001'


# pylint: disable=protected-access
# pylint: disable=consider-using-with


class GRRShellREPLTest(parameterized.TestCase):
  """Unit tests for the Grr Shell REPL driver."""

  shell: grr_shell_repl.GRRShellREPL

  @mock.patch.object(grr_api, 'InitHttp', autospec=True)
  @mock.patch.object(grr_shell_client.GRRShellClient, '_ResolveClientID')
  @mock.patch.object(grr_shell_client.GRRShellClient, 'GetOS')
  @mock.patch.object(grr_shell_client.GRRShellClient, 'CollectTimeline')
  def setUp(self,  # pylint: disable=arguments-differ
            mock_collect_timeline,
            mock_get_os,
            mock_resolve_client_id,
            _mock_init_http):
    """Set up tests."""
    super().setUp()

    mock_collect_timeline.return_value = open(
        _SAMPLE_TIMELINE_LINUX, 'rb').read()
    mock_get_os.return_value = 'Linux'
    mock_resolve_client_id.return_value = _CLIENT_ID

    shell_client = grr_shell_client.GRRShellClient('url', 'user', 'pass', 'host.domain.com')
    shell_client.StartBackgroundMonitors()
    self.shell = grr_shell_repl.GRRShellREPL(shell_client)

  def test_Init(self):
    """Tests initialisation."""
    self.assertIsNotNone(self.shell)

  def test_GeneratePrompt(self):
    """Tests the _GeneratePrompt method."""
    result = self.shell._GeneratePrompt()
    self.assertEqual(result, f'{_CLIENT_ID}:/ $ ')

  @parameterized.named_parameters(
      ('online', 300, 'class:online', '3 minutes', '4 minutes'),
      ('stale', 1000, 'class:stale', '15 minutes', '16 minutes'),
      ('offline', 30000, 'class:offline', '8 hours', '8 hours'),
  )
  @mock.patch('datetime.datetime', wraps=datetime.datetime)
  def test_GenerateBottomBar(self,
                             now,
                             expected_format_class,
                             expected_relative_lastseen,
                             expected_relative_timeline,
                             mock_dt):
    """Tests generating the status bar content."""
    def mock_isinstance_method(obj, classinfo):  # pylint: disable=invalid-name
      """Mocked version of isinstance needed due to the wrapping of datetime."""
      if hasattr(classinfo, '_mock_wraps'):
        return isinstance(obj, classinfo._mock_wraps)
      return isinstance(obj, classinfo)

    mock_dt.now.return_value = datetime.datetime.fromtimestamp(
        now, tz=datetime.timezone.utc)

    with (mock.patch.object(self.shell._grr_shell_client, 'GetRunningFlowCount'
                            ) as mock_get_flow_count,
          mock.patch.object(self.shell._grr_shell_client, 'GetLastSeenTime'
                            ) as mock_get_last_seen,
          mock.patch.object(self.shell._emulated_fs, 'GetTimelineTime'
                            ) as mock_get_timeline_time,
          mock.patch('humanize.time.isinstance') as mock_isinstance):
      mock_get_flow_count.return_value = 4, 8
      mock_get_last_seen.return_value = datetime.datetime.fromtimestamp(
          75, tz=datetime.timezone.utc)
      mock_get_timeline_time.return_value = 1000000  # microseconds past epoch
      mock_isinstance.side_effect = mock_isinstance_method

      result = self.shell._GenerateBottomBar()
      self.assertEqual(
          result,
          [(expected_format_class, ' Last seen: 1970-01-01 00:01:15 '
                                   f'({expected_relative_lastseen} ago) '),
           ('class:bottom-toolbar', ' 4/8 flows running '),
           (expected_format_class, ' Timeline freshness: 1970-01-01 00:00:01'
                                   f' ({expected_relative_timeline} ago) ')])

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_help(self, mock_prompt):
    """Tests printing help text, and its content."""
    mock_prompt.side_effect = ['help', EOFError]

    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
      self.shell.RunShell()

      for c in _COMMANDS:
        self.assertIn(f'\t{c} ', buf.getvalue())
      for c in _ALIASES:
        self.assertNotIn(f'\t{c} ', buf.getvalue())

  @parameterized.named_parameters(
      ('with_path', 'ls path', 'path', None, True),
      ('without_path', 'ls', None, None, True),
      ('without_path_reversed', 'ls -r', None, None, False),
      ('without_path_size', 'ls -S', None, 'S', True),
      ('without_path_time', 'ls -t', None, 't', True),
      ('without_path_time_reversed', 'ls -tr', None, 't', False),
  )
  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_ls(self,
                       in_text,
                       expected_path,
                       expected_sort_key,
                       expected_reversed,
                       mock_prompt):
    """Tests entering ls at the prompt correctly calls ls for the emulated_fs."""
    mock_prompt.side_effect = [in_text, EOFError]

    with mock.patch.object(self.shell._emulated_fs, 'Ls') as mock_ls:
      self.shell.RunShell()
      mock_ls.assert_called_once_with(expected_path,
                                      expected_sort_key,
                                      expected_reversed)

  @parameterized.named_parameters(
      ('nonexistent', 'ls /nonexist', 'No such file or directory: /nonexist'),
      ('bad_glob', 'ls /tm*/file',
       'Globbing only supported for the final path component: /tm*'),
      ('invalid_option', 'ls -x', 'option -x not recognized'),
      ('mutually_exclusive_options', 'ls -St',
       'Options S, t are mutually exclusive'),
  )
  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_ls_error(self, in_text, expected_error, mock_prompt):
    """Tests ls failure modes."""
    mock_prompt.side_effect = [in_text, EOFError]

    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
      self.shell.RunShell()
      self.assertIn(expected_error, buf.getvalue())

  def test_LS_Colours(self):
    """Tests the colouring of LS results."""
    with mock.patch.object(self.shell._emulated_fs, 'Ls') as mock_ls:
      mock_ls.return_value = [
          grr_shell_emulated_fs._LSEntry('d------', 1, 2, 3, '4', 'directory'),
          grr_shell_emulated_fs._LSEntry('l------', 5, 6, 7, '8', 'symlink'),
          grr_shell_emulated_fs._LSEntry('-------', 9, 10, 11, '12', 'file')
      ]

      with io.StringIO() as buf, contextlib.redirect_stdout(buf):
        self.shell._Ls(['/path'])

        output = buf.getvalue()

        self.assertIn(' \x1b[94mdirectory\x1b[0m', output)
        self.assertIn(' \x1b[93msymlink\x1b[0m', output)
        self.assertIn(' file', output)

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_cd(self, mock_prompt):
    """Tests entering cd at the prompt correctly calls cd for the emulated_fs."""
    mock_prompt.side_effect = ['cd path', EOFError]

    with mock.patch.object(self.shell._emulated_fs, 'Cd') as mock_cd:
      self.shell.RunShell()
      mock_cd.assert_called_once_with('path')

  @parameterized.named_parameters(
      ('nonexistent', 'cd /nonexistent',
       'No such file or directory: /nonexistent'),
      ('file', 'cd /root/.bashrc', 'Not a directory: /root/.bashrc'),
  )
  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_cd_error(self, in_text, expected, mock_prompt):
    """Tests invalid cd arguments."""
    mock_prompt.side_effect = [in_text, EOFError]

    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
      self.shell.RunShell()
      self.assertIn(expected, buf.getvalue())

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_pwd(self, mock_prompt):
    """Tests entering pwd at the prompt correctly calls GetPWD for the emulated_fs."""
    mock_prompt.side_effect = ['pwd', EOFError]

    with mock.patch.object(self.shell._emulated_fs, 'GetPWD') as mock_pwd:
      self.shell.RunShell()

      # 3 because PWD gets called in prompt generation, which happens twice, and
      # once more because we've ran the shell command.
      self.assertEqual(mock_pwd.call_count, 3)

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_refresh(self, mock_prompt):
    """Tests entering refresh at the prompt correctly collects and parses a timeline."""
    mock_prompt.side_effect = ['refresh', EOFError]

    with (mock.patch.object(self.shell._grr_shell_client,
                            'CollectTimeline') as mock_collect_timeline,
          mock.patch.object(self.shell._emulated_fs,
                            'ParseTimelineFlow') as mock_parse_timeline):
      self.shell.RunShell()
      mock_collect_timeline.assert_called_once()
      mock_parse_timeline.assert_called_once_with(
          mock_collect_timeline.return_value, 0)

  def test_Refresh_cwd(self):
    """Tests running refresh manually on the current working dir."""
    with (mock.patch.object(self.shell._grr_shell_client,
                            'CollectTimeline') as mock_collect_timeline,
          mock.patch.object(self.shell._emulated_fs,
                            'ParseTimelineFlow') as mock_parse_timeline):
      self.shell._Cd(['/root'])
      self.shell._Refresh(['.'])
      mock_collect_timeline.assert_called_once()
      mock_parse_timeline.assert_called_once_with(
          mock_collect_timeline.return_value, 0)

  @parameterized.named_parameters(
      ('basic', 'collect path', '/path'),
      ('directory', 'collect root', '/root/*'),
      ('recursive', 'collect root/**', '/root/**'),
      ('file', 'collect root/.bashrc', '/root/.bashrc'),
  )
  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_collect(self, in_text, expected_param, mock_prompt):
    """Tests entering collect at the prompt correctly calls CollectFilesInBackground."""
    mock_prompt.side_effect = [in_text, EOFError]

    with (mock.patch.object(self.shell._grr_shell_client,
                            'CollectFilesInBackground') as mock_collect):
      self.shell.RunShell()
      mock_collect.assert_called_once_with(expected_param, './')

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_info(self, mock_prompt):
    """Tests entering stat at the prompt correctly calls StatFile."""
    mock_prompt.side_effect = ['info /path', EOFError]

    with (mock.patch.object(self.shell._grr_shell_client,
                            'FileInfo') as mock_fileinfo):
      self.shell.RunShell()
      mock_fileinfo.assert_called_once_with('/path', False)

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_info_offline(self, mock_prompt):
    """Tests entering stat at the prompt correctly calls StatFile."""
    mock_prompt.side_effect = ['info /path --offline', EOFError]

    with (mock.patch.object(self.shell._emulated_fs,
                            'OfflineFileInfo') as mock_fileinfo):
      self.shell.RunShell()
      mock_fileinfo.assert_called_once_with('/path')

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_flows(self, mock_prompt):
    """Tests entering flows at the prompt correctly calls GetBackgroundFlowsState."""
    mock_prompt.side_effect = ['flows', EOFError]

    with (mock.patch.object(self.shell._grr_shell_client,
                            'GetBackgroundFlowsState') as mock_flows):
      self.shell.RunShell()
      mock_flows.assert_called_once()

  @parameterized.named_parameters(
      ('default', 'flows --all', 50),
      ('with_count', 'flows --all 30', 30),
      ('invalid_count', 'flows --all asdf', 50)
  )
  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_flows_all(self, in_text, expected_count, mock_prompt):
    """Tests entering flows --all at the prompt correctly calls ListAllFlows."""
    mock_prompt.side_effect = [in_text, EOFError]

    with (mock.patch.object(self.shell._grr_shell_client,
                            'ListAllFlows') as mock_list_all):
      self.shell.RunShell()
      mock_list_all.assert_called_once_with(count=expected_count)

  @parameterized.named_parameters(
      ('one_param', 'find a', './', 'a'),
      ('two_param', 'find a b', 'a', 'b'),
  )
  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_find(
      self, in_text, expected_param1, expected_param2, mock_prompt):
    """Tests entering find at the prompt correctly calls find for the emaulated fs."""
    mock_prompt.side_effect = [in_text, EOFError]

    with mock.patch.object(self.shell._emulated_fs, 'Find') as mock_find:
      self.shell.RunShell()
      mock_find.assert_called_once_with(expected_param1, expected_param2)

  @parameterized.named_parameters(
      ('bare', 'set', 'Valid properties: max-file-size'),
      ('invalid_name', 'set invalid', 'Valid properties: max-file-size'),
      ('no_value', 'set max-file-size', 'set requires two parameters'),
  )
  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_set_invalid(self, in_text, expected_out, mock_prompt):
    """Tests entinering set with invalid params at the prompt."""
    mock_prompt.side_effect = [in_text, EOFError]

    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
      self.shell.RunShell()
      self.assertIn(expected_out, buf.getvalue())

  @parameterized.named_parameters(
      ('zero', 'set max-file-size 0', 0),
      ('10', 'set max-file-size 10', 10),
  )
  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_set_maxfilesize(self, in_text, expected_param, mock_prompt):
    """Tests setting the max file size."""
    mock_prompt.side_effect = [in_text, EOFError]

    with (mock.patch.object(self.shell._grr_shell_client,
                            'SetMaxFilesize') as mock_set_file_size):
      self.shell.RunShell()
      mock_set_file_size.assert_called_once_with(expected_param)

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  @mock.patch.object(sys, 'exit')
  def test_RunShell_exit(self, mock_exit, mock_prompt):
    """Tests entering exit at the prompt correctly exits."""
    mock_prompt.side_effect = ['exit', EOFError]

    self.shell.RunShell()
    mock_exit.assert_called_once()

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  @mock.patch.object(prompt_toolkit.shortcuts, 'clear')
  def test_RunShell_clear(self, mock_clear, mock_prompt):
    """Tests entering clear at the prompt correctly calls the clear method."""
    mock_prompt.side_effect = ['clear', EOFError]

    self.shell.RunShell()
    mock_clear.assert_called_once()

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  @mock.patch.object(prompt_toolkit.shortcuts, 'clear', autospec=True)
  @mock.patch.object(sys, 'exit', autospec=True)
  def test_RunShell_multiple(self, mock_exit, mock_clear, mock_prompt):
    """Tests entering multiple commands works correctly."""
    mock_prompt.side_effect = ['clear', 'exit', EOFError]
    self.shell.RunShell()
    mock_clear.assert_called_once()
    mock_exit.assert_called_once()

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_invalid_command(self, mock_prompt):
    """Tests an invalid command only complains (ie, no exceptions thrown.)"""
    mock_prompt.side_effect = ['invalid', EOFError]

    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
      self.shell.RunShell()
      self.assertIn('Unrecognised command', buf.getvalue())

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_empty(self, mock_prompt):
    """Tests an empty command (ie, no exceptions thrown.)"""
    mock_prompt.side_effect = ['', EOFError]

    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
      self.shell.RunShell()
      self.assertEqual('Exiting\n', buf.getvalue())

  @parameterized.named_parameters(
      ('american_spelling', 'artifact name'),
      ('correct_spelling', 'artefact name'),
  )
  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_artifact(self, in_text, mock_prompt):
    """Tests 'artifact' at the prompt calls CollectArtifactsInBackground."""
    with mock.patch.object(self.shell._grr_shell_client,
                           'CollectArtefact') as mock_collect:
      mock_prompt.side_effect = [in_text, EOFError]
      self.shell.RunShell()
      mock_collect.assert_called_once_with('name', './')

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  @mock.patch.object(sys, 'exit')
  def test_RunShell_CTRLC(self, mock_exit, mock_prompt):
    """Tests that if the user hits CTRL+C, they are returned to the prompt."""
    mock_prompt.side_effect = ['info path', KeyboardInterrupt, 'exit', EOFError]

    with mock.patch.object(
        self.shell._grr_shell_client, 'FileInfo') as mock_stat:
      mock_stat.side_effect = [KeyboardInterrupt]

      self.shell.RunShell()
      mock_exit.assert_called_once()

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  @mock.patch.object(sys, 'exit')
  def test_RunShell_UnknownException(self, mock_exit, mock_prompt):
    """Tests that if the user hits CTRL+C, they are returned to the prompt."""
    mock_prompt.side_effect = ['info path', 'exit', EOFError]

    with mock.patch.object(
        self.shell._grr_shell_client, 'FileInfo') as mock_info:
      mock_info.side_effect = [RuntimeError('Test RuntimeError')]

      with io.StringIO() as buf, contextlib.redirect_stdout(buf):
        self.shell.RunShell()
        self.assertIn(
            "Unknown exception: <class 'RuntimeError'> - Test RuntimeError",
            buf.getvalue())
        mock_exit.assert_called_once()

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_resume(self, mock_prompt):
    """Tests resuming a flow works as expected."""
    mock_prompt.side_effect = ['resume flowid', EOFError]

    with mock.patch.object(
        self.shell._grr_shell_client, 'ReattachFlow') as mock_resume:

      self.shell.RunShell()
      mock_resume.assert_called_once_with('flowid', './')

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_resume_error(self, mock_prompt):
    """Tests resuming an invalid flow is correctly handled."""
    mock_prompt.side_effect = ['resume flowid', EOFError]

    with mock.patch.object(
        self.shell._grr_shell_client, 'ReattachFlow') as mock_resume:
      mock_resume.side_effect = errors.NotResumeableFlowTypeError('test error')

      with io.StringIO() as buf, contextlib.redirect_stdout(buf):
        self.shell.RunShell()

        mock_resume.assert_called_once_with('flowid', './')
        self.assertIn('test error', buf.getvalue())

  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_detail(self, mock_prompt):
    """Tests entering detail at the prompt calls the correct method."""
    mock_prompt.side_effect = ['detail flowid', EOFError]

    with mock.patch.object(
        self.shell._grr_shell_client, 'FlowDetail') as mock_detail:

      self.shell.RunShell()
      mock_detail.assert_called_once_with('flowid')

  @parameterized.named_parameters(
      ('short_only', 'help ls', grr_shell_repl._LS_HELP.short),
      ('long_check_short', 'help find', grr_shell_repl._FIND_HELP.short),
      ('long_check_long', 'help find', grr_shell_repl._FIND_HELP_LONG),
      ('invalid', 'help foobar', 'Unknown command'),
  )
  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_extended_help(self, in_text, expected, mock_prompt):
    """Tests fetching extended help text for a command."""
    mock_prompt.side_effect = [in_text, EOFError]

    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
      self.shell.RunShell()

      self.assertIn(expected, buf.getvalue())

  @parameterized.named_parameters(
      ('help', 'help one two', grr_shell_repl._HELP_HELP.short),
      ('ls', 'ls one two', grr_shell_repl._LS_HELP.short),
      ('cd', 'cd one two', grr_shell_repl._CD_HELP.short),
      ('refresh', 'refresh one two', grr_shell_repl._REFRESH_HELP.short),
      ('collect', 'collect', grr_shell_repl._COLLECT_HELP.short),
      ('find_short', 'find', grr_shell_repl._FIND_HELP.short),
      ('find_long', 'find one two three', grr_shell_repl._FIND_HELP.short),
      ('artefact', 'artefact', grr_shell_repl._ARTEFACT_HELP.short),
      ('info_flags', 'info --ads --offline', grr_shell_repl._INFO_HELP.short),
      ('info_count', 'info', grr_shell_repl._INFO_HELP.short),
      ('resume', 'resume', grr_shell_repl._RESUME_HELP.short),
      ('detail', 'detail', grr_shell_repl._DETAIL_HELP.short)
  )
  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_malformed_command(self, in_text, expected, mock_prompt):
    """Tests output when command syntax is incorrect."""
    mock_prompt.side_effect = [in_text, EOFError]

    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
      self.shell.RunShell()

      self.assertIn(expected, buf.getvalue())


class GRRShellREPLTestWindows(parameterized.TestCase):
  """Windows specific unit tests for the Grr Shell REPL driver."""

  shell: grr_shell_repl.GRRShellREPL

  @mock.patch.object(grr_api, 'InitHttp')
  @mock.patch.object(grr_shell_client.GRRShellClient, '_ResolveClientID')
  @mock.patch.object(grr_shell_client.GRRShellClient, 'GetOS')
  @mock.patch.object(grr_shell_client.GRRShellClient, 'CollectTimeline')
  def setUp(self,  # pylint: disable=arguments-differ
            mock_collect_timeline,
            mock_get_os,
            mock_resolve_client_id,
            _mock_init_http):
    """Set up tests."""
    super().setUp()

    mock_collect_timeline.return_value = open(
        _SAMPLE_TIMELINE_WINDOWS, 'rb').read()
    mock_get_os.return_value = 'Windows'
    mock_resolve_client_id.return_value = _CLIENT_ID

    shell_client = grr_shell_client.GRRShellClient('url', 'user', 'pass', 'host.domain.com')
    shell_client.StartBackgroundMonitors()
    self.shell = grr_shell_repl.GRRShellREPL(shell_client)

  @parameterized.named_parameters(
      ('no_ads', 'info C:/pagefile.sys', '/C:/pagefile.sys', False),
      ('with_ads', 'info C:/pagefile.sys --ads', '/C:/pagefile.sys', True),
      ('with_ads_but_directory', 'info C:/$Recycle.Bin --ads',
       '/C:/$Recycle.Bin', False),
  )
  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_info(self,
                         in_text,
                         expected_filepath,
                         ads_expected,
                         mock_prompt):
    """Tests entering stat at the prompt correctly calls StatFile."""
    mock_prompt.side_effect = [in_text, EOFError]

    with (mock.patch.object(self.shell._grr_shell_client,
                            'FileInfo') as mock_fileinfo):
      self.shell.RunShell()
      mock_fileinfo.assert_called_once_with(expected_filepath, ads_expected)

  @parameterized.named_parameters(
      ('with_slash', 'refresh D:/'),
      ('without_slash', 'refresh D:'),
  )
  @mock.patch.object(prompt_toolkit.PromptSession, 'prompt', autospec=True)
  def test_RunShell_refresh_d_drive(self, in_text, mock_prompt):
    """Tests attempting to refresh a Windows volume."""
    mock_prompt.side_effect = [in_text, EOFError]

    with (mock.patch.object(self.shell._grr_shell_client,
                            'CollectTimeline') as mock_collect_timeline,
          mock.patch.object(self.shell._emulated_fs,
                            'ClearPath') as mock_clear_path):
      self.shell.RunShell()

      mock_collect_timeline.assert_called_once_with('D:/', None)
      mock_clear_path.assert_called_once_with('D:/', 0)


class GrrShellREPLPromptCompleterLinuxTest(parameterized.TestCase):
  """Unit tests for the Grr Shell REPL autompleter for Linux."""

  def setUp(self):  # pylint: disable=arguments-differ
    """Set up tests."""
    super().setUp()
    timeline_data = open(
        _SAMPLE_TIMELINE_LINUX, 'rb').read()

    emulated_fs = grr_shell_emulated_fs.GrrShellEmulatedFS('Linux')
    emulated_fs.ParseTimelineFlow(timeline_data)

    mock_grr_client = mock.MagicMock()
    mock_grr_client.GetOS.return_value = 'Linux'

    repl = grr_shell_repl.GRRShellREPL(mock_grr_client)
    commands = [
        name for name in repl._commands if not repl._commands[name].is_alias]
    commands_with_params = [
        name for name in repl._commands if repl._commands[name].path_param]

    self.completer = grr_shell_repl._GrrShellREPLPromptCompleter(
        emulated_fs, commands, commands_with_params, _ARTIFACT_NAMES)

  def test_Init(self):
    """Tests initialisation."""
    self.assertIsNotNone(self.completer)

  @parameterized.named_parameters(
      # go/keep-sorted start
      ('artefact_f', 'artefact f', ['first', 'fourth'], -1),
      ('artefact_first', 'artefact first', []),
      ('artefact_ir', 'artefact ir', ['first', 'third'], -2),
      ('artefact_space', 'artefact ', []),
      ('artifact_r', 'artifact r', ['first', 'third', 'fourth'], -1),
      ('cd_error', 'cd /nonexist', []),
      ('cd_invalid', 'cd root/xxx/dir', []),
      ('cd_only', 'cd', ['cd'], -2),
      ('cd_r', 'cd r', ['root/'], -1),
      ('cd_root', 'cd root/', ['..', '.pki/', '.cache/', '.local/', '.ssh/',
                               '.augeas/', r'directory\ with\ spaces/']),
      ('cd_space_only', 'cd ', ['..', 'root/', 'odd/']),
      ('cd_spaces', 'cd root/dir', [r'directory\ with\ spaces/'], -3),
      ('collect_space_only', 'collect ', ['..', 'root/', 'odd/', 'root_file']),
      ('empty', '', ['help', 'ls', 'pwd', 'cd', 'info', 'refresh', 'collect',
                     'exit', 'flows', 'find', 'set', 'artefact', 'clear',
                     'resume', 'detail']),
      ('find_space_only', 'find ', []),
      ('hash_space_only', 'hash ', ['..', 'root/', 'odd/', 'root_file']),
      ('help_c', 'help c', ['cd', 'clear', 'collect'], -1),
      ('info_space_only', 'info ', ['..', 'root/', 'odd/', 'root_file']),
      ('ls_bare', 'ls', ['ls'], -2),
      ('ls_r', 'ls r', ['root/', 'root_file'], -1),
      ('ls_root', 'ls root/', ['..', '.pki/', '.cache/', '.local/', '.ssh/',
                               '.augeas/', '.bashrc', '.profile', '.wget-hsts',
                               '.lesshst', 'dead.letter', 'xorg.conf.new',
                               r'directory\ with\ spaces/']),
      ('ls_space_only', 'ls ', ['..', 'root/', 'root_file', 'odd/']),
      ('ls_spaces', r'ls root/directory\ with\ spaces/f',
       [r'file\ with\ spaces'], -1),
      ('pwd_extra', 'pwd extra', []),
      ('pwd_space_only', 'pwd ', []),
      ('refresh_bare', 'refresh', ['refresh'], -7),
      ('refresh_space', 'refresh ', ['..', 'root/', 'odd/']),
      ('set_space_only', 'set ', []),
      ('single_char', 'c', ['cd', 'collect', 'clear'], -1),
      ('too_many', 'cd one two', [])
      # go/keep-sorted end
  )
  def test_GetCompletion(self,
                         in_text,
                         expected_suggestions,
                         expected_offset=0):
    """Tests the get_completion method."""
    document = prompt_toolkit.document.Document(in_text, len(in_text))

    results = list(self.completer.get_completions(document, None))
    self.assertCountEqual(expected_suggestions, [r.text for r in results])
    self.assertCountEqual([expected_offset] * len(expected_suggestions),
                          [r.start_position for r in results])


class GrrShellREPLPromptCompleterWindowsTest(parameterized.TestCase):
  """Unit tests for the Grr Shell REPL autompleter for Windows."""

  def setUp(self):  # pylint: disable=arguments-differ
    """Set up tests."""
    super().setUp()
    timeline_data = open(
        _SAMPLE_TIMELINE_WINDOWS, 'rb').read()

    emulated_fs = grr_shell_emulated_fs.GrrShellEmulatedFS('Windows')
    emulated_fs.ParseTimelineFlow(timeline_data)

    mock_grr_client = mock.MagicMock()
    mock_grr_client.GetOS.return_value = 'Windows'

    repl = grr_shell_repl.GRRShellREPL(mock_grr_client)
    commands = [
        name for name in repl._commands if not repl._commands[name].is_alias]
    commands_with_params = [
        name for name in repl._commands if repl._commands[name].path_param]

    self.completer = grr_shell_repl._GrrShellREPLPromptCompleter(
        emulated_fs, commands, commands_with_params, _ARTIFACT_NAMES)

  def test_Init(self):
    """Tests initialisation."""
    self.assertIsNotNone(self.completer)

  @parameterized.named_parameters(
      ('empty', '', ['help', 'ls', 'pwd', 'cd', 'info', 'refresh', 'collect',
                     'exit', 'flows', 'find', 'set', 'artefact', 'clear',
                     'resume', 'detail']),
      ('single_char', 'c', ['cd', 'collect', 'clear']),
      ('cd_only', 'cd', ['cd']),
      ('cd_error', 'cd /nonexist', []),
      ('cd_root', 'cd C:/', ['$Recycle.Bin/', '$WinREAgent/', 'Config.Msi/',
                             r'Documents\ and\ Settings/', 'PerfLogs/',
                             r'Program\ Files/', '..']),
      ('ls_root', 'ls C:/', ['$Recycle.Bin/', '$WinREAgent/', 'Config.Msi/',
                             r'Documents\ and\ Settings/', 'DumpStack.log.tmp',
                             'hiberfil.sys', 'pagefile.sys', 'PerfLogs/',
                             r'Program\ Files/', '..'])
  )
  def test_GetCompletion(self, in_text, expected_suggestions):
    """Tests the get_completion method."""
    document = prompt_toolkit.document.Document(in_text, len(in_text))

    results = (c.text for c in self.completer.get_completions(document, None))
    self.assertCountEqual(expected_suggestions, results)


if __name__ == '__main__':
  absltest.main()
