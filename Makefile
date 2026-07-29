.PHONY: setup test sample-data forecast-sample dev frontend-dev worker-dev clean

setup:
	pip install -r forecast/requirements.txt
	cd frontend && npm install
	cd worker && npm install

test:
	cd forecast && pytest -v
	cd frontend && npm run typecheck && npm test
	cd worker && npm run typecheck && npm test

sample-data forecast-sample:
	python scripts/run_forecast.py --sample --verbose
	python -c "import shutil; shutil.rmtree('frontend/public/data/latest', ignore_errors=True); shutil.copytree('data/generated/latest', 'frontend/public/data/latest')"

dev: frontend-dev

frontend-dev:
	cd frontend && npm run dev

worker-dev:
	cd worker && npm run dev

clean:
	rm -rf frontend/dist frontend/node_modules worker/node_modules data/cache
	find forecast -name "__pycache__" -type d -prune -exec rm -rf {} +
