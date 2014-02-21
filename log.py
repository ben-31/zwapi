#!/usr/bin/python

"""
	Copyright (C) 2009 Poltorak Serguei <poltorak@alsenet.com>
	This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License.
	This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
	of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

	See the GNU General Public License for more details.
"""

import sys
from datetime import datetime

#debug = True
debug = False

flush = False

ident_shift = 0
ident_str = ''

def flush_stdout():
	global flush
	if flush:
		sys.stdout.flush()

def crit(s):
	mprint("CRITICAL", s)

def info(s):
	mprint("INFO", s)

def send(s):
	global debug
	if debug:
		mprint("SEND", s)

def warn(s):
	mprint("WARN", s)

def todo(s):
	mprint("TODO", s)

def receive(s):
	global debug
	if debug:
		mprint("RECEIVE", s)

def error(s):
	mprint("ERROR", s)

def zwstack(s):
	global debug
	if debug:
		mprint("Z-WAVE STACK", s)

def exception(e, s):
	mprint("EXCEPTION", "Type: %s" % type(e))
	mprint("EXCEPTION", "Exception: %s" % e)
	if type(s) is tuple:
		for ss in s:
			mprint("EXCEPTION", "%s" % ss)
	else:	
		mprint("EXCEPTION", "%s" % s)

def mprint(l, s):
	print("%s  %s: %s%s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), l, ident_str, s))
	flush_stdout()

def ident():
	global ident_shift
	ident_shift += 1
	mk_ident_str()

def deident():
	global ident_shift
	ident_shift -= 1
	if ident_shift < 0:
		ident_shift = 0
	mk_ident_str()

def mk_ident_str():
	global ident_str, ident_shift
	ident_str = ''.join(map(lambda(x): " ", range(ident_shift)))

import inspect
def print_lineno(s):
	print("%s: line %i in %s" % (s, inspect.currentframe().f_back.f_lineno, inspect.currentframe().f_back.f_code.co_filename))
