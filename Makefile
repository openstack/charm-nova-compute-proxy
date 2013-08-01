#!/usr/bin/make
PYTHON := /usr/bin/env python

lint:
	@flake8 --exclude hooks/charmhelpers hooks
	@flake8 --exclude hooks/charmhelpers tests
	@charm proof

test:
	@echo Starting tests...
	@$(PYTHON) /usr/bin/nosetests --nologcapture --with-coverage  tests

sync:
	@charm-helper-sync -c charm-helpers-sync.yaml
