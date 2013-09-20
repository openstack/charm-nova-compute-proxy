#!/usr/bin/make
PYTHON := /usr/bin/env python

lint:
	@flake8 --exclude hooks/charmhelpers hooks
	@flake8 --exclude hooks/charmhelpers unit_tests
	@charm proof

test:
	@echo Starting tests...
	@$(PYTHON) /usr/bin/nosetests --nologcapture --with-coverage  unit_tests

sync:
	@charm-helper-sync -c charm-helpers.yaml
