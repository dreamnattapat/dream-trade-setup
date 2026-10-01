VENV := venv
PYTHON := $(VENV)/bin/python3
STREAMLIT := $(VENV)/bin/streamlit

AGENT := $(HOME)/Library/LaunchAgents/com.dreamtradesetup.paper.plist

.PHONY: install run stop paper schedule unschedule

install:
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

run:
	$(STREAMLIT) run app.py

stop:
	lsof -ti:8501 -sTCP:LISTEN | xargs -r kill

paper:
	$(PYTHON) -m src.paper

# Run the paper-trading cycle every day at 07:00 (after the US close in Thai time).
schedule:
	mkdir -p data $(dir $(AGENT))
	sed 's|__REPO__|$(CURDIR)|g' scripts/paper.plist > $(AGENT)
	launchctl bootout gui/$$(id -u) $(AGENT) 2>/dev/null || true
	launchctl bootstrap gui/$$(id -u) $(AGENT)
	@echo "Scheduled daily at 07:00. Log: data/paper_schedule.log"

unschedule:
	launchctl bootout gui/$$(id -u) $(AGENT) 2>/dev/null || true
	rm -f $(AGENT)
