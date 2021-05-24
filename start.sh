#!/bin/bash

pip3 install scrapyd
scrapyd > /dev/null 2>&1 &
scrapyd-deploy

tail -f /dev/null