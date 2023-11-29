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
"""GRRShell background monitoring classes."""

import abc
import datetime
import itertools
import threading
import time
from typing import Iterator

from absl import logging

from grr_api_client import flow
from grr_api_client import api as grr_api
from grr_response_proto import flows_pb2


logger = logging.logging.getLogger('grrshell')


class _MonitorBase(metaclass=abc.ABCMeta):
  """Base class for background monitor classes."""

  DELAY = 60

  @abc.abstractmethod
  def __init__(self):
    self._mutex = threading.Lock()

  @abc.abstractmethod
  def _SingleFetch(self):
    """Collect the information that will be cached."""

  def StartMonitor(self):
    """Starts the monitor background thread."""
    logger.debug('Starting monitor thread for %s', self.__class__.__name__)
    threading.Thread(target=self._Monitor, daemon=True).start()

  def _Monitor(self):
    """Repeatedly polls _SingleFetch()."""
    while True:
      with self._mutex:
        self._SingleFetch()
      time.sleep(self.DELAY)


class LastSeenMonitor(_MonitorBase):
  """Background caching class for LastSeen time of a client."""

  def __init__(self, grr_client: grr_api.client.ClientRef):
    """Initialises the Monitor."""
    super().__init__()
    self._last_seen: datetime.datetime
    self._grr_client = grr_client

  def _SingleFetch(self):
    """Caches the LastSeen time of the client."""
    self._last_seen = datetime.datetime.fromtimestamp(
        self._grr_client.Get().data.last_seen_at / 1000000,
        tz=datetime.timezone.utc)
    logger.debug('Last seen: %s', self._last_seen)

  def GetLastSeen(self) -> datetime.datetime:
    """Gets the last seen time.

    Returns:
      The cached last seen time of the client.
    """
    with self._mutex:
      return self._last_seen


class FlowMonitor(_MonitorBase):
  """Background caching of Flow information."""

  def __init__(self, grr_client: grr_api.client.ClientRef):
    """Initialises the FlowMonitor."""
    super().__init__()
    self._grr_client = grr_client
    self._flows: dict[str, flow.Flow] = {}

  def _Monitor(self):
    """Repeatedly polls _SingleFetch()."""
    while True:
      with self._mutex:
        self._SingleFetch()

      for flow_id in self._flows:
        self._UpdateCachedFlow(flow_id)

      time.sleep(self.DELAY)

  def _SingleFetch(self):
    """Fetches all launched flows on the client."""
    logger.debug('Fetching launched flows')
    for flow_handle in self._grr_client.ListFlows():
      if flow_handle.flow_id not in self._flows:
        self._flows[flow_handle.flow_id] = flow_handle

  def GetFlowsInfoList(self, count: int = 50) -> Iterator[flow.Flow]:
    """Returns info on flows from the cache."""
    with self._mutex:
      values = list(self._flows.values())
      values = sorted(values,
                      key=lambda x: x.data.started_at, reverse=True)
      for f in itertools.islice(values, 0, count):
        yield f

  def GetFlow(self, flow_id: str) -> flow.Flow:
    """Returns cached info on a single flow."""
    self._UpdateCachedFlow(flow_id)
    with self._mutex:
      return self._flows[flow_id]

  def TrackFlow(self, flow_handle: flow.Flow) -> None:
    """Adds a launched flow to monitoring."""
    with self._mutex:
      self._flows[flow_handle.flow_id] = flow_handle

  def _UpdateCachedFlow(self, flow_id: str) -> None:
    """Fetches and caches info for a single flow."""
    if (flow_id not in self._flows or
        not self._flows[flow_id].data.args.TypeName() or
        self._flows[flow_id].data.state == flows_pb2.FlowContext.State.RUNNING):
      with self._mutex:
        flow_handle = self._grr_client.Flow(flow_id).Get()
        self._flows[flow_id] = flow_handle
