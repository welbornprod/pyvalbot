#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ircbot.py

    Taken from https://gist.github.com/habnabit/5823693 for expirimental use.

    -Christopher Welborn (original: github.com/habnabit)
"""


# System/General stuff
from datetime import datetime
from os import getpid
import os.path
import sys


#from datetime import datetime
from docopt import docopt

# Irc stuff
from twisted.internet import defer, endpoints, protocol, reactor, task
from twisted.python import log
from twisted.words.protocols import irc
 
# Local stuff (Command Handler)
from pyval_commands import AdminHandler, CommandHandler
from pyval_util import NAME, VERSIONSTR

SCRIPT = os.path.split(sys.argv[0])[1]

BANFILE = '{}_banned.lst'.format(NAME.lower().replace(' ', '-'))

USAGESTR = """{versionstr}

    Usage:
        {script} -h
        {script} [options]
        
    Options:
        -c chans,--channels chans  : Comma-separated list of channels to join.
        -d,--data                  : Log all sent/received data.
        -h,--help                  : Show this message.
        -i,--ips                   : Print all messages to log, 
                                     include ip addresses.
        -l,--logfile               : Use log file instead of stderr/stdout.
        -m,--monitor               : Print all messages to log.
        -n <nick>,--nick <nick>    : Choose what NICK to use for this bot.
        
""".format(versionstr=VERSIONSTR, script=SCRIPT)


class MyFirstIRCProtocol(irc.IRCClient):
 
    def __init__(self):
        self.argd = main_argd
        self.deferred = defer.Deferred()
        nick = self.get_argd('--nick', 'pyval')

        # Class to handle admin stuff. Needs to be accessed here and in
        # CommandHandler.
        self.admin = AdminHandler(nick=nick)
        self.admin.monitor = self.get_argd('--monitor', False)
        self.admin.monitordata = self.get_argd('--data', False)
        self.admin.monitorips = self.get_argd('--ips', False)
        # Give admin access to certain functions.
        self.admin.quit = self.quit
        self.admin.sendLine = self.sendLine
        self.admin.handlinglock = defer.DeferredLock()
        # IRCClient must hold a nickname attribute.
        self.nickname = self.admin.nickname

        # Class to handle messages and commands.
        self.commandhandler = CommandHandler(defer_=defer,
                                             reactor_=reactor,
                                             adminhandler=self.admin)

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        print('\nConnected.')
        
    def connectionLost(self, reason):
        print('\nConnection Lost.\n')
        self.deferred.errback(reason)
 
    def lineReceived(self, line):
        """ Receive line, catch what is being received for logs. """
        irc.IRCClient.lineReceived(self, line)
        if self.admin.monitordata:
            print('\nRecv: {}'.format(line))
    
    def sendLine(self, line):
        """ Send line, catch what is being sent for logs. """
        irc.IRCClient.sendLine(self, line)
        if self.admin.monitordata:
            print('\nSent: {}'.format(line))
    
    def setArg(self, argname, argval):
        """ Function to call from other places, to set argd args. """
        
        if self.argd:
            self.argd[argname] = argval
            print('Set arg: {} = {}'.format(argname, argval))

    def signedOn(self):
        # This is called once the server has acknowledged that we sent
        # both NICK and USER.
        for channel in self.factory.channels:
            print('Joining :{}'.format(channel))
            self.join(channel)
 
    # Obviously, called when a PRIVMSG is received.
    def privmsg(self, user, channel, message):
        nick, _, host = user.partition('!')
        message = message.strip()
        is_admin = (nick in self.admin.admins)

        if (channel == self.admin.nickname) and (nick.lower() == 'nickserv'):
            print('NickServ: {}'.format(message))

        # Disallow banned nicks.
        if nick in self.admin.banned:
            return None

        # rate-limit responses, handle auto-bans.
        ban_msg = None
        if self.admin.last_handle and self.admin.last_nick:
            # save seconds since last response.
            respondtime = (datetime.now() - self.admin.last_handle)
            respondsecs = respondtime.total_seconds()
            # If this user has been ban warned, check their last response time.
            if nick in self.admin.banned_warned.keys():
                lasttime = self.admin.banned_warned[nick]['last']
                usersecs = (datetime.now() - lasttime).total_seconds()
                if usersecs < 4:
                    if self.admin.ban_add(nick):
                        ban_msg = 'no more.'
                    else:
                        ban_msg = 'slow down.'

            elif (nick == self.admin.last_nick) and (respondsecs < 3):
                # first time offender
                self.admin.ban_add(nick)

        if ban_msg:
            # Send ban msg instead of usual command response.
            d = defer.maybeDeferred(lambda: ban_msg)
        else:
            # Process command.

            # Ignore this if we just processed the same command.
            if message == self.admin.last_command:
                if is_admin:
                    print('Would\'ve ignored cmd: {}, '.format(message) +
                          'last: {}'.format(self.admin.last_command))
                else:
                    print('Ignoring cmd: {}, '.format(message) +
                          'last: {}'.format(self.admin.last_command))
                    return None

            # Handle message parsing and commands.
            # If the message triggers a command, then a function is returned to
            # handle it. If there is no function returned, then just return.
            func = self.commandhandler.parse_data(user, channel, message)
            
            # Nothing returned from commandhandler, no response is needed.
            if not func:
                return None

            # Get '!cmd rest' to send to func args...
            command, sep, rest = message.lstrip('!').partition(' ')
            # Save this message, and build deferred with these args.
            self.admin.last_command = message
            d = defer.maybeDeferred(func, rest.strip(), nick=nick)

        if self.admin.limit_rate:
            # Disallow backup of requests. If handlingcount is too much
            # just ignore this one.
            if (not is_admin) and (self.admin.handlingcount > 3):
                print('Too busy, ignoring command: {}'.format(message))
                return None
            # Keep track of how many requests are unanswered (handling).
            self.admin.handlinglock.acquire()
            self.admin.handlingcount += 1
            self.admin.handlinglock.release()
            #print('Request Count: {}'.format(self.admin.handlingcount))

        # Add error callbackfor func, the _show_error callback will turn the
        # error into a terse message first:
        d.addErrback(self._showError)
        # Pick args for _sendMessage based on where the message came from.
        # This will fire off our send function
        if channel == self.admin.nickname:
            # Send private response.
            d.addCallback(self._sendMessage, nick)
        else:
            # Send channel response.
            d.addCallback(self._sendMessage, channel, nick)

        # Save the last command-handled time for next time.
        self.admin.last_handle = datetime.now()
        self.admin.last_nick = nick

    def _handleMessage(self, msg, target, nick=None):
        """ Actually send the message, decrease the handling count. """
        if msg:
            if nick:
                msg = '{}, {}'.format(nick, msg)
            self.msg(target, msg)
        # admin cmds have no msg sometimes, but still count as 'handling'.
        if self.admin.handlingcount > 0:
            self.admin.handlinglock.acquire()
            self.admin.handlingcount -= 1
            self.admin.handlinglock.release()

    def _sendMessage(self, msg, target, nick=None):
        if self.admin.handlingcount > 1:
            # Calculate delay needed based on current handling count.
            # Ends up being around 2 seconds per response.
            # Schedule message handling for later.
            if msg:
                timeout = 2 * self.admin.handlingcount
                print('Delaying msg response for later: {}'.format(timeout))
            else:
                # admin commands have no msg sometimes, still 'handling'
                # though. Don't delay commands that don't have a msg.
                timeout = 0.25
            reactor.callLater(timeout,
                              self._handleMessage,
                              msg,
                              target,
                              nick)
        else:
            # Handle response right away-ish.
            # (give twisted a split-second to do other things like
            #  increase the self.admin.handlingcount if needed)
            reactor.callLater(0.25,
                              self._handleMessage,
                              msg,
                              target,
                              nick)

    def _showError(self, failure):
        return failure.getErrorMessage()
    
    def get_argd(self, argname, defaultval=None):
        """ Safely retrieves a command-line arg from self.argd. """
        if not self.argd:
            print('\nSomething went wrong, self.argd was None!\n'
                  'Setting to main_argd.')
            self.argd = main_argd
        if self.argd:
            if argname in self.argd.keys():
                return self.argd[argname]
            else:
                print('Key not found in self.argd!: {}'.format(argname))
        return defaultval
    

class MyFirstIRCFactory(protocol.ReconnectingClientFactory):

    def __init__(self, argd=None):
        self.protocol = MyFirstIRCProtocol
        self.protocol.argd = argd
        self.argd = argd
        
        if self.get_argd('--channels'):
            # Comma-separated list of channels to join from cmd-line args.
            if ',' in self.get_argd('--channels'):
                self.channels = self.get_argd('--channels').split(',')
            else:
                self.channels = [self.get_argd('--channels')]
        else:
            # Default channel to join when none are supplied
            self.channels = ['#pyval']
    
    def get_argd(self, argname):
        """ Safely retrieve arg from self.argd """
        
        if self.argd:
            if argname in self.argd.keys():
                return self.argd[argname]
            else:
                print('Key not found in self.argd!: {}'.format(argname))
        return None


def write_pidfile():
    """ Writes the current pid to file, for pyval_restart. """

    try:
        pyvalpid = getpid()
        with open('pyval_pid', 'w') as fwrite:
            fwrite.write(str(pyvalpid))
        print('Wrote pid to pyval_pid: {}'.format(pyvalpid))
        return True
    except (IOError, OSError) as ex:
        print('Unable to write pid file, pyval_restart will be useless.\n'
              '{}'.format(ex))
        return False


def main(reactor, description, argd):
    """ main-entry point for ircbot. """
    try:
        endpoint = endpoints.clientFromString(reactor, description)
        factory = MyFirstIRCFactory(argd=argd)
        d = endpoint.connect(factory)
        d.addCallback(lambda protocol: protocol.deferred)
        return d
    except Exception as ex:
        print('\nError in main():\n{}'.format(str(ex)))
        return None
 
if __name__ == '__main__':
    # Get docopt args
    main_argd = docopt(USAGESTR, version=VERSIONSTR)
    # Open log file if --logfile is passed, (fallback to stderr on error)
    if main_argd['--logfile']:
        logfilename = '{}.log'.format(NAME.lower().replace(' ', '-'))
        try:
            logfile = open(logfilename, 'w')
            log.startLogging(logfile)
        except (IOError, OSError) as exio:
            print('\nUnable to open logfile!: '
                  '{}\nstderr will be used instead.\n'.format(logfilename))
            log.startLogging(sys.stderr)
    else:
        # normal stderr logging
        log.startLogging(sys.stderr)

    # Write pid file.
    write_pidfile()

    # Start irc client.
    task.react(main, ['tcp:irc.freenode.net:6667', main_argd])
