.PHONY: install run build-win build-mac clean

VENV?=.venv
PYTHON?=$(VENV)/bin/python
PIP?=$(VENV)/bin/pip
DATA_SEP?=:

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

run: install
	$(PYTHON) src/main.py

build-win:
	@echo "请在 Windows 环境下执行打包命令"

build-mac: install
	$(PYTHON) -m PyInstaller --noconfirm --clean --windowed \
		--name video-converter \
		--osx-bundle-identifier "com.example.videoconverter" \
		--add-data "resources/ffmpeg/macos/ffmpeg$(DATA_SEP)resources/ffmpeg/macos" \
		--add-data "resources/ffmpeg/macos/ffprobe$(DATA_SEP)resources/ffmpeg/macos" \
		src/main.py

clean:
	rm -rf $(VENV) build dist __pycache__ src/__pycache__ *.spec

