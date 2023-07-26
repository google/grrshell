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
"""GRR Shell client."""

from concurrent import futures
import dataclasses
import datetime
import io
import itertools
import os
import re
import shutil
import stat
import tempfile
import time
import traceback
import typing
from typing import Any, Callable
import zipfile

from absl import logging
import humanize

from grr_api_client import errors as grr_errors
from grr_api_client import flow
from grr_api_client import api as grr_api
from grr_response_proto import flows_pb2
from grr_response_proto import jobs_pb2
from grr_response_proto import timeline_pb2
from grrshell.lib import errors
from grrshell.lib import utils


_GRR_ENDPOINT = 'blade:grr-adminui-stubby'
_STALE_TIMELINE_THRESHOLD = datetime.timedelta(hours=3)
_ROOT_TIMELINE_REGEX = r'/|(?:/?)[A-Z]:[/\\]'
_RESUMABLE_FLOW_TYPES = ('ClientFileFinder', 'ArtifactCollectorFlow', 'GetFile')


logger = logging.logging.getLogger('grrshell')


@dataclasses.dataclass
class _LaunchedFlow:
  """Holds information about a asynchronous flow."""
  future: futures.Future[None]
  flow: flow.Flow
  exception_displayed: bool = False


class GRRShellClient:
  """For use by GRR Shell, handles scheduling and collecting GRR flows."""

  def __init__(self,
               grr_server: str,
               grr_user: str,
               grr_pass: str,
               client_id: str,
               max_collect_size: int = 0):
    """Initialises the GRR Shell client.

    Args:
      grr_server: The GRR server endpoint url.
      grr_user: The GRR username.
      grr_pass: The GRR users password.
      client_id: The client to use. Can be a FQDN or GRR client ID.
      max_collect_size: The max file size for GRR collection. 0 for the GRR
        default.
    """
    logger.debug('Initialising GRRShellClient')

    self._launched_flows: dict[str, _LaunchedFlow] = {}
    self._collection_threads = futures.ThreadPoolExecutor(max_workers=40)

    self._grr_stubby = grr_api.InitHttp(api_endpoint=grr_server,
                                        auth=(grr_user, grr_pass))

    self._grr_client_id = self._ResolveClientID(client_id)
    self._grr_client = self._grr_stubby.Client(self._grr_client_id)
    self._os: str = None
    self._max_collect_size = max_collect_size
    self._artefact_list: list[str] = []
    self.last_timeline_time = 0

    try:
      self._grr_client.VerifyAccess()
    except grr_errors.AccessForbiddenError as exc:
      raise errors.NoGRRApprovalError(f'No approval for client access to {self._grr_client_id}') from exc

  def __del__(self):
    """Destructor for GRRShellClient.

    Waits for any launched flows to complete before exiting.
    """
    logger.debug('GRRShellClient Destruction')

    if any(f.future.running() for f in self._launched_flows.values()):
      pending_flows = ', '.join(f.flow.flow_id for f in self._launched_flows.values() if f.future.running())
      logger.debug('Waiting on flows to finish: %s', pending_flows)
      print(f'Waiting for collection threads {pending_flows} to finish (<CTRL+C> to force exit)')

    self._collection_threads.shutdown()
    logger.debug('ThreadPoolExecutor shutdown completed.')

    for launched in self._launched_flows.values():
      if launched.future.exception():
        logger.debug('Flow %s encountered exception:\n%s',
                     launched.flow.flow_id,
                     ''.join(traceback.format_exception(launched.future.exception())))
        if not launched.exception_displayed:
          print(f'{launched.flow.flow_id} - {str(launched.future.exception())}')

  def GetOS(self) -> str:
    """Gets the operating system of the client.

    Returns:
      The OS of the client.
    """
    if not self._os:
      logger.debug('Fetching OS info from grr')
      self._os = self._grr_client.Get().data.os_info.system
    return self._os

  def GetLastSeenTime(self) -> datetime.datetime:
    """Gets the last seen time of the client.

    Returns:
      The last seen time of the client.
    """
    last_seen = datetime.datetime.fromtimestamp(self._grr_client.Get().data.last_seen_at / 1000000,
                                                tz=datetime.timezone.utc)
    logger.debug('Last seen: %s', last_seen)
    return last_seen

  def GetClientID(self) -> str:
    """Gets the GRR client ID of the client.

    Returns:
      The GRR client ID of the client.
    """
    return self._grr_client_id

  def GetSupportedArtifacts(self) -> list[str]:
    """Returns a list of supported artifacts for the client."""
    if not self._artefact_list:
      self._artefact_list = [a.data.artifact.name for a in self._grr_stubby.ListArtifacts()
                             if self.GetOS() in a.data.artifact.supported_os]
    logger.debug('%d supported artefacts found', len(self._artefact_list))
    return self._artefact_list

  def GetLastTimeline(self) -> str | None:
    """Returns the Flow ID of the most recent root timeline."""
    flows = self._grr_client.ListFlows()
    latest_timeline = None
    latest_timestamp = (time.time() - _STALE_TIMELINE_THRESHOLD.total_seconds()) * 1000000
    for f in flows:
      if f.data.state != flows_pb2.FlowContext.TERMINATED:
        continue
      if f.data.name != 'TimelineFlow':
        continue
      if not re.fullmatch(_ROOT_TIMELINE_REGEX, str(f.Get().args.root, 'utf-8')):
        continue
      for result in f.ListResults():
        if result.timestamp > latest_timestamp:
          latest_timestamp = result.timestamp
          latest_timeline = f.flow_id

    return latest_timeline

  def CollectTimeline(self,
                      path: str | None = None,
                      existing_timeline: str | None = None) -> str:
    """Creates and waits for a GRR timeline flow.

    Args:
      path: The path for which to fetch a Timeline.
      existing_timeline: An existing TimelineFlow ID to use, rather than
        launching a new flow.

    Returns:
      The timeline flow data.
    """
    if existing_timeline:
      msg = f'Using existing timeline flow {existing_timeline}'
      print(msg)
      logger.debug(msg)
      flow_handle = self._grr_client.Flow(existing_timeline).Get()
    else:
      flow_args = self._grr_stubby.types.CreateFlowArgs('TimelineFlow')
      flow_args.root = b'/'
      if path:
        if self.GetOS() == utils.WINDOWS and path.startswith('/') and len(path) > 1:
          path = path[1:]
        flow_args.root = bytes(path, 'utf-8')
      flow_handle = self._grr_client.CreateFlow(name='TimelineFlow', args=flow_args)
      msg = f'Running timeline flow {flow_handle.flow_id}'
      print(msg)
      logger.debug(msg)
      logger.debug('TimelineFlow Args:\n%s', flow_args)

    flow_handle.WaitUntilDone()

    logger.debug('Timeline flow complete, collecting and decoding')

    results = flow_handle.ListResults()
    for result in results:
      self.last_timeline_time = result.timestamp
      break

    io_stream = io.BytesIO()
    body = flow_handle.GetCollectedTimelineBody()
    body.WriteToStream(io_stream)

    return io_stream.getvalue().decode()

  def FileInfo(self,
               remote_path: str,
               collect_ads: bool = False) -> str:
    """Synchronously collects file info and hashes for remote files.

    Also attempts to collect the "Zone.Identifier" Alternate Data Stream for
    single files on windows. (Multiple files are not supported currently:
    b/288501445)

    Args:
      remote_path: The remote files to stat.
      collect_ads: True to attempt to collect the Zone.Identifier alternate
        data stream, False otherwise.

    Returns:
      Information on the files for display.
    """
    if self.GetOS() == utils.WINDOWS and remote_path.startswith('/'):
      remote_path = remote_path[1:]

    collect_ads = collect_ads and self.GetOS() == utils.WINDOWS and '*' not in remote_path
    zone_ads_result = ''

    hash_flow_handle = self._CreateFileFinderFlow(remote_path, flows_pb2.FileFinderAction.HASH)
    print(f'Running Hash flow {hash_flow_handle.flow_id}')

    if collect_ads:
      ads_flow_handle = self._CreateADSCollectionFlow(remote_path)
      print(f'Running ADS (Zone.Identifier) collection flow {ads_flow_handle.flow_id}')
      try:
        ads_flow_handle.WaitUntilDone()
        zone_ads_result = self._ExtractADSResults(ads_flow_handle)
      except grr_errors.FlowFailedError as error:
        msg = f'ADS Flow collection {ads_flow_handle.flow_id} failed: {str(error)}'
        logger.debug(msg, exc_info=True)
        print(msg)

    try:
      hash_flow_handle.WaitUntilDone()
    except grr_errors.FlowFailedError as error:
      msg = f'HASH Flow collection {hash_flow_handle.flow_id} failed: {str(error)}'
      logger.debug(msg, exc_info=True)
      print(msg)
      return ''

    lines: list[str] = self._ExtractFileFinderInfo(hash_flow_handle)
    if zone_ads_result:
      lines += zone_ads_result
    lines.append('')

    return '\n'.join(lines)

  def CollectFiles(self,
                   remote_path: str,
                   local_path: str) -> None:
    """Collects files from the remote client.

    Args:
      remote_path: A GRR ClientFileFinder path
      local_path: local path to store results
    """
    local_path = os.path.realpath(local_path)
    self._CreateOutputDir(local_path)

    print(f'Collecting files: {remote_path}')

    ff_flow = self._CreateFileFinderFlow(remote_path, flows_pb2.FileFinderAction.DOWNLOAD)
    print(f'Started flow {ff_flow.flow_id}')

    self._WaitAndCompleteFlow(ff_flow, local_path)

  def CollectArtifact(self,
                      artifact: str,
                      local_path: str) -> None:
    """Collects artifacts from the remote client via the ArtifactCollectorFlow.

    Args:
      artifact: The artifact name.
      local_path: Where to store flow results.
    """
    local_path = os.path.realpath(local_path)
    self._CreateOutputDir(local_path)

    print(f'Collecting artifact: {artifact}')

    ac_flow = self._CreateArtifactCollectorFlow(artifact)

    print(f'Started flow {ac_flow.flow_id}')

    self._WaitAndCompleteFlow(ac_flow, local_path)

  def CollectFilesInBackground(self,
                               remote_path: str,
                               local_path: str) -> None:
    """Asynchronously collects files from the remote client.

    Args:
      remote_path: The remote files to collect.
      local_path: The local path to store the collected files.
    """
    print(f'Collecting files: {remote_path}')
    logger.debug('Launching background ClientFileFinder flow')

    ff_flow = self._CreateFileFinderFlow(remote_path, flows_pb2.FileFinderAction.DOWNLOAD)
    future = self._collection_threads.submit(self._WaitAndCompleteFlow, ff_flow, local_path)
    self._launched_flows[ff_flow.flow_id] = _LaunchedFlow(future, ff_flow)

    print(f'Started flow {ff_flow.flow_id}')

  def CollectArtifactInBackground(self,
                                  artifact: str,
                                  local_path: str) -> None:
    """Asynchronously collects artifacts from the remote client.

    Args:
      artifact: The artifact name.
      local_path: The local path to store the collected files.
    """
    print(f'Collecting artifact: {artifact}')
    logger.debug('Launching background ArtifactCollectorFlow flow')

    ac_flow = self._CreateArtifactCollectorFlow(artifact)

    future = self._collection_threads.submit(self._WaitAndCompleteFlow, ac_flow, local_path)
    self._launched_flows[ac_flow.flow_id] = _LaunchedFlow(future, ac_flow)

    print(f'Started flow {ac_flow.flow_id}')

  def GetBackgroundFlowsState(self) -> str:
    """Gets information about launched flows.

    Returns:
      Details on background flows tha thave been launched.
    """
    logger.debug('Fetching background flow states')
    if not self._launched_flows:
      return 'No launched flows'

    to_return: list[str] = []

    for bg_flow in self._launched_flows.values():
      running = bg_flow.future.running()

      # Refresh flow state if last known state was RUNNING
      if bg_flow.flow.data.state == flows_pb2.FlowContext.RUNNING:
        logger.debug('Refreshing state for flow: %s', bg_flow.flow.flow_id)
        bg_flow.flow = bg_flow.flow.Get()
      if bg_flow.flow.data.state == flows_pb2.FlowContext.TERMINATED:
        if running:
          state = 'DOWNLOADING'
        else:
          state = 'COMPLETE'
      else:
        state = flows_pb2.FlowContext.State.Name(bg_flow.flow.data.state)

      param = self._ParseArgsFromFlow(bg_flow.flow)

      error_msg = ''
      if not running and bg_flow.future.exception():
        error_msg = f' "{str(bg_flow.future.exception())}"'
        bg_flow.exception_displayed = True

      to_return.append(f'\t{bg_flow.flow.flow_id} {bg_flow.flow.data.name} {param} {state}{error_msg}')

    return '\n'.join(to_return)

  def GetRunningFlowCount(self) -> tuple[int, int]:
    """Gets the current running and total background flows count.

    Returns:
      A Tuple of:
        * The number of flows currently running.
        * The total number of background flows launched.
    """
    running = sum((1 for f in self._launched_flows.values() if f.future.running()))
    return running, len(self._launched_flows)

  def SetMaxFilesize(self,
                     size: int) -> None:
    """Sets the max file size for collection.

    Args:
      size: The size to use. 0 for GRR default.
    """
    self._max_collect_size = size

  def ListAllFlows(self,
                   count: int) -> str:
    """Lists flow details for flows launched on the client.

    Includes all flows, not just those launched by GRRShell.
    
    Args:
      count: Max number of flows to detail.

    Returns:
      A string with details, one per line, of floaws launched on the client.
    """
    lines: list[str] = []
    flows = itertools.islice(self._grr_client.ListFlows(), count)

    for f in flows:
      flow_handle = f.Get()
      lines.append(f'\t{flow_handle.flow_id} {utils.UnixTSToReadable(flow_handle.data.started_at / 1000000)} '
                   f'{flow_handle.data.name} {self._ParseArgsFromFlow(flow_handle)} '
                   f'{flows_pb2.FlowContext.State.Name(flow_handle.data.state)}')
    return '\n'.join(lines)

  def ResumeFlow(self,
                 flow_id: str,
                 local_path: str | None = None) -> list[str]:
    """Resumes an existing flow, not attached to this GRRShell session.

    Adds the existing launched flow to the background flows.

    Args:
      flow_id: The flow to resume.
      local_path: The path to download files to, if needed.

    Returns:
      A list of strings split on newlines for output.

    Raises:
      NotResumeableFlowTypeError: If the flow type is not supported for
        resumption.
    """
    flow_handle = self._grr_client.Flow(flow_id).Get()

    if flow_handle.data.name not in _RESUMABLE_FLOW_TYPES:
      raise errors.NotResumeableFlowTypeError(
        f'Flow {flow_handle.flow_id} is of type {flow_handle.data.name}, not supported for resumption.')

    if flow_handle.flow_id in self._launched_flows:
      return [f'{flow_handle.flow_id} already tracked by this GRRShell session']

    is_synchronous, callback = self._GetResumableFlowSyncDetails(flow_handle)

    if is_synchronous:
      flow_handle.WaitUntilDone()
      lines = callback(flow_handle) + ['']
      return lines
    else:
      future = self._collection_threads.submit(self._WaitAndCompleteFlow, flow_handle, local_path)
      self._launched_flows[flow_handle.flow_id] = _LaunchedFlow(future, flow_handle)
      return [f'Queued {flow_handle.flow_id} for completion.']

  def Detail(self,
             flow_id: str) -> str:
    """Fetches detailed information on a flow.

    Args:
      flow_id: The Flow ID to fetch information on.

    Returns:
      Detailed information on the flow.
    """
    flow_handle = self._grr_client.Flow(flow_id).Get()

    lines: list[str] = [
        flow_handle.data.name,
        f'\tCreator     {flow_handle.data.creator}',
        f'\tArgs        {self._ParseArgsFromFlow(flow_handle)}',
        f'\tState       {flows_pb2.FlowContext.State.Name(flow_handle.data.state)}',
        f'\tStarted     {utils.UnixTSToReadable(flow_handle.data.started_at / 1000000)}',
        f'\tLast Active {utils.UnixTSToReadable(flow_handle.data.last_active_at / 1000000)}']

    if flow_handle.data.state == flows_pb2.FlowContext.ERROR and flow_handle.data.context.status:
      # We need to manually parse out the error message :(
      status_lines = [l.strip() for l in flow_handle.data.context.status.splitlines()]
      error_message = [l.replace('error_message : ', '') for l in status_lines
                       if l.startswith('error_message : ')][0]
      lines.append('\tError Details')
      lines.append(f'\t\t{error_message}')

    return '\n'.join(lines)

  def _ResolveClientID(self,
                       client_id: str) -> str:
    """Resolves a client id or hostname to a client id.

    Args:
      client_id: A FQDN or GRR client ID.

    Returns:
      A GRR Client ID.

    Raiese:
      ClientNotFoundError: If a single GRR client could not be found, or
        multiple potential clients are found.
    """
    logger.debug('Resolving client identifier: %s', client_id)
    results = list(self._grr_stubby.SearchClients(client_id))

    if len(results) == 1:
      logger.debug('Client identifier resolved to: %s', results[0].client_id)
      return results[0].client_id

    logger.debug('%d potential clients found', len(results))
    logger.debug('Potential clients: %s', ', '.join([r.client_id for r in results]))
    raise errors.ClientNotFoundError(f'{len(results)} potential clients found with search {client_id}. Specify a client ID instead.')

  def _CreateFileFinderFlow(self,
                            remote_path: str,
                            action: flows_pb2.FileFinderAction.Action) -> flow.Flow:
    """Launches a FileFinder flow.

    Args:
      remote_path: The remote file path to collect.
      action: The FileFinder action to take.

    Returns:
      A GRR flow object.
    """
    logger.debug('Launching a ClientFileFinder flow')

    flow_args: flows_pb2.FileFinderArgs = self._grr_stubby.types.CreateFlowArgs('ClientFileFinder')

    if self.GetOS() == utils.WINDOWS:
      flow_args.pathtype = jobs_pb2.PathSpec.NTFS
      if remote_path.startswith('/'):
        remote_path = remote_path[1:]
    else:
      flow_args.pathtype = jobs_pb2.PathSpec.OS

    flow_args.paths.append(remote_path)
    flow_args.action.action_type = action
    if self._max_collect_size:
      if action == flows_pb2.FileFinderAction.HASH:
        flow_args.action.hash.max_size = self._max_collect_size
      elif action == flows_pb2.FileFinderAction.DOWNLOAD:
        flow_args.action.download.max_size = self._max_collect_size

    ff_flow = self._grr_client.CreateFlow(name='ClientFileFinder', args=flow_args)

    logger.debug('Launched flow %s', ff_flow.flow_id)
    logger.debug('Flow args: %s', ff_flow.data)

    return ff_flow

  def _CreateADSCollectionFlow(self,
                               remote_path: str) -> flow.Flow:
    """Creates a GetFile flow for a Zone.Identifier ADS of a file."""
    flow_args = flows_pb2.GetFileArgs(
        pathspec=jobs_pb2.PathSpec(path=remote_path,
                                   pathtype=jobs_pb2.PathSpec.NTFS,
                                   stream_name='Zone.Identifier'))
    ads_flow = self._grr_client.CreateFlow(name='GetFile', args=flow_args)

    logger.debug('Launched flow %s', ads_flow.flow_id)
    logger.debug('Flow args: %s', ads_flow.data)

    return ads_flow

  def _CreateArtifactCollectorFlow(self,
                                   artifact: str) -> flow.Flow:
    """Launches an ArtifactCollectorFlow.

    Args:
      artifact: The artifact to collect.

    Returns:
      A Flow handle.
    """
    logger.debug('Launching a ArtifactCollectorFlow flow')

    flow_args: flows_pb2.ArtifactCollectorFlowArgs = self._grr_stubby.types.CreateFlowArgs('ArtifactCollectorFlow')
    flow_args.artifact_list.append(artifact)
    flow_args.use_raw_filesystem_access = self.GetOS() == utils.WINDOWS
    flow_args.apply_parsers = False
    if self._max_collect_size:
      flow_args.max_file_size = self._max_collect_size

    ac_flow = self._grr_client.CreateFlow(name='ArtifactCollectorFlow', args=flow_args)

    logger.debug('Launched flow %s', ac_flow.flow_id)
    logger.debug('Flow args: %s', ac_flow.data)

    return ac_flow

  def _WaitAndCompleteFlow(self,
                           ff_flow: flow.Flow,
                           local_path: str) -> None:
    """Waits for a flow to complete, and writes the results to disk.

    Args:
      ff_flow: The Flow to wait for.
      local_path: Path on local machine to write the flow results to. If the
        path is the current working directory, create a directory based on the
        client ID, and use that.
    """
    logger.debug('Waiting for flow: %s', ff_flow.flow_id)
    ff_flow.WaitUntilDone()
    logger.debug('Completed flow: %s', ff_flow.flow_id)
    logger.debug('Completed flow data: %s', ff_flow.data)

    if os.path.abspath(local_path) == os.getcwd():
      if not os.getcwd().endswith(self._grr_client.client_id):
        # Create a directory based on the client ID
        local_path = os.path.join(local_path, self._grr_client_id)
        os.makedirs(local_path, exist_ok=True)

    self._ExportFlowResults(ff_flow, local_path)

  def _ExtractFileFinderInfo(self,
                             flow_handle: flow.Flow) -> list[str]:
    """Extracts file info for a ClientFileFinder flow with HASH action.

    Args:
      flow_handle: The flow to extract file info from.

    Returns:
      A list of lines detailing the flow results.
    """
    lines: list[str] = []

    for result in flow_handle.ListResults():
      payload = typing.cast(flows_pb2.FileFinderResult, result.payload)
      stats = payload.stat_entry
      natural_size = humanize.naturalsize(stats.st_size,
                                          binary=True,
                                          format='%.1f')

      if self.GetOS() == utils.WINDOWS:
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

  def _ExtractADSResults(self,
                         ads_flow: flow.Flow) -> list[str]:
    """Given an ADS collection (GetFile flow), extracts the content.

    ADS is a secondary stream in NTFS, so the data is returned similar to
    collecting a file: file content within a collected zip, so needs to be
    extracted.

    Args:
      ads_flow: The flow handle for the ADS collection.

    Returns:
      A list of strings, split on newlines, of the ADS data.
    """
    results = list(ads_flow.ListResults())
    if not results:
      return []

    stats = typing.cast(jobs_pb2.StatEntry, results[0].payload)  # Only ever one result
    pathtype = jobs_pb2.PathSpec.PathType.Name(stats.pathspec.nested_path.pathtype).lower()
    path = (f'{ads_flow.client_id}_flow_{ads_flow.data.name}_'
            f'{ads_flow.flow_id}/{ads_flow.client_id}/fs/{pathtype}'
            f'{stats.pathspec.path}{stats.pathspec.nested_path.path}:'
            f'{stats.pathspec.nested_path.stream_name}')

    with io.BytesIO() as buf:
      for chunk in ads_flow.GetFilesArchive():
        buf.write(chunk)
      zip_file = zipfile.ZipFile(buf)
      try:
        zip_content = zip_file.read(path).decode('utf-8')
        lines: list[str] = []
        lines.append('    Zone.Identifier:')
        for line in zip_content.splitlines():
          lines.append(f'        {line}')
        return lines
      except KeyError as e:
        return []

  def _ExportFlowResults(self,
                         ff_flow: flow.Flow,
                         local_path: str) -> None:
    """Writes the results of a flow to disk.

    Args:
      ff_flow: The Flow to collect a result from.
      local_path: The local path to export the results to.

    Raises:
      InvalidRemotePathError: If the flow found no files at the remote path.
    """
    logger.debug('Exporting results for flow: %s', ff_flow.flow_id)
    os_base = 'ntfs' if self.GetOS() == utils.WINDOWS else 'os'

    if not list(ff_flow.ListResults()):
      raise errors.InvalidRemotePathError(f'No FileFinder results for {ff_flow.flow_id}')

    with tempfile.NamedTemporaryFile(mode='wb+') as fp:
      logger.debug('Writing zip file for %s to %s', ff_flow.flow_id, fp.name)
      for chunk in ff_flow.GetFilesArchive():
        fp.write(chunk)

      logger.debug('Extracting zip file for %s to %s', ff_flow.flow_id, local_path)
      zip_file = zipfile.ZipFile(fp)
      zip_root_dir = f'{self._grr_client.client_id}_flow_{ff_flow.data.name}_{ff_flow.flow_id}'

      for file_info in zip_file.infolist():
        if (file_info.filename.endswith(f'{ff_flow.flow_id}/MANIFEST') or
            file_info.filename.endswith(f'{self._grr_client.client_id}/client_info.yaml')):
          logger.debug('Skipping extraction of %s based on filename match', file_info.filename)
          continue
        logger.debug('Extracting %s to %s', file_info.filename, local_path)

        nested_file_path = file_info.filename.replace(
            os.path.join(zip_root_dir, self._grr_client.client_id, 'fs', os_base) + os.path.sep,
            '')
        dest_file_path = os.path.join(local_path, nested_file_path)
        os.makedirs(os.path.dirname(dest_file_path), exist_ok=True)

        extracted_file = zip_file.extract(file_info, local_path)
        logger.debug('Moving %s to %s', extracted_file, dest_file_path)
        shutil.move(extracted_file, dest_file_path)

      shutil.rmtree(os.path.join(local_path, zip_root_dir))

  def _CreateOutputDir(self,
                       local_path: str) -> None:
    """Creates a directory for collected file output.

    Args:
      local_path: The local path to create.
    Raises:
      FileExistsError: If local_path exists and is not a directory
      DirectoryNotEmptyError: If local_path exists, and is a non-empty directory
    """
    logger.debug('Creating output directory: %s', local_path)
    if os.path.exists(local_path):
      if not os.path.isdir(local_path):
        raise FileExistsError(local_path)
    else:
      os.makedirs(local_path, exist_ok=True)

  def _ParseArgsFromFlow(self, flow_handle: flow.Flow) -> str:
    """Parse out flow args from a flow object.

    Args:
      flow_handle: The flow to extract runtime args from.

    Returns:
      The argument for the flow.
    """
    # Flow data args can be various args protos, depending on the flow type
    # that was launched.
    def FileFinderArgsParse(args: Any) -> str:
      ff_args = flows_pb2.FileFinderArgs.FromString(args.value)
      action = flows_pb2.FileFinderAction.Action.Name(ff_args.action.action_type)
      return f'{action} {ff_args.paths[0]}'

    def TimelineArgsParse(args: Any) -> str:
      return timeline_pb2.TimelineArgs.FromString(args.value).root.decode('utf-8')

    def ArtifactCollectorFlowArgsParse(args: Any) -> str:
      return flows_pb2.ArtifactCollectorFlowArgs.FromString(args.value).artifact_list[0]

    def GetFileArgsParse(args: Any) -> str:
      args = flows_pb2.GetFileArgs.FromString(args.value)
      param = args.pathspec.path
      if args.pathspec.stream_name:
        param = f'{param}:{args.pathspec.stream_name}'
      return param

    parsing_functions = {
        'google3.ops.security.grr.FileFinderArgs': FileFinderArgsParse,
        'google3.ops.security.grr.GetFileArgs': GetFileArgsParse,
        'google3.ops.security.grr.TimelineArgs': TimelineArgsParse,
        'google3.ops.security.grr.ArtifactCollectorFlowArgs': ArtifactCollectorFlowArgsParse,
    }

    typename = flow_handle.data.args.TypeName()
    if typename in parsing_functions:
      return parsing_functions[typename](flow_handle.data.args)
    return '<UNSUPPORTED FLOW TYPE>'

  def _GetResumableFlowSyncDetails(
      self,
      flow_handle: flow.Flow) -> tuple[bool, Callable[[flow.Flow], list[str]] | None]:
    """Given a flow, details if resuming the flow should be synchronous or not.

    If a flow is synchronous, then a callback is also provided for how to handle
    the flow result. All asynchronous flows use _ExportFlowResults via the
    background handler, so a callback is not provided in that scenario.

    Args:
      flow_handle: The flow to calculate details on synchronicity.

    Returns:
      A tuple of:
        bool: True if resuming the flow should be synchronous, False for
          asynchronous.
        Callable: The method to handle flow result when it completes. None if
          the flow is asynchronous.

    Raises
      NotResumeableFlowTypeError: If the flow is not supported for resumption.
    """
    if flow_handle.data.name == 'GetFile':
      return True, self._ExtractADSResults
    if flow_handle.data.name == 'ArtifactCollectorFlow':
      return False, None
    if flow_handle.data.name == 'ClientFileFinder':
      ff_args = flows_pb2.FileFinderArgs.FromString(flow_handle.data.args.value)
      if ff_args.action.action_type == flows_pb2.FileFinderAction.DOWNLOAD:
        return False, None
      return True, self._ExtractFileFinderInfo

    raise errors.NotResumeableFlowTypeError(
        f'Flow {flow_handle.flow_id} is of type {flow_handle.data.name}, not supported for resumption.')
