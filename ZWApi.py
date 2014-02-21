#!/usr/bin/python

"""
	Copyright (C) 2009 Poltorak Serguei <poltorak@alsenet.com>
	Based on LMCE ZWave code by Harald Klein <hari@vt100.at> and rewritten from scratch
	This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License.
	This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
	of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

	See the GNU General Public License for more details.
"""

import threading
import time

# my modules
import SerialAPI
import log

from ZWApi_define import *

# Receive thread
class ZWaveReceiveThread (threading.Thread):
	def run(self):
		receiveFunction()

# print lists in hex
class hexList(list):
	def __str__(self):
		return "( " + " ".join(("%02X" % i) for i in self).__str__() + " )"

# ZWave job to send
class ZWJob:
	def __init__(self):
		self.buffer = hexList()

# ZWave jobs awaiting devices wakeup
class ZWSleepJob:
	pass

# ZWave node
class ZWNode:
	pass

class ZWState:
	def __init__(self):
		# queue for sending
		self.ZWSendQueue = []
		# postpone queue for wakeup
		self.ZWWakeupQueue = []
		# ZWave node map
		self.ZWNodeMap = {}
		# counter to get a unique callback id
		self.callbackid = 1
		# the node id of our controller
		self.ournodeid = -1
		# our controller capabilities
		self.capabilities = []
		# callback function for events
		self.poll_callback_func = None
		# callback function for requests
		self.req_callback_func = None
		# request function for virtual values
		self.get_virtual_func = None
		# request callback node id and command
		self.req_node_id = None
		self.req_cmd = None
		# serial port
		self.serialPort = None
		# mutex for send queue
		self.mutexSendQueue = None

		#### CONFIGURATION ####
		# queue loop wait time
		self.dt = 0.01
		# timeout with no ACK before resending packet
		self.ackTimeout = 0.1
		# timeout with no RESPONSE before resending packet
		self.responseTimeout = 0.1
		# timeout with no CALLBACK before resending packet
		self.firstCallbackTimeout = 10
		# timeout with no last CALLBACK before removing packet
		self.moreCallbackTimeout = 20
		# number of resend before dropping command
		self.resend_count = 3
		# number of jobs waiting for callback
		self.awaiting_cbk_jobs = 3

ZWS = ZWState()

event = None

# receive thread
readThread = ZWaveReceiveThread()

# opens the serial port and starts the initalization of the zwave device
def init(serialPortName, poll_callback_function, req_callback_function, get_virtual_func):
	log.info("Initialization...")

	ZWS.poll_callback_func = poll_callback_function
	ZWS.req_callback_func = req_callback_function
	ZWS.get_virtual_func = get_virtual_func

	log.info("Open serial port %s" % serialPortName)
	ZWS.serialPort = SerialAPI.Port()
	ZWS.serialPort.Open(serialPortName)

	ZWS.mutexSendQueue = threading.Lock()

	# run receive thread as a daemon thread
	readThread.daemon = True
	readThread.start()

	zwGetCapabilities()
	log.info("Waiting sevral seconds for controller capabilities")
	time.sleep(2)  # wait for capabilities
	zwGetHomeId()
	zwGetVersion()
	zwGetControllerCapabilities()
	zwGetSUCNodeId()
	zwGetInitData()

# function to check if this is the requested report
def is_requested_reply(node_id, cmd, val):
	if ZWS.req_node_id == node_id and ZWS.req_cmd == cmd:
		ZWS.req_callback_func(val)

# calculate a xor checksum for the zwave frame
def checksum(buf):
	ret = 0xff
	for i in range(0, len(buf)):
		ret = ret ^ buf[i]
	return ret

# decodes a frame received from the dongle
def decodeFrame(frame):
	if (frame[0] == RESPONSE):
		# get the job this is a response to
		resp_job_index = awaitingResponse()
		if resp_job_index is None:
			log.crit("A response received with no request!")
			return

		resp_job = ZWS.ZWSendQueue[resp_job_index]
		markResponse(resp_job_index)


		if frame[1] == FUNC_ID_ZW_GET_SUC_NODE_ID:
				log.info("Got reply to GET_SUC_NODE_ID: %s" % ("No SUC"	if (frame[2] == 0) else ("SUC node is %i" % frame[2])))
		elif frame[1] == FUNC_ID_ZW_SET_SUC_NODE_ID:
				log.info("Got reply to FUNC_ID_ZW_SET_SUC_NODE_ID: %s" % ("started" if frame[2] else "failed"))
				if not frame[2] and resp_job.callbackid != 0:
					removeJob(resp_job_index)
		elif frame[1] == FUNC_ID_ZW_ENABLE_SUC:
				log.info("Got reply to FUNC_ID_ZW_ENABLE_SUC: %s" % ("done" if frame[2] else "failed: trying to disable running SUC?"))
		elif frame[1] == FUNC_ID_MEMORY_GET_ID:
				log.info("Got reply to FUNC_ID_MEMORY_GET_ID, Home id: 0x%02x%02x%02x%02x, our node id: %i" % (frame[2], frame[3], frame[4], frame[5], frame[6]))
				ZWS.ournodeid = frame[6]
		elif frame[1] == FUNC_ID_SERIAL_API_GET_CAPABILITIES:
				log.info("FUNC_ID_SERIAL_API_GET_CAPABILITIES: Version: %i.%i, Manufacture ID: %i/%i, Manufacture Product Type: %i/%i, Manufacture Product ID: %i/%i" % tuple(frame[2:10]))
				log.ident()
				for i in range(len(frame) - 10):
					F = []
					F.extend("".join([str(((frame[i + 10] >> x) & 1) * (x + 1)) for x in range(8, -1, -1)]))
					F.reverse()
					for x in filter(lambda(z): z != '0', F):
						func = int(x) + i * 8
						func_strs = filter(lambda(y): y[0:8] == 'FUNC_ID_' and eval(y) == func, globals())
						if len(func_strs) == 0:
							log.info("undefined FUNC_ID 0x%02x" % func)
						elif len(func_strs) == 1:
							log.info(func_strs[0])
						else:
							log.error("Two FUNC_ID are defined for the same value 0x%02x" % func)
						ZWS.capabilities.append(func)
				log.deident()
		elif frame[1] == FUNC_ID_SERIAL_API_GET_INIT_DATA:
				log.info("Got reply to FUNC_ID_SERIAL_API_GET_INIT_DATA: Version: 0x%02x, Z-Wave Chip: ZW%02i%02i" % (frame[2], frame[5 if frame[4] == MAGIC_LEN else (5 + MAGIC_LEN)], frame[6 if frame[4] == MAGIC_LEN else (6 + MAGIC_LEN)]))
				log.info("Capabilities: %s, %s, %s, %s" % ("Slave API" if frame[3] & 0x01 else "Controller API", "Timer function supported" if frame[3] & 0x02 else "Timer function not supported", "Secondary Controller" if frame[3] & 0x04 else "Primary Controller", "some reserved bits" if frame[3] & 0xf8 else "no reserved bit"))
				if frame[4] == MAGIC_LEN:
					for i in range(5, 5 + MAGIC_LEN):
						for j in range(0, 8):
							if frame[i] & (0x01 << j):
								node_id = (i - 5) * 8 + j + 1
								# requesting node protocol information and is_virtual flag
								zwRequestNodeProtocolInfo(node_id)
								zwRequestIsVirtual(node_id)
		elif frame[1] == FUNC_ID_GET_ROUTING_TABLE_LINE:
				node_id_str = ""
				for i in range(2, 2 + MAGIC_LEN):
					for j in range(0, 8):
						if frame[i] & (0x01 << j):
							node_id_str += "%i " % ((i - 2) * 8 + j + 1)
				log.info("List of neighbours: %s" % node_id_str)
		elif frame[1] == FUNC_ID_ZW_GET_VIRTUAL_NODES:
				node_id_str = ""
				for i in range(2, 2 + MAGIC_LEN):
					for j in range(0, 8):
						if frame[i] & (0x01 << j):
							node_id_str += "%i " % ((i - 2) * 8 + j + 1)
				log.info("List of virtual nodes: %s" % node_id_str)
		elif frame[1] == FUNC_ID_ZW_GET_NODE_PROTOCOL_INFO:
				log.info("Got reply to FUNC_ID_ZW_GET_NODE_PROTOCOL_INFO:")
				job_nodeid = resp_job.buffer[4]

				# test if node is valid
				if frame[6] != 0:
					log.info("***FOUND NODE: %i" % job_nodeid)
					log.ident()
					newNode = ZWNode()
					newNode.typeBasic = frame[5]
					newNode.typeGeneric = frame[6]
					newNode.typeSpecific = frame[7]
					newNode.stateBasic = -1

					if (frame[2]) & (0x01 << 7):
						log.info("listening node")
						newNode.sleepingDevice = 0
						# request version from the device
						# zwRequestVersion(job_nodeid)
						# zwRequestManufacturerSpecificReport(job_nodeid)
					else:
						log.info("sleeping node")
						newNode.sleepingDevice = 1

					if (frame[3]) & (0x01 << 7):
						log.info("optional functionality")

					parseNodeType(frame[5:8])
					log.deident()

					ZWS.ZWNodeMap[job_nodeid] = newNode
				else:
					log.info("Invalid generic class (0x%02x), ignoring device" % frame[6])
		elif frame[1] == FUNC_ID_ZW_SEND_DATA:
				if frame[2] == 1:
						log.zwstack("ZW_SEND delivered to Z-Wave stack")
				elif frame[2] == 0:
						log.error("ZW_SEND could not be delivered to Z-Wave stack")
						if ZWS.ZWSendQueue[resp_job_index].sendcount < 3:
							resendJob(resp_job_index)
						else:
							removeJob(resp_job_index)
				else:
						log.error("ZW_SEND Response is invalid!")

		elif frame[1] == FUNC_ID_ZW_IS_VIRTUAL_NODE:
				job_nodeid = resp_job.buffer[4]
				try:
					ZWS.ZWNodeMap[job_nodeid].isVirtual = frame[2]
					log.info("Node %i is %s " % (job_nodeid, "virtual" if frame[2] == 1 else "real"))
				except KeyError:
					log.error("New node %i found (not in list)" % job_nodeid)
		elif frame[1] == FUNC_ID_ZW_GET_CONTROLLER_CAPABILITIES:
				if frame[2] & CONTROLLER_IS_SECONDARY:
					log.info("Controller is secondary on current Z-Wave network")
				if frame[2] & CONTROLLER_ON_OTHER_NETWORK:
					log.info("Unknown capability ON_OTHER_NETWORK")
				if frame[2] & CONTROLLER_NODEID_SERVER_PRESENT:
					log.info("Controller is a member of a Z-Wave network with a NodeID Server present")
				if frame[2] & CONTROLLER_IS_REAL_PRIMARY:
					log.info("Controller is the original owner of the current Z-Wave network HomeID")
				if frame[2] & CONTROLLER_IS_SUC:
					log.info("Controller is the SUC in current Z-WAve network")
				if frame[2] & ~(CONTROLLER_IS_SECONDARY | CONTROLLER_ON_OTHER_NETWORK | CONTROLLER_NODEID_SERVER_PRESENT | CONTROLLER_IS_REAL_PRIMARY | CONTROLLER_IS_SUC):
					log.info("Unknown FUNC_ID_ZW_GET_CONTROLLER_CAPABILITIES bit: Capability = 0x%02x" % frame[2])
		elif frame[1] == FUNC_ID_ZW_TYPE_LIBRARY:
				if frame[2] == ZW_LIB_CONTROLLER_STATIC:
					log.info("Library type: Static Controller")
				elif frame[2] == ZW_LIB_CONTROLLER:
					log.info("Library type: Portable Controller")
				elif frame[2] == ZW_LIB_CONTROLLER_BRIDGE:
					log.info("Library type: Bridge Controller")
				elif frame[2] == ZW_LIB_SLAVE_ENHANCED:
					log.info("Library type: Enhanced Slave")
				elif frame[2] == ZW_LIB_SLAVE_ROUTING:
					log.info("Library type: Routing Slave")
				elif frame[2] == ZW_LIB_SLAVE:
					log.info("Library type: Slave")
				elif frame[2] == ZW_LIB_INSTALLER:
					log.info("Library type: Installer")
				elif frame[2] == ZW_NO_INTELLIGENT_LIFE:
					log.info("Library type: no inteligent life")
				else:
					log.todo("unknown respose to FUNC_ID_ZW_TYPE_LIBRARY: 0x%02x" % frame[2])
		elif frame[1] == FUNC_ID_ZW_GET_VERSION:
				log.info("Library version is: %s" % ''.join(map(lambda i: chr(frame[i]), range(2, 2 + 12))))
				if frame[14] == ZW_LIB_CONTROLLER_STATIC:
					log.info("Library type: Static Controller")
				elif frame[14] == ZW_LIB_CONTROLLER:
					log.info("Library type: Portable Controller")
				elif frame[14] == ZW_LIB_CONTROLLER_BRIDGE:
					log.info("Library type: Bridge Controller")
				elif frame[14] == ZW_LIB_SLAVE_ENHANCED:
					log.info("Library type: Enhanced Slave")
				elif frame[14] == ZW_LIB_SLAVE_ROUTING:
					log.info("Library type: Routing Slave")
				elif frame[14] == ZW_LIB_SLAVE:
					log.info("Library type: Slave")
				elif frame[14] == ZW_LIB_INSTALLER:
					log.info("Library type: Installer")
				elif frame[14] == ZW_NO_INTELLIGENT_LIFE:
					log.info("Library type: no inteligent life")
				else:
					log.todo("unknown respose to FUNC_ID_ZW_GET_VERSION: 0x%02x" % frame[14])
		elif frame[1] == FUNC_ID_ZW_IS_FAILED_NODE:
				log.info("Node is %s failed" % ("" if frame[2] else "not"))
		elif frame[1] == FUNC_ID_ZW_REMOVE_FAILED_NODE_ID:
				if frame[2] == FAILED_NODE_REMOVE_STARTED:
						log.info("FUNC_ID_ZW_REMOVE_FAILED_NODE_ID: FAILED_NODE_REMOVE_STARTED")
				elif frame[2] == FAILED_NODE_REMOVE_NOT_PRIMARY_CONTROLLER:
						log.info("FUNC_ID_ZW_REMOVE_FAILED_NODE_ID: FAILED_NODE_REMOVE_NOT_PRIMARY_CONTROLLER")
						removeJob(resp_job_index)
				elif frame[2] == FAILED_NODE_REMOVE_NO_CALLBACK_FUNCTION:
						log.info("FUNC_ID_ZW_REMOVE_FAILED_NODE_ID: FAILED_NODE_REMOVE_NO_CALLBACK_FUNCTION")
						removeJob(resp_job_index)
				elif frame[2] == FAILED_NODE_REMOVE_NODE_NOT_FOUND:
						log.info("FUNC_ID_ZW_REMOVE_FAILED_NODE_ID: FAILED_NODE_REMOVE_NODE_NOT_FOUND")
						removeJob(resp_job_index)
				elif frame[2] == FAILED_NODE_REMOVE_PROCESS_BUSY:
						log.info("FUNC_ID_ZW_REMOVE_FAILED_NODE_ID: FAILED_NODE_REMOVE_PROCESS_BUSY")
						removeJob(resp_job_index)
				elif frame[2] == FAILED_NODE_REMOVE_FAIL:
						log.info("FUNC_ID_ZW_REMOVE_FAILED_NODE_ID: FAILED_NODE_REMOVE_FAIL")
						removeJob(resp_job_index)
				else:
						log.error("invalid FUNC_ID_ZW_REMOVE_FAILED_NODE_ID status 0x%02x" % frame[2])
		elif frame[1] == FUNC_ID_ZW_REPLACE_FAILED_NODE:
				if frame[2] == FAILED_NODE_REMOVE_STARTED:
						log.info("FUNC_ID_ZW_REPLACE_FAILED_NODE: FAILED_NODE_REMOVE_STARTED")
				elif frame[2] == FAILED_NODE_REMOVE_NOT_PRIMARY_CONTROLLER:
						log.info("FUNC_ID_ZW_REPLACE_FAILED_NODE: FAILED_NODE_REMOVE_NOT_PRIMARY_CONTROLLER")
						removeJob(resp_job_index)
				elif frame[2] == FAILED_NODE_REMOVE_NO_CALLBACK_FUNCTION:
						log.info("FUNC_ID_ZW_REPLACE_FAILED_NODE: FAILED_NODE_REMOVE_NO_CALLBACK_FUNCTION")
						removeJob(resp_job_index)
				elif frame[2] == FAILED_NODE_REMOVE_NODE_NOT_FOUND:
						log.info("FUNC_ID_ZW_REPLACE_FAILED_NODE: FAILED_NODE_REMOVE_NODE_NOT_FOUND")
						removeJob(resp_job_index)
				elif frame[2] == FAILED_NODE_REMOVE_PROCESS_BUSY:
						log.info("FUNC_ID_ZW_REPLACE_FAILED_NODE: FAILED_NODE_REMOVE_PROCESS_BUSY")
						removeJob(resp_job_index)
				elif frame[2] == FAILED_NODE_REMOVE_FAIL:
						log.info("FUNC_ID_ZW_REPLACE_FAILED_NODE: FAILED_NODE_REMOVE_FAIL")
						removeJob(resp_job_index)
				else:
						log.error("invalid FUNC_ID_ZW_REPLACE_FAILED_NODE status 0x%02x" % frame[2])
		elif frame[1] == FUNC_ID_ZW_GET_NEIGHBOR_COUNT:
				log.info("Neighbor count: %i" % frame[2])
		elif frame[1] == FUNC_ID_ZW_ARE_NODES_NEIGHBOURS:
				log.info("Nodes are %s neighbor" % ("" if frame[2] else "not"))
		elif frame[1] == FUNC_ID_ZW_SET_SLAVE_LEARN_MODE:
				log.info("FUNC_ID_ZW_SET_SLAVE_LEARN_MODE: mode change %s" % ("succesful" if frame[2] else "could not be done"))
				if not frame[2]:
					removeJob(resp_job_index)
		elif frame[1] == FUNC_ID_ZW_REQUEST_NETWORK_UPDATE:
				log.warn("Got reply to FUNC_ID_ZW_REQUEST_NETWORK_UPDATE: %s" % ("started" if frame[2] else "failed"))
				if not frame[2] and resp_job.callbackid != 0:
					removeJob(resp_job_index)
		else:
				log.todo("unhandled response for 0x%02x" % frame[1])

	#####################################################################################################################
	elif frame[0] == REQUEST:
		# generic callback handling
		cbks = awaitingCallback(frame[1], frame[2])
		cbk = None
		if cbks is not None:
			if len(cbks) > 1:
				log.crit("There is more than one job with the same callbackid and callback_type")
			if len(cbks) == 1:
				cbk = cbks[0]
		doRemoveJob = False
		doMarkFirstCallback = False

		if frame[1] == FUNC_ID_ZW_SEND_DATA:
				if cbk is not None:
					if frame[3] == 1:
							# can't deliver frame
							log.error("ZW_SEND Response with callback 0x%02x received: not delivered to recipient" % frame[2])
							if ZWS.ZWSendQueue[cbk].sendcount > 3:
								log.error("Removing job")
								doRemoveJob = True
					elif frame[3] == 0:
							# command reception acknowledged by node
							log.zwstack("ZW_SEND Response with callback 0x%02x received: received by recipient" % frame[2])
							doRemoveJob = True
					else:
							log.error("ZW_SEND Response with callback 0x%02x received: ZW_SEND Response is invalid!" % frame[2])
							doRemoveJob = True
				else:
					# wrong callback id
					log.error("ZW_SEND Response callback id is invalid: %0x02x!" % frame[2])
		elif frame[1] == FUNC_ID_ZW_ADD_NODE_TO_NETWORK:
				if frame[3] == NODE_STATUS_LEARN_READY:
						log.info("FUNC_ID_ZW_NODE_TO_NETWORK: NODE_STATUS_LEARN_READY: node %i" % frame[4])
						doMarkFirstCallback = True
				elif frame[3] == NODE_STATUS_NODE_FOUND:
						log.info("FUNC_ID_ZW_NODE_TO_NETWORK: NODE_STATUS_NODE_FOUND: node %i" % frame[4])
						if frame[5] > 0:
							parseNodeType(frame[6:9])
							parseNodeInfo(frame[9:9 + frame[5] - 3])
				elif frame[3] == NODE_STATUS_ADDING_SLAVE:
						log.info("FUNC_ID_ZW_NODE_TO_NETWORK: NODE_STATUS_ADDING_SLAVE: node %i" % frame[4])
						if frame[5] > 0:
							parseNodeType(frame[6:9])
							parseNodeInfo(frame[9:9 + frame[5] - 3])
				elif frame[3] == NODE_STATUS_ADDING_CONTROLLER:
						log.info("FUNC_ID_ZW_NODE_TO_NETWORK: NODE_STATUS_ADDING_CONTROLLER: node %i" % frame[4])
						if frame[5] > 0:
							parseNodeType(frame[6:9])
							parseNodeInfo(frame[9:9 + frame[5] - 3])
				elif frame[3] == NODE_STATUS_PROTOCOL_DONE:
						log.info("FUNC_ID_ZW_NODE_TO_NETWORK: NODE_STATUS_PROTOCOL_DONE")
						zwAddNodeToNetwork(0, 0)
				elif frame[3] == NODE_STATUS_DONE:
						log.info("FUNC_ID_ZW_NODE_TO_NETWORK: NODE_STATUS_DONE")
						doRemoveJob = True
				elif frame[3] == NODE_STATUS_FAILED:
						log.info("FUNC_ID_ZW_NODE_TO_NETWORK: NODE_STATUS_FAILED")
						zwAddNodeToNetwork(0, 0)
						doRemoveJob = True
				else:
						log.error("invalid FUNC_ID_ZW_ADD_NODE_TO_NETWORK status 0x%02x" % frame[3])
						doRemoveJob = True
						zwAddNodeToNetwork(0, 0)
		elif frame[1] == FUNC_ID_ZW_REMOVE_NODE_FROM_NETWORK:
				if frame[3] == NODE_STATUS_LEARN_READY:
						log.info("FUNC_ID_ZW_REMOVE_NODE_FROM_NETWORK: NODE_STATUS_LEARN_READY: node %i" % frame[4])
						doMarkFirstCallback = True
				elif frame[3] == NODE_STATUS_NODE_FOUND:
						log.info("FUNC_ID_ZW_REMOVE_NODE_FROM_NETWORK: NODE_STATUS_NODE_FOUND: node %i" % frame[4])
						if frame[5] > 0:
							parseNodeType(frame[6:9])
							parseNodeInfo(frame[9:9 + frame[5] - 3])
				elif frame[3] == NODE_STATUS_ADDING_SLAVE:
						log.info("FUNC_ID_ZW_REMOVE_NODE_FROM_NETWORK: NODE_STATUS_REMOVING_SLAVE: node %i" % frame[4])
						if frame[5] > 0:
							parseNodeType(frame[6:9])
							parseNodeInfo(frame[9:9 + frame[5] - 3])
				elif frame[3] == NODE_STATUS_ADDING_CONTROLLER:
						log.info("FUNC_ID_ZW_REMOVE_NODE_FROM_NETWORK: NODE_STATUS_REMOVING_CONTROLLER: node %i" % frame[4])
						if frame[5] > 0:
							parseNodeType(frame[6:9])
							parseNodeInfo(frame[9:9 + frame[5] - 3])
				elif frame[3] == NODE_STATUS_DONE:
						log.info("FUNC_ID_ZW_REMOVE_NODE_FROM_NETWORK: NODE_STATUS_DONE")
						doRemoveJob = True
				elif frame[3] == NODE_STATUS_FAILED:
						log.info("FUNC_ID_ZW_REMOVE_NODE_FROM_NETWORK: NODE_STATUS_FAILED")
						zwRemoveNodeFromNetwork(0)
						doRemoveJob = True
				else:
						log.error("invalid FUNC_ID_ZW_REMOVE_NODE_FROM_NETWORK status 0x%02x" % frame[3])
						doRemoveJob = True
						zwRemoveNodeFromNetwork(0)
		elif frame[1] == FUNC_ID_ZW_CONTROLLER_CHANGE:
				if frame[3] == NODE_STATUS_LEARN_READY:
						log.info("FUNC_ID_ZW_CONTROLLER_CHANGE: NODE_STATUS_LEARN_READ: node %i" % frame[4])
						doMarkFirstCallback = True
				elif frame[3] == NODE_STATUS_NODE_FOUND:
						log.info("FUNC_ID_ZW_CONTROLLER_CHANGE: NODE_STATUS_NODE_FOUND: node %i" % frame[4])
						if frame[5] > 0:
							parseNodeType(frame[6:9])
							parseNodeInfo(frame[9:9 + frame[5] - 3])
				elif frame[3] == NODE_STATUS_ADDING_CONTROLLER:
						log.info("FUNC_ID_ZW_CONTROLLER_CHANGE: NODE_STATUS_ADDING_CONTROLLER: node %i" % frame[4])
						if frame[5] > 0:
							parseNodeType(frame[6:9])
							parseNodeInfo(frame[9:9 + frame[5] - 3])
				elif frame[3] == NODE_STATUS_PROTOCOL_DONE:
						log.info("FUNC_ID_ZW_CONTROLLER_CHANGE: NODE_STATUS_PROTOCOL_DONE")
						zwChangePrimaryController(0, 0)
				elif frame[3] == NODE_STATUS_DONE:
						log.info("FUNC_ID_ZW_CONTROLLER_CHANGE: NODE_STATUS_DONE")
						doRemoveJob = True
				elif frame[3] == NODE_STATUS_FAILED:
						log.info("FUNC_ID_ZW_CONTROLLER_CHANGE: NODE_STATUS_FAILED")
						zwChangePrimaryController(0, 0)
						doRemoveJob = True
				else:
						log.error("invalid FUNC_ID_ZW_CONTROLLER_CHANGE status 0x%02x" % frame[3])
						doRemoveJob = True
						zwChangePrimaryController(0, 0)
		elif frame[1] == FUNC_ID_ZW_SET_LEARN_MODE:
				if frame[3] == NODE_STATUS_LEARN_READY:
						log.info("FUNC_ID_ZW_SET_LEARN_MODE: NODE_STATUS_LEARN_READY: inclusion by node %i" % frame[4])
						doMarkFirstCallback = True
				elif frame[3] == NODE_STATUS_NODE_FOUND:
						log.info("FUNC_ID_ZW_SET_LEARN_MODE: NODE_STATUS_NODE_FOUND: node %i" % frame[4])
						if frame[5] > 0:
							parseNodeInfo(frame[6:6 + frame[5]])
				elif frame[3] == NODE_STATUS_ADDING_CONTROLLER:
						log.info("FUNC_ID_ZW_SET_LEARN_MODE: NODE_STATUS_ADDING_CONTROLLER: node %i" % frame[4])
				elif frame[3] == NODE_STATUS_PROTOCOL_DONE:
						log.info("FUNC_ID_ZW_SET_LEARN_MODE: NODE_STATUS_PROTOCOL_DONE")
						zwSetLearnMode(0)
				elif frame[3] == NODE_STATUS_DONE:
						log.info("FUNC_ID_ZW_SET_LEARN_MODE: NODE_STATUS_DONE")
						zwGetHomeId()
						zwGetControllerCapabilities()
						zwGetSUCNodeId()
						zwGetInitData()
						doRemoveJob = True
				elif frame[3] == NODE_STATUS_FAILED:
						log.info("FUNC_ID_ZW_SET_LEARN_MODE: NODE_STATUS_FAILED")
						doRemoveJob = True
				else:
						log.error("invalid FUNC_ID_ZW_SET_LEARN_MODE status 0x%02x" % frame[3])
						doRemoveJob = True
						zwSetLearnMode(0)
		elif frame[1] == FUNC_ID_ZW_REMOVE_FAILED_NODE_ID:
				if frame[3] == FAILED_NODE_OK:
						log.info("FUNC_ID_ZW_REMOVE_FAILED_NODE_ID: FAILED_NODE_OK")
				elif frame[3] == FAILED_NODE_REMOVED:
						log.info("FUNC_ID_ZW_REMOVE_FAILED_NODE_ID: FAILED_NODE_REMOVED")
				elif frame[3] == FAILED_NODE_NOT_REMOVED:
						log.info("FUNC_ID_ZW_REMOVE_FAILED_NODE_ID: FAILED_NODE_NOT_REMOVED")
				else:
						log.error("invalid FUNC_ID_ZW_REMOVE_FAILED_NODE_ID status 0x%02x" % frame[3])
				doRemoveJob = True
		elif frame[1] == FUNC_ID_ZW_REPLACE_FAILED_NODE:
				if frame[3] == FAILED_NODE_OK:
						log.info("FUNC_ID_ZW_REPLACE_FAILED_NODE: FAILED_NODE_OK")
						doRemoveJob = True
				elif frame[3] == FAILED_NODE_REPLACE:
						log.info("FUNC_ID_ZW_REPLACE_FAILED_NODE: FAILED_NODE_REPLACE: waiting for node information from new node")
						doMarkFirstCallback = True
				elif frame[3] == FAILED_NODE_REPLACE_DONE:
						log.info("FUNC_ID_ZW_REPLACE_FAILED_NODE: FAILED_NODE_REPLACE_DONE")
						doRemoveJob = True
				elif frame[3] == FAILED_NODE_REPLACE_FAILED:
						log.info("FUNC_ID_ZW_REPLACE_FAILED_NODE: FAILED_NODE_REPLACE_FAILED")
						doRemoveJob = True
				else:
						log.error("invalid FUNC_ID_ZW_REPLACE_FAILED_NODE status 0x%02x" % frame[3])
						doRemoveJob = True
		elif frame[1] == FUNC_ID_ZW_SET_SLAVE_LEARN_MODE:
				if frame[3] == ASSIGN_COMPLETE:
						log.info("FUNC_ID_ZW_SET_SLAVE_LEARN_MODE: ASSIGN_COMPLETE")
						doRemoveJob = True
				elif frame[3] == ASSIGN_NODEID_DONE:
						log.info("FUNC_ID_ZW_SET_SLAVE_LEARN_MODE: ASSIGN_NODEID_DONE: Original Node Id = %i, New Node Id = %i" % (frame[4], frame[5]))
						doRemoveJob = True
						log.todo("When this status is received the Slave Learn Mode is complete for all Slave Learn Modes except the VIRTUAL_SLAVE_LEARN_MODE_ENABLE mode.")
				elif frame[3] == ASSIGN_RANGE_INFO_UPDATE:
						log.info("FUNC_ID_ZW_SET_SLAVE_LEARN_MODE: ASSIGN_RANGE_INFO_UPDATE")
						doRemoveJob = True
				else:
						log.error("invalid FUNC_ID_ZW_SET_SLAVE_LEARN_MODE status 0x%02x" % frame[3])
						doRemoveJob = True
		elif frame[1] == FUNC_ID_APPLICATION_COMMAND_HANDLER:
				log.info("FUNC_ID_APPLICATION_COMMAND_HANDLER:")
				log.ident()
				if frame[5] == COMMAND_CLASS_CONTROLLER_REPLICATION:
						log.info("COMMAND_CLASS_CONTROLLER_REPLICATION")
						if frame[6] == CTRL_REPLICATION_TRANSFER_GROUP:
							# we simply ack the group information for now
							sendFunction((FUNC_ID_ZW_REPLICATION_COMMAND_COMPLETE,), REQUEST, 0, 0)
						else:
							# ack everything else, too
							sendFunction((FUNC_ID_ZW_REPLICATION_COMMAND_COMPLETE,), REQUEST, 0, 0)

				elif frame[5] == COMMAND_CLASS_MULTI_INSTANCE:
						log.info("COMMAND_CLASS_MULTI_INSTANCE")
						if frame[6] == MULTI_INSTANCE_REPORT:
							log.info("Got MULTI_INSTANCE_REPORT from node %i: Command Class 0x%02x, instance count: %i" % (frame[3], frame[7], frame[8]))
						else:
							log.todo("unhandled command type 0x%02x" % frame[6])
				elif frame[5] == COMMAND_CLASS_VERSION:
						log.info("COMMAND_CLASS_VERSION")
						if frame[6] == VERSION_REPORT:
							log.info("REPORT: Library type: %i, Protocol version: %i.%i, Application version: %i.%i" % tuple(frame[7:12]))
						else:
							log.todo("unhandled command type 0x%02x" % frame[6])
				elif frame[5] == COMMAND_CLASS_METER:
						log.info("COMMAND_CLASS_METER")
						if frame[6] == METER_REPORT:
							log.info("Got meter report from node %i" % frame[3])
							scale = (frame[8] & METER_REPORT_SCALE_MASK) >> METER_REPORT_SCALE_SHIFT
							precision = (frame[8] & METER_REPORT_PRECISION_MASK) >> METER_REPORT_PRECISION_SHIFT
							size = frame[8] & METER_REPORT_SIZE_MASK
							if size == 1:
									value = frame[9]
							elif size == 2:
									tmpval = (frame[9] << 8) + frame[10]
									value = tmpval
							else:
									value = (frame[9] << 24) + (frame[10] << 16) + (frame[11] << 8) + frame[12]
							log.info("METER DEBUG: precision: %i scale: %i size: %i value: %i" % (precision, scale, size, value))

							# meter type:
							if frame[7] == METER_REPORT_ELECTRIC_METER:
									if scale == 0:
										log.info("Electric meter measurement received: %f kWh" % value)
						else:
							log.todo("unhandled command type 0x%02x" % frame[6])
				elif frame[5] == COMMAND_CLASS_MANUFACTURER_SPECIFIC:
						log.info("COMMAND_CLASS_MANUFACTURER_SPECIFIC")
						if frame[6] == MANUFACTURER_SPECIFIC_REPORT:
							log.info("REPORT: Manufacture Id: %i/%i, Product type: %i/%i, Product Id: %i/%i" % tuple(frame[7:13]))
						else:
							log.todo("unhandled command type 0x%02x" % frame[6])
				elif frame[5] == COMMAND_CLASS_WAKE_UP:
						log.info("COMMAND_CLASS_WAKE_UP")
						if frame[6] == WAKE_UP_NOTIFICATION:
							# we got a wake up frame, make sure we remember the device does not always listen
							try:
								if ZWS.ZWNodeMap[frame[3]]:
									ZWS.ZWNodeMap[frame[3]].sleepingDevice = 1
									if ZWS.ZWNodeMap[frame[3]].typeGeneric == GENERIC_TYPE_SENSOR_MULTILEVEL:
										zwRequestMultilevelSensorReport(frame[3])

								zwBatteryGet(frame[3])

								# inject commands from the sleeping queue for this nodeid
								wakeupHandler(frame[3])

								if frame[2] & RECEIVE_STATUS_TYPE_BROAD:
									log.info("Got broadcast wakeup from node %i" % frame[3])
								else:
									log.info("Got unicast wakeup from node %i, doing WAKE_UP_NO_MORE_INFORMATION" % frame[3])
									sendFunction((FUNC_ID_ZW_SEND_DATA, frame[4], 2, COMMAND_CLASS_WAKE_UP, WAKE_UP_NO_MORE_INFORMATION, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)
							except KeyError:
								log.error("New node %i found (not in list)" % frame[3])
						else:
							log.todo("unhandled command type 0x%02x" % frame[6])
				elif frame[5] == COMMAND_CLASS_SENSOR_BINARY:
						log.info("COMMAND_CLASS_SENSOR_BINARY")
						if frame[6] == SENSOR_BINARY_REPORT:
							log.info("Got sensor report from node %i, level: %i" % (frame[3], frame[7]))
							is_requested_reply(frame[3], COMMAND_CLASS_SENSOR_BINARY, frame[7])
						else:
							log.todo("unhandled command type 0x%02x" % frame[6])
				elif frame[5] == COMMAND_CLASS_SENSOR_MULTILEVEL:
						log.info("COMMAND_CLASS_SENSOR_MULTILEVEL")
						if frame[6] == SENSOR_MULTILEVEL_REPORT:
							log.info("Got sensor report from node %i" % frame[3])
							log.ident()
							scale = (frame[8] & SENSOR_MULTILEVEL_REPORT_SCALE_MASK) >> SENSOR_MULTILEVEL_REPORT_SCALE_SHIFT
							precision = (frame[8] & SENSOR_MULTILEVEL_REPORT_PRECISION_MASK) >> SENSOR_MULTILEVEL_REPORT_PRECISION_SHIFT
							size = frame[8] & SENSOR_MULTILEVEL_REPORT_SIZE_MASK
							if size == 1:
								value = frame[9]
							elif size == 2:
								tmpval = (frame[9] << 8) + frame[10]
								value = tmpval
							else:  # size == 4
								value = (frame[9] << 24) + (frame[10] << 16) + (frame[11] << 8) + frame[12]
							log.info("MULTILEVEL: precision: %i scale: %i size: %i value: %i" % (precision, scale, size, value))

							# sensor type
							if frame[7] == SENSOR_MULTILEVEL_REPORT_GENERAL_PURPOSE_VALUE:
									if scale == 0:
										log.info("General purpose measurement value received: %i%%" % value)
									else:
										log.info("General purpose measurement value received: %i (dimensionless)" % value)
							elif frame[7] == SENSOR_MULTILEVEL_REPORT_LUMINANCE:
									if scale == 0:
										log.info("Luminance measurement received: %i%%" % value)
									else:
										log.info("Luminance measurement received: %i Lux" % value)
							elif frame[7] == SENSOR_MULTILEVEL_REPORT_POWER:
									if scale == 0:
										log.info("Power level measurement received: %i W" % value)
									else:
										log.info("Power level measurement received: %i" % value)
							elif frame[7] == SENSOR_MULTILEVEL_REPORT_CO2_LEVEL:
									log.info("CO2 level measurement received: %i ppm" % value)
							elif frame[7] == SENSOR_MULTILEVEL_REPORT_RELATIVE_HUMIDITY:
									log.info("Relative humidity measurement received: %i percent" % value)
							elif frame[7] == SENSOR_MULTILEVEL_REPORT_TEMPERATURE:
									if scale == 0:
										log.info("Temperature level measurement received: %i C" % value)
									else:
										log.info("Temperature level measurement received: %i F" % value)
							else:
									log.info("Sensor type 0x%02x not handled" % frame[7])
							log.deident()
							is_requested_reply(frame[3], COMMAND_CLASS_SENSOR_MULTILEVEL, value)
						else:
							log.todo("unhandled command type 0x%02x" % frame[6])
				elif frame[5] == COMMAND_CLASS_BASIC:
						log.info("COMMAND_CLASS_BASIC")
						if frame[6] == BASIC_REPORT:
							log.info("Got basic report from node %i, value: %i" % (frame[3], frame[7]))
							is_requested_reply(frame[3], COMMAND_CLASS_BASIC, frame[7])
						elif frame[6] == BASIC_SET:
							log.info("Got BASIC_SET from node %i, value %i" % (frame[3], frame[7]))
							ZWS.poll_callback_func(1, frame[3], ZWS.ournodeid, (frame[7],))
						elif frame[6] == SWITCH_MULTILEVEL_GET:
							log.info("Got BASIC_GET from node %i to node %i" % (frame[3], ZWS.ournodeid))
							reportVal = ZWS.get_virtual_func(frame[3], ZWS.ournodeid)
							if reportVal is not None:
								zwSendBasicReport(frame[3], reportVal)
						else:
							log.todo("Got COMMAND_CLASS_BASIC: 0x%02x, ignoring" % frame[6])
				elif frame[5] == COMMAND_CLASS_SWITCH_MULTILEVEL:
						log.info("COMMAND_CLASS_SWITCH_MULTILEVEL")
						if frame[6] == SWITCH_MULTILEVEL_REPORT:
							log.info("Got switch multilevel report from node %i, level: %i" % (frame[3], frame[7]))
							is_requested_reply(frame[3], COMMAND_CLASS_SWITCH_MULTILEVEL, frame[7])
						elif frame[6] == SWITCH_MULTILEVEL_SET:
							log.info("Got switch multilevel set from node %i, level: %i" % (frame[3], frame[7]))
							ZWS.poll_callback_func(1, frame[3], ZWS.ournodeid, (frame[3], frame[7]))
						elif frame[6] == SWITCH_MULTILEVEL_GET:
							log.info("Got SWITCH_MULTILEVEL_GET from node %i to node %i" % (frame[3], ZWS.ournodeid))
							reportVal = ZWS.get_virtual_func(frame[3], ZWS.ournodeid)
							if reportVal is not None:
								zwSendBasicReport(frame[3], reportVal)
						else:
							log.todo("unhandled command type 0x%02x" % frame[6])
				elif frame[5] == COMMAND_CLASS_SWITCH_ALL:
						log.info("COMMAND_CLASS_SWITCH_ALL")
						if frame[6] == SWITCH_ALL_ON:
							log.info("Got switch all ON from node %i" % frame[3])
							ZWS.poll_callback_func(6, frame[3], 0, (0xff,))
						elif frame[6] == SWITCH_ALL_OFF:
							log.info("Got switch all OFF from node %i" % frame[3])
							ZWS.poll_callback_func(6, frame[3], 0, (0x00,))
						else:
							log.todo("unhandled command type 0x%02x" % frame[6])
				elif frame[5] == COMMAND_CLASS_ALARM:
						log.info("COMMAND_CLASS_ALARM")
						if frame[6] == ALARM_REPORT:
							log.info("Got ALARM from node %i, type: %i, level: %i" % (frame[3], frame[7], frame[8]))
							ZWS.poll_callback_func(8, frame[3], 0, frame[7:9])
						else:
							log.todo("unhandled command type 0x%02x" % frame[6])
				elif frame[5] == COMMAND_CLASS_SENSOR_ALARM:
						log.info("COMMAND_CLASS_SENSOR_ALARM")
						if frame[6] == SENSOR_ALARM_REPORT:
							log.info("Got ALARM from node %i" % frame[3])
							ZWS.poll_callback_func(8, frame[3], 0, frame[7:12])
						else:
							log.todo("unhandled command type 0x%02x" % frame[6])
				elif frame[5] == COMMAND_CLASS_CLIMATE_CONTROL_SCHEDULE:
						log.info("COMMAND_CLASS_CLIMATE_CONTROL_SCHEDULE")
						if frame[6] == SCHEDULE_GET:
							log.info("Got SCHEDULE_GET from node %i for day: %i" % (frame[3], frame[7]))
							log.todo("unhandled command type SCHEDULE_GET")
						else:
							log.todo("unhandled command type 0x%02x" % frame[6])
				elif frame[5] == COMMAND_CLASS_ASSOCIATION:
						log.info("COMMAND_CLASS_ASSOCIATION")
						if frame[6] == ASSOCIATION_REPORT:
							tmp_group = frame[7]
							log.info("Associations for group: %i" % tmp_group)
							log.info("Max nodes supported: %i" % frame[8])
							log.info("Reports to follow: %i" % frame[9])
							if len(frame) > 10:
								log.info("Nodes: %s" % ', '.join(("%i" % frame[i]) for i in range(10, len(frame))))
						else:
							log.todo("unhandled command type 0x%02x" % frame[6])
				elif frame[5] == COMMAND_CLASS_MULTI_CMD:
						log.info("COMMAND_CLASS_MULTI_CMD")
						if frame[6] == MULTI_CMD_ENCAP:
							log.info("Got encapsulated multi command from node %i" % frame[3])
							# iterate over commands
							offset = 8
							for i in range(0, frame[7]):
								log.info("COMMAND LENGTH: %i, CLASS: 0x%02x" % (frame[offset], frame[offset + 1]))
								if frame[offset + 1] == COMMAND_CLASS_BATTERY:
										if BATTERY_REPORT == frame[offset + 2]:
											log.info("COMMAND_CLASS_BATTERY:BATTERY_REPORT: Battery level: %i" % frame[offset + 3])
											ZWS.poll_callback_func(7, frame[3], 0, (frame[offset + 3],))
								elif frame[offset + 1] == COMMAND_CLASS_CLIMATE_CONTROL_SCHEDULE:
										if SCHEDULE_CHANGED_GET == frame[offset + 2]:
											log.info("COMMAND_CLASS_CLIMATE_CONTROL_SCHEDULE:SCHEDULE_CHANGED_GET")
										if SCHEDULE_OVERRIDE_GET == frame[offset + 2]:
											log.info("COMMAND_CLASS_CLIMATE_CONTROL_SCHEDULE:SCHEDULE_OVERRIDE_GET")
										if SCHEDULE_OVERRIDE_REPORT == frame[offset + 2]:
											log.info("COMMAND_CLASS_CLIMATE_CONTROL_SCHEDULE:SCHEDULE_OVERRIDE_REPORT: Setback state: 0x%02x" % frame[offset + 4])
											# update basic device state in map
											if ZWS.ZWNodeMap[frame[3]]:  # todo try/except KeyError:
												ZWS.ZWNodeMap[frame[3]].stateBasic = 0xff if frame[offset + 4] == 0 else 0x0
								elif frame[offset + 1] == COMMAND_CLASS_CLOCK:
										if CLOCK_GET == frame[offset + 2]:
											log.info("COMMAND_CLASS_CLOCK:CLOCK_GET")
								elif frame[offset + 1] == COMMAND_CLASS_WAKE_UP:
										if WAKE_UP_NOTIFICATION == frame[offset + 2]:
											log.info("COMMAND_CLASS_WAKE_UP:WAKE_UP_NOTIFICATION")
								else:
										pass
								offset += frame[offset] + 1

							# ## This is from Harald lein code: sendFunction( (FUNC_ID_ZW_SEND_DATA, frame[3], 19, COMMAND_CLASS_MULTI_CMD, MULTI_CMD_ENCAP, 4, 4, COMMAND_CLASS_CLOCK, CLOCK_REPORT, ( (7 if timestruct.tm_wday == 0 else timestruct.tm_wday) << 5 ) | timestruct.tm_hour, 0 if timestruct.tm_min == 60 else timestruct.tm_min, 3, COMMAND_CLASS_CLIMATE_CONTROL_SCHEDULE, SCHEDULE_CHANGED_REPORT, 17, 3, COMMAND_CLASS_BASIC, BASIC_SET, basic_state, 2, COMMAND_CLASS_WAKE_UP, WAKE_UP_NO_MORE_INFORMATION, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)
						else:
							log.todo("unhandled command type 0x%02x" % frame[6])
				elif frame[5] == COMMAND_CLASS_BATTERY:
						log.info("COMMAND_CLASS_BATTERY")
						if frame[6] == BATTERY_REPORT:
							log.info("Battery = %i%%" % frame[7])
							ZWS.poll_callback_func(7, frame[3], 0, (frame[7],))
						else:
							log.todo("unhandled command type 0x%02x" % frame[6])
				else:
						log.info("Function not implemented - unhandled command class")
				log.deident()
		elif frame[1] == FUNC_ID_ZW_APPLICATION_UPDATE:
				if frame[2] == UPDATE_STATE_NODE_INFO_RECEIVED:
						log.info("FUNC_ID_ZW_APPLICATION_UPDATE: UPDATE_STATE_NODE_INFO_RECEIVED received from node %i" % frame[3])

						if zwIsSleepingNode(frame[3]):
							zwBatteryGet(frame[3])
							wakeupHandler(frame[3])

						parseNodeType(frame[5:8])
						parseNodeInfo(frame[8:8 + frame[4] - 3])

				elif frame[2] == UPDATE_STATE_NODE_INFO_REQ_FAILED:
						log.info("FUNC_ID_ZW_APPLICATION_UPDATE: UPDATE_STATE_NODE_INFO_REQ_FAILED received")
				elif frame[2] == UPDATE_STATE_ADD_DONE:
						log.info("** Network change **: ID %i was assigned to a new Z-Wave node" % frame[3])

						newNode = ZWNode()
						newNode.typeBasic = frame[5]
						newNode.typeGeneric = frame[6]
						newNode.typeSpecific = frame[7]

						parseNodeType(frame[5:8])
						parseNodeInfo(frame[8:8 + frame[4] - 3])

						ZWS.ZWNodeMap[frame[3]] = newNode
				elif frame[2] == UPDATE_STATE_DELETE_DONE:
						log.info("Network change: Z-Wave node %i was removed" % frame[3])
				elif frame[2] == UPDATE_STATE_SUC_ID:
						log.info("New SUC assigned: %i" % frame[3])
				else:
						log.todo("unhandled FUNC_ID_ZW_APPLICATION_UPDATE frame: %s" % hexList(frame))
		elif frame[1] == FUNC_ID_APPLICATION_SLAVE_COMMAND_HANDLER:
				log.info("Slave Command handler from %i to %i" % (frame[4], frame[3]))
				log.ident()

				if frame[6] == COMMAND_CLASS_BASIC:
					if frame[7] == BASIC_SET:
						log.info("Got BASIC_SET from node %i to node %i, value: %i" % (frame[4], frame[3], frame[8]))
						ZWS.poll_callback_func(1, frame[4], frame[3], (frame[8],))
					elif frame[7] == BASIC_GET:
						log.info("Got BASIC_GET from node %i to node %i" % (frame[4], frame[3]))
						reportVal = ZWS.get_virtual_func(frame[3], frame[4])
						if reportVal is not None:
							zwSendBasicReport(frame[4], reportVal)
					else:
						log.error("invalid slave COMMAND_CLASS_BASIC command 0x%02x" % frame[7])
				elif frame[6] == COMMAND_CLASS_SWITCH_MULTILEVEL:
					if frame[7] == SWITCH_MULTILEVEL_REPORT_BEGIN:
						if frame[8] == SWITCH_MULTILEVEL_REPORT_BEGIN_UP:
							log.info("Got SWITCH_MULTILEVEL_REPORT_BEGIN direction: up")
							ZWS.poll_callback_func(3, frame[4], frame[3], ())
						elif frame[8] == SWITCH_MULTILEVEL_REPORT_BEGIN_DOWN:
							log.info("Got SWITCH_MULTILEVEL_REPORT_BEGIN direction: down")
							ZWS.poll_callback_func(4, frame[4], frame[3], ())
						else:
							log.error("invalid slave SWITCH_MULTILEVEL_REPORT_BEGIN parameter 0x%02x" % frame[8])
					elif frame[7] == SWITCH_MULTILEVEL_REPORT_END:
						log.info("Got SWITCH_MULTILEVEL_REPORT_END")
						ZWS.poll_callback_func(5, frame[4], frame[3], ())
					elif frame[7] == SWITCH_MULTILEVEL_GET:
						log.info("Got SWITCH_MULTILEVEL_GET from node %i to node %i" % (frame[4], frame[3]))
						reportVal = ZWS.get_virtual_func(frame[3], frame[4])
						if reportVal is not None:
							zwSendBasicReport(frame[4], reportVal)
					else:
						log.error("invalid slave COMMAND_CLASS_SWITCH_MULTILEVEL command 0x%02x" % frame[7])
				elif frame[6] == COMMAND_CLASS_WAKE_UP:
					log.info("COMMAND_CLASS_WAKE_UP")
					if frame[7] == WAKE_UP_NOTIFICATION:
						# we got a wake up frame, make sure we remember the device does not always listen
						try:
							if ZWS.ZWNodeMap[frame[4]]:
								ZWS.ZWNodeMap[frame[4]].sleepingDevice = 1
								if ZWS.ZWNodeMap[frame[4]].typeGeneric == GENERIC_TYPE_SENSOR_MULTILEVEL:
									zwRequestMultilevelSensorReport(frame[4])

							zwBatteryGet(frame[4])

							# inject commands from the sleeping queue for this nodeid
							wakeupHandler(frame[4])

							if frame[2] & RECEIVE_STATUS_TYPE_BROAD:
								log.info("Got broadcast wakeup from node %i" % frame[4])
							else:
								log.info("Got unicast wakeup from node %i, doing WAKE_UP_NO_MORE_INFORMATION" % frame[4])
								sendFunction((FUNC_ID_ZW_SEND_DATA, frame[4], 2, COMMAND_CLASS_WAKE_UP, WAKE_UP_NO_MORE_INFORMATION, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)
						except KeyError:
							log.error("New node %i found (not in list)" % frame[3])
					else:
						log.todo("unhandled command type 0x%02x" % frame[7])
				elif frame[6] == COMMAND_CLASS_ALARM:
					if frame[7] == ALARM_REPORT:
						log.info("Got ALARM from node %i, type: %i, level: %i" % (frame[4], frame[8], frame[9]))
						ZWS.poll_callback_func(8, frame[4], frame[3], frame[8:10])
					else:
						log.error("unhandled command type 0x%02x" % frame[7])
				elif frame[6] == COMMAND_CLASS_SENSOR_ALARM:
					log.info("COMMAND_CLASS_SENSOR_ALARM")
					if frame[7] == SENSOR_ALARM_REPORT:
						log.info("Got ALARM from node %i" % frame[4])
						ZWS.poll_callback_func(8, frame[4], 0, frame[8:13])
					else:
						log.todo("unhandled command type 0x%02x" % frame[7])
				else:
						log.error("unhandled command class in slave handler: 0x%02x" % frame[6])
				log.deident()
		elif frame[1] == FUNC_ID_ZW_REQUEST_NODE_NEIGHBOR_UPDATE:
				if frame[3] == NODE_NEIGHBOR_UPDATE_STARTED:
					log.info("Neighbor update started")
					doMarkFirstCallback = True
				elif frame[3] == NODE_NEIGHBOR_UPDATE_DONE:
					log.info("Neighbor update done")
					doRemoveJob = True
				elif frame[3] == NODE_NEIGHBOR_UPDATE_FAILED:
					log.error("Neighbor update failed")
					doRemoveJob = True
				else:
					log.todo("unknown respose to FUNC_ID_ZW_REQUEST_NODE_NEIGHBOR_UPDATE: 0x%02x" % frame[3])
					doRemoveJob = True
		elif frame[1] == FUNC_ID_ZW_REQUEST_NETWORK_UPDATE:
				if frame[3] == ZW_SUC_UPDATE_DONE:
					log.info("Network update done")
				elif frame[3] == ZW_SUC_UPDATE_ABORT:
					log.info("Network update failed due to some error")
				elif frame[3] == ZW_SUC_UPDATE_WAIT:
					log.info("Network update failed: SUC is busy")
				elif frame[3] == ZW_SUC_UPDATE_DISABLED:
					log.info("Network update failed: SUC is disabled")
				elif frame[3] == ZW_SUC_UPDATE_OVERFLOW:
					log.info("Network update failed due to too much changes since last update: replication is needed")
				else:
					log.todo("unknown response to FUNC_ID_ZW_REQUEST_NETWORK_UPDATE: 0x%02x" % frame[3])
				doRemoveJob = True
		elif frame[1] == FUNC_ID_ZW_SEND_NODE_INFORMATION:
				if frame[3] == TRANSMIT_COMPLETE_NO_ACK:
					log.info("No ACK received for FUNC_ID_ZW_SEND_NODE_INFORMATION")
				elif frame[3] == TRANSMIT_COMPLETE_FAIL:
					log.info("Can not send FUNC_ID_ZW_SEND_NODE_INFORMATION: network is busy")
				elif frame[3] == TRANSMIT_COMPLETE_NOROUTE:
					log.info("Can not send FUNC_ID_ZW_SEND_NODE_INFORMATION: no route")
				elif frame[3] == TRANSMIT_COMPLETE_OK:
					pass
				else:
					log.todo("unknown response to FUNC_ID_ZW_SEND_NODE_INFORMATION: 0x%02x" % frame[3])
				doRemoveJob = True
		elif frame[1] == FUNC_ID_ZW_SET_SUC_NODE_ID:
				if frame[3] == ZW_SUC_SET_SUCCEEDED:
					log.info("SUC set succeeded")
				elif frame[3] == ZW_SUC_SET_FAILED:
					log.info("SUC set failed")
				else:
					log.todo("unknown response to FUNC_ID_ZW_SET_SUC_NODE_ID: 0x%02x" % frame[3])
				doRemoveJob = True
		elif frame[1] == FUNC_ID_ZW_SET_DEFAULT:
				log.info("Controller was set to default")
				doRemoveJob = True
		else:
				log.todo("handle request for 0x%02x: %s" % (frame[1], hexList(frame)))

		if doMarkFirstCallback and cbk is not None:
			markFirstCallback(cbk)

		if doRemoveJob and cbk is not None:
			removeJob(cbk)
	else:
		# should not happen
		pass

def isAwaitingAck():
	return len(filter(lambda(x): ZWS.ZWSendQueue[x].sent and ZWS.ZWSendQueue[x].await_ack, range(len(ZWS.ZWSendQueue))))

def awaitingResponse():
	try:
		return filter(lambda(x): ZWS.ZWSendQueue[x].sent and not ZWS.ZWSendQueue[x].await_ack and ZWS.ZWSendQueue[x].await_response, range(len(ZWS.ZWSendQueue)))[0]
	except:
		return None

def awaitingCallback(Type, cbkId):
	try:
		return filter(lambda(x): ZWS.ZWSendQueue[x].sent and not ZWS.ZWSendQueue[x].await_ack and not ZWS.ZWSendQueue[x].await_response and ZWS.ZWSendQueue[x].callbackid == cbkId and ZWS.ZWSendQueue[x].callback_type == Type, range(len(ZWS.ZWSendQueue)))
	except:
		return None

# this function is always called outside of queue locked block
def markFirstCallback(n):
	ZWS.mutexSendQueue.acquire()
	ZWS.ZWSendQueue[n].first_callback_received = 1
	ZWS.ZWSendQueue[n].timeout = ZWS.moreCallbackTimeout
	ZWS.mutexSendQueue.release()

# this function is always called outside of queue locked block
def markResponse(n):
		ZWS.mutexSendQueue.acquire()
		ZWS.ZWSendQueue[n].await_response = 0
		# got response for a job: remove the job if no callback is needed
		if ZWS.ZWSendQueue[n].callbackid == 0 :
			removeJob(n, False)
		else:
			ZWS.ZWSendQueue[n].timeout = ZWS.firstCallbackTimeout
		ZWS.mutexSendQueue.release()

# this function is always called inside queue locked block
def ackJob(n):
	if not ZWS.ZWSendQueue[n].callbackid and not ZWS.ZWSendQueue[n].await_response:
		removeJob(n, False)
	else:
		ZWS.ZWSendQueue[n].await_ack = 0
		if ZWS.ZWSendQueue[n].await_response:
			ZWS.ZWSendQueue[n].timeout = ZWS.responseTimeout
		else:  # ZWS.ZWSendQueue[n].callbackid > 0
			ZWS.ZWSendQueue[n].timeout = ZWS.firstCallbackTimeout

# this function is always called inside queue locked block
def resendNAck():
	if len(filter(lambda(x): ZWS.ZWSendQueue[x].sent and ZWS.ZWSendQueue[x].await_ack, range(len(ZWS.ZWSendQueue)))) == 0:
		log.crit("There are no job waiting for ACK")
	elif len(filter(lambda(x): ZWS.ZWSendQueue[x].sent and ZWS.ZWSendQueue[x].await_ack, range(len(ZWS.ZWSendQueue)))) > 1:
		log.crit("There are more than one job waiting for ACK")
	else:
		ZWS.ZWSendQueue[filter(lambda(x): ZWS.ZWSendQueue[x].sent and ZWS.ZWSendQueue[x].await_ack, range(len(ZWS.ZWSendQueue)))[0]].sent = 0

def resendJob(n, lock=True):
	if lock:
		ZWS.mutexSendQueue.acquire()
	if ZWS.ZWSendQueue[n].sendcount > ZWS.resend_count:
		log.warn("Dropping command: too much resends")
		removeJob(n, False)
	else:
		ZWS.ZWSendQueue[n].timeout = ZWS.ackTimeout
		ZWS.ZWSendQueue[n].await_ack = 1
		ZWS.ZWSendQueue[n].await_response = ZWS.ZWSendQueue[n].response
		ZWS.ZWSendQueue[n].sent = 0
		ZWS.ZWSendQueue[n].first_callback_received = 0
	if lock:
		ZWS.mutexSendQueue.release()

def removeJob(n, lock=True):
	if lock:
		ZWS.mutexSendQueue.acquire()
	ZWS.ZWSendQueue.pop(n)
	log.zwstack("Removing job")
	if lock:
		ZWS.mutexSendQueue.release()

# this is the function for our reader/writer thread, handles frame flow and read/write
def receiveFunction():
	log.info("receiveFunction started")
	queue_trace = 0
	while 1:
		# # Debug
		try:
			queue_trace = (queue_trace + 1) % (5 / ZWS.dt)
		except:
			queue_trace = 0
		if len(ZWS.ZWSendQueue) > 0 and queue_trace == 0:
			for n in range(len(ZWS.ZWSendQueue)):
				log.zwstack(" -- callback 0x%02x, sent %i, await_ack %i, await_respose %i, response %i, first_callback_received %i, timeout %i " % (ZWS.ZWSendQueue[n].callbackid, ZWS.ZWSendQueue[n].sent, ZWS.ZWSendQueue[n].await_ack, ZWS.ZWSendQueue[n].await_response, ZWS.ZWSendQueue[n].response, ZWS.ZWSendQueue[n].first_callback_received, ZWS.ZWSendQueue[n].timeout))

		# read a byte from the serial port
		if ZWS.serialPort.inWaiting() > 0:
			mybuf1 = ZWS.serialPort.Read(1)
			if mybuf1[0] == SOF:
					# if we await an ack instead, trigger resend to be sure
					if  len(ZWS.ZWSendQueue) > 0 and isAwaitingAck():
						log.error("SOF Found while awaiting ack...")
						resendNAck()

					# read the length byte
					mybuf2 = ZWS.serialPort.Read(1)

					# read the rest of the frame
					mybuf3 = ZWS.serialPort.Read(mybuf2[0])

					mybuf = mybuf1 + mybuf2 + mybuf3
					log.receive("%s" % hexList(mybuf))

					# verify checksum
					if mybuf[len(mybuf) - 1] == checksum(mybuf[1:-1]):
						ZWS.serialPort.Write((ACK,))
						try:
							decodeFrame(mybuf[2:-1])
						except Exception, inst:
							log.exception(inst, "Decode frame: %s" % hexList(mybuf[2:-1]))
					else:
						log.crit("Checksum incorrect - sending NAK")
						ZWS.serialPort.Write((NAK,))
			elif mybuf1[0] == CAN:
					log.receive("CAN RECEIVED")
					resendNAck()
			elif mybuf1[0] == NAK:
					log.receive("NAK RECEIVED")
					resendNAck()
			elif mybuf1[0] == ACK:
					log.receive("ACK RECEIVED")
					# if we await an ack pop the command, it got an ACK
					ZWS.mutexSendQueue.acquire()
					if len(ZWS.ZWSendQueue) > 0:
						ack_jobs = filter(lambda(x): ZWS.ZWSendQueue[x].sent and ZWS.ZWSendQueue[x].await_ack, range(len(ZWS.ZWSendQueue)))
						if len(ack_jobs) == 0:
							log.crit("There is no job waiting for ACK")
						elif len(ack_jobs) > 1:
							log.crit("There are more than one job waiting for ACK")
						else:
							ackJob(ack_jobs[0])
					else:
						log.crit("To late ACK !!")
					ZWS.mutexSendQueue.release()
			else:
					log.crit("ERROR! Out of frame flow!!")
		else:
			# nothing received, let's see if there is a job to send
			ZWS.mutexSendQueue.acquire()
			if len(ZWS.ZWSendQueue) > 0:
				# search for new job to dequeue:
				next_job = None
				awaiting_cbk_jobs = 0
				for n in range(len(ZWS.ZWSendQueue)):
					if awaiting_cbk_jobs >= ZWS.awaiting_cbk_jobs:
						break  # too much jobs awaiting for callback
					if ZWS.ZWSendQueue[n].sent:
						if ZWS.ZWSendQueue[n].await_ack or ZWS.ZWSendQueue[n].await_response:
							break  # there is a job awaiting for for ACK or RESPONSE
						else:
							awaiting_cbk_jobs += 1
					else:
						next_job = n
						break

				if next_job is not None:
					# we are not waiting for ack/response: send the next job
					log.send("Sending job (cb 0x%02x) - %s" % (ZWS.ZWSendQueue[next_job].callbackid, ZWS.ZWSendQueue[next_job].buffer))

					ZWS.ZWSendQueue[next_job].sent = 1
					ZWS.ZWSendQueue[next_job].sendcount += 1
					ZWS.serialPort.Write(ZWS.ZWSendQueue[next_job].buffer)

				# reverse list of jobs awaiting for ack/response/first callback (reverse not to break the for loop)
				waiting_jobs = filter(lambda(x): ZWS.ZWSendQueue[x].sent, range(len(ZWS.ZWSendQueue)))
				waiting_jobs.reverse()
				if waiting_jobs is not None:
					for n in waiting_jobs:
						ZWS.ZWSendQueue[n].timeout -= ZWS.dt
						if ZWS.ZWSendQueue[n].timeout <= 0:
							if ZWS.ZWSendQueue[n].await_ack:
								log.warn("No ACK received before timeout")
								resendJob(n, False)
							elif ZWS.ZWSendQueue[n].await_response:
								log.warn("No RESPONSE received before timeout")
								resendJob(n, False)
							elif ZWS.ZWSendQueue[n].callbackid > 0 and not ZWS.ZWSendQueue[n].first_callback_received:
								log.warn("No callback received before timeout")
								resendJob(n, False)
							else:
								log.warn("Job not removed before timeout (awaiting for more callbacks?)")
								removeJob(n, False)
			ZWS.mutexSendQueue.release()

		time.sleep(ZWS.dt)

def waitQueue():
	while 1:
		ZWS.mutexSendQueue.acquire()
		qLen = len(ZWS.ZWSendQueue)
		ZWS.mutexSendQueue.release()
		if qLen == 0:
			return
		time.sleep(ZWS.dt)

# prepare the job
# must have a mutex lock around the call of this function!
def prepareJob(Buffer, Type, response, callback):
	newJob = ZWJob()

	newJob.await_ack = 1
	newJob.await_response = response
	newJob.response = response
	newJob.sendcount = 0
	newJob.sent = 0
	newJob.first_callback_received = 0
	newJob.timeout = ZWS.ackTimeout

	newJob.buffer.append(SOF)
	newJob.buffer.append(len(Buffer) + 2 + (1 if callback else 0))
	newJob.buffer.append(Type)
	newJob.buffer[len(newJob.buffer):] = Buffer
	newJob.len = len(Buffer) + 4 + 1 if callback else 0
	if callback:
		if ZWS.callbackid > 255 or ZWS.callbackid == 0:
			ZWS.callbackid = 1
		newJob.buffer.append(ZWS.callbackid)
		newJob.callbackid = ZWS.callbackid
		newJob.callback_type = Buffer[0]
		ZWS.callbackid += 1
	else:
		newJob.callbackid = 0
		newJob.callback_type = 0

	newJob.buffer.append(checksum(newJob.buffer[1:]))

	return newJob

def isCapable(func):
	if func == FUNC_ID_SERIAL_API_GET_CAPABILITIES:
		# Allow request for capabilities
		return True
	elif func in ZWS.capabilities:
		return True
	else:
		func_strs = filter(lambda(y): y[0:8] == 'FUNC_ID_' and eval(y) == func, globals())
		if len(func_strs) == 0:
			log.info("Controller does not support undefined FUNC_ID 0x%02x" % func)
		elif len(func_strs) == 1:
			log.info("Controller does not support function %s" % func_strs[0])
		else:
			log.error("Two FUNC_ID are defined for the same unsupported by controller function 0x%02x" % func)

		return False

# adds a zwave job to the queue
def sendFunction(Buffer, Type, response, callback):
	log.zwstack("Adding job")
	if not isCapable(Buffer[0]):
		log.info("Job was not queued")
		return
	ZWS.mutexSendQueue.acquire()
	newJob = prepareJob(Buffer, Type, response, callback)
	ZWS.ZWSendQueue.append(newJob)
	ZWS.mutexSendQueue.release()

# adds a zwave job to the wake up queue
def sendFunctionSleeping(nodeid, Buffer, Type, response, callback):
	if zwIsSleepingNode(nodeid):
		log.zwstack("Adding job to sleeping queue")
		if not isCapable(Buffer[0]):
			log.info("Job was not queued")
			return
		ZWS.mutexSendQueue.acquire()
		newJob = prepareJob(Buffer, Type, response, callback)
		newSleepJob = ZWSleepJob()
		newSleepJob.nodeid = nodeid
		newSleepJob.job = newJob
		ZWS.ZWWakeupQueue.append(newSleepJob)
		ZWS.mutexSendQueue.release()
	else:
		sendFunction(Buffer, Type, response, callback)

# check if device powers down the rf part to save power
def zwIsSleepingNode(node_id):
	rvalue = 0
	# verify if device is battery powered
	ZWS.mutexSendQueue.acquire()
	try:
		if ZWS.ZWNodeMap[node_id]:
			if ZWS.ZWNodeMap[node_id].sleepingDevice == 1:
				rvalue = 1
	except KeyError:
		log.error("New node %i found (not in list)" % node_id)
	ZWS.mutexSendQueue.release()
	return rvalue

def wakeupHandler(node_id):
	log.zwstack("Running wakeupHandler for node %i" % node_id)

	wakeupQueueIt = filter(lambda q: q.nodeid == node_id, ZWS.ZWWakeupQueue)
	for wq in wakeupQueueIt:
		log.info("Moving job from wakeup to send queue")
		ZWS.mutexSendQueue.acquire()
		ZWS.ZWSendQueue.append(wq.job)
		ZWS.ZWWakeupQueue.remove(wq)
		ZWS.mutexSendQueue.release()

def parseNodeType(nodetype):
	log.ident()

	b_type = filter(lambda(y): y[0:11] == 'BASIC_TYPE_' and eval(y) == nodetype[0], globals())
	if len(b_type) == 0:
		log.info("undefined BASIC_TYPE_ 0x%02x" % nodetype[0])
	elif len(b_type) == 1:
		log.info(b_type[0])
	else:
		log.error("Two BASIC_TYPE_ are defined for the same value 0x%02x" % nodetype[0])

	g_type = filter(lambda(y): y[0:13] == 'GENERIC_TYPE_' and eval(y) == nodetype[1], globals())
	if len(g_type) == 0:
		log.info("undefined GENERIC_TYPE_ 0x%02x" % nodetype[1])
	elif len(g_type) == 1:
		log.info(g_type[0])
	else:
		log.error("Two GENERIC_TYPE_ are defined for the same value 0x%02x" % nodetype[1])

	log.info("SPECIFIC TYPE: 0x%02x" % nodetype[2])
	log.deident()

def parseNodeInfo(nodeinfo):
	log.ident()
	log.info("Supported command classes:")
	log.ident()
	for i in range(len(nodeinfo)):
		if nodeinfo[i] == COMMAND_CLASS_MARK:
			log.deident()
			log.info("Can control the following command classes:")
			log.ident()
			continue

		cmd_cls = filter(lambda(y): y[0:14] == 'COMMAND_CLASS_' and eval(y) == nodeinfo[i], globals())
		if len(cmd_cls) == 0:
			log.info("undefined COMMAND_CLASS_ 0x%02x" % nodeinfo[i])
		elif len(cmd_cls) == 1:
			log.info(cmd_cls[0])
		else:
			log.error("Two COMMAND_CLASS_ are defined for the same value 0x%02x" % nodeinfo[i])
	log.deident()
	log.deident()


####################################################################################################

# used to reset the controller and remove it from the z-wave network
def zwSetDefault():
	log.info("Reset controller and erase all node information")
	sendFunction((FUNC_ID_ZW_SET_DEFAULT,), REQUEST, 0, 1)

# add a node to the network
def zwAddNodeToNetwork(startstop, highpower):
	if startstop:
		log.info("Adding new node - start")
		sendFunction((FUNC_ID_ZW_ADD_NODE_TO_NETWORK, MODE_NODE_ANY | (MODE_NODE_OPTION_HIGH_POWER if highpower else 0x00)), REQUEST, 0, 1)
	else:
		log.info("Adding new node - end")
		sendFunction((FUNC_ID_ZW_ADD_NODE_TO_NETWORK, MODE_NODE_STOP), REQUEST, 0, 0)

# add new controller as primary
def zwChangePrimaryController(startstop, highpower):
	if startstop:
		log.info("Changing primary controller - start")
		sendFunction((FUNC_ID_ZW_CONTROLLER_CHANGE, MODE_NODE_CONTROLLER | (MODE_NODE_OPTION_HIGH_POWER if highpower else 0x00)), REQUEST, 0, 1)
	else:
		log.info("Changing primary controller - end")
		sendFunction((FUNC_ID_ZW_CONTROLLER_CHANGE, MODE_NODE_STOP), REQUEST, 0, 0)

# set learn mode
def zwSetLearnMode(startstop):
	log.info("Setting Learn Mode %s" % ("ON" if startstop else "OFF"))
	sendFunction((FUNC_ID_ZW_SET_LEARN_MODE, 1 if startstop else 0), REQUEST, 0, 1)

# remove a node from the network
def zwRemoveNodeFromNetwork(startstop):
	if startstop:
		log.info("Removing node - start")
		sendFunction((FUNC_ID_ZW_REMOVE_NODE_FROM_NETWORK, MODE_NODE_ANY), REQUEST, 0, 1)
	else:
		log.info("Removing node - end")
		sendFunction((FUNC_ID_ZW_REMOVE_NODE_FROM_NETWORK, MODE_NODE_STOP), REQUEST, 0, 0)

# remove a failed node from the network
def zwRemoveFailedNode(nodeid):
	log.info("Removing failed node %i" % nodeid)
	sendFunction((FUNC_ID_ZW_REMOVE_FAILED_NODE_ID, nodeid), REQUEST, 1, 1)

# replace failed node
def zwReplaceFailedNode(nodeid):
	log.info("Removing failed node %i" % nodeid)
	sendFunction((FUNC_ID_ZW_REPLACE_FAILED_NODE, nodeid), REQUEST, 1, 1)

# test if node is failed
def zwIsFailedNode(nodeid):
	sendFunction((FUNC_ID_ZW_IS_FAILED_NODE, nodeid), REQUEST, 1, 0)

# add a slave node to the network
def zwAddSlaveNodeToNetwork():
	log.info("Adding new node - start")
	sendFunction((FUNC_ID_ZW_SET_SLAVE_LEARN_MODE, 0, SLAVE_LEARN_MODE_ADD), REQUEST, 1, 1)

# remove a slave node from the network
def zwRemoveSlaveNodeFromNetwork(nodeId):
	log.info("Removing slave node")
	sendFunction((FUNC_ID_ZW_SET_SLAVE_LEARN_MODE, nodeId, SLAVE_LEARN_MODE_REMOVE), REQUEST, 1, 1)

# set slave learn mode
def zwSetSlaveLearnMode(node_id, enable):
	log.info("Setting Slave Learn Mode to %s" % ("enable" if enable else "disable"))
	sendFunction((FUNC_ID_ZW_SET_SLAVE_LEARN_MODE, node_id, SLAVE_LEARN_MODE_ENABLE if enable else SLAVE_LEARN_MODE_DISABLE), REQUEST, 1, 1)

# send slave node protocol information
def zwSendSlaveNodeProtocolInfo(node_id, dst_node_id):
	sendFunction((FUNC_ID_ZW_SEND_SLAVE_NODE_INFO, node_id, dst_node_id, TRANSMIT_OPTION_NONE), REQUEST, 1, 1)

# send my node information
def zwSendMyNodeProtocolInfo(node_id):
	sendFunction((FUNC_ID_ZW_SEND_NODE_INFORMATION, node_id, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 0, 1)

# get neighbor count
def zwGetNeighborCount(node_id):
	sendFunction((FUNC_ID_ZW_GET_NEIGHBOR_COUNT, node_id), REQUEST, 1, 0)

# are nodes neighbours
def zwAreNodesNeighbours(node_id_a, node_id_b):
	sendFunction((FUNC_ID_ZW_ARE_NODES_NEIGHBOURS, node_id_a, node_id_b), REQUEST, 1, 0)

# get node neighbours
def zwGetRoutingInfo(node_id, remove_bad, remove_repeaters):
	sendFunction((FUNC_ID_GET_ROUTING_TABLE_LINE, node_id, 1 if remove_bad else 0, 1 if remove_repeaters else 0), REQUEST, 1, 0)

# get all virtual nodes
def zwGetVirtualNodes():
	sendFunction((FUNC_ID_ZW_GET_VIRTUAL_NODES,), REQUEST, 1, 0)

# update the network information
def zwRequestNetworkUpdate():
	log.info("Requesting Network Update")
	sendFunction((FUNC_ID_ZW_REQUEST_NETWORK_UPDATE,), REQUEST, 1, 1)

def zwAssignReturnRoute(node_id, target_node_id):
	log.info("Assigning return route for node %i, target %i" % (node_id, target_node_id))
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_ASSIGN_RETURN_ROUTE, node_id, target_node_id), REQUEST, 1, 1)

# test function
def zwReadMemory(offset):
	log.info("Reading eeprom at offset %i" % offset)
	sendFunction((FUNC_ID_MEMORY_GET_BUFFER, (offset >> 8) & 0xff, (offset & 0xff), 64), REQUEST, 1, 0)

def zwSoftReset():
	log.info("Soft-resetting the Z-Wave chip")
	sendFunction((FUNC_ID_SERIAL_API_SOFT_RESET,), REQUEST, 0, 0)

# request if node is virtual
def zwRequestIsVirtual(node_id):
	sendFunction((FUNC_ID_ZW_IS_VIRTUAL_NODE, node_id), REQUEST, 1, 0)

# request node protocol information
def zwRequestNodeProtocolInfo(node_id):
	sendFunction((FUNC_ID_ZW_GET_NODE_PROTOCOL_INFO, node_id), REQUEST, 1, 0)
def zwGetVersion():
	log.info("Get version")
	sendFunction((FUNC_ID_ZW_GET_VERSION,), REQUEST, 1, 0)

def zwGetHomeId():
	log.info("Get home/node id")
	sendFunction((FUNC_ID_MEMORY_GET_ID,), REQUEST, 1, 0)

def zwGetCapabilities():
	log.info("Get capabilities")
	sendFunction((FUNC_ID_SERIAL_API_GET_CAPABILITIES,), REQUEST, 1, 0)

def zwGetSUCNodeId():
	log.info("Get SUC node id")
	sendFunction((FUNC_ID_ZW_GET_SUC_NODE_ID,), REQUEST, 1, 0)

def zwGetInitData():
	log.info("Get init data")
	sendFunction((FUNC_ID_SERIAL_API_GET_INIT_DATA,), REQUEST, 1, 0)

def zwPromiscSet(val):
	log.info("Set Promiscous mode to %s" % ("ON" if val else "Off"))
	sendFunction((FUNC_ID_ZW_SET_PROMISCUOUS_MODE, 0xff if val else 0x00), REQUEST, 0, 0)

def zwGetControllerCapabilities():
	log.info("Get controller capabilities")
	sendFunction((FUNC_ID_ZW_GET_CONTROLLER_CAPABILITIES,), REQUEST, 1, 0)

def zwEnableSUC(enable, sis):
	log.info("Enable SUC/SIS")
	sendFunction((FUNC_ID_ZW_ENABLE_SUC, 1 if enable else 0, ZW_SUC_FUNC_NODEID_SERVER if sis else ZW_SUC_FUNC_BASIC_SUC), REQUEST, 1, 0)

def zwSetSUCNodeId(node_id, enable, sis):
	log.info("Set SUC Node Id")
	sendFunction((FUNC_ID_ZW_SET_SUC_NODE_ID, node_id, 1 if enable else 0, 0, ZW_SUC_FUNC_NODEID_SERVER if sis else ZW_SUC_FUNC_BASIC_SUC), REQUEST, 1, 0 if node_id == ZWS.ournodeid else 1)

def zwGetLibType():
	sendFunction((FUNC_ID_ZW_TYPE_LIBRARY,), REQUEST, 1, 0)


###########################################################################################################

# send BasicSet command
def zwBasicSet(node_id, level):
	log.info("Sending BasicSet for %i, val: %i" % (node_id, level))
	sendFunction((FUNC_ID_ZW_SEND_DATA, node_id, 3, COMMAND_CLASS_BASIC, BASIC_SET, level, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

# send DimBegin command
def zwDimBegin(node_id, updown):
	log.info("Sending DimBegin for %i, direction: %s" % (node_id, "up" if updown == 1 else "down"))
	sendFunction((FUNC_ID_ZW_SEND_DATA, node_id, 4, COMMAND_CLASS_SWITCH_MULTILEVEL, SWITCH_MULTILEVEL_REPORT_BEGIN, SWITCH_MULTILEVEL_REPORT_BEGIN_UP if updown == 1 else SWITCH_MULTILEVEL_REPORT_BEGIN_DOWN, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

# send DimEnd command
def zwDimEnd(node_id):
	log.info("Sending DimEnd for %i" % (node_id))
	sendFunction((FUNC_ID_ZW_SEND_DATA, node_id, 3, COMMAND_CLASS_SWITCH_MULTILEVEL, SWITCH_MULTILEVEL_REPORT_END, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

def zwSendBasicReport(node_id, value):
	sendFunction((FUNC_ID_ZW_SEND_DATA, node_id, 3, COMMAND_CLASS_BASIC, BASIC_REPORT, value, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

# get the association list for a specific group from a device
def zwAssociationGet(node_id, group):
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 3, COMMAND_CLASS_ASSOCIATION, ASSOCIATION_GET, group, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

# set the association for a specific group of a device
def zwAssociationSet(node_id, group, target_node_id):
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 4, COMMAND_CLASS_ASSOCIATION, ASSOCIATION_SET, group, target_node_id, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

# remove the association for a specific group of a device
def zwAssociationRemove(node_id, group, target_node_id):
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 4, COMMAND_CLASS_ASSOCIATION, ASSOCIATION_REMOVE, group, target_node_id, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

def zwBatteryGet(node_id):
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 2, COMMAND_CLASS_BATTERY, BATTERY_GET, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

# send switch all command
def zwSwitchAll(val):
	sendFunction((FUNC_ID_ZW_SEND_DATA, NODE_BROADCAST, 2, COMMAND_CLASS_SWITCH_ALL, SWITCH_ALL_OFF if val == False else SWITCH_ALL_ON, TRANSMIT_OPTION_NONE), REQUEST, 1, 1)

# include/exclude to/from ALL ON/OFF
def zwSwitchAllSet(node_id, include):
	if include == True:
		sendFunction((FUNC_ID_ZW_SEND_DATA, node_id, 3, COMMAND_CLASS_SWITCH_ALL, SWITCH_ALL_SET, SWITCH_ALL_ENABLE_ON_OFF, TRANSMIT_OPTION_NONE), REQUEST, 1, 1)
	else:
		sendFunction((FUNC_ID_ZW_SEND_DATA, node_id, 3, COMMAND_CLASS_SWITCH_ALL, SWITCH_ALL_SET, SWITCH_ALL_EXCLUDE_ON_OFF, TRANSMIT_OPTION_NONE), REQUEST, 1, 1)

# request a basic report
def zwRequestBasicGet(node_id):
	(ZWS.req_node_id, ZWS.req_cmd) = (node_id, COMMAND_CLASS_BASIC)
	sendFunctionSleeping (node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 2, COMMAND_CLASS_BASIC, BASIC_GET, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

# request a mutilevel report
def zwRequestMultilevelGet(node_id):
	(ZWS.req_node_id, ZWS.req_cmd) = (node_id, COMMAND_CLASS_SWITCH_MULTILEVEL)
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 2, COMMAND_CLASS_SWITCH_MULTILEVEL, SWITCH_MULTILEVEL_GET, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

def zwRequestManufacturerSpecificReport(node_id):
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 2, COMMAND_CLASS_MANUFACTURER_SPECIFIC, MANUFACTURER_SPECIFIC_GET, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

# request binary sensor report
def zwRequestBinarySensorReport(node_id):
	(ZWS.req_node_id, ZWS.req_cmd) = (node_id, COMMAND_CLASS_SENSOR_BINARY)
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 2, COMMAND_CLASS_SENSOR_BINARY, SENSOR_BINARY_REPORT, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

# request multilevel sensor report
def zwRequestMultilevelSensorReport(node_id):
	(ZWS.req_node_id, ZWS.req_cmd) = (node_id, COMMAND_CLASS_SENSOR_MULTILEVEL)
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 2, COMMAND_CLASS_SENSOR_MULTILEVEL, SENSOR_MULTILEVEL_GET, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

# request the version from a node
def zwRequestVersion(node_id):
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 2, COMMAND_CLASS_VERSION, VERSION_GET, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

# configuration_set
def zwConfigurationSet(node_id, parameter, value):
	if value <= 0xff:
		mybuf = (FUNC_ID_ZW_SEND_DATA, node_id, 5, COMMAND_CLASS_CONFIGURATION, CONFIGURATION_SET, parameter, 1, value, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE)
	elif value <= 0xffff:
		mybuf = (FUNC_ID_ZW_SEND_DATA, node_id, 6, COMMAND_CLASS_CONFIGURATION, CONFIGURATION_SET, parameter, 2, (value >> 8) & 0xff, (value & 0xff), TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE)
	else:
		mybuf = (FUNC_ID_ZW_SEND_DATA, node_id, 8, COMMAND_CLASS_CONFIGURATION, CONFIGURATION_SET, parameter, 4, (value >> 24) & 0xff, (value >> 16) & 0xff, (value >> 8) & 0xff, (value & 0xff), TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE)

	log.info("Configuration set for node: %i Parameter: %i Value: %i" % (node_id, parameter, value))
	sendFunctionSleeping(node_id, mybuf, REQUEST, 1, 1)

# configuration_get
def zwConfigurationGet(node_id):
	mybuf = (FUNC_ID_ZW_SEND_DATA, node_id, 2, COMMAND_CLASS_CONFIGURATION, CONFIGURATION_GET, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE)

	log.info("Configuration get for node: %i" % node_id)
	sendFunctionSleeping(node_id, mybuf, REQUEST, 1, 1)

# configuration_report
def zwConfigurationReport(node_id, param, size, value1, value2):
	mybuf = (FUNC_ID_ZW_SEND_DATA, node_id, 6, COMMAND_CLASS_CONFIGURATION, CONFIGURATION_REPORT, param, size, value1 & 0xff, value2 & 0xff, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE)

	log.info("Configuration report for node: %i Parameter: %i" % (node_id, param))
	sendFunctionSleeping(node_id, mybuf, REQUEST, 1, 1)

# wakeup set
def zwWakeupSet(node_id, value, multi):
	value = value * 60
	if not multi:
		mybuf = (FUNC_ID_ZW_SEND_DATA, node_id, 6, COMMAND_CLASS_WAKE_UP, WAKE_UP_INTERVAL_SET, (value >> 16) & 0xff, (value >> 8) & 0xff, (value & 0xff), ZWS.ournodeid, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE)
	else:
		mybuf = (FUNC_ID_ZW_SEND_DATA, node_id, 10, COMMAND_CLASS_MULTI_CMD, MULTI_CMD_ENCAP, 1, 6, COMMAND_CLASS_WAKE_UP, WAKE_UP_INTERVAL_SET, (value >> 16) & 0xff, (value >> 8) & 0xff, (value & 0xff), ZWS.ournodeid, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE)
		# mybuf = (FUNC_ID_ZW_SEND_DATA, node_id, 10, COMMAND_CLASS_MULTI_CMD, MULTI_CMD_ENCAP, 2, 6, COMMAND_CLASS_WAKE_UP, WAKE_UP_INTERVAL_SET, (value >> 16) & 0xff, (value >> 8) & 0xff, (value & 0xff), ZWS.ournodeid, 2, COMMAND_CLASS_WAKE_UP, WAKE_UP_NO_MORE_INFORMATION, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE)

	log.info("Sending Wakeup Set to node %i, value: %i" % (node_id, value))
	sendFunctionSleeping(node_id, mybuf, REQUEST, 1, 1)

# update the neighbour information of a node
def zwRequestNodeNeighborUpdate(node_id):
	log.info("Requesting Neighbour Update for node %i" % node_id)
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_REQUEST_NODE_NEIGHBOR_UPDATE, node_id), REQUEST, 0, 1)

# read meter
def zwMeterGet(node_id):
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 2, COMMAND_CLASS_METER, METER_GET, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

def zwMultiInstanceGet(node_id, command_class):
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 3, COMMAND_CLASS_MULTI_INSTANCE, MULTI_INSTANCE_GET, command_class, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

def zwRequestMultilevelSensorReportInstance(node_id, instance):
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 5, COMMAND_CLASS_MULTI_INSTANCE, MULTI_INSTANCE_CMD_ENCAP, instance, COMMAND_CLASS_SENSOR_MULTILEVEL, SENSOR_MULTILEVEL_GET, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

# thermostat
# fan mode, 0 - auto/auto low, 1 - on/on low, 2 - auto high, 3 - on high
def zwThermostatFanModeSet(node_id, fan_mode):
	# fan_mode & 0xf # zero high nibble conf. to specs
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 3, COMMAND_CLASS_THERMOSTAT_FAN_MODE, THERMOSTAT_FAN_MODE_SET, fan_mode & 0xf, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

# 0 off, 1 heat, 2 cool, 3 auto, 4 aux/emer heat, 5 resume, 6 fan only, 7 furnace, 8 dry air, 9 moist air, 10 auto changeover
def zwThermostatModeSet(node_id, mode):
	# mode & 0x1f # zero highest 3 bit
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 3, COMMAND_CLASS_THERMOSTAT_MODE, THERMOSTAT_MODE_SET, mode & 0x1f, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

def zwThermostatModeGet(node_id):
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 2, COMMAND_CLASS_THERMOSTAT_MODE, THERMOSTAT_MODE_GET, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

def zwThermostatSetpointSet(node_id, Type, value):
	# type & 0xf # zero high-nibble
	# 1 # 3 bit precision, 2 bit scale (0 = C,1=F), 3 bit size
	# value # TODO: proper negative values..
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 5, COMMAND_CLASS_THERMOSTAT_SETPOINT, THERMOSTAT_MODE_SET, Type & 0xf, 1, value, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

def zwThermostatSetpointGet(node_id, Type):
	# type & 0xf # zero high nibble
	sendFunctionSleeping(node_id, (FUNC_ID_ZW_SEND_DATA, node_id, 3, COMMAND_CLASS_THERMOSTAT_SETPOINT, THERMOSTAT_MODE_GET, Type & 0xf, TRANSMIT_OPTION_ACK | TRANSMIT_OPTION_AUTO_ROUTE), REQUEST, 1, 1)

