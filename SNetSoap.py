#!/usr/bin/python

"""
	Copyright (C) 2013 Benoit Maricau <benoit.maricau@gmail.com>
	This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License.
	This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
	of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

	See the GNU General Public License for more details.
"""

import threading, time, SOAPpy

class NetConfig:
	def __init__(self):
		self.callback_func = None
		self.rules_nspace = None
		self.port = 12080
		self.host = ""
		self.cli = []

# Net server thread
class NetServThread (threading.Thread):
	def run(self):
		netServ()

N = NetConfig()

def init(host, port, callback_function, rules_nspace):
	N.host = host
	N.port = port
	N.callback_func = callback_function
	N.rules_nspace = rules_nspace

	# net thread
	netThread = NetServThread
	netThread().start()

def etatChaudiere():
	nspace = dict({ "addEvent": N.callback_func }, **N.rules_nspace)
	if eval("zw.Chaudiere.Value()", nspace) == 255:
		return "ON"
	else:
		return "OFF"

def eteindreChaudiere():
	nspace = dict({ "addEvent": N.callback_func }, **N.rules_nspace)
	exec "zw.Chaudiere.BasicSet(0)" in nspace
	return "OK"

def allumerChaudiere():
	nspace = dict({ "addEvent": N.callback_func }, **N.rules_nspace)
	exec "zw.Chaudiere.BasicSet(1)" in nspace
	return "OK"

def etatTemperature():
	return "22"

def netServ():
	server = SOAPpy.SOAPServer((N.host, N.port))
	server.registerFunction(etatChaudiere)
	server.registerFunction(eteindreChaudiere)
	server.registerFunction(allumerChaudiere)
	server.registerFunction(etatTemperature)
	while 1:
		try:
			server.serve_forever()
		except:
			continue
		time.sleep(0.1)
