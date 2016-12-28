#!/usr/bin/python

"""
	Copyright (C) 2013 Benoit Maricau <benoit.maricau@gmail.com>
	This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License.
	This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
	of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

	See the GNU General Public License for more details.
"""

import flask, threading

app = flask.Flask(__name__)

class NetConfig:
	def __init__(self):
		self.callback_func = None
		self.rules_nspace = None
		self.host = '0.0.0.0'
		self.port = 55000

N = NetConfig()

class RestThreading(threading.Thread):
	def run(self):
		app.run(host=N.host, port=N.port)

def init(host, port, callback_function, rules_nspace):
	N.host = host
	N.port = port
	N.callback_func = callback_function
	N.rules_nspace = rules_nspace

	restThread = RestThreading()
	restThread.start()

@app.route('/Chaudiere')
def etatChaudiere():
	nspace = dict({ "addEvent": N.callback_func }, **N.rules_nspace)
	if eval("zw.Chaudiere.Value()", nspace) == 255:
		return "ON"
	else:
		return "OFF"

@app.route('/Chaudiere/OFF')
def eteindreChaudiere():
	nspace = dict({ "addEvent": N.callback_func }, **N.rules_nspace)
	exec "zw.Chaudiere.BasicSet(0)" in nspace
	return "OK"

@app.route('/Chaudiere/ON')
def allumerChaudiere():
	nspace = dict({ "addEvent": N.callback_func }, **N.rules_nspace)
	exec "zw.Chaudiere.BasicSet(1)" in nspace
	return "OK"

@app.route('/Temperature')
def etatTemperature():
	return "22"

@app.route('/Temperature/<temp>')
def set_temp(temp):
	return '{}'.format(temp)


