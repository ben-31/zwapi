#!/usr/bin/python

"""
	Copyright (C) 2009 Poltorak Serguei <poltorak@alsenet.com>
	This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License.
	This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
	of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

	See the GNU General Public License for more details.
"""

import os, time
import xml.dom.minidom
import collections
import threading

import ZWApi, STimer, SNet, log, SNetSoap, SNetREST

config_file = "./config.xml"

# class to hold event
class Event:
	def __init__(self, event, srcNode, dstNode, value):
		(self.event, self.srcNode, self.dstNode, self.value) = (event, srcNode, dstNode, value)

class ZWaveDevices:
	pass

class ZWaveDevice:
	def __init__(self, node_id, name, description):
		self.id = node_id
		self.name = name
		self.description = description

	def BasicSet(self, val):
		ZWApi.zwBasicSet(self.id, val)

	def DimBegin(self, direction):
		ZWApi.zwDimBegin(self.id, direction)

	def DimEnd(self):
		ZWApi.zwDimEnd(self.id)

	def BatteryGet(self):
		ZWApi.zwBatteryGet(self.id)

	def addTimer(self, name, val):
		STimer.addTimer(self.id, name, val)

	def removeTimer(self, name):
		STimer.removeTimer(self.id, name)

	# return value of ZWave device
	def Value(self):
		ZWApi.zwRequestBasicGet(self.id)
		# wait for reply
		reqEvent.clear()
		reqEvent.wait()

		global reqValue
		return reqValue

	# check if ZWave value equals to Val
	# IfNone is returned if ZWave device is unavailable
	def ValueEq(self, Val, IfNone):
		zwValue = self.Value()
		if zwValue == None:
			return IfNone
		else:
			return True if zwValue == Val else False

	# check if ZWave value is in range (inclusive)
	# IfNone is returned if ZWave device is unavailable
	# max or min may be None: in this case the condition is not checked.
	def ValueInRange(self, Min, Max, IfNone):
		zwValue = self.Value()
		if zwValue == None:
			return IfNone
		else:
			return True if (Min == None or Min <= zwValue) and (Max == None or zwValue <= Max) else False

	# check if variable is defined
	def isDefined(self, var):
		try:
			eval("self." + var)
			return True
		except AttributeError:
			return False

	VirtualValue = {}

def breakRules():
	global stopRulesExecution
	stopRulesExecution = True

# Rules list
rules = []

# flag to stop rules execution
stopRulesExecution = None

# ZWave devices named list [ zw.MyDevice = ZWaveDevice() ]
zw = ZWaveDevices()

# Mutex lock for the Events queue
queueMutex = threading.Lock()

# Thread event lock for requests from condition
reqEvent = threading.Event()

# Value returned upon requests
reqValue = None

# Events queue
Events = collections.deque()

device = ""
host = ""
port = 0


def NodeVal(x):
	if x is None: return None
	return x.nodeValue.strip(" \t\r\n")

# get basic configuration
def LoadConfig():
	global config_file, device, net_host, net_port
	config = xml.dom.minidom.parse(config_file)
	cfgs = config.getElementsByTagName("program")
	if cfgs is None:
		raise Exception("program section not found")
	device = cfgs[0].attributes["device"].value
	net_host = cfgs[0].attributes["host"].value
	net_port = int(cfgs[0].attributes["port"].value)

# Load devices
def LoadDevices():
	global config_file
	config = xml.dom.minidom.parse(config_file)
	for dev in config.getElementsByTagName("device"):
		if "id" not in dev.attributes.keys() or "name" not in dev.attributes.keys() or "description" not in dev.attributes.keys():
			raise Exception("Invalid node in config: %s" % dev.nodeName)
		exec "zw." + dev.attributes["name"].value + " = ZWaveDevice(" + dev.attributes["id"].value + ", \"" + dev.attributes["name"].value + "\", \"" + dev.attributes["description"].value + "\")" in {"zw": zw, "ZWaveDevice": ZWaveDevice }
		log.info(("ZWave node \"%s\" (%s): %s" % (dev.attributes["name"].value, dev.attributes["id"].value, dev.attributes["description"].value)).encode("utf8"))

# Load and parse rules
def LoadRules():
	global config_file
	config = xml.dom.minidom.parse(config_file)
	for rule in config.getElementsByTagName("rule"):
		condition = None
		action = None
		description = ""
		for child in rule.childNodes:
			if child.nodeType != xml.dom.Node.ELEMENT_NODE:
				continue

			if child.nodeName == "condition":
				condition = NodeVal(child.firstChild)
			elif child.nodeName == "action":
				action = NodeVal(child.firstChild)
			elif child.nodeName == "description":
				description = NodeVal(child.firstChild).encode("utf8")
			else:
				raise Exception("Invalid node in config: %s" % child.nodeName)

		if condition is None:
			raise Exception("Condition not found")
		if action is None:
			raise Exception("Action not found")

		log.info("Rule:")
		log.ident()
		log.info("Condition: %s" % condition)
		log.info("Action: %s" % action)
		log.info("Description: %s" % description)
		log.deident()

		rules.append((condition, action))

# load nad execute startup rules from config
def LoadStartUpRules():
	global config_file
	config = xml.dom.minidom.parse(config_file)
	for rule in config.getElementsByTagName("startuprule"):
		action = None
		for child in rule.childNodes:
			if child.nodeType != xml.dom.Node.ELEMENT_NODE:
				continue

			if child.nodeName == "action":
				action = NodeVal(child.firstChild)
			elif child.nodeName == "description":
				description = NodeVal(child.firstChild).encode("utf8")
			else:
				raise Exception("Invalid node in config: %s" % child.nodeName)

		if action is None:
			raise Exception("Action not found")

		log.info("Startup Rule:")
		log.ident()
		log.info("Action: %s" % action)
		log.info("Description: %s" % description)
		log.deident()

		try:
			exec action in rules_nspace
		except Exception, inst:
			log.exception(inst, "Action: %s" % action)

# Configure devices
def ConfigureDevices():
	config = xml.dom.minidom.parse(config_file)
	for dev in config.getElementsByTagName("device"):
		if "id" not in dev.attributes.keys() and "name" not in dev.attributes.keys():
				raise Exception("Invalid node in config: %s" % dev.nodeName)

		name = dev.attributes["name"].value

		if "association" in dev.attributes.keys():
				group = 1
				for grp in dev.attributes["association"].value.split(";"):
					if grp != "":
						for asc in grp.split(","):
							if asc != "":
								try:
									exec "ZWApi.zwAssociationSet(zw." + name + ".id, " + str(group) + ", zw." + asc + ".id)" in rules_nspace
								except Exception, inst:
									log.exception(inst, "Configuration: %s" % ("ZWApi.zwAssociationSet(zw." + name + ".id, " + str(group) + ", zw." + asc + ".id)"))
					group += 1

		cfgs = filter(lambda (n): n.nodeName == "config", dev.childNodes)
		if len(cfgs) > 0:
			cfg = NodeVal(cfgs[0].firstChild).replace("@node@", "zw." + name + ".id")
			for c in cfg.split(";"):
				try:
					exec c.strip() in rules_nspace
				except Exception, inst:
					log.exception(inst, "Configuration: %s" % c.strip())

rules_nspace = { "STimer": STimer, "zw": zw, "ZWApi": ZWApi, "time": time, "ConfigureDevices": ConfigureDevices, "os": os }
rules_events = { "OnOff" : 1, "Timer" : 2, "DimBeginUp": 3, "DimBeginDown": 4, "DimEnd": 5, "AllOnOff": 6, "BatteryLevel": 7, "Alarm": 8 }

# Apped new event to the queue
def Poll(event, srcNode, dstNode, value):
	queueMutex.acquire()
	Events.append(Event(event, srcNode, dstNode, value))
	queueMutex.release()

def ReqReply(value):
	global reqValue
	reqValue = value
	# release thread requesting this value
	reqEvent.set()

# Return Virtual value to be returned to wall paddles
def VirtualValue(vNodeId, NodeId):
	for device in dir(zw):
		if "id" in dir(device) and device.id == NodeId:
			try:
				return device.VirtualValue[vNodeId]
			except (AttributeError, IndexError):
				return None
			break

def Quit():
	log.info("\nEnding due to KeyboardInterrupt")
	SNet._exit()
	os._exit(0)

# Wait for events in the queue and execute them
def Loop():
	global stopRulesExecution, rules_nspace

	while True:
		queueMutex.acquire()
		if len(Events) > 0:
			ev = Events.popleft()
		else:
			ev = None
		queueMutex.release()

		if ev is not None:
			log.info("Got event %s from %i to %i: %s" % (filter(lambda (x): rules_events[x] == ev.event, rules_events)[0], ev.srcNode, ev.dstNode, ev.value))

			eval_rules_events = rules_events.copy()  # map(lambda (e): True if ev.event == rules_events[e] else False, rules_events)
			for e in eval_rules_events:
				eval_rules_events[e] = True if ev.event == rules_events[e] else False

			executed = 0
			stopRulesExecution = False

			nspace = dict(dict({ "sNode": ev.srcNode, "dNode": ev.dstNode, "val": ev.value, "breakRules": breakRules }, **eval_rules_events), **rules_nspace)
			for (cond, act) in rules:
				try:
					if eval(cond, nspace):
						exec act in nspace
						executed = 1
						if stopRulesExecution:
							break
				except Exception, inst:
					log.exception(inst, ("Condition: %s" % cond, "Action: %s" % act))
			if executed == 0:
				log.info(" -->> trap")

		time.sleep(0.001)

# main()

log.info("Loading config...")
LoadConfig()
LoadDevices()
LoadRules()

try:
	STimer.init(Poll)
	SNet.init(net_host, net_port, Poll, dict(rules_nspace, **rules_events))
	SNetSoap.init(net_host, 12080, Poll, dict(rules_nspace, **rules_events))
        SNetREST.init('::', 55000, Poll, dict(rules_nspace, **rules_events))
	ZWApi.init(device, Poll, ReqReply, VirtualValue)

	time.sleep(10)

	log.info("Running start up rules")
	LoadStartUpRules()

	log.info("Running rules loop")
	Loop()
except KeyboardInterrupt:
	Quit()
