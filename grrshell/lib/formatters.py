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
"""GRR Shell flow result formatting."""

import io
import stat
from typing import Any, Callable
import zipfile

import humanize

from grr_api_client import flow
from grr_response_proto import flows_pb2
from grr_response_proto import jobs_pb2
from grrshell.lib import utils


class GRRShellFormatter:
  """Handles formatting flow output."""

  def __init__(self):
    """Initialises a formatter object."""
    self._callback_map: dict[str, Callable[[Any, flow.Flow], list[str]]] = {
        'FileFinderResult': self._FormatFileFinderInfoResult,
        'StatEntry': self._FormatStatEntry,
    }

  def FormatFlowResult(self, flow_handle: flow.Flow) -> list[str]:
    """Formats the result of a flow for display to an operator.

    Args:
      flow_handle: The Flow handle with which to extract results.

    Returns:
      A list of strings, one per line, of formatted output.

    Raises:
      RuntimeError: When unsupported output types are encountered.
    """
    lines: list[str] = []
    for result in flow_handle.ListResults():
      name = result.payload.DESCRIPTOR.name  # pytype: disable=attribute-error
      if name in self._callback_map:
        lines += self._callback_map[name](result.payload, flow_handle)
      else:
        raise RuntimeError(f'Unsupported result type for output formatting: {name}. Consider raising a bug for support.')
    return lines

  def _FormatStatEntry(self,
                       payload: jobs_pb2.StatEntry,
                       flow_handle: flow.Flow) -> list[str]:
    """Formats details for a StatEntry payload.

    Args:
      payload: The StatEntry payload to format.
      flow_handle: The Flow the stat entry originates from.

    Returns:
      A list of strings, one per line, of formatted output.

    Raises:
      RuntimeError: If the StatEntry type is unsupported.
    """
    args_typename = flow_handle.data.args.TypeName()

    if args_typename == 'grr.GetFileArgs':
      return self._FormatADSResults(payload, flow_handle)
    if payload.pathspec.pathtype == jobs_pb2.PathSpec.PathType.REGISTRY:
      return self._FormatRegistryResult(payload)
    raise RuntimeError('Unsupported StatEntry type')

  def _FormatFileFinderInfoResult(self,
                                  payload: flows_pb2.FileFinderResult,
                                  flow_handle: flow.Flow) -> list[str]:
    """Extracts file info for a ClientFileFinder flow with HASH action.

    Args:
      payload: The flow results to extract file info from.
      flow_handle: Unused for this formatter.

    Returns:
      A list of strings, one per line, of formatted output.
    """
    del flow_handle  # unused
    lines: list[str] = []

    stats = payload.stat_entry
    natural_size = humanize.naturalsize(stats.st_size, binary=True, format='%.1f')

    if stats.pathspec.mount_point and stats.pathspec.nested_path.path:
      pathname = stats.pathspec.mount_point + stats.pathspec.nested_path.path
    else:
      pathname = stats.pathspec.path

    lines.append(pathname)
    lines.append(f'    mode:           {stat.filemode(stats.st_mode)}')
    lines.append(f'    inode:          {stats.st_ino}')
    lines.append(f'    dev:            {stats.st_dev}')
    lines.append(f'    st_nlink:       {stats.st_nlink}')
    lines.append(f'    st_uid:         {stats.st_uid}')
    lines.append(f'    st_gid:         {stats.st_gid}')
    lines.append(f'    st_size:        {stats.st_size} 'f'({natural_size})')
    lines.append(f'    st_atime:       {stats.st_atime} - {utils.UnixTSToReadable(stats.st_atime)}')
    lines.append(f'    st_mtime:       {stats.st_mtime} - {utils.UnixTSToReadable(stats.st_mtime)}')
    lines.append(f'    st_ctime:       {stats.st_ctime} - {utils.UnixTSToReadable(stats.st_ctime)}')
    lines.append(f'    st_blocks:      {stats.st_blocks}')
    lines.append(f'    st_blksize:     {stats.st_blksize}')
    lines.append(f'    st_rdev:        {stats.st_rdev}')
    lines.append(f'    st_flags_osx:   {stats.st_flags_osx}')
    lines.append(f'    st_flags_linux: {stats.st_flags_linux}')
    lines.append(f'    md5:            {payload.hash_entry.md5.hex()}')
    lines.append(f'    sha1:           {payload.hash_entry.sha1.hex()}')
    lines.append(f'    sha256:         {payload.hash_entry.sha256.hex()}')

    return lines

  def _FormatADSResults(self,
                        payload: jobs_pb2.StatEntry,
                        flow_handle: flow.Flow) -> list[str]:
    """Extracts ADS info from a GetFile flow.

    Args:
      payload: A stat entry for the result.
      flow_handle: The ADS collection flow.

    Returns:
      A list of strings, one per line, of formatted output.
    """
    pathtype = jobs_pb2.PathSpec.PathType.Name(
        payload.pathspec.nested_path.pathtype).lower()
    path = (f'{flow_handle.client_id}_flow_{flow_handle.data.name}_{flow_handle.flow_id}/{flow_handle.client_id}/fs/{pathtype}'
            f'{payload.pathspec.path}{payload.pathspec.nested_path.path}:{payload.pathspec.nested_path.stream_name}')

    with io.BytesIO() as buf:
      for chunk in flow_handle.GetFilesArchive():
        buf.write(chunk)
      with zipfile.ZipFile(buf) as zip_file:
        try:
          zip_content = zip_file.read(path).decode('utf-8')
        except KeyError:
          return []
        lines: list[str] = []
        lines.append('    Zone.Identifier:')
        for line in zip_content.splitlines():
          lines.append(f'        {line}')
        return lines

  def _FormatRegistryResult(self, payload: jobs_pb2.StatEntry) -> list[str]:
    """Formats a Windows Registry payload for display.

    Args:
      payload: The StatEntry with the Registry results.

    Returns:
      A list of strings, one per line, of formatted output.
    """
    lines: list[str] = [
        f'    {payload.pathspec.path} '
        f'({jobs_pb2.StatEntry.RegistryType.Name(payload.registry_type)})']
    for descriptor, value in payload.registry_data.ListFields():
      lines.append(f'        {descriptor.name}: {value}')
    return lines
