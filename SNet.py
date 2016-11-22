#!/usr/bin/python

"""
	Copyright (C) 2009 Poltorak Serguei <poltorak@alsenet.com>
	This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License.
	This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
	of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

	See the GNU General Public License for more details.
"""

import threading, time, socket, os, sys, StringIO

import log

# ##/# This sign marks the commented code for outout redirect during the command execution

class NetConfig:
	def __init__(self):
		self.callback_func = None
		self.rules_nspace = None
		self.port = 12345
		self.host = ""
		self.cli = []

# Net server thread
class NetServThread (threading.Thread):
	def run(self):
		netServ()

# Net client thread
class NetCliThread (threading.Thread):
	def setCli(self, cliSock, cliAddr):
		self.cliSock = cliSock
		self.cliAddr = cliAddr

	def run(self):
		netCli(self.cliSock, self.cliAddr, self)

N = NetConfig()

def init(host, port, callback_function, rules_nspace):
	N.host = host
	N.port = port
	N.callback_func = callback_function
	N.rules_nspace = rules_nspace

	# net thread
	netThread = NetServThread
	netThread().start()

def netServ():
	try:
		N.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		N.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # this is not to have "Addres is already in use"
		N.sock.bind((N.host, N.port))
		N.sock.listen(10)
	except Exception, inst:
		log.exception(inst, "Can not configure port")
		os._exit(0)

	while 1:
		try:
			(cliSock, cliAddr) = N.sock.accept()
			C = NetCliThread()
			C.setCli(cliSock, cliAddr)
			C.start()
			N.cli.append(C)
		except:
			continue
		time.sleep(0.01)

def netCli(cliSock, cliAddr, cliThread):
	log.info("Net connection from %s:%s" % socket.getnameinfo(cliAddr, 0))
	cliSock.send("Write command like 'zw.BathRoomDimmer.BasicSet(0)' or send an event like 'addEvent(event, srcNode, dstNode, value[])'. Use 'print dir()' to get possible objects.\n\n")
	cmd = cliSock.recv(4096).lstrip().rstrip()
	log.info("Net cmd = %s" % cmd)
	redirected = StringIO.StringIO()

	nspace = dict({ "addEvent": N.callback_func }, **N.rules_nspace)
	try:
		sys.stdout = redirected
		exec cmd in nspace
	except Exception, inst:
		log.exception(inst, "Cmd: %s" % cmd)
	sys.stdout = sys.__stdout__
	output = redirected.getvalue()
	redirected.close()
	print(output)
	cliSock.send(output)
	cliSock.close()
	N.cli.remove(cliThread)

def _exit():
	N.sock.close()
	for c in N.cli:
		c.cliSock.close()
