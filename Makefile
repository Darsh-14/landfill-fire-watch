# WeSave. Run from Git Bash; recipes are POSIX sh (CLAUDE.md §3).

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

.PHONY: setup test sites receptors backtest scan-local replay draft verify web api-local fixtures lock package lint check compliance deploy-check deploy

setup:
	python -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev,agent]"

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

api-local:
	STORE=local $(PY) scripts/local_api.py --port 8001

# pip evaluates environment markers (e.g. sys_platform == "win32") for the HOST, not --platform,
# so a Windows host would pull pywin32 into a Linux package. Resolve once for Linux with uv,
# commit the locks, then install exactly those pins with pip --no-deps (Linux wheels only).
lock:
	for fn in $(FUNCTIONS); do \
	  $(PY) -m uv pip compile --quiet --python-platform x86_64-manylinux2014 --python-version $(LAMBDA_PY) --only-binary :all: \
	    --no-header --output-file "handlers/requirements-$$fn.lock.txt" "handlers/requirements-$$fn.txt" \
	  || exit 1; \
	done

package:
	rm -rf build
	for fn in $(FUNCTIONS); do \
	  mkdir -p "build/$$fn/handlers" "build/$$fn/data/sites" "build/$$fn/data/receptors" && \
	  $(PY) -m pip install --quiet --platform $(LAMBDA_PLATFORM) --only-binary=:all: \
	    --python-version $(LAMBDA_PY) --implementation cp \
	    --no-deps --target "build/$$fn" -r "handlers/requirements-$$fn.lock.txt" && \
	  cp -r src/lfw "build/$$fn/" && \
	  cp handlers/__init__.py "handlers/$$fn.py" "build/$$fn/handlers/" && \
	  cp data/sites.yaml data/rules.yaml "build/$$fn/data/" && \
	  cp data/sites/*.geojson "build/$$fn/data/sites/" && \
	  cp data/receptors/*.geojson "build/$$fn/data/receptors/" \
	  || exit 1; \
	done
	cp out/backtest.json build/api/data/backtest.json
	find build -type d -name "__pycache__" -prune -exec rm -rf {} +
	$(PY) scripts/zip_packages.py $(FUNCTIONS)

compliance:
	gitleaks git --no-banner -v
	$(PY) scripts/compliance_check.py

lint:
	"$(dir $(PY))cfn-lint" --regions ap-south-1 -- template.yaml

# Everything a reviewer can run without AWS: static checks, template checks, tests.
check: lint
	$(PY) -m ruff check src handlers scripts tests
	$(PY) -m pytest

# Deviation from CLAUDE.md §5 (`sam build && sam deploy`): without Docker, `sam build` on Windows
# drops the Linux .so files from the prebuilt packages. CodeUri points at build/<fn>.zip instead,
# and sam deploy uploads those zips unchanged. Never run `sam build` for this stack.
ALERT_EMAIL ?=
BEDROCK_MODEL_ID ?=
ALLOWED_ORIGIN ?= *
# Bedrock may be enabled in a different region from the stack (the IAM policy allows that).
BEDROCK_REGION ?= ap-south-1

deploy-check:
	@test -n "$(ALERT_EMAIL)" && test -n "$(BEDROCK_MODEL_ID)" || { \
	  echo "usage: make deploy ALERT_EMAIL=you@example.com BEDROCK_MODEL_ID=<id> [BEDROCK_REGION=us-east-1] [ALLOWED_ORIGIN=https://...]"; exit 2; }

deploy: deploy-check package
	rm -rf .aws-sam
	sam deploy --template-file template.yaml --parameter-overrides \
	  AlertEmail="$(ALERT_EMAIL)" BedrockModelId="$(BEDROCK_MODEL_ID)" AllowedOrigin="$(ALLOWED_ORIGIN)" \
	  BedrockRegion="$(BEDROCK_REGION)"
