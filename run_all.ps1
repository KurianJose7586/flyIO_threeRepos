# Start AI LLM
Write-Host "Starting flyio-ai-llm..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\Kurian Jose\Desktop\kurian stuff\FlyIO\Three repos\flyio-ai-llm'; .\.venv\Scripts\activate; pip install -r requirements.txt; uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

# Start Scraper Service
Write-Host "Starting flyio-scraper-service..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\Kurian Jose\Desktop\kurian stuff\FlyIO\Three repos\flyio-scraper-service'; if (!(Test-Path .venv)) { python -m venv .venv }; .\.venv\Scripts\activate; pip install -r requirements.txt; uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload"

# Start Admin
Write-Host "Starting flyio-admin backend..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\Kurian Jose\Desktop\kurian stuff\FlyIO\Three repos\flyio-admin'; npm install; npm run dev"

# Start Admin Frontend
Write-Host "Starting flyio-admin frontend..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\Kurian Jose\Desktop\kurian stuff\FlyIO\Three repos\flyio-admin\frontend'; npm install; npm run dev"

Write-Host "All services started in separate windows."
