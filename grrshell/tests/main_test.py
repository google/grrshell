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
"""Unit tests for main driver."""

# pylint: disable=wrong-import-order,ungrouped-imports
import contextlib
import datetime
import io
import os
from unittest import mock

from absl.testing import flagsaver

from grrshell.lib import errors
from grrshell.lib import grr_shell_client
from grrshell.lib import grr_shell_repl
from grrshell.cli import main
from absl.testing import absltest
from absl.testing import parameterized


# pylint: disable=unused-argument


main.Main.DefineFlags()


class MainTest(parameterized.TestCase):
  """Unit test for GRRShell Main driver."""

  def setUp(self):  # pylint: disable=arguments-differ
    """Set up the test suite."""
    super().setUp()

    self.main = main.Main()

  @parameterized.named_parameters(
      ('with_command', ['binary_path', 'shell']),
      ('no_command', ['binary_path'])
  )
  @flagsaver.flagsaver(**{'grr-server': 'server-address', 'username': 'grr-user', 'password': 'grr-password'})
  @flagsaver.flagsaver(client='C.000')
  @mock.patch.object(grr_shell_client.GRRShellClient, '__new__', autospec=True)
  @mock.patch.object(grr_shell_repl.GRRShellREPL, '__new__', autospec=True)
  def test_RunShell(self, args, mock_repl, mock_client):
    """Tests that when no command is provided, `shell` is used."""
    self.main.main(args)

    mock_client.assert_called_once_with(
        grr_shell_client.GRRShellClient, 'server-address', 'grr-user', 'grr-password', 'C.000', 0)
    mock_repl.assert_called_once_with(
        grr_shell_repl.GRRShellREPL, mock_client.return_value, True, '')
    mock_repl.return_value.RunShell.assert_called_once()

  @flagsaver.flagsaver(**{'grr-server': 'server-address', 'username': 'grr-user', 'password': 'grr-password'})
  @flagsaver.flagsaver(debug=True, client='C.000')
  @mock.patch.object(grr_shell_client.GRRShellClient, '__new__', autospec=True)
  @mock.patch.object(grr_shell_repl.GRRShellREPL, '__new__', autospec=True)
  @mock.patch('datetime.datetime', wraps=datetime.datetime)
  def test_DebugLogging(self, mock_dt, mock_repl, mock_client):
    """Tests a debug log file is created if `--debug` is specified."""
    mock_dt.now.return_value = datetime.datetime.fromtimestamp(
        10, tz=datetime.timezone.utc)  # 10 seconds past epoch

    self.main.main([])

    self.assertTrue(os.path.exists('/tmp/grrshell_19700101T000010.log'))

  @mock.patch.object(grr_shell_client.GRRShellClient, '__new__', autospec=True)
  @mock.patch.object(grr_shell_repl.GRRShellREPL, '__new__', autospec=True)
  def test_Help(self, mock_repl, mock_client):
    """Tests calling help outputs the help text and exits."""
    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
      self.main.main(['binary_path', 'help'])

      self.assertIn(main._USAGE(), buf.getvalue())  # pylint: disable=protected-access

    mock_client.assert_not_called()
    mock_repl.assert_not_called()

  @parameterized.named_parameters(
      ('no_client_id', 'shell', {}, '--client is required'),
      ('conflicting_timelines', 'shell', {'client': 'C.000',
                                          'no-initial-timeline': True,
                                          'initial-timeline': 'ABCDEF012345'},
       '--no-initial-timeline and --initial-timeline are mutually exclusive.'),
      ('invalid_command', 'invalid', {'client': 'C.000'},
       'Unrecognised command')
  )
  @mock.patch.object(grr_shell_client.GRRShellClient, '__new__', autospec=True)
  @mock.patch.object(grr_shell_repl.GRRShellREPL, '__new__', autospec=True)
  @flagsaver.flagsaver(**{'grr-server': 'server-address', 'username': 'grr-user', 'password': 'grr-password'})
  def test_InvalidArgs(self,
                       command,
                       flags,
                       expected_error,
                       mock_repl,
                       mock_client):
    """Tests invalid args correctly exit the tool."""
    with flagsaver.flagsaver(**flags):
      with io.StringIO() as buf, contextlib.redirect_stdout(buf):
        self.main.main(['binary_path', command])

        self.assertIn(expected_error, buf.getvalue())

    mock_client.assert_not_called()
    mock_repl.assert_not_called()

  @flagsaver.flagsaver(**{'grr-server': 'server-address', 'username': 'grr-user', 'password': 'grr-password'})
  @flagsaver.flagsaver(**{'client': 'C.000',
                          'artefact': 'BrowserHistory',
                          'local-path': '/local/path'})
  @mock.patch.object(grr_shell_client.GRRShellClient, '__new__', autospec=True)
  def test_Artefact(self, mock_client):
    """Tests using the artefact command."""
    self.main.main(['binary_path', 'artefact'])

    mock_client.assert_called_once_with(
        grr_shell_client.GRRShellClient, 'server-address', 'grr-user', 'grr-password', 'C.000', 0)
    mock_client.return_value.ScheduleAndDownloadArtefact.assert_called_once_with(
        'BrowserHistory', '/local/path')

  @flagsaver.flagsaver(**{'grr-server': 'server-address', 'username': 'grr-user', 'password': 'grr-password'})
  @flagsaver.flagsaver(**{'client': 'C.000',
                          'remote-path': '/etc/passwd',
                          'local-path': '/local/path'})
  @mock.patch.object(grr_shell_client.GRRShellClient, '__new__', autospec=True)
  def test_Collect(self, mock_client):
    """Tests using the artefact command."""
    self.main.main(['binary_path', 'collect'])

    mock_client.assert_called_once_with(
        grr_shell_client.GRRShellClient, 'server-address', 'grr-user', 'grr-password', 'C.000', 0)
    mock_client.return_value.CollectFiles.assert_called_once_with(
        '/etc/passwd', '/local/path')

  @flagsaver.flagsaver(**{'grr-server': 'server-address', 'username': 'grr-user', 'password': 'grr-password'})
  @flagsaver.flagsaver(**{'client': 'C.000',
                          'flow': 'ABCDEF012345',
                          'local-path': '/local/path'})
  @mock.patch.object(grr_shell_client.GRRShellClient, '__new__', autospec=True)
  def test_Complete(self, mock_client):
    """Tests using the artefact command."""
    self.main.main(['binary_path', 'complete'])

    mock_client.assert_called_once_with(
        grr_shell_client.GRRShellClient, 'server-address', 'grr-user', 'grr-password', 'C.000', 0)
    mock_client.return_value.CompleteFlow.assert_called_once_with(
        'ABCDEF012345', '/local/path')

  @flagsaver.flagsaver(**{'grr-server': 'server-address', 'username': 'grr-user', 'password': 'grr-password'})
  @flagsaver.flagsaver(client='C.000')
  @mock.patch.object(grr_shell_client.GRRShellClient, '__new__', autospec=True)
  @mock.patch.object(grr_shell_repl.GRRShellREPL, '__new__', autospec=True)
  def test_ClientNotFound(self, mock_repl, mock_client):
    """Tests an unfound client correctly errors."""
    mock_client.side_effect = errors.ClientNotFoundError()

    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
      self.main.main(['binary_path', 'shell'])

      self.assertIn('Error accessing grr client', buf.getvalue())

    mock_client.assert_called_once_with(
        grr_shell_client.GRRShellClient, 'server-address', 'grr-user', 'grr-password', 'C.000', 0)
    mock_repl.assert_not_called()

  @flagsaver.flagsaver(**{'grr-server': 'server-address', 'username': 'grr-user', 'password': 'grr-password'})
  @flagsaver.flagsaver(client='C.000')
  @mock.patch.object(grr_shell_client.GRRShellClient, '__new__', autospec=True)
  @mock.patch.object(grr_shell_repl.GRRShellREPL, '__new__', autospec=True)
  def test_RequestClientAccess(self, mock_repl, mock_client):
    """Tests access is requested if not currently granted."""
    mock_client.return_value.CheckAccess.return_value = False
    mock_client.return_value.RequestAccess.return_value = True

    self.main.main(['binary_path', 'shell'])

    mock_client.assert_called_once_with(
        grr_shell_client.GRRShellClient, 'server-address', 'grr-user', 'grr-password', 'C.000', 0)
    mock_client.return_value.RequestAccess.assert_called_once()
    mock_repl.assert_called_once_with(
        grr_shell_repl.GRRShellREPL, mock_client.return_value, True, '')
    mock_repl.return_value.RunShell.assert_called_once()

  @flagsaver.flagsaver(**{'grr-server': 'server-address', 'username': 'grr-user', 'password': 'grr-password'})
  @flagsaver.flagsaver(**{'client': 'C.000', 'no-initial-timeline': True})
  @mock.patch.object(grr_shell_client.GRRShellClient, '__new__', autospec=True)
  @mock.patch.object(grr_shell_repl.GRRShellREPL, '__new__', autospec=True)
  def test_NoInitialTimeline(self, mock_repl, mock_client):
    """Tests no timeline is requested with appropriate flag use."""
    self.main.main(['binary_path', 'shell'])

    mock_client.assert_called_once_with(
        grr_shell_client.GRRShellClient, 'server-address', 'grr-user', 'grr-password', 'C.000', 0)
    mock_repl.assert_called_once_with(
        grr_shell_repl.GRRShellREPL, mock_client.return_value, False, '')
    mock_repl.return_value.RunShell.assert_called_once()

  @flagsaver.flagsaver(**{'grr-server': 'server-address', 'username': 'grr-user', 'password': 'grr-password'})
  @flagsaver.flagsaver(**{'client': 'C.000', 'initial-timeline': 'id'})
  @mock.patch.object(grr_shell_client.GRRShellClient, '__new__', autospec=True)
  @mock.patch.object(grr_shell_repl.GRRShellREPL, '__new__', autospec=True)
  def test_SpecifiedInitialTimeline(self, mock_repl, mock_client):
    """Tests a specific timeline is requested with appropriate flag use."""
    self.main.main(['binary_path', 'shell'])

    mock_client.assert_called_once_with(
        grr_shell_client.GRRShellClient, 'server-address', 'grr-user', 'grr-password', 'C.000', 0)
    mock_repl.assert_called_once_with(
        grr_shell_repl.GRRShellREPL, mock_client.return_value, True, 'id')
    mock_repl.return_value.RunShell.assert_called_once()

  @parameterized.named_parameters(
      ('zero', {}, 0),
      ('ten', {'max-file-size': '10'}, 10),
      ('invalid', {'max-file-size': 'asdf'}, 0),
  )
  @mock.patch.object(grr_shell_client.GRRShellClient, '__new__', autospec=True)
  @mock.patch.object(grr_shell_repl.GRRShellREPL, '__new__', autospec=True)
  @flagsaver.flagsaver(**{'grr-server': 'server-address', 'username': 'grr-user', 'password': 'grr-password'})
  def test_MaxFileSize(self, flags, expected_max_size, mock_repl, mock_client):
    """Tests usage of the max-file-size flag."""
    flags['client'] = 'C.000'
    with flagsaver.flagsaver(**flags):
      self.main.main(['binary_path', 'shell'])

    mock_client.assert_called_once_with(
        grr_shell_client.GRRShellClient, 'server-address', 'grr-user', 'grr-password', 'C.000', expected_max_size)
    mock_repl.assert_called_once_with(
        grr_shell_repl.GRRShellREPL, mock_client.return_value, True, '')
    mock_repl.return_value.RunShell.assert_called_once()


if __name__ == '__main__':
  absltest.main()
