VENV := venv
PYTHON := $(VENV)/bin/python3
STREAMLIT := $(VENV)/bin/streamlit

.PHONY: install run stop paper

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
