#!/usr/bin/python

"""
	Copyright (C) 2009 Poltorak Serguei <poltorak@alsenet.com>
	This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License.
	This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
	of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

	See the GNU General Public License for more details.
"""

import threading
import time

import log

#class Schedule:
#	def __init__(self, schedule_str):
#		def parce_sched_item(str, zero_start, max_val):
#			z = 0 if zero_start == True else 1
#			val = range(z, max_val + z)
#			str_slash = str.split("/")
#			if len(str_slash) not in (1, 2):
#
#				log.crit("Error in schedule description: %s. Expecting x[-y][/z]." % str
#			str = str.replace("*", "1"
#		wds = { "Monday": 1, "Mon": 1, "Tuesday": 2, "Tue": 2, "Wednesday": 3, "Wed": 3, "Thursday": 4, "Thu": 4, "Friday": 5, "Fri": 5, "Saturday": 6, "Sat": 6, "Sunday": 7, "Sun": 7 }
#		ms = { "January": 1, "Jan": 1, "February": 2, "Feb": 2, "March": 3, "Mar": 3, "April": 4, "Apr": 4, "May": 5, "June": 6, "Jun": 6, "July": 7, "Jul": 7, "August": 8, "Aug": 8, "September": 9, "Sep": 9, "October": 10, "Oct": 10, "November": 11, "Nov": 11, "December": 12, "Dec": 12 }		
#		schedule_arr = schedule_str.split()
#		if len(schedule_arr) != 6:
#			log.crit("Wrong schedule definition: %s. Expecting \"sec min hour wday mday month\"" % schedule_str)
#		
#		for wd in wds.keys():
#			schedule_arr[3] = schedule_arr[3].lower().replace(lower(wd), wds[wd])
#		for m in ms.keys():
#			schedule_arr[5] = schedule_arr[5].lower().replace(lower(m), ms[m])
#		self.s = parce_sched_item(schedule_arr[0], 60, True)
			
class Event:
	def __init__(self, node, name, time):
		self.node = node
		self.name = name
		self.time = time

class Timer:
	def __init__(self):
		self.callback_func = None
		self.events = []

# Receive thread
class TimerThread ( threading.Thread ):
        def run(self):
		timerEvent()
                        
                        
# callback function and events storage
T = Timer()

mutexEvents = threading.Lock()        

def init(callback_function):
	T.callback_func = callback_function

	# timer thread
	timerThread = TimerThread
	timerThread().start()

def timerEvent():
	while True:
		mutexEvents.acquire()
		curTime = time.time()
		for ev in T.events:
			if curTime-ev.time >= 0:
				log.info("Triggering timer for \"%s\" %i" % (ev.name, ev.node))
				if curTime-ev.time >= 1:
					log.crit("Trigger is late by %i sec!" % (curTime-ev.time))
				T.callback_func(2, ev.node, 0, (ev.name,))
				T.events.remove(ev)
		mutexEvents.release()
		time.sleep(1)

def addTimer(node, name, inTime):
	mutexEvents.acquire()
	log.info("Adding timer \"%s\" for %i in %i sec" % (name, node, inTime))
	# before remove previous timer with same name
	T.events = filter(lambda x: not (x.node == node and x.name == name), T.events)
	e = Event(node, name, inTime + time.time())
	T.events.append(e)
	mutexEvents.release()

#def addAtTimer(node, name, atTime):
#	mutexEvents.acquire()
#	log.info("Adding timer \"%s\" for %i at %i sec" % (name, node, inTime))
#	# before remove previous timer with same name
#	T.events = filter(lambda x: not (x.node == node and x.name == name), T.events)
#	e = Event(node, name, inTime + time.time())
#	T.events.append(e)
#	mutexEvents.release()

#def addScheduleTimer(node, name, schedule_str):
#	mutexEvents.acquire()
#	log.info("Adding schedule \"%s\" for %i at %i sec" % (name, node, inTime))
#	
#	schedule_struct = 
#	e = Schedule(node, name, schedule_struct)
#	T.events.append(e)
#	mutexEvents.release()

def removeTimer(node, name):
	mutexEvents.acquire()
	log.info("Removing timer \"%s\" for %i" % (name, node))
	T.events = filter(lambda x: not (x.node == node and x.name == name), T.events)
	mutexEvents.release()
