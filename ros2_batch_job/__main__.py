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

import argparse
import os
import platform
import sys

# Make sure we're using Python3
assert sys.version.startswith('3'), "This script is only meant to work with Python3"

from .util import change_directory
from .util import clean_workspace
from .util import force_color
from .util import generated_venv_vars
from .util import info
from .util import log
from .util import UnbufferedIO

# Enforce unbuffered output
sys.stdout = UnbufferedIO(sys.stdout)
sys.stderr = UnbufferedIO(sys.stderr)

pip_dependencies = [
    'nose',
    'pep8',
    'pyflakes',
    'flake8',
    'mock',
    'coverage',
    'EmPy',
    'vcstool',
]


def main(sysargv=None):
    parser = argparse.ArgumentParser(
        description="Builds the ROS2 repositories as a single batch job")
    parser.add_argument(
        '--repo-file-url',
        default='https://raw.githubusercontent.com/ros2/examples/master/ros2.repos',
        help="url of the ros2.repos file to fetch and use for the basis of the batch job")
    parser.add_argument(
        '--test-branch', default=None,
        help="branch to attempt to checkout before doing batch job")
    parser.add_argument(
        '--white-space-in', nargs='*', default=None,
        choices=['sourcespace', 'buildspace', 'installspace', 'workspace'],
        help="which folder structures in which white space should be added")
    parser.add_argument(
        '--do-venv', default=False, action='store_true',
        help="create and use a virtual env in the build process")
    parser.add_argument(
        '--os', default=None, choices=['linux', 'osx', 'windows'])
    parser.add_argument(
        '--connext', default=False, action='store_true',
        help="try to build with connext")
    parser.add_argument(
        '--force-ansi-color', default=False, action='store_true',
        help="forces this program to output ansi color")

    args = parser.parse_args(sysargv)

    if args.force_ansi_color:
        force_color()

    info("run_ros2_batch called with args:")
    for arg in vars(args):
        info("  - {0}={1}".format(arg, getattr(args, arg)))

    job = None

    args.white_space_in = args.white_space_in or []
    args.workspace = 'work space' if 'workspace' in args.white_space_in else 'workspace'
    args.sourcespace = 'source space' if 'sourcespace' in args.white_space_in else 'src'
    args.buildspace = 'build space' if 'buildspace' in args.white_space_in else 'build'
    args.installspace = 'install space' if 'installspace' in args.white_space_in else 'install'

    platform_name = platform.platform().lower()
    if args.os == 'linux' or platform_name.startswith('linux'):
        args.os = 'linux'
        from .linux_batch import LinuxBatchJob
        job = LinuxBatchJob(args)
    elif args.os == 'osx' or platform_name.startswith('darwin'):
        args.os = 'osx'
        from .osx_batch import OSXBatchJob
        job = OSXBatchJob(args)
    elif args.os == 'windows' or platform_name.startswith('windows'):
        args.os = 'windows'
        from .windows_batch import WindowsBatchJob
        job = WindowsBatchJob(args)

    if args.do_venv and args.os == 'windows':
        sys.exit("--do-venv is not supported on windows")

    # Set the TERM env variable to coerce the output of Make to be colored.
    os.environ['TERM'] = os.environ.get('TERM', 'xterm-256color')
    if args.os == 'windows':
        # Set the ConEmuANSI env variable to trick some programs (vcs) into
        # printing ANSI color codes on Windows.
        os.environ['ConEmuANSI'] = 'ON'

    info("Using workspace: @!{0}", fargs=(args.workspace,))
    clean_workspace(args.workspace)

    # Allow batch job to do OS specific stuff
    job.pre()
    # Check the env
    job.show_env()
    # Make sure virtual env is installed
    if args.os != 'linux':
        # Do not try this on Linux, as elevated privileges are needed.
        # Also there is no good way to get elevated privileges.
        # So the Linux host or Docker vm will need to ensure a modern
        # version of virtualenv is available.
        job.run([sys.executable, '-m', 'pip', 'install', '-U', 'virtualenv'])
    # Now inside of the workspace...
    with change_directory(args.workspace):
        # Enter a venv if asked to
        if args.do_venv:
            job.run([sys.executable, '-m', 'virtualenv', '-p', sys.executable, 'venv'])
            venv_path = os.path.abspath(os.path.join(os.getcwd(), 'venv'))
            venv, venv_python = generated_venv_vars(venv_path)
            job.push_run(venv)  # job.run is now venv
            job.push_python(venv_python)  # job.python is now venv_python
            job.show_env()
        # Update setuptools
        job.run([job.python, '-m', 'pip', 'install', '-U', 'pip', 'setuptools'])
        # Print setuptools version
        job.run([job.python, '-c', '"import setuptools; print(setuptools.__version__)"'],
                shell=True)
        # Print the pip version
        job.run([job.python, '-m', 'pip', '--version'])
        # Install pip dependencies
        job.run([job.python, '-m', 'pip', 'install', '-U'] + pip_dependencies)
        # Get the repositories
        job.run(['curl', '-sk', args.repo_file_url, '-o', 'ros2.repos'])
        # Show the contents
        log("@{bf}==>@| Contents of `ros2.repos`:")
        with open('ros2.repos', 'r') as f:
            print(f.read())
        # Use the repository listing and vcstool to fetch repositories
        if not os.path.exists(args.sourcespace):
            os.makedirs(args.sourcespace)
        job.run(['vcs', 'import', '"%s"' % args.sourcespace, '--input', 'ros2.repos'], shell=True)
        # Attempt to switch all the repositories to a given branch
        if args.test_branch is not None:
            info("Attempting to switch all repositories to the '{0}' branch"
                 .format(args.test_branch))
            vcs_custom_cmd = ['vcs', 'custom', '.', '--args', 'checkout', args.test_branch]
            ret = job.run(vcs_custom_cmd, exit_on_error=False)
            info("'{0}' returned exit code '{1}'", fargs=(" ".join(vcs_custom_cmd), ret))
            print()
        # Show the latest commit log on each repository (includes the commit hash).
        job.run(['vcs', 'log', '-l1', 'src'])
        # Allow the batch job to push custom sourcing onto the run command
        job.setup_env()
        ament_py = '"%s"' % os.path.join(
            '.', args.sourcespace, 'ament', 'ament_tools', 'scripts', 'ament.py'
        )
        # Now run ament build
        ret_build = job.run([
            job.python, '-u', ament_py, 'build', '--build-tests',
            '--build-space', '"%s"' % args.buildspace,
            '--install-space', '"%s"' % args.installspace,
            '"%s"' % args.sourcespace
        ], exit_on_error=False)
        if ret_build != 0:
            from .util import warn
            from remote_pdb import set_trace
            warn("Starting remote Python debugger...")
            set_trace()
        # Run tests
        ret_test = job.run([
            job.python, '-u', ament_py, 'test',
            '--build-space', '"%s"' % args.buildspace,
            '--install-space', '"%s"' % args.installspace,
            # Skip building and installing, since we just did that successfully.
            '--skip-build', '--skip-install',
            '"%s"' % args.sourcespace
        ], exit_on_error=False)
        info("ament.py test returned: '{0}'".format(ret_test))
        # Collect the test results
        ret_test_results = job.run(
            [job.python, '-u', ament_py, 'test_results', '"%s"' % args.buildspace],
            exit_on_error=False
        )
        info("ament.py test_results returned: '{0}'".format(ret_test_results))
        # Uncomment this line to failing tests a failrue of this command.
        # return 0 if ret_test == 0 and ret_testr == 0 else 1
        return 0


if __name__ == '__main__':
    sys.exit(main())
