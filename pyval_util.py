#!/usr/bin/env python
# -*- coding: utf-8 -*-

""" PyVal Utilities Module
    Holds globally shared info about pyval and utility functions.
"""

NAME = 'PyVal'
VERSION = '1.0.6'
VERSIONX = '7'
VERSIONSTR = '{} v. {}-{}'.format(NAME, VERSION, VERSIONX)

DAYS = {i: v for i, v in enumerate([
        'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'])}

DAYS_SHORT = {i: v for i, v in enumerate(['Mon', 'Tue', 'Wed', 'Thur', 'Fri'])}

MONTHS = {i + 1: v for i, v in enumerate([
    'January', 'February', 'March', 'April',
    'May', 'June', 'July', 'August',
    'Septemer', 'October', 'November', 'December'])}
MONTHS_SHORT = {i + 1: v for i, v in enumerate([
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Nov', 'Dec'])}


def humantime(d, short=False):
    """ Parse a datetime.datetime() into a human readable string.
        Ex: d = datetime(2014, 2, 5, 13, 5, 6)
            print(humantime(d))
            # prints: Wednesday, February 5 1:5:6pm

        If no time is included in the datetime() (time zeroed out), 
        only the date string is returned.

        Arguments:
            d      :  A datetime() object with or without time included.
            short  : Use abbreviations if True, otherwise use proper names.
                     Default: False 
    """
    if short:
        monthstr = '{}.'.format(MONTHS_SHORT[d.month])
        daystr = '{}.'.format(DAYS_SHORT[d.weekday()])
    else:
        monthstr = MONTHS[d.month]
        daystr = DAYS[d.weekday()]
    datestr = '{}, {} {} {}'.format(daystr,
                                    monthstr,
                                    d.day,
                                    d.year)

    # Return only the date if no time is set.
    if not any([d.hour, d.minute, d.second]):
        return datestr
    # Parse human readable time. (12-Hour am/pm)
    shift = 'am' if d.hour < 13 else 'pm'
    hourstr = str(d.hour) if d.hour < 13 else str(d.hour - 12)
    timestr = ':'.join([hourstr, str(d.minute), str(d.second)])
    timestr = '{}{}'.format(timestr, shift)
    return ' '.join([datestr, timestr])


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
