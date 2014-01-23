PyVal
=====

Python Evaluation Bot for IRC (using PyPy-Sandbox, Twisted, and Python 2.7) 

Requirements: 
-------------

- **python-pypy.sandbox** or **python-pypy.translator.sandbox**
 package found in debian/ubuntu distros.
 
 this package provides the prebuilt `pypy-sandbox` executable 
 which is used to by pyval to run code safely.  
 
 pyval looks for `pypy-sandbox` in `/usr/bin`.
 

- **pastebinit**
 package found in debian/ubuntu distros.

 cmd-line utility to pastebin content when the output limit for chat is exceeded
 
 as of right now, http://paste.pound-python.org is used.
 
 pyval looks for pastebinit in `/usr/bin`.


- **Twisted** python module. 

 `twisted.internet` is used for the irc bot.
 

- **Python 2.7**

 When Twisted supports **Python 3.x**, this project may be ported over.


Notes:
------

Please read the <a href='#tests'>Tests</a> section, it will help you to make sure that your system can
even run PyVal.

The project page for PyVal is http://welbornprod.com/projects/pyval.
The info in this README and the project page may not always be in sync.

By default the bot connects to `irc.freenode.net`.

The bot joins `#pyval` on succesful connection. (channels can be set with `--channels` also, 
see <a href='#example-bot-usage'>Example Bot Usage</a>.)

Nickname is set to *pyval*, which is registered to me so you will want to change it.
You can set the nick with the `--nick` command-line option.
(see <a href='#example-bot-usage'>Example Bot Usage</a>.)

You are certainly free to take this code and start your own eval bot.
If you change the source in any way, please change the name from **pyval** / **pyvalbot** to
something else.

If you want to contribute to the original **pyval**, you can clone this project and send pull requests.


About:
------

This bot consists of a Twisted IRC client, code execution helpers (pyval-exec, and pyval-sandbox), and pypy-sandbox.

Input is taken from the irc message/chatroom when the !py or !python command is used, and is then channeled through
pyval-exec and pyval-sandbox (via pypy-sandbox). The input is compiled and ran inside the sandbox.

The usual bot/eval killers can't stop the bot itself, though the interpreters subprocess may crash. If that happens,
the bot reports that a crash happened, but continues to run. Since the code is executed in pypy-sandbox, there are a few limitations. The only directories available for reading are 2 'virtual directories' set up by pypy-sandbox. Technically,
pyval-exec and pypy-sandbox can read the entire content of any file in those directories (consisting of pyval-sandbox.py, some Python 2.7 libraries, and some Pypy-related libraries). This bot will not return the full content to the chatroom/message. It is limited to a smaller number of characters. Newlines are replaced before reporting the output to the user. Write access, and many IO/Socket libraries, are all disabled inside the sandbox. So a user can technically call `open("file", "w")`, but will not be able to actually `write()` anything.

This has not been fully tested in the public, it is only a starting point. I think bots can serve as good teaching/help tools. I would like to see a working bot in #python, because some times it's easier to show somebody the result of your answer instead of just showing them the answer. It makes things 'click' better with some people.

There is an option to 'blacklist' certain strings. You can enable it by typing '!blacklist on' from irc, or to test it out through pyval-exec just use the --blacklist option. It basically blocks certain strings from being executed. It may be removed if this bot proves strong enough with only the pypy-sandbox protection.


Example Bot Usage:
------------------

To run the full pyval irc bot:

    ./pyvalbot.py --nick MyBot --channels #mychan1,#mychan2
    
There is also a symlink setup (`pyval`), to view all options you can do this:

    ./pyval --help



Example PyValExec Usage:
------------------------

The pyval-exec module can be executed by itself from the command line.

To test the functionality of the sandbox without connecting to irc:

    $./pyval_exec.py "print('okay')"
     Content: print('okay')
     
     Results: (safe_output()):
         okay

Notice the `safe_output()`, it means that newlines are escaped and long output is truncated.

         
PyValExec also has a symlink, and an option to view raw output with `--raw`:

    $./pyvalexec "print('\\\\n'.join([str(i) for i in range(3)]))" -r
    Content: print('\\n'.join([str(i) for i in range(3)]))
    Results (raw output):
    0
    1
    2

PyValExec interprets `\\n` as python's `\n`, but the shell needs escaping too.

Hince the need for `\\\\n` just to get a newline. Which PyValExec receives as `\\n` and uses
as Python's `\n`. If you send PyValExec a `\n`, it will insert an actual newline
(as if you pressed Enter while typing the code).


Running scripts with PyValExec:
-------------------------------

PyValExec can load code from a file if you pass it a file name instead of code:

    $ ./pyvalexec myscriptfile.py
    # don't forget to use -r or --raw to get the raw output instead of safe_output().


The `\n` problem goes away when reading from a file, and all forms of `\n` are treated
exactly as Python would treat them.

There is a difference between Python and PyValExec when loading script files,
`__name__` is not set to `'__main__'`.

When a script is ran with PyValExec, `__name__` is set to `'__pyval__'`.

This allows you to do things like this:

    import sys
    if __name__ == '__main__':
        print('This script is not allowed to run outside of the PyValExec sandbox!')
        sys.exit(1)
    elif __name__ == '__pyval__':
        print('We are in the sandbox, everything is okay.')
    else:
        print('This script is not meant to be imported!')
        sys.exit(1)


Or just:

    import os
    if __name__ != '__pyval__':
        print('This script is designed to run in PyValExec's sandbox!')
        sys.exit(1)
    

Example Chat Usage:
-------------------

        User1: How can I make a dict out the first and last items in a list of lists?
    PyValUser: !py {l[0]:l[-1] for l in [['a', 'b', 'c', 'd'], ['e', 'f', 'g', 'h']]}
        pyval: PyValUser, {'a': 'd', 'e': 'h'}

Advanced Chat Usage:
--------------------

To insert newlines in more advanced code:

    PyValUser: !py x = 5\nfor i in range(x):\n    print(str(i))
        pyval: PyValUser,  0\n1\n2\n3\n4
`print()` must be used because this is not simple `eval()` code. Even with lines like `x=5\nprint(x)`.

To escape newlines in more advanced code:

    PyValUser: !py print('\\n'.join(['test', 'this']))
        pyval: PyValUser, test\nthis

To get long output (there is a time limit on executing code):

    PyValUser: !py for i in range(65):\n    print('test' * 55)
        pyval: cjwelborn, testtesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttest
               full: http://paste.pound-python.org/show/AcDrJg9NszeyXmxcOKBI/

Long output is sent to a pastebin, but even then it is truncated.
You can get up to 65 lines of output, each line must not exceed ~240 characters.

This limit is to ease the bandwidth used on the pastebin site. I don't want to be responsible for the abuse of
pastebins.

If you are trying to evaluate honest code in the sandbox and must have the full output, then you should probably download PyVal and run PyValExec yourself with `--raw` on your own machine.

Tests:
------

Coverage is not where it should be, but if all tests pass then basic functionality should be okay.
As of right now, the tests confirm existence of required third-party executables,
confirm `pastebinit` functionality, and basic code execution.

Tests are `unittest`-based, run them with your favorite test runner for python
(`pytest`, `nose`, etc.).

I would recommend running these tests before trying to run the full bot or pyval-exec.
Any configuration/dependency errors should show up right away and give you a hint about how to fix them.

Updates:
--------

Version 1.0.6:

 - Added channel tracking, admins can list current channels with the `channels` command.
 - Added `partall` command to part all current channels. (must /msg pyval to rejoin, or restart the bot)
 - Changed `join`/`part` commands to accept a comma-separated list for multiple channels.
 - Added better logging, NOTICE and NickServ messages are automatically logged.
 - Added the ability to load scripts with PyValExec (__name__ is set to '__pyval__' for sandbox-detection) 
 - Added `adminhelp` descriptions, admins can now do `adminhelp [cmd]`.