SHELL := /bin/bash

run:
	set -a; source .env; set +a; \
	env | grep BAMBU_; \
	env | grep TG_; \
	docker run -it --rm bambu-monitor

build:
	docker build -t bambu-monitor .

