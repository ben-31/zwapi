#!/bin/bash

start-stop-daemon --start --background --chdir /data/download/zwapi --pidfile /var/run/zwapi.pid --exec /usr/bin/python -- -u rules.py 

