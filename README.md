# MCP Chat Backend

This project is a serverless FastAPI backend for a chatbot that generates and executes SQL queries on a Postgres database using OpenAI's GPT models, then returns structured, UI-friendly responses. It is designed to run on AWS Lambda via AWS SAM, but can also be run locally or in Docker.

## Features
- FastAPI REST API with a single `/ask` endpoint
- Uses OpenAI GPT models to generate and summarize SQL queries
- Connects to a Postgres (Supabase) database
- Returns structured JSON responses for easy frontend rendering
- CORS enabled for frontend integration
- Deployable to AWS Lambda (SAM), or run locally/Docker
- Verbose logging for debugging (CloudWatch)

## Project Structure
```
├── main.py            # Main FastAPI app and Lambda handler
├── requirements.txt   # Python dependencies
├── template.yaml      # AWS SAM template for Lambda deployment
├── samconfig.toml     # AWS SAM deployment config
├── Dockerfile         # For local/Docker deployment
├── .gitignore         # Files to ignore in git
└── .env               # (Not committed) Environment variables
```

## Setup

### 1. Clone the repository
```sh
git clone <your-repo-url>
cd mcp-chat-3
```

### 2. Install Python dependencies
```sh
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### 3. Set up environment variables
Create a `.env` file (not committed to git):
```
OPENAI_API_KEY=your-openai-key
SUPABASE_DB_NAME=your-db
SUPABASE_DB_USER=your-user
SUPABASE_DB_PASSWORD=your-password
SUPABASE_DB_HOST=your-host
SUPABASE_DB_PORT=your-port
```

## Running Locally

### With Uvicorn
```sh
uvicorn main:app --reload --port 8080
```

### With Docker
```sh
docker build -t mcp-chat-backend .
docker run -p 8080:8080 --env-file .env mcp-chat-backend
```

## Deploying to AWS Lambda (SAM)
1. Install [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)
2. Build and deploy:
```sh
sam build
sam deploy --guided
```
- Configure environment variables in `template.yaml` or via the AWS Console.
- The API will be available at the endpoint shown after deployment (e.g. `https://xxxxxx.execute-api.region.amazonaws.com/Prod/ask`).

## API Usage

### POST /ask
- **Body:** `{ "question": "your question here" }`
- **Response:** Structured JSON for chatbot UI, e.g.
```json
{
  "messages": [
    {
      "type": "text",
      "content": "Sample 588 has a resistance of 1.2 ohms.",
      "entity": {
        "entity_type": "sample",
        "id": "588"
      }
    },
    {
      "type": "list",
      "items": ["Item 1", "Item 2"]
    }
  ]
}
```
- See `main.py` for the full schema and more details.

## Environment Variables
- `OPENAI_API_KEY`: Your OpenAI API key
- `SUPABASE_DB_NAME`, `SUPABASE_DB_USER`, `SUPABASE_DB_PASSWORD`, `SUPABASE_DB_HOST`, `SUPABASE_DB_PORT`: Your Postgres database credentials

## Development Notes
- All logs are sent to stdout (and CloudWatch on Lambda)
- CORS is enabled for all origins by default
- The backend expects the frontend to handle the structured response format

## License
MIT (or your license here) 