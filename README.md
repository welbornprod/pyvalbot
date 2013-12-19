pyvalbot
========

Python Evaluation Bot for IRC (using PyPy-Sandbox, Twisted, and Python 2.7) 

Requirements: 
-------------

python-pypy.sandbox or python-pypy.translator.sandbox package found in debian/ubuntu distros. (looks for pypy-sandbox in /usr/bin)

Twisted python package.

Python 2.7


Notes:
------

By default it connects to irc.freenode.net.

Joins '#pyval' on succesful connection. (channels can be set with cmdline args also)

Nickname is set to 'pyval', which is registered to me so you will want to change it.


About:
------

This bot consists of a Twisted IRC client, code execution helpers (pyval-exec, and pyval-sandbox), and pypy-sandbox.

Input is taken from the irc message/chatroom when the !py or !python command is used, and is then channeled through
pyval-exec and pyval-sandbox (via pypy-sandbox). The input is compiled and ran inside the sandbox.

The usual bot/eval killers can't stop the bot itself, though the interpreters subprocess may crash. If that happens,
the bot reports that a crash happened, but continues to run. Since the code is executed in pypy-sandbox, there are a few limitations. The only directories available for reading are 2 'virtual directories' set up by pypy-sandbox. Technically,
pyval-exec and pypy-sandbox can read the entire content of any file in those directories (consisting of pyval-sandbox.py, some Python 2.7 libraries, and some Pypy-related libraries). This bot will not return the full content to the chatroom/message. It is limited to a smaller number of characters. Newlines are replaced before reporting the output to the user. Write access, and many IO/Socket libraries, are all disabled inside the sandbox. So a user can technically call `open("file", "w")`, but will not be able to actually `write()` anything.

This has not been fully tested in the public, it is only a starting point. I think bots can serve as good teaching/help tools. I would like to see a working bot in #python, because some times it's easier to show somebody the result of your answer instead of just showing them the answer. It makes things 'click' better with some people.

There is an option to 'blacklist' certain strings. You can enable it by typing '!blacklist on' from irc, or to test it out through pyval-exec just use the --blacklist option. It basically blocks certain strings from being executed. It may be removed if this bot proves strong enough with just pypy-sandbox


Example Bot Usage:
------------------

    ./pyvalbot.py --nick MyBot --channels mychan1,mychan2 --monitor --logfile


Example PyValExec Usage:
------------------------

The pyval-exec module can be ran by itself from the command line, to test the functionality of the sandbox itself.

    ./pyval_exec.py "print('okay')"
    result: (safe_output()):
        okay
    

Example Chat Usage:
-------------------

        User1: How can I make a dict out the first and last items in a list of lists?
    PyValUser: !py {l[0]:l[-1] for l in [['a', 'b', 'c', 'd'], ['e', 'f', 'g', 'h']]}
        pyval: PyValUser, result: {'a': 'd', 'e': 'h'}




