# Landfill Fire Watch. Run from Git Bash; recipes are POSIX sh (CLAUDE.md §3).

ifeq ($(OS),Windows_NT)
PY := .venv/Scripts/python.exe
else
PY := .venv/bin/python
endif

EVENT ?=
INCIDENT ?=

# Windows consoles default to cp1252; scripts print UTF-8 (arrows, °, Devanagari).
export PYTHONUTF8 := 1

# Lambda packaging without Docker: Linux wheels only (CLAUDE.md §3, MVP §12).
FUNCTIONS := scan api draft
LAMBDA_PY := 3.13
LAMBDA_PLATFORM := manylinux2014_x86_64

.PHONY: setup test sites receptors backtest scan-local replay draft verify web fixtures package deploy

setup:
	python -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest

sites:
	$(PY) scripts/build_sites.py

receptors:
	$(PY) scripts/build_receptors.py

fixtures:
	$(PY) scripts/fetch_fixtures.py

backtest:
	$(PY) scripts/backtest.py

scan-local:
	STORE=local $(PY) -m handlers.scan

replay:
	@test -n "$(EVENT)" || { echo "usage: make replay EVENT=<event_id>"; exit 2; }
	$(PY) scripts/backtest.py --replay "$(EVENT)"

draft:
	@test -n "$(INCIDENT)" || { echo "usage: make draft INCIDENT=<incident_id>"; exit 2; }
	$(PY) -m lfw.agent.run "$(INCIDENT)"

verify:
	$(PY) scripts/verify_sources.py

web:
	cd web && "../$(PY)" -m http.server 8000

package:
	rm -rf build
	for fn in $(FUNCTIONS); do \
	  mkdir -p "build/$$fn" && \
	  $(PY) -m pip install --quiet --platform $(LAMBDA_PLATFORM) --only-binary=:all: \
	    --python-version $(LAMBDA_PY) --implementation cp \
	    --target "build/$$fn" -r "handlers/requirements-$$fn.txt" && \
	  cp -r src/lfw "build/$$fn/" && \
	  mkdir -p "build/$$fn/handlers" && cp handlers/__init__.py "handlers/$$fn.py" "build/$$fn/handlers/" \
	  || exit 1; \
	done

deploy: package
	sam build && sam deploy
