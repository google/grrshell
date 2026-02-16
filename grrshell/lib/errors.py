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
"""Grr shell error definitions."""


class InvalidRemotePathError(Exception):
  """Raised when an invalid remote path is specified."""


class ClientNotFoundError(Exception):
  """Raised when a hostname does not resolve to exactly one client."""


class IsAFileError(Exception):
  """Raised when a file is treated like a directory (eg. cd'ing to a file.)"""


class NoGRRApprovalError(Exception):
  """Raised when the user has not gotten approval to access the client."""


class NotResumeableFlowTypeError(Exception):
  """"Raised when attempting to resume a flow which does not support resumption.
  """


class TimelineDecodingError(Exception):
  """Raised when decoding the timeline fails."""


class InvalidOSError(Exception):
  """Raised when the OS is not applicable for a given operation."""
