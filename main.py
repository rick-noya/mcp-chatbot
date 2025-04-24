import os
import openai
import psycopg2
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import re
from mangum import Mangum
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import logging
import json

# Load environment variables from .env file
load_dotenv()

# OpenAI API key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = openai.OpenAI(api_key=OPENAI_API_KEY)

#App constants
MAX_TOKENS = 32768
openai_model = "gpt-4.1-2025-04-14"

# Supabase/Postgres connection info
DB_NAME = os.getenv("SUPABASE_DB_NAME")
DB_USER = os.getenv("SUPABASE_DB_USER")
DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD")
DB_HOST = os.getenv("SUPABASE_DB_HOST")
DB_PORT = os.getenv("SUPABASE_DB_PORT")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Paste your schema here for prompt context ---
SCHEMA = '''
TABLES:
assemblages(id, created_at, assemblage_name, sorbent_id, installed_at, removed_at). These are assemblies that contain one sorbent sample and get ls-rs tested, vitrek tested, and pressure drop tested.
bad_bin_dashboard(id, updated_at, gamma_shape, gamma_loc, gamma_scale, gamma_max, normal_mean, normal_std, min_resistance, max_resistance, mean_resistance, std_resistance, current_inventory, future_inventory, bins, histogram_data, pdf_data)
boxes(id, location, description, created_at, name). These are the boxes that contain the sorbent samples.
cartridge_assemblages(id, cartridge_id, string_id, assemblage_id, position). These are the assemblies that are inside the cartridges.
cartridge_draft_sorbents(id, cartridge_id, string_id, sorbent_id, position). These are the sorbents that are inside the cartridges.
cartridge_strings(id, cartridge_id, string_index). These are the electrical strings that are inside the cartridges.
cartridges(id, created_at, size, num_strings, label, notes). These are the cartridges that contain the assemblages.
filter_views(id, user_id, view_name, description, table_name, filters, sort_by, sort_dir, include_nulls, is_default, created_at, updated_at, order, column_order, active_filters)
heatmaps(id, created_at, sample_id, hot_proportion, heatmap, heatmap_dimensions). This is data constructed from infrared images of the sorbent samples. Hot_proportion is the percentage of the sample that is above 100C.
inventory_log(log_id, sample_id, box_id, action_type, event_timestamp, user_identifier). This is a log of all the actions taken on the sorbent samples, including when they were moved from one box to another.
"ls-rs_measurements"(id, created_at, sample_id, test_type, inductance, resistance, tester, normalized_timestamp, gui_version, assemblage_id). This is data from the ls-rs tests. It is in henries and ohms. Both samples and assemblages get ls-rs tested. Make sure sql calls look like "ls-rs_measurements" or "ls-rs_measurements.id" or "ls-rs_measurements.created_at" etc.
pressure_drop_measurements(id, created_at, measurement_time, measurement_index, sample_id, assemblage_id, target_flow, measured_flow, pressure_in_h2o, voltage_v, raw_adc, temperature, humidity). This is data from the pressure drop tests. It is in h2o, volts, and degrees celsius and relative humidity.
profiles(id, updated_at, created_at, first_name, last_name, phone_number). This is data about the users who run the tests.
resistivities(id, created_at, sample_id, date_measured, resistivities). This is data from the resistivity tests. It is in ohms. It applies to sorbent samples.
samples(id, sample_name, box_id, created_at, batch_number, shipment). This is data about the sorbent samples.
test_sequences(id, sequence_name, description, created_at, updated_at). This is data about the test sequences of the vitrek tests.
test_steps(id, sequence_id, step_number, step_type, parameters, created_at, updated_at). This is data about the steps of the vitrek tests.
users(id, created_at, user)
vitrek_test_results(id, test_timestamp, assemblage_id, overall_result, step_number, test_step_type, termination_state_code, termination_state_text, elapsed_time_seconds, status_code, status_description, test_level, test_level_unit, breakdown_current_peak, measurement_result, measurement_unit, arc_current_peak, operator_name, notes, sequence_id). This is data from the vitrek tests. It is in volts and amps.
wrappers_fdw_stats(fdw_name, create_times, rows_in, rows_out, bytes_in, bytes_out, metadata, created_at, updated_at)
'''

app = FastAPI()

# Enable CORS for all origins (customize for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CustomCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
        return response

app.add_middleware(CustomCORSMiddleware)

class AskRequest(BaseModel):
    question: str

# Your schema as a string for the prompt
MESSAGE_SCHEMA_DESCRIPTION = """
Respond with a JSON object with this structure:
{
  "messages": [
    {
      "type": "text" | "list" | "code" | "error",
      "content": "string (for text, code, or error)",
      "items": ["string", ...] (for type = 'list', optional),
      "entity": {
        "entity_type": "sample" | "assemblage",
        "id": "string (the unique id of the sample or assemblage)",
        "sorbent_id": "string (for assemblage only, optional)"
      } (optional)
    },
    ...
  ]
}
Only include 'items' for type 'list'. For other types, omit 'items'.
Only include 'entity' if the message references a sample or assemblage. For 'entity', always include 'entity_type' and 'id', and include 'sorbent_id' for assemblages if available.
"""

@app.post("/ask")
async def ask(request: AskRequest, simple: bool = Query(True, description="If true, return only the answer string.")):
    logger.info(f"Received /ask request: {request.dict()} | simple={simple}")

    # 1. Use OpenAI to generate a SQL query
    prompt = f"""
Given the following database schema:
{SCHEMA}

Write a single, read-only SQL query (no modifications, only SELECTs) to answer the following question.

Before returning the query, carefully check for common Postgres errors, such as:
- Table or column names with dashes must be double-quoted.
- If using SELECT DISTINCT, ORDER BY expressions must appear in the select list. If you want to order randomly, use a subquery.
- Avoid reserved words as identifiers, or quote them.
- Ensure all joins and conditions are valid.

If you find any issues, fix them before returning the final SQL.

Question: {request.question}
SQL:
"""

    try:
        logger.info("Sending prompt to OpenAI for SQL generation.")
        completion = client.chat.completions.create(
            model=openai_model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that writes safe, valid, and correct read-only SQL queries for a Postgres database. Only output the SQL query, nothing else."},
                {"role": "user", "content": prompt}
            ],
            temperature=1,
            max_completion_tokens=MAX_TOKENS
        )
        sql_query = completion.choices[0].message.content.strip().split(';')[0] + ';'
        logger.info(f"Generated SQL: {sql_query}")
    except Exception as e:
        logger.error(f"OpenAI SQL generation error: {e}")
        raise HTTPException(status_code=500, detail=f"OpenAI SQL generation error: {e}")

    sql_query = sql_query.replace('```sql', '').replace('```', '').strip()

    # 2. Execute the SQL query (read-only)
    try:
        logger.info("Connecting to database.")
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        cur = conn.cursor()
        logger.info(f"Executing SQL: {sql_query}")
        cur.execute(sql_query)
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        results = [dict(zip(columns, row)) for row in rows]
        logger.info(f"Query results: {results}")
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Database query error: {e}\nSQL: {sql_query}")
        raise HTTPException(status_code=500, detail=f"Database query error: {e}\nSQL: {sql_query}")

    # 3. Use OpenAI to summarize the results
    summary_prompt = f"""
Given the question: '{request.question}' and the following SQL results:
{results}

{MESSAGE_SCHEMA_DESCRIPTION}
Respond in valid JSON only, no extra text.
"""

    try:
        logger.info("Sending results to OpenAI for structured summarization.")
        summary_completion = client.chat.completions.create(
            model=openai_model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that summarizes SQL query results for users in a structured JSON format."},
                {"role": "user", "content": summary_prompt}
            ],
            temperature=1,
            max_completion_tokens=MAX_TOKENS
        )
        answer_json = summary_completion.choices[0].message.content.strip()
        logger.info(f"Generated structured answer: {answer_json}")
        answer = json.loads(answer_json)
    except Exception as e:
        logger.error(f"OpenAI structured summarization error: {e}")
        raise HTTPException(status_code=500, detail=f"OpenAI summarization error: {e}")

    if simple:
        logger.info("Returning simple answer.")
        return answer
    logger.info("Returning full response object.")
    return {
        "question": request.question,
        "sql_query": sql_query,
        "results": results,
        "answer": answer
    }

handler = Mangum(app) 