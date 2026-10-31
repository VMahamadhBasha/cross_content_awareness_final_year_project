.PHONY: api web ngrok

api:
	# Go to backend path and run this command to start the FastAPI server
	python -m uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm install && npm run dev

ngrok:
	ngrok http 8000