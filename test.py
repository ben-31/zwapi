#!/usr/bin/python

"""
	Copyright (C) 2009 Poltorak Serguei <poltorak@alsenet.com>
	This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License.
	This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
	of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

	See the GNU General Public License for more details.
"""

from ZWApi import *

def cbk(a, b, c, d):
  print("Callback: event %i, srcNode: %i, dstNode: %i, val %s" % (a, b, c, d))

def rep(a, b):
  print("Report for %i, %i" % (a, b))

init("/dev/ttyACM0", cbk, None, rep)
