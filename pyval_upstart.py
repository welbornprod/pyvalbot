#!/usr/bin/env python
# -*- coding: utf-8 -*-

""" pyval_service.py

    Used to generate an upstart config file, and place it in /etc/init.
    If the file already exists, then nothing is done.
    If /etc/init doesn't exist, then this won't be supported. Nothing is done.

    -Christopher Welborn 2014
"""

import os
import sys

try:
    from docopt import docopt
except ImportError as exdocopt:
    print('\nUnable to import docopt.\n'
          'Please make sure it is installed. (pip install docopt)\n'
          'Error was:\n{}'.format(exdocopt))
    sys.exit(1)

try:
    import pyval_util
except ImportError as eximp:
    print('\nUnable to import the pyval_util module!: '
          'pyval_util\n{}'.format(eximp))
    sys.exit(1)

NAME = 'PyVal Upstart'
VERSION, VERSIONX = '1.0.0', '0'
VERSIONSTR = '{} v. {}-{}'.format(NAME, VERSION, VERSIONX)
SERVICENAME = 'pyvalbot'
SERVICEFILE = '{}.conf'.format(SERVICENAME)

SCRIPT = os.path.split(sys.argv[0])[1]

USAGESTR = """{verstr}
    Usage:
        {script} -h | -v
        {script} [-d] [-a args]
        {script} -i [-a args]
        {script} -q | -r | -s | -x

    Options:
        -a args,--args args  : Arguments for pyvalbot service.
                               ex: "arg1 arg2"
        -d,--debug           : Just show what would've been written to the
                               service file.
        -h,--help            : Show this message.
        -i,--install         : Install the service. Running this again
                               will overwrite the previous service file.
        -q,--query           : Query the status of the service, if installed.
        -r,--remove          : Remove the service file to uninstall the
                               service.
        -s,--start           : Start the service, if installed.
        -x,--stop            : Stop the service, if installed.

    Notes:
        When no arguments are passed to {script}, the default behaviour is
        to look for the installed service. If it is installed, then the
        service is started. If it is not installed, then {script} will
        install it.
""".format(script=SCRIPT, verstr=VERSIONSTR)


def main(argd):
    """ Main entry-point. Expects arg dict from docopt. """
    # show root warning if needed.
    warn_root()

    if argd['--debug']:
        do_debug(argd['--args'])
    elif argd['--install']:
        do_install(argd['--args'])
    elif argd['--query']:
        do_query()
    elif argd['--remove']:
        do_remove()
    elif argd['--start']:
        do_start()
    elif argd['--stop']:
        do_stop()
    else:
        # no args.
        do_auto(argd['--args'])

    # Everything breaks/exits on error. If we have reached this point it
    # was a success.
    print('\nFinished.\n')
    return 0


def warn_root():
    """ Show a warning if the user is not running as root. """

    if os.getuid() == 0:
        return False

    print('\nYou are not running as root!\n'
          'You will need the proper permissions to manage services!\n')
    return True


def confirm(s):
    """ Confirm an answer to a question. (return True/False for Yes/No) """
    s = '{} (y/n): '.format(s)
    answer = raw_input(s)  # noqa
    return answer.strip().lower().startswith('y')


def do_auto(pvargs=None):
    """ Check for existing service, start it if it exists.
        Otherwise try installing it.
    """
    if os.path.isfile(get_service_file()):
        # Start existing service.
        do_start()
    else:
        # Try installing it.
        do_install(pvargs=pvargs)


def do_debug(pvargs=None):
    """ Print what would be written to the service file. """
    content = parse_template(pvargs=pvargs)
    print('\nThis would\'ve been written to: {}\n'.format(get_service_file()))
    print(content)


def do_install(pvargs=None):
    """ Attempt to install the pyval service. """
    
    if os.path.isfile(get_service_file()):
        # service already exists.
        print('\nThe service is already installed.')
        confirmmsg = 'Overwrite previously installed PyVal service?'
    else:
        print('\nThis will install a system-wide service.')
        confirmmsg = 'Do you want to install the PyVal service?'

    if not confirm(confirmmsg):
        fail('User Cancelled.')

    print('\nAttempting to write a new service file...')
    write_config(pvargs=pvargs)
    print('\nConfig file written.')
    refresh_upstart()
    print('\nUpstart config reloaded.')
    do_start()


def do_query():
    """ Query an existing pyval service (started/stopped/waiting) """

    if not query_pyval_service():
        fail('Status command returned non-zero,\n'
             'status is unknown.')


def do_remove():
    """ Remove an existing service file. """
    servicefile = get_service_file()
    if os.path.isfile(servicefile):
        if not confirm('Remove the install pyval service?'):
            fail('User Cancelled')
        try:
            os.remove(servicefile)
            print('\nService file was removed: {}'.format(servicefile))
            return True
        except (IOError, OSError) as exio:
            fail('Error removing the service file: '
                 '{}\n{}'.format(servicefile, exio))
    # No service file exists.
    fail_notinstalled()


def do_start():
    """ Attempt to start the pyval service. """
    if start_pyval_service():
        print('\nPyVal service started.')
    else:
        print('\nStart command returned non-zero.\n'
              'Service may not have started.')


def do_stop():
    if stop_pyval_service():
        print('\nPyVal service was stopped.')
    else:
        print('\nStop command returned non-zero.\n'
              'Service may not have stopped.')


def fail(reason=None, retcode=1):
    """ print a message and exit the program.
        The msg defaults to something like: 'unable to generate a config'
    """

    if reason:
        reason = '\n{}\n'.format(reason.strip())
        print(reason)
    else:
        # Basic msg that says this whole thing didn't work out.
        print('\nUnable to generate an upstart config file.')
    sys.exit(retcode)


def fail_notinstalled():
    """ Just like fail(), but with a preset msg 'service not installed'. """
    fail('PyVal service is not installed yet.')


def get_init_dir():
    if os.path.isdir('/etc/init'):
        return '/etc/init'
    fail('Can\'t find /etc/init! This won\'t work!')


def get_python_exe():
    """ Locate the main python executable.
        A 'python2' executable is preferred over just 'python'.
        Searches several well-known dirs for 'python2', 'python2.7',
        and  'python'.
    """

    dirs = ['/usr/bin',
            '/usr/local/bin',
            os.path.expanduser('~/bin'),
            os.path.expanduser('~/.local/bin'),
            ]

    files = ['python2', 'python2.7', 'python']

    for dirname in dirs:
        for filename in files:
            fullpath = os.path.join(dirname, filename)
            if os.path.exists(fullpath):
                return fullpath
    # No python exe was found.
    fail('No python executable could be located!')


def get_service_file():
    """ Return the final filename and path for the upstart config file. """

    etcinit = get_init_dir()
    return os.path.join(etcinit, SERVICEFILE)


def get_template():
    """ Read the template file's content. """
    template_file = 'pyval_upstart.template'
    if os.path.isfile(template_file):
        try:
            with open(template_file, 'r') as fread:
                return fread.read()
        except (IOError, OSError) as exio:
            fail('Unable to read the pyval upstart template!: '
                 '{}\n{}'.format(template_file, exio))
    fail('Can\'t find the template file: {}'.format(template_file))


def parse_template(pvargs=None):
    """ Read the template file, and put appropriate dirs/scripts in it. """

    content = get_template()
    if not content:
        print('Unable to generate an upstart config for PyVal.')
        return None

    pyexe = get_python_exe()
    pyvalutil = pyval_util.__file__
    pyvaldir = os.path.split(pyvalutil)[0]
    pyvalscript = os.path.join(pyvaldir, 'pyvalbot.py')
    # Parse user/default args for pyvalbot.
    if pvargs:
        userargs = pvargs.strip().split()
        if ('--logfile' not in userargs) and ('-l' not in userargs):
            userargs.append('--logfile')
        pyvalargs = ' {}'.format(' '.join(userargs))
    else:
        pyvalargs = ' --logfile'

    if not (os.path.isdir(pyvaldir) and os.path.isfile(pyvalscript)):
        fail('Missing dirs/files for pyval!\n'
             'Make sure both of these exist:\n'
             '    {}\n    {}'.format(pyvaldir, pyvalscript))

    try:
        content = content.format(pyvaldir=pyvaldir,
                                 pyvalscript=pyvalscript,
                                 pyvalargs=pyvalargs,
                                 pyvalservice=SERVICENAME,
                                 pyexe=pyexe)
    except Exception as ex:
        fail('Malformed template file!\n{}'.format(ex))

    # Parsing was a success.
    print('\n'.join(['\nSettings:',
                     '       PyVal Dir: {}'.format(pyvaldir),
                     '    PyVal Script: {}'.format(pyvalscript),
                     '      PyVal Args: {}'.format(pyvalargs)]))
    return content


def query_pyval_service():
    """ Query the status of the pyval service. """
    if os.path.isfile(get_service_file()):
        print('\nAttempting to query the PyVal service...')
        try:
            ret = os.system('initctl status {}'.format(SERVICENAME))
            return (ret == 0)
        except Exception as ex:
            fail('Unable to query the pyval service: '
                 '{}\n{}'.format(SERVICENAME, ex))
    fail_notinstalled()


def refresh_upstart():
    """ Refresh upstart configuration. """
    try:
        ret = os.system('initctl reload-configuration')
        return (ret == 0)
    except Exception as ex:
        fail('Unable to refresh upstart config!\n{}'.format(ex))


def start_pyval_service():
    """ Start the pyval service. """

    if os.path.isfile(get_service_file()):
        print('\nAttempting to start the PyVal service...')
        try:
            ret = os.system('start {}'.format(SERVICENAME))
            return (ret == 0)
        except Exception as ex:
            fail('Unable to start pyval service: '
                 '{}\n{}'.format(SERVICENAME, ex))
    fail_notinstalled()


def stop_pyval_service():
    """ Stop the pyval service. """

    if os.path.isfile(get_service_file()):
        print('\nAttempting to stop the PyVal service...')
        try:
            ret = os.system('stop {}'.format(SERVICENAME))
            return (ret == 0)
        except Exception as ex:
            fail('Unable to stop the pyval service: '
                 '{}\n{}'.format(SERVICENAME, ex))
    fail_notinstalled()


def write_config(pvargs=None):
    """ generates and writes the upstart config file to /etc/init. """
    content = parse_template(pvargs=pvargs)

    targetfile = get_service_file()
    try:
        with open(targetfile, 'w') as fwrite:
            fwrite.write(content)
            return True
    except (IOError, OSError) as exio:
        fail('Unable to write upstart config file: '
             '{}\n{}'.format(targetfile, exio))


if __name__ == '__main__':
    mainret = main(docopt(USAGESTR, version=VERSIONSTR))
    sys.exit(mainret)
