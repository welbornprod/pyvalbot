#!/usr/bin/env python2
# -*- coding: utf-8 -*-

""" pyval_exec.py
    A safer exec/eval container for pyval bot or anything else that
    might require it.
    Supports a limited subset of python, mostly hiding the nasty parts
    that aren't really needed for basic teaching purposes anyway.

    Designed for python2, python3 may work but has not been tested.
    Designed mainly for use with twisted-based pyvalbot which is not
    fully python3 compatible.

    This module is designed to be testable/runnable from the cmdline.
    Run `pyval_exec.py -h` for options.
    -Christopher Welborn 2013

    Killer Strings:
        Known to crash python or cause problems, ignore the '# noqa'.

        eval() will fail with these strings in a normal interpreter:

        SegFault (crashes python/pypy):
            (lambda fc=(lambda n: [c for c in ().__class__.__bases__[0].__subclasses__() if c.__name__ == n][0]):fc("function")(fc("code")(0,0,0,0,"KABOOM",(),(),(),"","",0,""),{})())() # noqa

        MemoryError (not in PyPy though):
            ((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((1)))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))) # noqa

    Even though these errors might occur, it doesn't mean the bot will die.
    Code is evaluated in a subprocess and is timed. It will fail gracefully.
"""
from __future__ import print_function
from tempfile import SpooledTemporaryFile
import inspect
import multiprocessing
import os
import subprocess
import sys

from docopt import docopt

from pyval_util import __file__ as PYVAL_FILE  # noqa
from pyval_util import VERSION

NAME = 'PyValExec'
SCRIPTNAME = os.path.split(sys.argv[0])[-1]

USAGESTR = """{name} v. {version}

    Usage:
        {script} -h | -p | -v
        {script} [-b] [-d] [-q] [-r] [-t secs] [CODE]

    Options:
        CODE                    : Code to evaluate/execute,
                                  or a file to read code from.
                                  stdin is used when not given.
        -b,--blacklist          : Use blacklist (testing).
        -d,--debug              : Prints extra info before,
                                  during, and after execution.
        -h,--help               : Show this message.
        -p,--printblacklist     : Print blacklisted strings only.
        -q,--quiet              : Print output only.
        -r,--raw                : Show unsafe, raw output.
        -t secs,--timeout secs  : Timeout for code execution in
                                  seconds. Default: 5
        -v,--version            : Show version and exit.

    Notes:
        You can pipe output from another program.
        When no 'evalcode' is given, stdin is used.
        If a filename is passed, the name __main__ is not
        set. So it may not run as expected.
        It will run each statement in the file, but:
            if __name__ == '__main__' will be False.
            if __name__ == '__pyval__' will be True.
        You can explicitly bypass this, but it may be
        better to write a specific sandbox-friendly
        script to test things out.
""".format(name=NAME, version=VERSION, script=SCRIPTNAME)

# Allow debug early.


def _debug(*args, **kwargs):
    """ Print a message only if DEBUG is truthy. """
    if not (DEBUG and args):
        return None
    # Include parent class name when given.
    parent = kwargs.get('parent', None)
    try:
        kwargs.pop('parent')
    except KeyError:
        pass
    # Go back more than once when given.
    backlevel = kwargs.get('back', 1)
    try:
        kwargs.pop('back')
    except KeyError:
        pass

    frame = inspect.currentframe()
    # Go back a number of frames (usually 1).
    while backlevel > 0:
        frame = frame.f_back
        backlevel -= 1
    fname = os.path.split(frame.f_code.co_filename)[-1]
    lineno = frame.f_lineno
    if parent:
        func = '{}.{}'.format(parent.__class__.__name__, frame.f_code.co_name)
    else:
        func = frame.f_code.co_name

    # Patch args to stay compatible with print().
    pargs = list(args)
    lineinfo = '{}:{} {}(): '.format(fname, lineno, func).ljust(40)
    pargs[0] = ''.join((lineinfo, pargs[0]))
    print(*pargs, **kwargs)


def debug(*args, **kwargs):
    """ This function is a dummy. It is overwritten when --debug is used. """
    return None

DEBUG = False

if __name__ == '__main__':
    # This -d conflicts with pyvalbot. Only use it when executed directly.
    DEBUG = ('-d' in sys.argv) or ('--debug' in sys.argv)
    if DEBUG:
        debug = _debug  # noqa

# Location for pypy-sandbox.
PYPYSANDBOX_EXE = None
PATH = set((s.strip() for s in os.environ.get('PATH', '').split(':') if s))
if not PATH:
    debug('No $PATH variable set!\n..only defaults will be used.')

for knownpath in (
        os.path.expanduser('~/bin'),
        os.path.expanduser('~/.local/bin'),
        os.path.expanduser('~/local/bin'),
        '/usr/bin',
        '/usr/local/bin'):
    PATH.add(knownpath)

for dirname in PATH:
    pypypath = os.path.join(dirname, 'pypy-sandbox')
    if os.path.exists(pypypath):
        debug('Found pypy-sandbox: {}'.format(pypypath))
        PYPYSANDBOX_EXE = pypypath
        break
else:
    print('\nUnable to find pypy-sandbox.')
    print('Looked in:\n    {}'.format('\n    '.join(PATH)))
    sys.exit(1)


class ExecBox(object):

    """ Handles python code execution using pypy-sandbox/pyval_sandbox.
        Uses safe_output() by default for irc-friendly short output.
        Uses timed_call() for a timeout on long running code.

    """

    def __init__(self, evalstr=None):
        self.debug = False
        self.output = ''
        self.inputstr = evalstr
        # Trimmed during execute()
        self.inputtrim = None
        # Set after newlines have been parsed.
        # This is the final string sent to the interpreter.
        self.parsed = ''
        # Maximum number of seconds to run.
        self.timeout = 5
        # Maximum lines/length for safe_output()
        # Disabled if < 1.
        self.maxlines = 0
        self.maxlength = 0

    def __str__(self):
        return self.output

    def __repr__(self):
        return self.output

    def blacklist(self):
        """ Return a dict of black-listed strings.
            Format is: {string: message}

            PyPy Sandbox already does a good job, so this is unnecessary.
            It's left over from early versions, which were not as strong.
        """
        badstrings = {
            '__bases__': 'too complicated for this bot.',
            '__import__': 'no __import__ allowed.',
            '__subclasses__': 'too complicated for this bot.',
            'builtin': 'no builtins allowed.',
            'eval(': 'no eval() allowed.',
            'exec(': 'no exec() allowed.',
            'exit': 'no exit allowed.',
            'help(': 'no help() allowed.',
            'import': 'no imports allowed.',
            'KABOOM': 'no way.',
            'kaboom': 'no way.',
            'open': 'no open() allowed.',
            'os.': 'no os module allowed.',
            'self': 'no self allowed.',
            'super': 'no super() allowed.',
            'sys': 'no sys allowed.',
            'SystemExit': 'no SystemExit allowed.',
        }
        return badstrings

    def check_blacklist(self):
        """ Checks current inputstr for blacklisted strings. """
        badstrings = self.blacklist()
        if self.inputtrim:
            for badstr, msg in badstrings.items():
                if badstr in self.inputtrim:
                    return msg
        return None

    def check_nesting(self, inputstr):
        """ Checks a single line for ( max. """
        for line in inputstr.split('\n'):
            if line.count('(') > self.nestedmax:
                return True
        return False

    def _exec(self, pipesend=None, stringmode=True, timeout=None):
        """ Execute actual code using pypy-sandbox/pyval_sandbox combo.
            This method does not blacklist anything.
            It runs whatever self.inputstr is set to.

            Arguments:
                pipesend    :  multiprocessing pipe to send output to.
                stringmode  :  fixes newlines so that they can be used from
                               cmdline/irc-chat.
                               default: True
        """
        if not self.inputstr:
            self.error_return('No source.')

        self.parsed = self.parse_input(self.inputstr, stringmode=stringmode)

        # Get locations for pypy-sandbox, sandbox dir, pyval_sandbox.

        parentdir = os.path.split(PYVAL_FILE)[0]
        sandboxdir = os.path.join(parentdir, 'pyval_sandbox')
        targetfile = '/tmp/pyval_sandbox.py'
        # Setup command args for Popen.
        cmdargs = [PYPYSANDBOX_EXE,
                   '--timeout={}'.format(timeout or self.timeout),
                   '--tmp={}'.format(sandboxdir),
                   targetfile]

        self.printdebug('running sandbox: {}'.format(' '.join(cmdargs)))

        # Fill temp file with user input, send it to pyval_sandbox.
        self.printdebug('_exec({})'.format(self.parsed))

        with TempInput(self.parsed) as stdinput:
            proc = subprocess.Popen(cmdargs,
                                    stdin=stdinput,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)

        output = self.proc_output(proc)
        if pipesend is not None:
            pipesend.send(output)
        return output

    def error_return(self, s):
        """ Set output as error str and return it.
            self.lasterror and self.output will be set to the same thing.
        """
        self.output = self.lasterror = str(s)
        return self.output

    def execute(self, **kwargs):
        """ Execute code inside the pypy sandbox/pyval_sandbox.

            This is the preferred method of code execution, as it has a
            timeout and allows "safe" output through configuration
            (self.maxlines and self.maxlength).

            Keyword Arguments:
                evalstr        : String to evaluate.
                maxlength      : Maximum length in characters for output.
                                 Default: self.maxlength (0, not used)
                maxlines       : Maximum number of lines for output.
                                 Default: self.maxlines (0, not used)
                raw_output     : Use raw output instead of safe_output().
                                 Default: False
                stringmode     : Fix newlines so they can be used with
                                 cmdline/irc-chat.
                                 Default: True
                timeout        : Timeout for code execution in seconds.
                                 Default: self.timeout (5)
                use_blacklist  : Enable the blacklist (forbidden strings).
                                 Default: False
        """

        evalstr = kwargs.get('evalstr', None)
        maxlength = kwargs.get('maxlength', self.maxlength) or 0
        maxlines = kwargs.get('maxlines', self.maxlines) or 0
        raw_output = kwargs.get('raw_output', False)
        stringmode = kwargs.get('stringmode', True)
        timeout = kwargs.get('timeout', self.timeout)
        if timeout is None:
            timeout = 0
        use_blacklist = kwargs.get('use_blacklist', False)

        # Reset last error.
        self.lasterror = None

        if evalstr:
            # Option to set inputstr during execute().
            self.inputstr = evalstr

        if self.inputstr:
            # Trim input to catch bad strings.
            self.inputtrim = self.inputstr.replace(' ', '').replace('\t', '')
            if not self.inputtrim.strip():
                return self.error_return('only whitespace found.')
        else:
            # No input, no execute().
            return self.error_return('no input.')

        # Check blacklisted strings.
        if use_blacklist:
            badinputmsg = self.check_blacklist()
            if badinputmsg:
                return self.error_return(badinputmsg)

        # Build kwargs for _exec.
        # 'timeout' for pypy-sandbox is not being honored, but is included for
        # debug messages
        execargs = {'stringmode': stringmode, 'timeout': timeout}

        # Actually execute it with fingers crossed.
        try:
            result = self.timed_call(
                self._exec,
                kwargs=execargs,
                timeout=timeout)
            self.output = str(result)
        except TimedOut:
            return self.error_return('Error: Operation timed out.')
        except Exception as ex:
            # This is a PyVal error, not the evaluated code's.
            # Any errors in the user code will be returned normally.
            return self.error_return('PyVal Error: {}'.format(ex))

        # Return the safe output version of self.output unless forced.
        if raw_output:
            return self.output

        return self.safe_output(maxlines=maxlines, maxlength=maxlength)

    @staticmethod
    def parse_input(s, stringmode=True):
        """ Replace newline symbols with real newlines,
            escape newlines where needed.
            Return the parsed input.
        """
        # let the user use '\n' (\\n) as newlines, and '\\n' ('\\\\n') as
        # escaped newline characters.
        if stringmode:
            s = s.replace('\\\\n', '{//n}')
            s = s.replace('\\n', '\n')
            s = s.replace('{//n}', '\\n')
        # Add shortcut for print, ?(value)
        s = s.replace('?(', 'print(')
        if ('\n' in s) and (not s.endswith('\n')):
                # Make sure code ends with \n.
            s = '{}\n'.format(s)

        return s

    def pprint(self, s):
        """ No longer used. DELETE ME. """
        s = str(s)
        if self.output:
            self.output += '\n{}'.format(s)
        else:
            self.output = s

    def printdebug(self, s):
        """ Print only if self.debug == True. """
        if self.debug:
            print('debug: {}'.format(s))

    def proc_output(self, proc):
        """ Get process output, whether its on stdout or stderr.
            Used with _exec/timed_call.
            Arguments:
                proc  : a POpen() process to get output from.
        """
        # Get stdout
        outlines = []
        for line in iter(proc.stdout.readline, ''):
            if line:
                outlines.append(line.strip('\n'))
            else:
                break
        self.printdebug('out lines:\n    {}'.format('\n    '.join(outlines)))

        # Get stderr
        errlines = []
        for line in iter(proc.stderr.readline, ''):
            if line:
                errlines.append(line.strip('\n'))
            else:
                break
        self.printdebug('err lines:\n    {}'.format('\n    '.join(errlines)))

        # Pick stdout or stderr.
        if outlines:
            output = '\n'.join(outlines)
        else:
            remove_items(errlines, ['', '\'import site\' failed'])
            if errlines:
                output = errlines[-1].strip('\n')
                if output == 'RuntimeError':
                    output = 'operation not permitted in the sandbox.'
                elif output == '[Subprocess killed by SIGIOT]':
                    output = 'crash! the interpreter choked.'
            else:
                output = 'No output.'

        if self.debug:
            debugout = '\n    '.join(output.split('\n'))
            self.printdebug('final output:\n    {}'.format(debugout))
        return output.strip('\n')

    def safe_output(self, maxlines=None, maxlength=None):
        """ Retrieves output safe for irc. """

        maxlines = maxlines if maxlines is not None else self.maxlines
        maxlength = maxlength if maxlength is not None else self.maxlength
        if self.lasterror:
            lines = self.lasterror.split('\n')
            msg = 'error'
        elif self.output:
            lines = self.output.split('\n')
            msg = None
        else:
            return 'No output.'

        # truncate by line count first.
        if (maxlines > 0) and (len(lines) > maxlines):
            lines = lines[:maxlines]
            lines.append('(...truncated at {} lines.)'.format(maxlines))
            # Truncate each line if maxlength is set.
            if maxlength > 0:
                trimmedlines = []
                for line in lines:
                    if len(line) > maxlength:
                        newline = '{} (..truncated)'.format(line[:maxlength])
                        trimmedlines.append(newline)
                    else:
                        trimmedlines.append(line)
                lines = trimmedlines

            # Save edited lines as a one-line string.
            oneliner = '\\n'.join(lines)
        # truncate whole output length
        elif (maxlength > 0) and (len(self.output) > maxlength):
            # Save original output as a one-line string.
            oneliner = '\\n'.join(lines)
            # Truncate at maxlength.
            oneliner = '{} (...truncated)'.format(oneliner[:maxlength])
        else:
            oneliner = '\\n'.join(lines)
        # Append error tag if any.
        if msg:
            oneliner = '{}: {}'.format(msg, oneliner)

        return oneliner

    def timed_call(self, func, args=None, kwargs=None, timeout=4):
        """ Calls a function in a separate process, joins that process
            after 'timeout' seconds. If the process timed out, then
            TimedOut is raised.

            func needs a 'pipesend' kwarg to send its result.
            timed_call() will receive the result and return it.
            example:
                def myfunc(x, pipesend=None):
                    x = x * 5
                    pipesend.send(x)

                result = timed_call(myfunc, args=[25])
                # result is now: 25

            Arguments:
                func     : Function to call in a timed thread.

            Keyword Arguments:
                args     : List of args for the function.
                kwargs   : Dict of keyword args for the function.
                timeout  : Seconds to wait before the function times out.
                           Default: 4
        """

        args = args or []
        kwargs = kwargs or {}
        piperecv, pipesend = multiprocessing.Pipe()
        kwargs.update({'pipesend': pipesend})
        execproc = multiprocessing.Process(
            target=func,
            name='ExecutionProc',
            args=args,
            kwargs=kwargs)
        execproc.start()
        execproc.join(timeout=timeout)
        if execproc.is_alive():
            execproc.terminate()
            # This is an ugly way to shutdown pypy-c-sandbox,
            # but I can't seem to make anything else work.
            # the --timeout option on pypy-sandbox isn't doing anything.
            os.system('killall pypy-c-sandbox')
            raise TimedOut('Operation timed out.')
        # Return good result.
        output = piperecv.recv()
        return output


class TempInput(object):

    def __init__(self, inputstr):
        self.inputstr = inputstr

    def __enter__(self):
        self.tempfile = SpooledTemporaryFile()
        self.tempfile.write(self.inputstr)
        self.tempfile.seek(0)
        return self.tempfile

    def __exit__(self, type_, value, traceback):
        self.tempfile.close()
        return False


class TimedOut(Exception):

    """ Raised on timed_call() timeout. """
    pass


def print_blacklist():
    """ Prints the current black list for ExecBox """

    badstrings = ExecBox().blacklist()
    print('Blacklisted items: ({})'.format(len(badstrings)))
    for badstring, msg in badstrings.items():
        print('    {} : {}'.format(badstring.rjust(25), msg))


def print_status(*args, **kwargs):
    """ Just a wrapper for print(). Can be overridden when --quiet is used. """
    return print(*args, **kwargs)


def remove_items(lst, items):
    """ Given a list of strings, rmeoves all occurrence from a list.
    """
    for s in items:
        while s in lst:
            lst.remove(s)


def main(args):
    """ Main entry point, expects args from sys. """
    # Parse args to return an arg dict like docopt.
    argd = docopt(USAGESTR, version=VERSION)

    if argd['--printblacklist']:
        # Catch blacklist printer.
        print_blacklist()
        return 0

    if argd['--quiet']:
        # All status prints are ignored.
        global print_status
        print_status = lambda s: None

    try:
        timeout = int(argd['--timeout'] or 5)
    except (TypeError, ValueError):
        print('\nInvalid number for --timeout: {}'.format(argd['--timeout']))
        return 1

    if argd['CODE']:
        evalstr = argd['CODE']
    else:
        # Read from stdin instead.
        if sys.stdin.isatty():
            print_status('\nReading from stdin, use EOF to run (Ctrl + D).\n')
        evalstr = sys.stdin.read()

    if (len(evalstr) < 256) and os.path.isfile(evalstr):
        # This is a filename, load the contents from it.
        filename = evalstr
        try:
            with open(filename, 'r') as fread:
                evalstr = fread.read()
        except (IOError, OSError) as exio:
            print('\nError reading from file: {}\n{}'.format(filename, exio))
            return 1
        print_status('Loaded contents from file: {}\n'.format(filename))
        stringmode = False
    else:
        stringmode = True
        evallines = evalstr.split('\n')
        evalpreview = evallines[0]
        evallen = len(evallines)
        if evallen > 1:
            morecount = evallen - 1
            plural = 'line' if morecount == 1 else 'lines'
            plusmsg = '...plus {} more {}.'.format(morecount, plural)
            evalpreview = ' '.join((evalpreview, plusmsg))

        print_status('Content: {}\n'.format(evalpreview))

    e = ExecBox(evalstr)
    e.debug = DEBUG

    try:
        output = e.execute(
            raw_output=argd['--raw'],
            stringmode=stringmode,
            use_blacklist=argd['--blacklist'],
            timeout=timeout)
    except TimedOut:
        print('\nOperation timed out. ({}s)'.format(e.timeout))
    except Exception as ex:
        print('\nExecution Error:\n{}'.format(ex))
    else:
        # Success
        outmethod = 'raw output' if argd['--raw'] else 'safe_output()'
        print_status('Results ({}):'.format(outmethod))
        print(output)
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv))
