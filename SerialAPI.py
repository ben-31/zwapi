#!/usr/bin/python

"""
	Copyright (C) 2009 Poltorak Serguei <poltorak@alsenet.com>
	This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License.
	This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
	of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

	See the GNU General Public License for more details.
"""

import serial
import sys

class Port:
	def Open(self, portname):
		self.ser = serial.Serial()
		self.ser.port = portname
		self.ser.baudrate = 115200
		self.ser.parity = serial.PARITY_NONE
		self.ser.rtscts = False
		self.ser.xonxoff = False
		self.ser.timeout = 1  # required so that the reader thread can exit
		try:
			self.ser.open()
		except serial.SerialException, e:
			sys.stderr.write("Could not open serial port %s: %s\n" % (self.ser.portstr, e))
			sys.exit(1)

	def Write(self, buf):
		try:
			self.ser.write("".join(chr(i) for i in buf))
		except serial.SerialException, e:
			sys.stderr.write("Could not write to serial port %s: %s\n" % (self.ser.portstr, e))
			sys.exit(1)

	def Read(self, size):
		try:
			return list(ord(ch) for ch in self.ser.read(size))
		except serial.SerialException, e:
			sys.stderr.write("Could not read from serial port %s: %s\n" % (self.ser.portstr, e))
			sys.exit(1)

	def inWaiting(self):
		try:
			return self.ser.inWaiting()
		except serial.SerialException, e:
			sys.stderr.write("Could not get size of waiting buffer from serial port %s: %s\n" % (self.ser.portstr, e))
			sys.exit(1)
