#!/bin/bash

# Kills the currently running pyvalbot process cleanly.
# Restarts it with args passed to pyval_restart.


if [ -f pyval_pid ]; then
    PYVALPID=`cat pyval_pid`
else
    echo "No pid file found: pyval_pid"
    echo "Won't be able to restart, do it manually."
    exit
fi

if [ "$PYVALPID" == "" ]; then
    echo "pyval_pid file found, but it was empty."
    echo "Won't be able to restart, do it manually."
    exit
fi

# Do a clean kill, where Twisted will cleanly disconnect. (send interrupt)
echo "Killing pyvalbot process: ${PYVALPID}"
kill -SIGINT $PYVALPID
if [ "$?" == "0" ]; then
    # Successful kill, restart it.
    echo "Restarting with args: ${@}"
    ./pyvalbot.py $@
else
    # Failed to kill.
    echo "Failed to kill pyvalbot process."
    echo "killall returned non-zero, restart it manually."
fi
