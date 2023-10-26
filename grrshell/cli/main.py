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

from absl import app
from absl import flags
from absl import logging

from grrshell.lib import errors
from grrshell.lib import grr_shell_client
from grrshell.lib import grr_shell_repl


_ARTIFACT_HELP = 'The artifact to collect from GRR via an ArtifactCollector flow'
_CLIENT_HELP = 'GRR ID or hostname of client'
_DEBUG_HELP = 'Enable debug logging'
_GRR_PASSWORD_HELP = 'GRR password'
_GRR_SERVER_HELP = 'GRR HTTP Endpoint'
_GRR_USERNAME_HELP = 'GRR username'
_INITIAL_TIMELINE_HELP = ('Specify an existing timeline flow to use instead of looking for a recent flow, or launching a new timeline flow.'
                          ' (Optional)')
_LOCAL_PATH_HELP = 'Location to store the collected files'
_MAX_FILE_SIZE_HELP = 'The max file size for GRR collection. 0 for the GRR default. (Optional)'
_NO_INITIAL_TIMELINE_HELP = 'Start without collecting a timeline from the client'
_REMOTE_PATH_HELP = 'ClientFileFinder expression for remote files'

_ARTEFACT = flags.DEFINE_string(name='artefact', default='', required=False, help=_ARTIFACT_HELP)
_CLIENT = flags.DEFINE_string(name='client', default='', required=False, help=_CLIENT_HELP)
_DEBUG = flags.DEFINE_bool(name='debug', default=False, help=_DEBUG_HELP)
_INITIAL_TIMELINE = flags.DEFINE_string(name='initial-timeline', default='', required=False, help=_INITIAL_TIMELINE_HELP)
_LOCAL_PATH = flags.DEFINE_string(name='local-path', default='', required=False, help=_LOCAL_PATH_HELP)
_MAX_FILE_SIZE = flags.DEFINE_string(name='max-file-size', default='0', required=False, help=_MAX_FILE_SIZE_HELP)
_NO_INITIAL_TIMELINE = flags.DEFINE_bool(name='no-initial-timeline', default=False, required=False, help=_NO_INITIAL_TIMELINE_HELP)
_REMOTE_PATH = flags.DEFINE_string(name='remote-path', default='', required=False, help=_REMOTE_PATH_HELP)

_GRR_USERNAME = flags.DEFINE_string(name='username', default='', required=False, help=_GRR_USERNAME_HELP)
_GRR_PASSWORD = flags.DEFINE_string(name='password', default='', required=False, help=_GRR_PASSWORD_HELP)
_GRR_SERVER = flags.DEFINE_string(name='grr-server', default='', required=False, help=_GRR_SERVER_HELP)

flags.DEFINE_alias('artifact', 'artefact')
flags.DEFINE_alias('user', 'username')
flags.DEFINE_alias('pass', 'password')

_USAGE = f"""grr_shell {{shell,collect,artefact,help}}

shell - Start an (emulated) interactive shell with CLIENT_ID (default if no command specified)
  --{_GRR_USERNAME.name} {_GRR_USERNAME_HELP}
  --{_GRR_PASSWORD.name} {_GRR_PASSWORD_HELP}
  --{_GRR_SERVER.name} {_GRR_SERVER_HELP}
  --{_CLIENT.name} {_CLIENT_HELP}
  --{_INITIAL_TIMELINE.name} {_INITIAL_TIMELINE_HELP}
  --{_MAX_FILE_SIZE.name} {_MAX_FILE_SIZE_HELP}
  --{_NO_INITIAL_TIMELINE.name} {_NO_INITIAL_TIMELINE_HELP}

collect - Collect files from the client (ClientFileFinder flow)
  --{_GRR_USERNAME.name} {_GRR_USERNAME_HELP}
  --{_GRR_PASSWORD.name} {_GRR_PASSWORD_HELP}
  --{_GRR_SERVER.name} {_GRR_SERVER_HELP}
  --{_CLIENT.name} {_CLIENT_HELP}
  --{_REMOTE_PATH.name} {_REMOTE_PATH_HELP}
  --{_LOCAL_PATH.name} {_LOCAL_PATH_HELP}
  --{_MAX_FILE_SIZE.name} {_MAX_FILE_SIZE_HELP}

artefact - Schedule and collect an ArtifactCollector flow
  --{_GRR_USERNAME.name} {_GRR_USERNAME_HELP}
  --{_GRR_PASSWORD.name} {_GRR_PASSWORD_HELP}
  --{_GRR_SERVER.name} {_GRR_SERVER_HELP}
  --{_CLIENT.name} {_CLIENT_HELP}
  --{_ARTEFACT.name} {_ARTIFACT_HELP}
  --{_LOCAL_PATH.name} {_LOCAL_PATH_HELP}
  --{_MAX_FILE_SIZE.name} {_MAX_FILE_SIZE_HELP}

help - Display this text and exit

Enable debug logging with --{_DEBUG.name}

Raise bugs here: https://github.com/google/grrshell/issues/new
"""


logger = logging.logging.getLogger('grrshell')


def main(argv: Sequence[str]) -> None:  # pylint: disable=invalid-name
  """Main driver.

  Args:
    argv: Command line args.
  """
  argv = argv[1:]  # Remove the binary path from argv, we don't need it

  if _DEBUG.value:
    _SetUpLogging()

  if not argv:
    argv = ('shell',)

  if argv[0] == 'help':
    print(_USAGE)
    return

  try:
    max_size = int(_MAX_FILE_SIZE.value)
  except ValueError as error:
    print(f'Could not set max-file-size to {_MAX_FILE_SIZE.value}: {str(error)}\nContinuing with default value.')
    max_size = 0

  for flag in (_GRR_SERVER, _GRR_USERNAME, _GRR_PASSWORD, _CLIENT):
    if not flag.value:
      print(f'--{flag.name} is required.')
      return

  if _NO_INITIAL_TIMELINE.value and _INITIAL_TIMELINE.value:
    print(f'--{_NO_INITIAL_TIMELINE.name} and --{_INITIAL_TIMELINE.name} are mutually exclusive.')
    return

  try:
    client = grr_shell_client.GRRShellClient(_GRR_SERVER.value,
                                             _GRR_USERNAME.value,
                                             _GRR_PASSWORD.value,
                                             _CLIENT.value,
                                             max_size)
  except (errors.NoGRRApprovalError, errors.ClientNotFoundError) as error:
    logger.error('Error accessing grr client', exc_info=True)
    print(str(error))
    return

  if argv[0] == 'collect':
    if not all((_REMOTE_PATH.value, _LOCAL_PATH.value)):
      print(_USAGE)
      return
    client.CollectFiles(_REMOTE_PATH.value, _LOCAL_PATH.value)
  elif argv[0] == 'shell':
    shell = grr_shell_repl.GRRShellREPL(client, not _NO_INITIAL_TIMELINE.value, _INITIAL_TIMELINE.value)
    shell.RunShell()
  elif argv[0] in ('artifact', 'artefact'):
    if not all((_ARTEFACT.value, _LOCAL_PATH.value)):
      print(_USAGE)
      return
    client.CollectArtifact(_ARTEFACT.value, _LOCAL_PATH.value)
  else:
    print(f'Unrecognised command\n{_USAGE}')


def _SetUpLogging() -> None:
  """Sets up logging if requested."""
  filename = os.path.join(tempfile.gettempdir(),
                          f'grrshell_{datetime.datetime.now().strftime("%Y%m%dT%H%M%S")}.log')

  logger.setLevel(logging.DEBUG)
  fh = logging.logging.FileHandler(filename)

  fh.setFormatter(logging.logging.Formatter(
      fmt=('%(asctime)s.%(msecs)03d - %(threadName)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s'),
      datefmt='%Y-%m-%dT%H:%M:%S'))
  logger.addHandler(fh)

  print(f'Logging to {filename}')

  logger.debug('Args: %s', ' '.join(sys.argv))
  logger.debug('artefact flag: %s', _ARTEFACT.value)
  logger.debug('client flag: %s', _CLIENT.value)
  logger.debug('initial-timeline flag: %s', _INITIAL_TIMELINE.value)
  logger.debug('no-initial-timeline flag: %s', _NO_INITIAL_TIMELINE.value)
  logger.debug('local-path flag: %s', _LOCAL_PATH.value)
  logger.debug('max-file-size flag: %s', _MAX_FILE_SIZE.value)
  logger.debug('remote-path flag: %s', _REMOTE_PATH.value)
  logger.debug('debug flag: %s', _DEBUG.value)


def Main():  # pylint: disable=missing-function-docstring
  app.run(main)

if __name__ == '__main__':
  app.run(main)
