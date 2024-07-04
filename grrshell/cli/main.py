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
"""GRR interactive shell. go/grrshell.

Supports commands shell, collect, artefact, help
"""

from collections.abc import Sequence
import datetime
import os
import sys
import tempfile
import typing

from absl import app
from absl import flags
from absl import logging

from grrshell.lib import errors
from grrshell.lib import grr_shell_client
from grrshell.lib import grr_shell_repl


logger = logging.logging.getLogger('grrshell')

# go/keep-sorted start
_ARTIFACT_HELP = (
    'The artifact to collect from GRR via an ArtifactCollector flow')
_CLIENT_HELP = 'GRR ID or hostname of client'
_DEBUG_HELP = 'Enable debug logging'
_GRR_PASSWORD_HELP = 'GRR password'
_GRR_SERVER_HELP = 'GRR HTTP Endpoint'
_GRR_USERNAME_HELP = 'GRR username'
_FLOW_HELP = 'A Flow ID'
_INITIAL_TIMELINE_HELP = (
    'Specify an existing timeline flow to use instead of looking for a recent '
    'flow, or launching a new timeline flow. (Optional)')
_LOCAL_PATH_HELP = 'Location to store the collected files. Default: "./"'
_MAX_FILE_SIZE_HELP = (
    'The max file size for GRR collection. 0 for the GRR default. (Optional)')
_NO_INITIAL_TIMELINE_HELP = (
    'Specify an existing timeline flow to use instead of looking for a recent '
    'flow, or launching a new timeline flow. (Optional)')
_REMOTE_PATH_HELP = 'ClientFileFinder expression for remote files'
_TIMELINE_THRESHOLD_HELP = (
    'Hours before a preexisting timeline is considered too old.')
# go/keep-sorted end


_COMMANDS = frozenset(
    ('shell', 'collect', 'artefact', 'artifact', 'complete', 'help'))


def _USAGE():
  return f"""grr_shell {{shell,collect,artefact,complete,help}}

shell - Start an (emulated) interactive shell with CLIENT_ID (default if no command specified)
  --{flags.FLAGS['username'].name} {_GRR_USERNAME_HELP}
  --{flags.FLAGS['password'].name} {_GRR_PASSWORD_HELP}
  --{flags.FLAGS['grr-server'].name} {_GRR_SERVER_HELP}
  --{flags.FLAGS['client'].name} {_CLIENT_HELP}
  --{flags.FLAGS['initial-timeline'].name} {_INITIAL_TIMELINE_HELP}
  --{flags.FLAGS['max-file-size'].name} {_MAX_FILE_SIZE_HELP}
  --{flags.FLAGS['no-initial-timeline'].name} {_NO_INITIAL_TIMELINE_HELP}
  --{flags.FLAGS['timeline-threshold'].name} {_TIMELINE_THRESHOLD_HELP}

collect - Collect files from the client (ClientFileFinder flow)
  --{flags.FLAGS['username'].name} {_GRR_USERNAME_HELP}
  --{flags.FLAGS['password'].name} {_GRR_PASSWORD_HELP}
  --{flags.FLAGS['grr-server'].name} {_GRR_SERVER_HELP}
  --{flags.FLAGS['client'].name} {_CLIENT_HELP}
  --{flags.FLAGS['remote-path'].name} {_REMOTE_PATH_HELP}
  --{flags.FLAGS['local-path'].name} {_LOCAL_PATH_HELP}
  --{flags.FLAGS['max-file-size'].name} {_MAX_FILE_SIZE_HELP}

artefact - Schedule and collect an ArtifactCollector flow
  --{flags.FLAGS['username'].name} {_GRR_USERNAME_HELP}
  --{flags.FLAGS['password'].name} {_GRR_PASSWORD_HELP}
  --{flags.FLAGS['grr-server'].name} {_GRR_SERVER_HELP}
  --{flags.FLAGS['client'].name} {_CLIENT_HELP}
  --{flags.FLAGS['artefact'].name} {_ARTIFACT_HELP}
  --{flags.FLAGS['local-path'].name} {_LOCAL_PATH_HELP}
  --{flags.FLAGS['max-file-size'].name} {_MAX_FILE_SIZE_HELP}

complete - Complete an existing flow, downloading the results
  --{flags.FLAGS['username'].name} {_GRR_USERNAME_HELP}
  --{flags.FLAGS['password'].name} {_GRR_PASSWORD_HELP}
  --{flags.FLAGS['grr-server'].name} {_GRR_SERVER_HELP}
  --{flags.FLAGS['client'].name} {_CLIENT_HELP}
  --{flags.FLAGS['flow'].name} {_FLOW_HELP}
  --{flags.FLAGS['local-path'].name} {_LOCAL_PATH_HELP}
  --{flags.FLAGS['max-file-size'].name} {_MAX_FILE_SIZE_HELP}

help - Display this text and exit

Enable debug logging with --{flags.FLAGS['debug'].name}

Raise bugs here: https://github.com/google/grrshell/issues/new
"""


class Main:
  """Main driver class."""

  def __init__(self):
    """Initializes the main driver."""
    self._max_size = 0
    self._timeline_threshold: datetime.timedelta = None
    self._client: grr_shell_client.GRRShellClient = None
    self._shell: grr_shell_repl.GRRShellREPL = None

  @classmethod
  def DefineFlags(cls):
    """Define absl flags for the application."""
    # go/keep-sorted start
    flags.DEFINE_bool(name='debug', default=False, help=_DEBUG_HELP)
    flags.DEFINE_bool(
        name='no-initial-timeline', default=False, required=False,
        help=_NO_INITIAL_TIMELINE_HELP)
    flags.DEFINE_string(
        name='artefact', default='', required=False, help=_ARTIFACT_HELP)
    flags.DEFINE_string(
        name='client', default='', required=False, help=_CLIENT_HELP)
    flags.DEFINE_string(
        name='flow', default='', required=False, help=_FLOW_HELP)
    flags.DEFINE_string(
        name='initial-timeline', default='', required=False,
        help=_INITIAL_TIMELINE_HELP)
    flags.DEFINE_string(
        name='local-path', default='./', required=False, help=_LOCAL_PATH_HELP)
    flags.DEFINE_string(
        name='max-file-size', default='0', required=False,
        help=_MAX_FILE_SIZE_HELP)
    flags.DEFINE_string(
        name='remote-path', default='', required=False, help=_REMOTE_PATH_HELP)
    flags.DEFINE_string(
        name='timeline-threshold', default='12', required=False,
        help=_TIMELINE_THRESHOLD_HELP)
    # go/keep-sorted end
    flags.DEFINE_string(name='username', default='', required=False, help=_GRR_USERNAME_HELP)
    flags.DEFINE_string(name='password', default='', required=False, help=_GRR_PASSWORD_HELP)
    flags.DEFINE_string(name='grr-server', default='', required=False, help=_GRR_SERVER_HELP)

    flags.DEFINE_alias('artifact', 'artefact')
    flags.DEFINE_alias('user', 'username')
    flags.DEFINE_alias('pass', 'password')

  def main(self, argv: Sequence[str]) -> None:
    """Main driver.

    Args:
      argv: Command line args.
    """
    if flags.FLAGS['debug'].value:
      self._SetUpLogging()

    command = self._ParseArgs(argv)
    if not command:
      return

    if not self._ConfigureClient():
      return

    self._RunCommand(command)

  def _ParseArgs(self, argv: Sequence[str]) -> typing.Union[bool, str]:
    """Minor arg parsing and validation.

    Args:
      argv: Args from command line

    Returns:
      False if the command line params are invalid. If the command line is valid
      then the command is returned.
    """
    argv = argv[1:]  # Remove the binary path from argv, we don't need it

    command = argv[0] if argv else 'shell'
    if command not in _COMMANDS:
      print(f'Unrecognised command\n{_USAGE()}')
      return False

    try:
      self._max_size = int(flags.FLAGS['max-file-size'].value)
    except ValueError as error:
      print(f'Could not set max-file-size to {flags.FLAGS["max-file-size"].value}: {str(error)}\nContinuing with default value.')
      self._max_size = 0

    try:
      hours = int(
          flags.FLAGS['timeline-threshold'].value)
    except ValueError as error:
      print('Could not set timeline-threshold to '
            f'{flags.FLAGS["timeline-threshold"].value}: '
            f'{str(error)}\nContinuing with default value.')
      hours = int(
          flags.FLAGS['timeline-threshold'].default)
    self._timeline_threshold = datetime.timedelta(hours=hours)
    logger.debug('timeline-threshold %s converted to %s hours',
                 flags.FLAGS['timeline-threshold'].value,
                 hours)

    if command == 'help':
      print(_USAGE())
      return False

    for flag in (flags.FLAGS['grr-server'], flags.FLAGS['username'], flags.FLAGS['password'], flags.FLAGS['client']):
      if not flag.value:
        print(f'--{flag.name} is required.')
        return False

    if (flags.FLAGS['no-initial-timeline'].value and
        flags.FLAGS['initial-timeline'].value):
      print(f'--{flags.FLAGS["no-initial-timeline"].name} and '
            f'--{flags.FLAGS["initial-timeline"].name} are mutually exclusive.')
      return False

    return command

  def _SetUpLogging(self) -> None:
    """Sets up logging if requested."""
    filename = os.path.join(
        tempfile.gettempdir(),
        f'grrshell_{datetime.datetime.now().strftime("%Y%m%dT%H%M%S")}.log')

    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    fh = logging.logging.FileHandler(filename)

    fh.setFormatter(logging.logging.Formatter(
        fmt=(
            '%(asctime)s.%(msecs)03d - %(threadName)s - %(module)s.%(funcName)s'
            ':%(lineno)d - %(message)s'),
        datefmt='%Y-%m-%dT%H:%M:%S'))
    logger.addHandler(fh)

    print(f'Logging to {filename}')

    logger.debug('Args: %s', ' '.join(sys.argv))
    logger.debug('artefact flag: %s', flags.FLAGS['artefact'].value)
    logger.debug('client flag: %s', flags.FLAGS['client'].value)
    logger.debug('initial-timeline flag: %s',
                 flags.FLAGS['initial-timeline'].value)
    logger.debug('no-initial-timeline flag: %s',
                 flags.FLAGS['no-initial-timeline'].value)
    logger.debug('local-path flag: %s', flags.FLAGS['local-path'].value)
    logger.debug('max-file-size flag: %s', flags.FLAGS['max-file-size'].value)
    logger.debug('remote-path flag: %s', flags.FLAGS['remote-path'].value)
    logger.debug('timeline-threshold flag: %s',
                 flags.FLAGS['timeline-threshold'].value)
    logger.debug('debug flag: %s', flags.FLAGS['debug'].value)

  def _ConfigureClient(self) -> bool:
    """Set up the GRRShell client member.

    Returns:
      True if the client was successfully set up, false otherwise.
    """
    try:
      self._client = grr_shell_client.GRRShellClient(
          flags.FLAGS['grr-server'].value,
          flags.FLAGS['username'].value,
          flags.FLAGS['password'].value,
          flags.FLAGS['client'].value,
          self._max_size)

    except (errors.ClientNotFoundError) as error:
      logger.error('Error accessing grr client', exc_info=True)
      print(f'Error accessing grr client{str(error)}')
      return False

    if not self._client.CheckAccess():
      print('No client access - Requesting....')
      if not self._client.RequestAccess():
        print('Exiting')
        return False

    return True

  def _RunCommand(self, command: str) -> None:
    """Needs a better name.

    Args:
      command: The GRRShell command to run.
    """
    try:
      if command == 'collect':
        if not flags.FLAGS['remote-path'].value:
          print(_USAGE())
          return
        self._client.CollectFiles(flags.FLAGS['remote-path'].value,
                                  flags.FLAGS['local-path'].value)
      elif command == 'shell':
        self._client.StartBackgroundMonitors()
        try:
          self._shell = self._GetGRRShellReplObject(
              self._client,
              not flags.FLAGS['no-initial-timeline'].value,
              flags.FLAGS['initial-timeline'].value,
              self._timeline_threshold)
        except KeyboardInterrupt:
          print('Exiting.')
          return
        self._shell.RunShell()
      elif command in ('artifact', 'artefact'):
        if not flags.FLAGS['artefact'].value:
          print(_USAGE())
          return
        self._client.ScheduleAndDownloadArtefact(
            flags.FLAGS['artefact'].value, flags.FLAGS['local-path'].value)
      elif command == 'complete':
        if not flags.FLAGS['flow'].value:
          print(_USAGE())
          return
        self._client.CompleteFlow(flags.FLAGS['flow'].value,
                                  flags.FLAGS['local-path'].value)
    except Exception as error:
      logger.error('Unknown error encountered', exc_info=True)
      raise error

  def _GetGRRShellReplObject(
      self,
      shell_client: grr_shell_client.GRRShellClient,
      collect_initial_timeline: bool,
      initial_timeline_id: str,
      timeline_staleness_threshold: datetime.timedelta
      ) -> grr_shell_repl.GRRShellREPL:
    """Returns a GRRShellREPL object. Exists to be overridden by subclasses."""
    return grr_shell_repl.GRRShellREPL(shell_client,
                                       collect_initial_timeline,
                                       initial_timeline_id,
                                       timeline_staleness_threshold)


def main():
  """Main."""
  Main.DefineFlags()
  m = Main()
  app.run(m.main)
