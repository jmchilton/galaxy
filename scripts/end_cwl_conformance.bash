#!/bin/bash

export GALAXY_SKIP_CLIENT_BUILD=1
export GALAXY_PID=cwl.pid
./run.sh --stop-daemon
