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
"""Unit tests for the Grr Shell Emulated FS class."""

from typing import Optional

from absl.testing import absltest
from absl.testing import parameterized

from grrshell.lib import errors
from grrshell.lib import grr_shell_emulated_fs


_SAMPLE_TIMELINE_DARWIN = 'grrshell/tests/testdata/sample_timeline_darwin'
_SAMPLE_TIMELINE_LINUX = 'grrshell/tests/testdata/sample_timeline_linux'
_SAMPLE_TIMELINE_LINUX_OVERLAY = 'grrshell/tests/testdata/sample_timeline_linux_overlay'
_SAMPLE_TIMELINE_WINDOWS = 'grrshell/tests/testdata/sample_timeline_windows'
_SAMPLE_TIMELINE_WINDOWS_D_DRIVE = 'grrshell/tests/testdata/sample_timeline_windows_d_drive'

_EXPECTED_OFFLINE_INFO_FILE = """/root/.bashrc
    mode:   -rw-------
    inode:  6815746
    uid:    0
    gid:    0
    size:   571 (571 Bytes)
    atime:  1644801907.2463605 - 2022-02-14T01:25:07Z
    mtime:  1618084800.0 - 2021-04-10T20:00:00Z
    ctime:  1644801907.2463605 - 2022-02-14T01:25:07Z
    crtime: 0.0 - 1970-01-01T00:00:00Z"""
_EXPECTED_OFFLINE_INFO_DIRECTORY = """/root
    mode:   drwx--S---
    inode:  6815745
    uid:    0
    gid:    0
    size:   4096 (4.0 KiB)
    atime:  1683360703.224626 - 2023-05-06T08:11:43Z
    mtime:  1679618652.750104 - 2023-03-24T00:44:12Z
    ctime:  1679618652.750104 - 2023-03-24T00:44:12Z
    crtime: 0.0 - 1970-01-01T00:00:00Z"""


# pytype: disable=attribute-error
# pylint: disable=protected-access


class GrrShellEmulatedFSLinuxTest(parameterized.TestCase):
  """Unit tests for the Grr Shell Emulated FS class with a linux FS."""

  def setUp(self):
    """Set up tests."""
    super().setUp()
    with open(_SAMPLE_TIMELINE_LINUX, 'rb') as f:
      self.timeline_data = f.read().decode('utf-8')
    self.emulated_fs = grr_shell_emulated_fs.GrrShellEmulatedFS('Linux')

  def test_ParseTimelineFlow(self):
    """Tests the ParseTimeline method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)

    self.assertIn('root', self.emulated_fs._root.children)
    self.assertIn('.bashrc', self.emulated_fs._root.children['root'].children)

  def test_AddRowToEmulatedFS(self):
    """Tests the AddRowToEmulatedFS method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)
    timeline_entry = '0|/root/file|7|-rwx------|6|5|4096|1683360700.01|1683360701.02|1683360702.03|0.0'
    row = grr_shell_emulated_fs._TimelineRow(*timeline_entry.split(sep='|'))

    self.assertNotIn('file', self.emulated_fs._root.children['root'].children)

    self.emulated_fs._AddRowToEmulatedFS(row)

    self.assertIn('file', self.emulated_fs._root.children['root'].children)
    self.assertEqual(self.emulated_fs._root.children['root'].children['file'].stats, row)

  def test_CD_PWD(self):
    """Tests the cd and pwd methods."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)
    self.assertEqual('/', self.emulated_fs.GetPWD())

    self.emulated_fs.Cd('/root/.local')
    self.assertEqual('/root/.local', self.emulated_fs.GetPWD())

    self.emulated_fs.Cd('share/')
    self.assertEqual('/root/.local/share', self.emulated_fs.GetPWD())

    with self.assertRaisesRegex(errors.IsAFileError, '/root/.local/share/nano'):
      self.emulated_fs.Cd('nano')
    self.assertEqual('/root/.local/share', self.emulated_fs.GetPWD())

    self.emulated_fs.Cd('../../.cache')
    self.assertEqual('/root/.cache', self.emulated_fs.GetPWD())

    with self.assertRaisesRegex(errors.InvalidRemotePathError, '/does not exist'):
      self.emulated_fs.Cd('does not exist')
    self.assertEqual('/root/.cache', self.emulated_fs.GetPWD())

    self.emulated_fs.Cd('../../../../../../../../')
    self.assertEqual('/', self.emulated_fs.GetPWD())

  @parameterized.named_parameters(
      ('dir_exists', '/root', False, True),
      ('dir_exists_dirs_only', '/root', True, True),
      ('file_exists', '/root/.bashrc', False, True),
      ('file_exists_dirs_only', '/root/.bashrc', True, False),
      ('doesnt_exist', '/nonexistent', False, False),
      ('doesnt_exist_dirs_only', '/nonexistent', True, False),
  )
  def test_RemotePathExists(self, path: str,
                            dirs_only: bool,
                            expected_resuslt: bool):
    """Tests the RemotePathExists method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)
    result = self.emulated_fs.RemotePathExists(path, dirs_only)
    self.assertEqual(result, expected_resuslt)

  @parameterized.named_parameters(
      ('no_path', None, ['.', 'odd', 'root', 'root_file']),
      ('root_dir', '/root', ['.', '.augeas', '.cache', '.local', '.pki', '.ssh', 'directory with spaces', '.bashrc', '.lesshst', '.profile',
                             '.wget-hsts', 'dead.letter', 'xorg.conf.new']),
      ('file', '/root/.bashrc', ['.bashrc']),
      ('glob_raw', '*', ['.', 'odd', 'root', 'root_file']),
      ('glob_root', '/*', ['.', 'odd', 'root', 'root_file']),
      ('glob_slash_ro', '/ro*', ['root', 'root_file']),
      ('glob_subdir', '/root/*e*', ['.augeas', '.cache', 'directory with spaces', '.lesshst', '.profile', '.wget-hsts', 'dead.letter',
                                    'xorg.conf.new'])
  )
  def test_LS(self, path: Optional[str], expected_results: list[str]):
    """Tests the LS method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)

    results = [r.name for r in self.emulated_fs.Ls(path)]
    self.assertEqual(results, expected_results)

  def test_LSGlobbingError(self):
    """Tests LS with invalid globbing."""
    with self.assertRaisesRegex(RuntimeError, r'Globbing only supported for the final path component: /tmp/pa\*th/entry'):
      self.emulated_fs.Ls('/tmp/pa*th/entry')

  @parameterized.named_parameters(
      ('root', '/root', False, ['.bashrc', '.profile', '.pki/', '.cache/', '.local/', '.wget-hsts', '.ssh/', '.lesshst',
                                '.augeas/', 'dead.letter', 'xorg.conf.new', 'directory with spaces/']),
      ('root_dirs_only', '/root', True, ['.pki/', '.cache/', '.local/', '.ssh/', '.augeas/', 'directory with spaces/'])
  )
  def test_GetChildrenOfPath(self,
                             remote_path: str,
                             dirs_only: bool,
                             expected_results: list[str]):
    """Tests the GetChildrenOfPath method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)

    results = self.emulated_fs.GetChildrenOfPath(remote_path, dirs_only=dirs_only)
    self.assertCountEqual(results, expected_results)

  def test_GetChildrenOfPathErrors(self):
    """Tests errors thrown by the GetChildrenOfPath method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)

    with self.assertRaisesRegex(errors.InvalidRemotePathError, '/nonexistent'):
      self.emulated_fs.GetChildrenOfPath('/nonexistent')

    with self.assertRaisesRegex(errors.IsAFileError, '/root/.bashrc'):
      self.emulated_fs.GetChildrenOfPath('/root/.bashrc')

  @parameterized.named_parameters(
      ('slash_none_bash', '/', '', 'bash', ['/root/.bashrc']),
      ('root_none_bash', '/root', '', 'bash', ['/root/.bashrc']),
      ('slash_root_bash', '/', 'root', 'bash', ['/root/.bashrc']),
      ('slash_none_regex', '/', '', '.*ca[cd].*', ['/root/.cache', '/root/.cache/dconf', '/root/.cache/dconf/user']),
  )
  def test_Find(self, starting_pwd, base_dir, needle, expected_results):
    """Tests the Find method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)

    self.emulated_fs.Cd(starting_pwd)

    results = self.emulated_fs.Find(base_dir, needle)
    self.assertCountEqual(results, expected_results)

  @parameterized.named_parameters(
      ('nonexistent_directory', '/', '/nonexistent', 'bash', errors.InvalidRemotePathError),
      ('directory_is_a_file', '/', '/root/.bashrc', 'bash', errors.IsAFileError),
  )
  def test_FindErrors(self, starting_pwd, base_dir, needle, expected_exception):
    """Tests the Find method with erroneous input."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)

    self.emulated_fs.Cd(starting_pwd)

    with self.assertRaisesRegex(expected_exception, base_dir):
      self.emulated_fs.Find(base_dir, needle)

  @parameterized.named_parameters(
      ('file', '/root/.bashrc', _EXPECTED_OFFLINE_INFO_FILE),
      ('directory', '/root/', _EXPECTED_OFFLINE_INFO_DIRECTORY),
      ('error', '/nonexistent', 'No such file or directory: /nonexistent'),
  )
  def test_OfflineFileInfo(self, path, expected_result):
    """Tests OfflineFileInfo with an invalid path."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)
    result = self.emulated_fs.OfflineFileInfo(path)
    self.assertEqual(result, expected_result)


class GrrShellEmulatedFSWindowsTest(parameterized.TestCase):
  """Unit tests for the Grr Shell Emulated FS class with a Windows FS."""

  def setUp(self):
    """Set up."""
    super().setUp()
    with open(_SAMPLE_TIMELINE_WINDOWS, 'rb') as f:
      self.timeline_data = f.read().decode('utf-8')
    self.emulated_fs = grr_shell_emulated_fs.GrrShellEmulatedFS('Windows')

  def test_ParseTimelineFlow(self):
    """Tests the ParseTimeline method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)

    self.assertIn('C:', self.emulated_fs._root.children)
    self.assertIn('$Recycle.Bin', self.emulated_fs._root.children['C:'].children)

  def test_AddRowToEmulatedFS(self):
    """Tests the AddRowToEmulatedFS method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)
    timeline_entry = (r'0|C:\\file|10|-rw-rw-rw-|0|1|2|1684122487|1684120499|1684120499|1684120499').replace(r'\\', '/')

    row = grr_shell_emulated_fs._TimelineRow(*timeline_entry.split(sep='|'))

    self.assertNotIn('file', self.emulated_fs._root.children['C:'].children)

    self.emulated_fs._AddRowToEmulatedFS(row)

    self.assertIn('file', self.emulated_fs._root.children['C:'].children)
    self.assertEqual(row, self.emulated_fs._root.children['C:'].children['file'].stats)

  def test_CD_PWD(self):
    """Tests the cd and pwd methods."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)
    self.assertEqual('/', self.emulated_fs.GetPWD())

    self.emulated_fs.Cd('/C:/$Recycle.Bin')
    self.assertEqual('/C:/$Recycle.Bin', self.emulated_fs.GetPWD())

    self.emulated_fs.Cd('S-1-5-18')
    self.assertEqual('/C:/$Recycle.Bin/S-1-5-18', self.emulated_fs.GetPWD())

    with self.assertRaisesRegex(errors.IsAFileError, r'/C:/\$Recycle.Bin/S-1-5-18/desktop.ini'):
      self.emulated_fs.Cd('desktop.ini')
    self.assertEqual('/C:/$Recycle.Bin/S-1-5-18', self.emulated_fs.GetPWD())

    self.emulated_fs.Cd('../../Program Files')
    self.assertEqual('/C:/Program Files', self.emulated_fs.GetPWD())

    with self.assertRaisesRegex(errors.InvalidRemotePathError, '/does not exist'):
      self.emulated_fs.Cd('does not exist')
    self.assertEqual('/C:/Program Files', self.emulated_fs.GetPWD())

    self.emulated_fs.Cd('../../../../../../../../')
    self.assertEqual('/', self.emulated_fs.GetPWD())

  @parameterized.named_parameters(
      ('dir_exists', '/C:', False, True),
      ('dir_exists_dirs_only', '/C:', True, True),
      ('file_exists', '/C:/pagefile.sys', False, True),
      ('file_exists_dirs_only', '/C:/pagefile.sys', True, False),
      ('doesnt_exist', '/nonexistent', False, False),
      ('doesnt_exist_dirs_only', '/nonexistent', True, False),
  )
  def test_RemotePathExists(self, path: str,
                            dirs_only: bool,
                            expected_resuslt: bool):
    """Tests the RemotePathExists method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)
    result = self.emulated_fs.RemotePathExists(path, dirs_only)
    self.assertEqual(result, expected_resuslt)

  @parameterized.named_parameters(
      ('no_path', None, ['.', 'C:']),
      ('c_drive', '/C:', ['.', '$Recycle.Bin', '$WinREAgent', 'Config.Msi', 'Documents and Settings',
                          'DumpStack.log.tmp', 'PerfLogs', 'Program Files', 'hiberfil.sys', 'pagefile.sys']),
      ('file', '/C:/pagefile.sys', ['pagefile.sys']),
      ('glob_raw', '*', ['.', 'C:']),
      ('glob_c_star', 'C*', ['C:']),
      ('glob_subdir', 'C:/*e*', ['$Recycle.Bin', '$WinREAgent', 'hiberfil.sys', 'Documents and Settings',
                                 'pagefile.sys', 'PerfLogs', 'Program Files'])
  )
  def test_LS(self, path: Optional[str], expected_results: list[str]):
    """Tests the LS method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)

    results = [r.name for r in self.emulated_fs.Ls(path)]
    self.assertCountEqual(results, expected_results)

  @parameterized.named_parameters(
      ('c_drive', '/C:', False, ['$Recycle.Bin/', '$WinREAgent/', 'Config.Msi/', 'Documents and Settings/',
                                 'DumpStack.log.tmp', 'PerfLogs/', 'Program Files/', 'hiberfil.sys', 'pagefile.sys']),
      ('c_drive_dirs_only', '/C:', True, ['Config.Msi/', '$Recycle.Bin/', 'Program Files/', '$WinREAgent/',
                                          'Documents and Settings/', 'PerfLogs/'])
  )
  def test_GetChildrenOfPath(self,
                             remote_path: str,
                             dirs_only: bool,
                             expected_results: list[str]):
    """Tests the GetChildrenOfPath method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)

    results = self.emulated_fs.GetChildrenOfPath(remote_path, dirs_only=dirs_only)
    self.assertCountEqual(results, expected_results)

  def test_GetChildrenOfPathErrors(self):
    """Tests errors thrown by the GetChildrenOfPath method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)

    with self.assertRaisesRegex(errors.InvalidRemotePathError, '/nonexistent'):
      self.emulated_fs.GetChildrenOfPath('/nonexistent')

    with self.assertRaisesRegex(errors.IsAFileError, '/C:/pagefile.sys'):
      self.emulated_fs.GetChildrenOfPath('/C:/pagefile.sys', dirs_only=True)

  def test_AddSecondDrive(self):
    """Tests adding a second timeline of a second volume."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)

    self.assertTrue(self.emulated_fs.RemotePathExists('C:/pagefile.sys'))
    self.assertFalse(self.emulated_fs.RemotePathExists('D:/directory/foobar'))

    with open(_SAMPLE_TIMELINE_WINDOWS_D_DRIVE, 'rb') as f:
      second_timeline = f.read().decode('utf-8')

    self.emulated_fs.ClearPath('D:/', 0)
    self.emulated_fs.ParseTimelineFlow(second_timeline)

    self.assertTrue(self.emulated_fs.RemotePathExists('C:/pagefile.sys'))
    self.assertTrue(self.emulated_fs.RemotePathExists('D:/directory/foobar'))


class GrrShellEmulatedFSDarwinTest(parameterized.TestCase):
  """Unit tests for the Grr Shell Emulated FS class with a MacOS FS."""

  def setUp(self):
    """Set up."""
    super().setUp()
    with open(_SAMPLE_TIMELINE_DARWIN, 'rb') as f:
      self.timeline_data = f.read().decode('utf-8')
    self.emulated_fs = grr_shell_emulated_fs.GrrShellEmulatedFS('Darwin')

  def test_ParseTimelineFlow(self):
    """Tests the ParseTimeline method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)

    self.assertIn('usr', self.emulated_fs._root.children)
    self.assertIn('bin', self.emulated_fs._root.children['usr'].children)

  def test_AddRowToEmulatedFS(self):
    """Tests the AddRowToEmulatedFS method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)
    timeline_entry = '0|/usr/file|7|-rwx------|6|5|4096|1683360700.01|1683360701.02|1683360702.03|0.0'
    row = grr_shell_emulated_fs._TimelineRow(*timeline_entry.split(sep='|'))

    self.assertNotIn('file', self.emulated_fs._root.children['usr'].children)

    self.emulated_fs._AddRowToEmulatedFS(row)

    self.assertIn('file', self.emulated_fs._root.children['usr'].children)
    self.assertEqual(self.emulated_fs._root.children['usr'].children['file'].stats, row)

  def test_CD_PWD(self):
    """Tests the cd and pwd methods."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)
    self.assertEqual('/', self.emulated_fs.GetPWD())

    self.emulated_fs.Cd('/System/Volumes/Data/Users')
    self.assertEqual('/System/Volumes/Data/Users', self.emulated_fs.GetPWD())

    self.emulated_fs.Cd('username')
    self.assertEqual('/System/Volumes/Data/Users/username', self.emulated_fs.GetPWD())

    with self.assertRaisesRegex(errors.IsAFileError, '/System/Volumes/Data/Users/username/.bash_history'):
      self.emulated_fs.Cd('.bash_history')
    self.assertEqual('/System/Volumes/Data/Users/username', self.emulated_fs.GetPWD())

    with self.assertRaisesRegex(errors.InvalidRemotePathError, '/does not exist'):
      self.emulated_fs.Cd('does not exist')
    self.assertEqual('/System/Volumes/Data/Users/username', self.emulated_fs.GetPWD())

    self.emulated_fs.Cd('../../../../../../../../')
    self.assertEqual('/', self.emulated_fs.GetPWD())

  @parameterized.named_parameters(
      ('dir_exists', '/usr/bin', False, True),
      ('dir_exists_dirs_only', '/usr/bin', True, True),
      ('file_exists', '/usr/bin/clang', False, True),
      ('file_exists_dirs_only', '/usr/bin/clang', True, False),
      ('doesnt_exist', '/nonexistent', False, False),
      ('doesnt_exist_dirs_only', '/nonexistent', True, False),
  )
  def test_RemotePathExists(self, path: str,
                            dirs_only: bool,
                            expected_resuslt: bool):
    """Tests the RemotePathExists method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)
    result = self.emulated_fs.RemotePathExists(path, dirs_only)
    self.assertEqual(result, expected_resuslt)

  @parameterized.named_parameters(
      ('no_path', None, ['.', 'usr', 'home', 'System', 'Users']),
      ('slash_usr', '/usr', ['.', 'bin']),
      ('file', '/usr/bin/clang', ['clang']),
  )
  def test_LS(self, path: Optional[str], expected_results: list[str]):
    """Tests the LS method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)

    results = [r.name for r in self.emulated_fs.Ls(path)]
    self.assertCountEqual(results, expected_results)

  @parameterized.named_parameters(
      ('usr_bin', '/usr/bin', False, ['dir/', 'vim', 'g++', 'clang']),
      ('usr_bin_only', '/usr/bin', True, ['dir/'])
  )
  def test_GetChildrenOfPath(self,
                             remote_path: str,
                             dirs_only: bool,
                             expected_results: list[str]):
    """Tests the GetChildrenOfPath method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)

    results = self.emulated_fs.GetChildrenOfPath(remote_path, dirs_only=dirs_only)
    self.assertCountEqual(results, expected_results)

  def test_GetChildrenOfPathErrors(self):
    """Tests errors thrown by the GetChildrenOfPath method."""
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)

    with self.assertRaisesRegex(errors.InvalidRemotePathError, '/nonexistent'):
      self.emulated_fs.GetChildrenOfPath('/nonexistent')

    with self.assertRaisesRegex(errors.IsAFileError, '/usr/bin/clang'):
      self.emulated_fs.GetChildrenOfPath('/usr/bin/clang', dirs_only=True)


class LSEntryTest(parameterized.TestCase):
  """Test the LSEntry class."""

  lse_a = grr_shell_emulated_fs._LSEntry('-rwx------', 0, 1, 2, '2023-01-01T00:00:00Z', 'a')
  lse_b = grr_shell_emulated_fs._LSEntry('drwx------', 3, 4, 5, '2023-01-01T00:00:01Z', 'b')
  lse_c = grr_shell_emulated_fs._LSEntry('lrwx------', 3, 4, 5, '2023-01-01T00:00:01Z', 'c')
  lse_d = grr_shell_emulated_fs._LSEntry('-rwx------', 6, 7, 8, '2023-01-01T00:00:02Z', 'd')
  lse_e = grr_shell_emulated_fs._LSEntry('drwx------', 12, 13, 14, '2023-01-01T00:00:04Z', 'e')
  lse_f = grr_shell_emulated_fs._LSEntry('lrwx------', 3, 4, 5, '2023-01-01T00:00:01Z', 'f')

  def test_ToStr(self):
    """"Tests the __str__ method."""
    self.assertEqual(str(self.lse_a), '-rwx------        0        1            2 2023-01-01T00:00:00Z a')

  @parameterized.named_parameters(
      ('two_dirs', lse_b, lse_e, True),
      ('two_dirs_reversed', lse_e, lse_b, False),
      ('two_files', lse_a, lse_d, True),
      ('two_files_reversed', lse_d, lse_a, False),
      ('two_symlinks', lse_c, lse_f, True),
      ('two_symlinks_reversed', lse_f, lse_c, False),
      ('file_and_dir', lse_a, lse_b, False),
      ('dir_and_file', lse_b, lse_a, True),
      ('file_first_and_symlink', lse_a, lse_c, True),
      ('file_first_and_symlink_reversed', lse_c, lse_a, False),
      ('symlink_first_and_file', lse_c, lse_d, True),
      ('symlink_first_and_file_reversed', lse_d, lse_c, False),
      ('dir_and_symlink', lse_b, lse_c, True),
      ('dir_and_symlink_reversed', lse_c, lse_b, False),
  )
  def test_LT(self,
              left: grr_shell_emulated_fs._LSEntry,
              right: grr_shell_emulated_fs._LSEntry,
              expected_result: bool):
    """Tests the __lt__ method."""
    result = left < right
    self.assertEqual(result, expected_result)


class GrrShellEmulatedFSRefreshTest(parameterized.TestCase):
  """Unit tests for the Grr Shell Emulated FS class with refreshed timelines."""

  def setUp(self):
    """Set up tests."""
    super().setUp()
    with open(_SAMPLE_TIMELINE_LINUX, 'rb') as f:
      self.timeline_data = f.read().decode('utf-8')
    self.emulated_fs = grr_shell_emulated_fs.GrrShellEmulatedFS('Linux')
    self.emulated_fs.ParseTimelineFlow(self.timeline_data)
    self.emulated_fs.Cd('/root/.local/share')

  def test_Overwrite(self):
    """Tests overwriting the timeline with a partial one."""
    # Check existing files.
    self.assertIn('nano',
                  self.emulated_fs._root.children['root'].children['.local'].children['share'].children)
    self.assertNotIn('nano_new',
                     self.emulated_fs._root.children['root'].children['.local'].children['share'].children)
    self.assertEqual(self.emulated_fs._pwd.timeline_time, 0)
    self.assertIn('.bashrc', self.emulated_fs._root.children['root'].children)

    with open(_SAMPLE_TIMELINE_LINUX_OVERLAY, 'rb') as f:
      overlay_data = f.read().decode('utf-8')

    # Parse overlay.
    self.emulated_fs.ClearPath('/root/.local/share', 75)
    self.emulated_fs.ParseTimelineFlow(overlay_data, 75)

    # Check updated files.
    self.assertNotIn('nano',
                     self.emulated_fs._root.children['root'].children['.local'].children['share'].children)
    self.assertIn('nano_new',
                  self.emulated_fs._root.children['root'].children['.local'].children['share'].children)
    self.assertEqual(self.emulated_fs._pwd.timeline_time, 75)
    self.assertIn('.bashrc', self.emulated_fs._root.children['root'].children)


if __name__ == '__main__':
  absltest.main()
