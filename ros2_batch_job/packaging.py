# Copyright 2015 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import shutil
import sys
import tarfile
import zipfile

from .__main__ import get_args
from .__main__ import run
from .util import info


def main(sysargv=None):
    args = get_args(sysargv=sysargv, skip_white_space_in=True, skip_connext=True, add_ros1=True)
    return run(args, build_and_package)


def build_and_package(args, job):
    # ignore ROS 1 bridge package for now
    ros1_bridge_path = os.path.join(args.sourcespace, 'ros2', 'ros1_bridge')
    info('ROS1 bridge path: %s' % ros1_bridge_path)
    ros1_bridge_ignore_marker = None
    if os.path.exists(ros1_bridge_path):
        ros1_bridge_ignore_marker = os.path.join(ros1_bridge_path, 'AMENT_IGNORE')
        info('ROS1 bridge path ignore file: %s' % ros1_bridge_ignore_marker)
        with open(ros1_bridge_ignore_marker, 'w'):
            pass

    ament_py = '"%s"' % os.path.join(
        '.', args.sourcespace, 'ament', 'ament_tools', 'scripts', 'ament.py'
    )
    # Now run ament build
    cmd = [
        job.python, '-u', ament_py, 'build',
        '--build-space', '"%s"' % args.buildspace,
        '--install-space', '"%s"' % args.installspace,
        '"%s"' % args.sourcespace]
    if args.isolated:
        cmd.append('--isolated')
    if args.os != 'windows':
        cmd += ['--cmake-args', '-DCMAKE_BUILD_TYPE=RelWithDebInfo']
    job.run(cmd)

    if ros1_bridge_ignore_marker:
        os.remove(ros1_bridge_ignore_marker)

    # It only makes sense to build the bridge for Linux or OSX, since
    # ROS1 is not supported on Windows
    if args.os in ['linux', 'osx']:
        # Now run ament build only for the bridge
        job.run([
            job.python, '-u', ament_py, 'build',
            '--build-space', '"%s"' % args.buildspace,
            '--install-space', '"%s"' % args.installspace,
            '--only', 'ros1_bridge',
            '"%s"' % args.sourcespace,
        ] + (['--isolated'] if args.isolated else []) + [
            '--cmake-args', '-DCMAKE_BUILD_TYPE=RelWithDebInfo',
            '--make-flags', '-j1'
        ])

    # Remove "unnecessary" executables
    install_bin_path = os.path.join(args.installspace, 'bin')
    for filename in os.listdir(install_bin_path):
        if (
            '__rmw_' in filename or
            filename.startswith('simple_bridge') or
            filename.startswith('static_bridge')
        ):
            os.remove(os.path.join(install_bin_path, filename))

    # create an archive
    folder_name = 'ros2-' + args.os
    if args.os == 'linux' or args.os == 'osx':
        archive_path = 'ros2-package-%s.tar.bz2' % args.os
        with tarfile.open(archive_path, 'w:bz2') as h:
            h.add(args.installspace, arcname=folder_name)
    elif args.os == 'windows':
        archive_path = 'ros2-package-windows.zip'
        # NOTE(esteve): hack to copy our custom built VS2015-compatible OpenCV DLLs
        opencv_libdir = os.path.join('c:/', 'opencv', 'build', 'x64', 'vc14', 'bin')
        for libfile in ['opencv_core%d.dll', 'opencv_highgui%d.dll']:
            origin_libpath = os.path.join(opencv_libdir, libfile % 2412)
            destination_libpath2411 = os.path.join(args.installspace, 'bin', libfile % 2411)
            destination_libpath2412 = os.path.join(args.installspace, 'bin', libfile % 2412)
            shutil.copy(origin_libpath, destination_libpath2411)
            shutil.copy(origin_libpath, destination_libpath2412)
        with zipfile.ZipFile(archive_path, 'w') as zf:
            for dirname, subdirs, files in os.walk(args.installspace):
                arcname = os.path.join(
                    folder_name, os.path.relpath(dirname, start=args.installspace))
                zf.write(dirname, arcname=arcname)
                for filename in files:
                    filearcname = os.path.join(
                        folder_name, os.path.relpath(dirname, start=args.installspace), filename)
                    zf.write(os.path.join(dirname, filename), arcname=filearcname)
    else:
        raise RuntimeError('Unsupported operating system: %s' % args.os)
    info("created archive: '{0}'".format(archive_path))

    return 0


if __name__ == '__main__':
    sys.exit(main())
