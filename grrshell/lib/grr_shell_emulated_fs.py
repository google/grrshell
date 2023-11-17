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
"""Emulated remote FS for the GRR Shell client."""

import dataclasses
import fnmatch
import os
import re
from typing import cast, Union, Optional

from absl import logging
import humanize

from grrshell.lib import errors
from grrshell.lib import utils


logger = logging.logging.getLogger('grrshell')


# GRR timelines use the Sleuthkit format
# https://wiki.sleuthkit.org/index.php?title=Body_file
# MD5|name|inode|mode_as_string|UID|GID|size|atime|mtime|ctime|crtime
@dataclasses.dataclass(eq=True)
class _TimelineRow:
  """Row for a Timeline FS entry."""
  md5: str = ''
  name: str = ''
  inode: int = 0
  mode_as_string: str = '----------'
  uid: int = 0
  gid: int = 0
  size: int = 0
  atime: float = 0.0  # Access
  mtime: float = 0.0  # Modified
  ctime: float = 0.0  # Changed
  crtime: float = 0.0  # Created

  def __post_init__(self):
    # Just casting to our actual types since they are all received as `str`
    self.md5 = str(self.md5)
    self.name = str(self.name)
    try:
      self.inode = int(self.inode)
    except ValueError:
      pass
    self.mode_as_string = str(self.mode_as_string)
    self.uid = int(self.uid)
    self.gid = int(self.gid)
    self.size = int(self.size)
    self.atime = float(self.atime)
    self.mtime = float(self.mtime)
    self.ctime = float(self.ctime)
    self.crtime = float(self.crtime)


_FSEntry = Union['_EmulatedFile', '_EmulatedDirectory']


@dataclasses.dataclass(eq=True)
class _EmulatedFile:
  filename: str
  stats: _TimelineRow

  def GetLSEntry(self, dot_name: bool = False) -> '_LSEntry':
    """Return an LSEntry object for the directory entry.

    Args:
      dot_name: True if the objects name should be a '.', False for the objects
        actual name.

    Returns:
      The LSEntry for the object.
    """
    return _LSEntry(self.stats.mode_as_string, self.stats.uid, self.stats.gid, self.stats.size,
                    utils.UnixTSToReadable(self.stats.mtime), '.' if dot_name else self.filename)


@dataclasses.dataclass(eq=True)
class _EmulatedDirectory(_EmulatedFile):
  children: dict[str, _FSEntry]
  timeline_time: int = 0


@dataclasses.dataclass(eq=True)
class _LSEntry:
  """An ls entry for a filesystem object."""
  mode_as_string: str = '----------'
  uid: int = 0
  gid: int = 0
  size: int = 0
  mtime: str = '1970-01-01T00:00:00Z'
  name: str = ''

  def __str__(self) -> str:
    return f'{self.mode_as_string} {self.uid:>8} {self.gid:>8} {self.size:>12} {self.mtime} {self.name}'

  def __lt__(self, other: '_LSEntry') -> bool:
    if (self.mode_as_string[0], other.mode_as_string[0]).count('d') == 1:
      return self.mode_as_string[0] == 'd'
    return self.name < other.name


_LS_SORT_KEY_MAP = {
    'S': lambda l: l.size,
    't': lambda l: l.mtime
}


class GrrShellEmulatedFS:
  """Emulated remote FS for the GRR Shell client."""

  def __init__(self,
               os_type: str):
    """Initialises the emulated remote FS.

    Args:
      os_type: The OS for the emulated FS.
    """
    if os_type not in utils.OS_TYPES:
      raise ValueError(f'Invalid OS specified: {os_type}')

    self._os = os_type
    self._root = _EmulatedDirectory('/', _TimelineRow(), {})
    self._pwd: _EmulatedDirectory = self._root

    logger.debug('Initialising GrrShellEmulatedFS')

  def GetTimelineTime(self) -> int:
    """Gets the timeline time for the current path.

    Returns:
      The current timeline time.
    """
    return self._pwd.timeline_time

  def GetPWD(self) -> str:
    """Gets the current emulated working directory.

    Returns:
      The current emulated working directory.
    """
    return self._pwd.stats.name if self._pwd.stats.name else '/'

  def ParseTimelineFlow(self,
                        timeline_data: str,
                        timeline_time: int = 0) -> None:
    """Parses the result of a GRR TimelineFlow into an emulated filesystem.

    Args:
      timeline_data: The result of a grr TimelineFlow.
      timeline_time: The time the Timeline flow was produced.
    """
    logger.debug('Parsing timeline data')

    timeline_data = timeline_data.replace('\r', '')  # b/285992786

    for line in timeline_data.splitlines():
      if line[0] == '#':
        continue
      if self._os == utils.WINDOWS:
        line = line.replace(r'\\', '/')
      parts = re.split(r'(?<!\\)\|', line)  # Split on |, but not \|
      try:
        row = _TimelineRow(*parts)
      except TypeError:
        logger.debug('Error parsing line: "%s"', line, exc_info=True)
        raise
      self._AddRowToEmulatedFS(row, timeline_time)
    logger.debug('Parsing timeline data complete - %s', timeline_time)

    # Check if current PWD exists
    if not self.RemotePathExists(self.GetPWD(), dirs_only=True):
      self._pwd = self._root

  def NormaliseFSPath(self,
                      path: str) -> str:
    """Normalises an OS path.

    This includes resolving '../' and converting relative paths to absolute,
    given the pwd.

    Args:
      path: The FS path to normalise.

    Returns:
      The normalised path.
    """
    if not path:
      return '/'
    if path[0] == '/':  # absolute already
      return os.path.normpath(path)
    return os.path.normpath(os.path.join(self.GetPWD(), path))

  def RemotePathExists(self,
                       path: str,
                       dirs_only: bool = False) -> bool:
    """Checks if the path exists in the emulated FS.

    Args:
      path: The path to test.
      dirs_only: True if only directory entries should be considered, False
        otherwise.

    Returns:
      True if the path exists in the emulated FS, considering dirs_only, False
      otherwise.
    """
    try:
      path_entry = self._ResolveRemotePathToEmulatedFS(path)
      if dirs_only:
        return isinstance(path_entry, _EmulatedDirectory)
      return True
    except errors.InvalidRemotePathError:
      return False

  def Ls(self,
         path: Optional[str] = None,
         sortkey: Optional[str] = None,
         ascending: bool = True) -> list[_LSEntry]:
    """Returns a list of ls entries for a path.

    If a directory is provided, a list of children is returned. If a file is
    provided, a single entry for that file is returned.

    Args:
      path: The path in which to look for children.
      sortkey: Sorting method. Key for _LS_SORT_KEY_MAP dict.
      ascending: True if entries should be in ascending order, False otherwise,

    Returns:
      A list of ls entries.

    Raises:
      errors.InvalidRemotePathError: If the path does not exist in the emulated
        FS.
      RuntimeError: If unsupported globbing is attempted.
    """
    if not path:
      path = self.GetPWD()
    else:
      path = self.NormaliseFSPath(path)

    glob_tail: str = None

    if '*' in path:
      glob_tail = os.path.basename(path)
      path = os.path.dirname(path)
      if '*' in path:
        raise RuntimeError(
          f'Globbing only supported for the final path component: {os.path.join(path, glob_tail)}')

    path_entry = self._ResolveRemotePathToEmulatedFS(path)

    if isinstance(path_entry, _EmulatedDirectory):
      entries = [path_entry.GetLSEntry(dot_name=True)]
      for child in path_entry.children.values():
        entries.append(child.GetLSEntry())
      if glob_tail:
        globbed_names = fnmatch.filter([e.name for e in entries], glob_tail)
        entries = [e for e in entries if e.name in globbed_names]
    else:
      entries = [path_entry.GetLSEntry()]
    return sorted(entries, key=_LS_SORT_KEY_MAP.get(sortkey), reverse=not ascending)

  def Cd(self,
         path: str) -> None:
    """Changes the emulated working directory.

    Args:
      path: Path to change to.

    Raises:
      errors.InvalidRemotePathError: If the remote path does not exist.
      errors.IsAFileError: If the remote path is not a directory.
    """
    path = self.NormaliseFSPath(path)
    path_entry = self._ResolveRemotePathToEmulatedFS(path)

    if not isinstance(path_entry, _EmulatedDirectory):
      raise errors.IsAFileError(path)

    self._pwd = path_entry

  def GetChildrenOfPath(self,
                        path: str,
                        dirs_only: bool = False) -> list[str]:
    """Gets a list of child entries of a path.

    Args:
      path: The remote path to list children for.
      dirs_only: True to only return directory entries, False otherwise.

    Returns:
      A list of child entry names.

    Raises:
      errors.InvalidRemotePathError: If the path cannot be found in the
        emulated FS.
      errors.IsAFileError: If the path exists but is a File, rather than a
        directory.
    """
    path_entry = self._ResolveRemotePathToEmulatedFS(self.NormaliseFSPath(path))

    if not isinstance(path_entry, _EmulatedDirectory):
      raise errors.IsAFileError(path)

    children = list(path_entry.children.values())

    if dirs_only:
      children = [c for c in children if c.stats.mode_as_string[0] == 'd']

    return [f'{c.filename}/' if c.stats.mode_as_string[0] == 'd' else c.filename for c in children]

  def Find(self,
           basedir: str,
           needle: str) -> list[str]:
    """Searches all children of a directory for a value.

    Args:
      basedir: The base directory to start searching from. Will be normalised,
        relative to PWD.
      needle: What to search for (regex.)

    Returns:
      A list of file paths matching the needle.

    Raises:
      IsAFileError: If basedir is a file instead of a directory.
      InvalidRemotePathError: If basedir does not exist in the remote client FS.
    """
    basedir = self.NormaliseFSPath(basedir)
    if not self.RemotePathExists(basedir):
      raise errors.InvalidRemotePathError(f'Invalid directory: {basedir}')

    directory = self._ResolveRemotePathToEmulatedFS(basedir)
    if not isinstance(directory, _EmulatedDirectory):
      raise errors.IsAFileError(f'Starting directory is actually a file: {basedir}')

    matcher = re.compile(needle)
    results = self._GetFSTreeFromPath(directory)
    results = [r.stats.name for r in results if matcher.search(r.stats.name)]

    return sorted(results)

  def _AddRowToEmulatedFS(self,
                          row: _TimelineRow,
                          timeline_time: int = 0) -> None:
    """Adds a timeline row into the emulated FS.

    Args:
      row: The row to add.
      timeline_time: The time the Timeline flow was run.
    """
    if self._os == utils.WINDOWS:
      row.name = f'/{row.name}'

    if row.name == '/':
      self._root.stats = row
      self._root.timeline_time = timeline_time
      return

    current_ptr = self._root
    path_parts = os.path.normpath(row.name).split('/')
    last_part = path_parts[-1]
    fs_entry = (_EmulatedDirectory(last_part, row, {}, timeline_time)
                if row.mode_as_string[0] == 'd' else
                _EmulatedFile(last_part, row))

    for path_part in path_parts:
      if not path_part:
        continue
      if path_part not in current_ptr.children:
        if path_part == last_part:
          current_ptr.children[path_part] = fs_entry
        else:
          current_ptr.children[path_part] = _EmulatedDirectory(path_part, _TimelineRow(), {}, timeline_time)
      current_ptr = current_ptr.children[path_part]
    if current_ptr.stats == _TimelineRow():
      current_ptr.stats = row

  def ClearPath(self,
                remote_path: str,
                timeline_time: int) -> None:
    """Zeros out a path in anticipation of refreshing its timeline.

    Args:
      remote_path: The path to zero out.
      timeline_time: The time to embed in the new empty path.
    """
    if remote_path == '/':
      self._root = _EmulatedDirectory('/', _TimelineRow(), {}, timeline_time)
      return

    try:
      node = cast(_EmulatedDirectory, self._ResolveRemotePathToEmulatedFS(remote_path))
      node.timeline_time = timeline_time
      parent = cast(_EmulatedDirectory, self._ResolveRemotePathToEmulatedFS(os.path.dirname(node.stats.name)))
      parent.children.pop(node.filename)
    except errors.InvalidRemotePathError:
      pass  # Path doesn't exist, so clearing fails, and that's ok.

  def OfflineFileInfo(self, remote_path: str) -> str:
    """Returns file information based on the EFS content.

    Args:
      remote_path: The remote file to return cached info on.

    Returns:
      A string with information on the remote file.
    """
    remote_path = self.NormaliseFSPath(remote_path)

    try:
      entry = self._ResolveRemotePathToEmulatedFS(remote_path)
    except errors.InvalidRemotePathError:
      return f'No such file or directory: {remote_path}'

    natural_size = humanize.naturalsize(entry.stats.size, binary=True, format='%.1f')

    lines: list[str] = []
    lines.append(entry.stats.name)
    lines.append(f'    mode:   {entry.stats.mode_as_string}')
    lines.append(f'    inode:  {entry.stats.inode}')
    lines.append(f'    uid:    {entry.stats.uid}')
    lines.append(f'    gid:    {entry.stats.gid}')
    lines.append(f'    size:   {entry.stats.size} 'f'({natural_size})')
    lines.append(f'    atime:  {entry.stats.atime} - {utils.UnixTSToReadable(entry.stats.atime)}')
    lines.append(f'    mtime:  {entry.stats.mtime} - {utils.UnixTSToReadable(entry.stats.mtime)}')
    lines.append(f'    ctime:  {entry.stats.ctime} - {utils.UnixTSToReadable(entry.stats.ctime)}')
    lines.append(f'    crtime: {entry.stats.crtime} - {utils.UnixTSToReadable(entry.stats.crtime)}')

    return '\n'.join(lines)

  def _ResolveRemotePathToEmulatedFS(self, remote_path: str) -> _FSEntry:
    """Resolves a remote path string to a pointer into the emulated FS.

    Args:
      remote_path: the remote path to resolve. Normalisation should be performed
        by the caller before calling this method.

    Returns:
      A pointer into the emulated FS.

    Raises:
      errors.InvalidRemotePathError: If the path cannot be found in the
        emulated FS.
    """
    parts = [p for p in os.path.normpath(remote_path).split(os.sep) if p]

    current_ptr = self._root
    for part in parts:
      if part not in current_ptr.children:
        raise errors.InvalidRemotePathError(remote_path)
      current_ptr = current_ptr.children[part]
    return current_ptr

  def _GetFSTreeFromPath(self,
                         directory: _EmulatedDirectory) -> list[_FSEntry]:
    """Builds a list of all FS Entries descendent from a directory."""
    to_return: list[_FSEntry] = []

    for child in directory.children.values():
      if isinstance(child, _EmulatedDirectory):
        to_return += self._GetFSTreeFromPath(child)
      to_return.append(child)

    return to_return
