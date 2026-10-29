.PHONY: help install test mock run serve lint clean

PY ?= python
export PYTHONPATH := src

help:
	@echo "resume-copilot"
	@echo "  make install   安装（可编辑模式，含 pdf/web 可选依赖）"
	@echo "  make test      跑测试（标准库 unittest，无需 pytest）"
	@echo "  make mock      离线跑一遍演示（不消耗 token）"
	@echo "  make run       用 examples/materials 真实跑一次（需要 .env）"
	@echo "  make serve     启动 Web 界面"
	@echo "  make lint      ruff 检查（可选）"
	@echo "  make clean     清理产物"

install:
	$(PY) -m pip install -e ".[pdf,web,dev]"

test:
	$(PY) -m unittest discover -s tests -t . -v

mock:
	$(PY) -m resume_copilot run --mock --dir examples/materials --role 客户经理 --out out

run:
	$(PY) -m resume_copilot run --dir examples/materials --role 客户经理 --photo examples/photo.jpg --out out

serve:
	$(PY) -m resume_copilot serve --port 8000

lint:
	ruff check src tests

clean:
	rm -rf out build dist *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
