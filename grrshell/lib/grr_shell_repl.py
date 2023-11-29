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
"""GRR shell REPL driver."""

import dataclasses
import datetime
import getopt
import os
import re
import shlex
import sys
from typing import Callable, Sequence, Optional

from absl import logging
import humanize
import prompt_toolkit

from grrshell.lib import errors
from grrshell.lib import grr_shell_client
from grrshell.lib import grr_shell_emulated_fs


logger = logging.logging.getLogger('grrshell')

_STALE_THRESHOLD = datetime.timedelta(minutes=10)
_OFFLINE_THRESHOLD = datetime.timedelta(minutes=30)
_PROMPT_STYLE = prompt_toolkit.styles.Style.from_dict({
    '': '',
    'bottom-toolbar': '#FFFFFF bg:#000000',
    'offline': '#FF0000 bg:#000000',
    'stale': '#FFFF00 bg:#000000',
    'online': '#00FF00 bg:#000000',
})
_OFFLINE = 'class:offline'
_STALE = 'class:stale'
_ONLINE = 'class:online'

_ANSI_BLUE_START = '\x1b[94m'
_ANSI_YELLOW_START = '\x1b[93m'
_ANSI_COLOUR_END = '\x1b[0m'

_SETTABLE_PROPERTIES = ('max-file-size',)


@dataclasses.dataclass
class _Help:
  short: str
  long: str = ''

  def __str__(self) -> str:
    if self.long:
      return f'{self.short}\n\n{self.long}\n'
    return f'{self.short}\n'


@dataclasses.dataclass
class _Command:
  name: str
  action: Callable[[list[str]], None]
  help: _Help
  path_param: bool = False
  is_alias: bool = False

# pylint: disable=line-too-long
_ARTEFACT_HELP_LONG = """\tRequires an artefact name argument, eg BrowserHistory."""
_COLLECT_HELP_LONG = """\tRequires a path argument. Supports both absolute and relative paths.
\tUses ClientFileFinder syntax. For information on ClientFileFinder syntax, see:
\thttps://grr-doc.readthedocs.io/en/latest/investigating-with-grr/flows/specifying-file-paths.html?#path-globbing"""
_DETAIL_HELP_LONG = """\tRequires a single Flow ID argument."""
_FIND_HELP_LONG = """\tRequires 1 or 2 arguments: find [dir] <regex>
\tFunctionally similar to "find <dir> | grep -P <regex>" in bash.
\tIf <dir> is not specified, ./ is assumed."""
_FLOWS_HELP_LONG = """\tOptionally specify "--all [count]" to show all flows, including those not launched by this GRR Shell session (Max 50)."""
_HELP_HELP_LONG = """\tUse help <command> for more detailed help on shell commands."""
_INFO_HELP_LONG = """\tOptional flags:
\t--ads - for Zone.Identifier alternate data stream collection.
\t--offline - Use the cached TimelineFlow info rather than launching a flow.
\tThese two flags are mutually exclusive."""
_LS_HELP_LONG = """\tDefault sorting is dirs first, alphabetically. Optional flags:
\t-S - sort by size
\t-r - Reverse sort order
\t-t - sort by modification time"""
_REFRESH_HELP_LONG = """\tOptionally provide a path to collect the TimelineFlow for a subdirectory."""
_RESUME_HELP_LONG = """\tRequires a Flow ID argument. (Re)attaches the flow to the current GRRShell session.
\tClientFileFinder, ArtifactCollectorFlow, and GetFile (Zone.Identifier ADS only) are supported.
\tResuming an asynchronous flow will download the flow results in the background.
\tSynchronous flows will display the flow result."""
_SET_LONG_HELP = """\tCurrently supported shell env values:
\t* max-file-size Specify a max file size for file collections. If not specified, the GRR default of 500MB is used."""
# pylint: enable=line-too-long

# go/keep-sorted start
_ARTEFACT_HELP = _Help(
    '\tLaunch and download an ArtifactCollectorFlow (asynchronous)',
    _ARTEFACT_HELP_LONG)
_CD_HELP = _Help('\tChange directory')
_CLEAR_HELP = _Help('\tClear the terminal')
_COLLECT_HELP = _Help('\tCollect remote files (asynchronous)',
                      _COLLECT_HELP_LONG)
_DETAIL_HELP = _Help('\tFetch and display detailed information on a flow',
                     _DETAIL_HELP_LONG)
_EXIT_HELP = _Help('\tExit shell (alias "quit" and <CTRL+D>)')
_FIND_HELP = _Help('\tSearch for file paths matching a pattern.',
                   _FIND_HELP_LONG)
_FLOWS_HELP = _Help('\tList background flows status.', _FLOWS_HELP_LONG)
_HELP_HELP = _Help('\tThis help text (aliases "h" and "?")', _HELP_HELP_LONG)
_INFO_HELP = _Help(
    '\tFetch FS information and hashes of a remote file (synchronous).',
    _INFO_HELP_LONG)
_LS_HELP = _Help('\tList directory entries, with an optional path argument.',
                 _LS_HELP_LONG)
_PWD_HELP = _Help('\tPrint current directory')
_REFRESH_HELP = _Help('\tRefresh remote emulated FS (synchronous)',
                      _REFRESH_HELP_LONG)
_RESUME_HELP = _Help('\tResume an existing flow', _RESUME_HELP_LONG)
_SET_HELP = _Help('\tSet a shell value', _SET_LONG_HELP)
# go/keep-sorted end


class GRRShellREPL:
  """GRR Shell REPL driver."""

  def __init__(self,
               shell_client: grr_shell_client.GRRShellClient,
               collect_initial_timeline: bool = True,
               initial_timeline_id: Optional[str] = None):
    """Initialises the REPL driver for GRR Shell.

    Args:
      shell_client: An instantiated GRRShellClient to use.
      collect_initial_timeline: True if the emulated FS should be initially
        populated by a TimelineFlow, False otherwise.
      initial_timeline_id: An existing TimelineFlow ID to use to populate the
        emulated FS. If None, a non-stale timeline is looked for, and if not
        found, a new TimelineFlow is launched and waited for. Ignored if
        collect_initial_timeline is False.
    """
    logger.debug('Initialising REPL')

    self._grr_shell_client = shell_client
    self._os = self._grr_shell_client.GetOS()
    self._emulated_fs = grr_shell_emulated_fs.GrrShellEmulatedFS(self._os)
    self._client_id = self._grr_shell_client.GetClientID()
    self._commands = self._BuildCommands()
    self._help = self._GenerateHelp()

    if collect_initial_timeline:
      if not initial_timeline_id:
        initial_timeline_id = self._grr_shell_client.GetLastTimeline()
      self._RefreshTimeline(existing_timeline=initial_timeline_id)

  def RunShell(self) -> None:
    """Runs the GRR Shell REPL."""
    completer = _GrrShellREPLPromptCompleter(
        self._emulated_fs, list(self._commands.keys()),
        [name for name in self._commands if self._commands[name].path_param],
        list(self._grr_shell_client.GetSupportedArtefactNames()))
    prompts = prompt_toolkit.PromptSession(completer=completer,
                                           style=_PROMPT_STYLE)

    try:
      while True:
        try:
          text = prompts.prompt(self._GeneratePrompt(),
                                bottom_toolbar=self._GenerateBottomBar())
          logger.debug('User entered "%s"', text)
          self._HandleCommand(text)
        except KeyboardInterrupt:
          print('CTRL+C captured (use CTRL+D to exit)')
          logger.debug('User entered <CTRL+C>')
        except EOFError:  # CTRL+D
          raise
        except Exception as error:  # pylint: disable=broad-exception-caught
          print(f'Unknown exception: {type(error)} - {str(error)}')
          logger.debug('Unknown exception encountered', exc_info=True)
    except EOFError:  # CTRL+D
      logger.debug('User entered <CTRL+D>')
    finally:
      self._grr_shell_client.WaitForBackgroundCompletions()
      print('Exiting')

  def _BuildCommands(self) -> dict[str, _Command]:
    """Builds a command dispatcher.

    Returns:
      A dict, keyed by command name, of _Command objects, used to direct user
        shell commands to methods.
    """
    commands = [
        # go/keep-sorted start
        _Command('?', self._PrintHelp, _HELP_HELP, is_alias=True),
        _Command('artefact', self._Artefact, _ARTEFACT_HELP),
        _Command('artifact', self._Artefact, _ARTEFACT_HELP, is_alias=True),
        _Command('cd', self._Cd, _CD_HELP, path_param=True),
        _Command('clear', self._Clear, _CLEAR_HELP),
        _Command('collect', self._Collect, _COLLECT_HELP, path_param=True),
        _Command('detail', self._Detail, _DETAIL_HELP),
        _Command('exit', self._Exit, _EXIT_HELP),
        _Command('find', self._FindFiles, _FIND_HELP),
        _Command('flows', self._Flows, _FLOWS_HELP),
        _Command('h', self._PrintHelp, _HELP_HELP, is_alias=True),
        _Command(
            'hash', self._Info, _INFO_HELP, is_alias=True, path_param=True),
        _Command('help', self._PrintHelp, _HELP_HELP),
        _Command('info', self._Info, _INFO_HELP, path_param=True),
        _Command('ls', self._Ls, _LS_HELP, path_param=True),
        _Command('pwd', self._Pwd, _PWD_HELP),
        _Command('quit', self._Exit, _EXIT_HELP, is_alias=True),
        _Command('refresh', self._Refresh, _REFRESH_HELP, path_param=True),
        _Command('resume', self._Resume, _RESUME_HELP),
        _Command('set', self._Set, _SET_HELP)
        # go/keep-sorted end
    ]
    return {c.name: c for c in commands}

  def _GenerateHelp(self) -> str:
    """Generates the help string based of the available commands.

    Returns:
      The help text for the shell.
    """
    return '\n'.join(sorted([
        f'\t{c.name:<12} {c.help.short}'
        for c in self._commands.values() if not c.is_alias]))

  def _GeneratePrompt(self) -> str:
    """Generates the shell prompt.

    Returns:
      A string for using as a prompt by prompt_toolkit.prompt()
    """
    pwd = self._emulated_fs.GetPWD()
    return f'{self._client_id}:{pwd} $ '

  def _GenerateColourClass(self,
                           input_time: datetime.datetime,
                           now: datetime.datetime) -> str:
    if now - _OFFLINE_THRESHOLD > input_time:
      return _OFFLINE
    if now - _STALE_THRESHOLD > input_time:
      return _STALE
    return _ONLINE

  def _GenerateBottomBar(self) -> list[tuple[str, str]]:
    """Generates the prompt bottom bar text, with formatting.

    Returns:
      A list of tuples of strings, used by prompt_toolkit.prompt() as a bottom
        status bar.
    """
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    running_count, total_count = self._grr_shell_client.GetRunningFlowCount()

    last_seen = self._grr_shell_client.GetLastSeenTime()
    last_seen_colour_class = self._GenerateColourClass(last_seen, now)
    last_seen_relative = humanize.naturaldelta(now - last_seen)

    last_timeline = datetime.datetime.fromtimestamp(
        self._emulated_fs.GetTimelineTime() / 1000000, tz=datetime.timezone.utc
    )
    last_timeline_colour_class = self._GenerateColourClass(last_timeline, now)
    last_timeline_relative = humanize.naturaldelta(now - last_timeline)

    last_seen = last_seen.strftime('%Y-%m-%d %H:%M:%S')
    last_timeline = last_timeline.strftime('%Y-%m-%d %H:%M:%S')

    return [
        (last_seen_colour_class,
         f' Last seen: {last_seen} ({last_seen_relative} ago) '),
        ('class:bottom-toolbar',
         f' {running_count}/{total_count} flows running '),
        (last_timeline_colour_class,
         f' Timeline freshness: {last_timeline} '
         f'({last_timeline_relative} ago) '),
    ]

  def _HandleCommand(self, text: str) -> None:
    """Handles the command from the user.

    A switch for commands, to then be handled by other methods, with results
    printed to the terminal.

    Args:
      text: The text input from the user
    """
    parts = shlex.split(text)
    if not parts:
      return
    command = parts[0].lower()

    if command in self._commands:
      self._commands[command].action(parts[1:])
    else:
      print('Unrecognised command. Use "help" for a command list.')

  def _Exit(self, params: Sequence[str]) -> None:
    """Exits the shell."""
    del params  # Unused
    sys.exit(0)

  def _PrintHelp(self, params: Sequence[str]) -> None:
    """Displays the help message."""
    if len(params) not in (0, 1):
      print('help requires 0 or 1 argument. Usage:')
      print(self._commands['help'].help)
      return

    if params:
      if params[0] not in self._commands:
        print(f'Unknown command {params[0]}')
      else:
        print(self._commands[params[0]].help)
    else:
      print(self._help)

  def _RefreshTimeline(self,
                       path: str = '/',
                       existing_timeline: Optional[str] = None) -> None:
    """(Re)collects a filesystem timeline from the client.

    Args:
      path: The path to refresh.
      existing_timeline: An initial TimelineFlow flow ID to use. None to collect
        a fresh TimelineFlow.
    """
    windows_volume_root_regex = re.compile('^[A-Z]:$')

    if path == '.':
      path = self._emulated_fs.GetPWD()
    elif windows_volume_root_regex.match(path):
      path += '/'

    timeline_data = self._grr_shell_client.CollectTimeline(
        path, existing_timeline)
    # Zero out the path we're refreshing.
    self._emulated_fs.ClearPath(path,
                                self._grr_shell_client.last_timeline_time)

    self._emulated_fs.ParseTimelineFlow(
        timeline_data,
        self._grr_shell_client.last_timeline_time
    )

    if self._emulated_fs.GetPWD() == path:
      self._Cd([path])

  def _Ls(self, params: list[str]) -> None:
    """Prints directory entries for a given directory.

    getopt options:
      * S - sort by size
      * a - ignored
      * l - ignored
      * r - Reverse sort order
      * t - sort by modification time

    Args:
      params: Command components from _HandleCommand.
    """
    try:
      optlist, args = getopt.getopt(params, 'Salrt')
    except getopt.GetoptError as error:
      print(error)
      return

    if len(args) not in (0, 1):
      print('Error: ls requires 0 or 1 arguments. Usage:')
      print(self._commands['ls'].help)
      return

    if sum((1 for opt, _ in optlist if opt[1] in 'St')) not in (0, 1):
      print('Options S, t are mutually exclusive')
      return

    sortkey = None
    reverse = True

    for opt, _ in optlist:
      if opt == '-S':
        sortkey = 'S'
      elif opt == '-t':
        sortkey = 't'
      elif opt == '-r':
        reverse = False

    path = args[0] if len(args) == 1 else None

    try:
      entries = self._emulated_fs.Ls(path, sortkey, reverse)
      for e in entries:
        if e.mode_as_string.startswith('d'):
          e.name = _ANSI_BLUE_START + e.name + _ANSI_COLOUR_END
        if e.mode_as_string.startswith('l'):
          e.name = _ANSI_YELLOW_START + e.name + _ANSI_COLOUR_END
      lines = [str(entry) for entry in entries]
      print('\n'.join(lines))
    except errors.InvalidRemotePathError as exception:
      print(f'No such file or directory: {str(exception)}')
    except RuntimeError as exception:
      print(str(exception))

  def _Cd(self, params: Sequence[str]) -> None:
    """Changes the current working directory.

    Args:
      params: Command components from _HandleCommand.
    """
    if len(params) != 1:
      print('cd requires 1 argument. Usage:')
      print(self._commands['cd'].help)
      return

    try:
      self._emulated_fs.Cd(params[0])
    except errors.IsAFileError as exception:
      print(f'Not a directory: {str(exception)}')
    except errors.InvalidRemotePathError as exception:
      print(f'No such file or directory: {str(exception)}')

  def _Pwd(self, params: Sequence[str]) -> None:
    """Prints the current working directory."""
    del params  # Unused
    print(self._emulated_fs.GetPWD())

  def _Refresh(self, params: list[str]) -> None:
    """Collects a new TimelineFlow from the client.

    Args:
      params: Command components from _HandleCommand.
    """
    if len(params) not in (0, 1):
      print('Error: refresh requires 0 or 1 arguments. Usage:')
      print(self._commands['refresh'].help)
      return

    path = params[0] if len(params) == 1 else '/'
    self._RefreshTimeline(path=path)

  def _Collect(self, params: Sequence[str]) -> None:
    """Collects files from the remote client.

    Args:
      params: Command components from _HandleCommand.
    """
    if len(params) != 1:
      print('collect requires 1 argument. Usage:')
      print(self._commands['collect'].help)
      return

    remote_path = self._emulated_fs.NormaliseFSPath(params[0])

    if self._emulated_fs.RemotePathExists(remote_path, dirs_only=True):
      remote_path = f'{remote_path}/*'
      remote_path = os.path.normpath(remote_path)
      print(f'Directory collection attempted: updating to "{remote_path}". '
            'This is not recursive! For recursive collection, use '
            'ClientFileFinder recursion syntax - ** or **N. See '
            'https://grr-doc.readthedocs.io/en/latest/investigating-with-grr/'
            'flows/specifying-file-paths.html?#path-globbing for more on CSFF '
            'syntax.')

    self._grr_shell_client.CollectFilesInBackground(
        self._emulated_fs.NormaliseFSPath(remote_path), './')

  def _Artefact(self, params: Sequence[str]) -> None:
    """Collects an artifact from the remote client.

    Args:
      params: Command components from _HandleCommand.
    """
    if len(params) != 1:
      print('artefact requires 1 argument. Usage:')
      print(self._commands['artefact'].help)
      return

    print('\n'.join(self._grr_shell_client.CollectArtefact(params[0], './')))

  def _Info(self, params: list[str]) -> None:
    """Prints stats info, including hashes for remote paths.

    If '--ads' is specified in params, the Zone.Identifier Alternate Data Stream
    is attempted collection (if the OS is windows, and the path is not a
    directory).

    Args:
      params: Command components from _HandleCommand.
    """
    collect_ads = False
    offline = False

    if '--ads' in params:
      collect_ads = True
      params.remove('--ads')

    if '--offline' in params:
      offline = True
      params.remove('--offline')

    if offline and collect_ads:
      print('--offline and --ads are mutually exclusive. Usage:')
      print(self._commands['info'].help)
      return
    if len(params) != 1:
      print('info requires 1 argument. Usage:')
      print(self._commands['info'].help)
      return

    path = self._emulated_fs.NormaliseFSPath(params[0])
    collect_ads = (not self._emulated_fs.RemotePathExists(path, dirs_only=True)
                   if collect_ads else collect_ads)

    if offline:
      print(self._emulated_fs.OfflineFileInfo(path))
    else:
      print(self._grr_shell_client.FileInfo(path, collect_ads))

  def _Flows(self, params: list[str]) -> None:
    """Prints information of launched flows and their status."""
    if '--all' in params:
      params.remove('--all')
      print(self._ListAllFlows(params))
    else:
      print(self._grr_shell_client.GetBackgroundFlowsState())

  def _FindFiles(self, params: Sequence[str]) -> None:
    """Searches the FS for files matching a string."""
    if len(params) not in (1, 2):
      print('find requires 1 or 2 arguments. Usage:')
      print(self._commands['find'].help)
      return

    if len(params) == 1:
      basedir = './'
      needle = params[0]
    else:
      basedir, needle = params

    try:
      print('\n'.join(self._emulated_fs.Find(basedir, needle)))
    except (errors.IsAFileError, errors.InvalidRemotePathError) as exc:
      print(str(exc))

  def _Set(self, params: Sequence[str]) -> None:
    """Sets a shell value."""
    if (not params) or params[0] not in _SETTABLE_PROPERTIES:
      print(f'Valid properties: {", ".join(_SETTABLE_PROPERTIES)}')
      return

    if len(params) != 2:
      print('set requires two parameters. Usage:')
      print(self._commands['set'].help)
      return

    if params[0] == 'max-file-size':
      try:
        self._grr_shell_client.SetMaxFilesize(int(params[1]))
      except ValueError as error:
        print(f'Could not set max-file-size to {params[1]}: {str(error)}')

  def _Clear(self, params: Sequence[str]) -> None:
    """Clear the terminal."""
    del params  # unused
    prompt_toolkit.shortcuts.clear()

  def _ListAllFlows(self, params: Sequence[str]) -> str:
    """List all flows, not just those launched by this shell session."""
    count = 50
    try:
      if len(params) == 1:
        count = int(params[0])
    except ValueError:
      print(f'Invalid count provided, using default value of {count}')

    return self._grr_shell_client.ListAllFlows(count=count)

  def _Resume(self, params: Sequence[str]) -> None:
    """Resume an existing flow, not attached to this GRRShell session."""
    if len(params) != 1:
      print('resume requires 1 Flow ID argument. Usage:')
      print(self._commands['resume'].help)
      return

    try:
      print('\n'.join(self._grr_shell_client.ResumeFlow(params[0], './')))
    except errors.NotResumeableFlowTypeError as error:
      print(str(error))

  def _Detail(self, params: Sequence[str]) -> None:
    """Display detailed information on a flow."""
    if len(params) != 1:
      print('detail requires exactly 1 Flow ID argument. Usage:')
      print(self._commands['detail'].help)
      return

    print(self._grr_shell_client.FlowDetail(params[0]))


class _GrrShellREPLPromptCompleter(prompt_toolkit.completion.Completer):
  """Implements autocomplete for the GRR Shell REPL.

  Uses the emulated FS for path completion, and also generates completions for
  commands.
  """

  def __init__(self,
               emulated_fs: grr_shell_emulated_fs.GrrShellEmulatedFS,
               commands: list[str],
               commands_with_params: list[str],
               artifacts: list[str]):
    """Initialises the autocomplete provider.

    Args:
      emulated_fs: A GRRShellEmulatedFS used for path completions.
      commands: Commands to offer completions for
      commands_with_params: Commands for which to offer path completions for.
      artifacts: A list of supported artifacts to offer completions for.
    """
    self._emulated_fs = emulated_fs
    self._commands = commands
    self._commands_with_params = commands_with_params
    self._artifacts = artifacts

  # pylint: disable=inconsistent-return-statements
  def get_completions(
      self,
      document: prompt_toolkit.document.Document,
      complete_event: prompt_toolkit.completion.base.CompleteEvent) -> ...:
    """Yields autocomplete entries for the grr shell."""
    try:
      parts = shlex.split(document.text)
      command = parts[0] if parts else ''

      suggestions = []
      offset = 0

      if not parts:  # Prompt is empty
        suggestions = self._commands

      elif len(parts) == 1:
        if not document.text.endswith(' '):
          suggestions = [c for c in self._commands if c.startswith(command)]
          offset = -len(command)
        else:
          if command not in self._commands_with_params:
            return None
          suggestions, offset = self._CompleteRemotePath(
              '', command in ('cd', 'refresh'))

      elif len(parts) == 2:
        if command in ('artefact', 'artifact'):
          if parts[1] in self._artifacts:
            return None
          suggestions = self._CompleteArtifactName(parts[1])
          offset = -len(parts[1])
        elif command in ('help', 'h', '?'):
          suggestions = [c for c in self._commands if c.startswith(parts[1])]
          offset = -len(parts[1])
        elif command not in self._commands_with_params:
          return None
        else:
          suggestions, offset = self._CompleteRemotePath(parts[1],
                                                         command == 'cd')
      for s in suggestions:
        yield prompt_toolkit.completion.Completion(s, start_position=offset)
    except Exception:  # pylint: disable=broad-exception-caught
      logger.error('Error in generating completion suggestions', exc_info=True)
      return None

  def _CompleteRemotePath(self,
                          remote_path: str,
                          dirs_only: bool) -> tuple[list[str], int]:
    """Generates completion suggestions for remote paths.

    Args:
      remote_path: The remote path for which to provide completion suggstions.
      dirs_only: True if only directories should be suggested, False otherwise.

    Returns:
      A Tuple of:
        A list of suggestions
        A length offset to be used by the base class get_completions method.
    """
    basename = os.path.basename(remote_path)
    dirname = os.path.dirname(remote_path)
    if not dirname:
      dirname = './'

    try:
      suggestions = ['..'] + self._emulated_fs.GetChildrenOfPath(dirname,
                                                                 dirs_only)
    except errors.InvalidRemotePathError:
      return [], 0

    suggestions = [s for s in suggestions if s.startswith(basename)]
    suggestions = [s.replace(' ', '\\ ') for s in suggestions]

    return suggestions, -len(basename)

  def _CompleteArtifactName(self, in_text: str) -> list[str]:
    """Generates completion suggestions for artifact names.

    Args:
      in_text: Text provided by the user to offer completions for.

    Returns:
      A list of suggestions
    """
    suggestions = [s for s in self._artifacts if in_text.lower() in s.lower()]
    return suggestions
