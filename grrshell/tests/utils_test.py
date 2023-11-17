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
"""Unit tests for util methods."""

from typing import Union

from absl.testing import absltest
from absl.testing import parameterized

from grrshell.lib import utils


class UnixTSToReadableTest(parameterized.TestCase):
  """Unit test for UnixTSToReadable utility method."""

  @parameterized.named_parameters(
      ('zero', 0, '1970-01-01T00:00:00Z'),
      ('from_int', 60, '1970-01-01T00:01:00Z'),
      ('from_float', 75.1234, '1970-01-01T00:01:15Z')
  )
  def test_UnixTSToReadable(self,
                            ts_in: Union[int, float],
                            expected: str):
    """Tests the UnixTSToReadable method."""
    result = utils.UnixTSToReadable(ts_in)
    self.assertEqual(result, expected)


if __name__ == '__main__':
  absltest.main()
