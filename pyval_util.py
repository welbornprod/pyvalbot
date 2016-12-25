#!/usr/bin/env python
# -*- coding: utf-8 -*-

""" PyVal Utilities Module
    Holds globally shared info about pyval and utility functions.
"""

import re

NAME = 'PyVal'
VERSION = '1.2.1'
VERSIONSTR = '{} v. {}'.format(NAME, VERSION)


def humantime(d, short=False):
    """ Formats a datetime.datetime() into a human readable string.

        Date, Time, and DateTime objects are accepted.
        If a time or date portion is zeroed out, it is not printed.

        Example:
            humantime(datetime.time(datetime.now()))
            # '09:26:18PM'
            humantime(datetime.date(datetime.now()))
            # 'Wednesday, May 27 2015'
            humantime(datetime.now())
            # 'Wednesday, May 27 2015 09:26:31PM'

        Arguments:
            d      :  A datetime() object with or without time included.
            short  : Use abbreviations if True, otherwise use proper names.
                     Default: False
    """
    if d.strftime('%m%d%y') == '010100':
        date = ''
    else:
        date = d.strftime('%a, %b %d %Y' if short else '%A, %B %d %Y')
    if d.strftime('%H%M%S') == '000000':
        time = ''
    else:
        time = d.strftime('%I:%M:%S%p')
    # This prevents a leading/trailing space in date/time-only mode.
    return ' '.join((s for s in (date, time) if s))


def timefromsecs(secs, label=True):
    """ Return a time string from total seconds.
        Calculates hours, minutes, and seconds.
        Returns '0d:1h:2m:3s' if label is True, otherwise just: '0:1:2:3'

        Output is only as big as the time.
            timefromsecs(30) == '30s'
            timefromsecs(61) == '1m:1s'
            timefromsecs(3661) == '1h:1m:1s'
            timefromsecs(90061) == '1d:1h:1m:1s'

            timefromsecs(90062, label=False) = '1:1:1:2'

        * Exact precision is not guaranteed. Conversion to int() loses some.
    """
    if secs < 60:
        # Seconds only.
        return '{}s'.format(secs) if label else str(int(secs))

    minutes = secs / 60
    seconds = int(secs % 60)
    if minutes < 60:
        # Minutes and seconds only.
        fmtstr = '{}m:{}s' if label else '{}:{}'
        return fmtstr.format(int(minutes), seconds)

    hours = minutes / 60
    minutes = int(minutes % 60)
    if hours < 24:
        # Hours, minutes, and seconds only.
        fmtstr = '{}h:{}m:{}s' if label else '{}:{}:{}'
        return fmtstr.format(int(hours), minutes, seconds)

    days = int(hours / 24)
    hours = int(hours % 24)
    # Days, hours, minutes, and seconds.
    fmtstr = '{}d:{}h:{}m:{}s' if label else '{}:{}:{}:{}'
    return fmtstr.format(days, hours, minutes, seconds)


def get_args(s, arglist):
    """ Grab arguments from the start of a string,
        trim them from the string and return a dict of:
            {argname: (arg found?)}
        This only grabs args from the beginning of the string.
        So things like this can be used: "--paste print('--help')"

        Expects a string and a tuple of:
            (('-s1', '--long1'), ('-s2', '--long2'))
        Returns:
            (argdict, trimmed_string)

        Example:
            >>> get_args('-r testing this', (('-r', '--reverse'),)
                ({'--reverse': True}, 'testing this')

            argdict, s = get_args(
                '-r blah.',
                (('-r', '--re'),
                ('-p', '--pr')))
            assert argdict == {'--re': True, '--pr': False}
            assert s == 'blah.'
    """
    if not (s and arglist):
        return {}, s
    # Map that will convert a short option into a long one.
    flagmap = {opt1: opt2 for opt1, opt2 in arglist}
    # Build a base dict, holds all long options with default value of False.
    argdict = {opt2: False for _, opt2 in arglist}
    # Build a regex pattern to match any arg at the start of the string.
    argpat = re.compile('|'.join(
        '((^{})|(^{}))'.format(opts[0], opts[1])
        for opts in arglist
    ))
    # Find any arg that matches. Save it, strip it, and try another.
    flagmatch = argpat.match(s)
    while flagmatch:
        # Strip it.
        s = argpat.sub('', s).lstrip()
        # Save it to the argdict.
        foundopt = flagmatch.group()
        if foundopt in flagmap:
            # short option, map to long name.
            argdict[flagmap[foundopt]] = True
        else:
            # long option. no mapping needed.
            argdict[foundopt] = True
        # Try another match.
        flagmatch = argpat.match(s)
    return argdict, s
