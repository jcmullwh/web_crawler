import pandas as pd
import re
import time
import json
import logging
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.common.exceptions import (
    WebDriverException,
    TimeoutException
)
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from selenium.webdriver.edge.service import Service as EdgeService

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
EXCEL_FILE = 'master_urls.xlsx'    # Path to your Excel file
SHEET_NAME = 'master URL list'     # Tab name in the Excel file
OUTPUT_FILE = 'crawler_results.csv'
LOG_FILE = 'crawler.log'
RATE_LIMIT_SECONDS = 1             # Simple rate-limiting between records

# Regex patterns
UUID_PATTERN = r'MFE_[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
OTHER_PATTERNS = [
    r'PAYMENTS_MFE',
    r'payments_tracking',
    # Add more patterns as needed
]

# -----------------------------------------------------------------------------
# Logging Setup
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

# -----------------------------------------------------------------------------
# Data Reading & Cleaning
# -----------------------------------------------------------------------------
def read_and_clean_data(file: str, sheet: str) -> pd.DataFrame:
    """
    Reads an Excel file, ensures a 'URL' column exists, cleans & normalizes URLs.
    Throws an exception if 'URL' is missing or the file is unreadable.
    """
    try:
        df = pd.read_excel(file, sheet_name=sheet)
        logging.info(f"Successfully read Excel file: {file}, sheet: {sheet}")
    except Exception as e:
        logging.error(f"Failed to read Excel file: {file} / sheet: {sheet}. Error: {e}")
        raise

    # Ensure the 'URL' column is present
    if 'URL' not in df.columns:
        raise KeyError("Missing 'URL' column in the Excel file.")

    # Drop rows with null/NaN in 'URL'
    df = df.dropna(subset=['URL'])

    # Strip whitespace
    df['URL'] = df['URL'].astype(str).str.strip()

    # Ensure URLs end with 'remoteEntry.js'
    df['URL'] = df['URL'].apply(
        lambda x: x if x.endswith('remoteEntry.js') else (x.rstrip('/') + '/remoteEntry.js')
    )

    # Remove duplicates based on URL
    initial_count = len(df)
    df = df.drop_duplicates(subset=['URL'])
    final_count = len(df)
    logging.info(f"Cleaned data: removed {initial_count - final_count} duplicates.")

    return df

# -----------------------------------------------------------------------------
# Browser Initialization
# -----------------------------------------------------------------------------
def initialize_browser() -> webdriver.Edge:
    """
    Initializes a headless Edge browser using webdriver-manager and returns it.
    """
    edge_options = Options()
    edge_options.use_chromium = True
    edge_options.add_argument("--headless")
    edge_options.add_argument("--no-sandbox")
    edge_options.add_argument("--disable-dev-shm-usage")
    edge_options.add_argument("--disable-gpu")
    edge_options.add_argument("--window-size=1920,1080")

    try:
        service = EdgeService(EdgeChromiumDriverManager().install())
        driver = webdriver.Edge(service=service, options=edge_options)
        driver.set_page_load_timeout(30)
        logging.info("Initialized headless Edge browser.")
        return driver
    except WebDriverException as e:
        logging.error(f"Error initializing Edge browser: {e}")
        raise

# -----------------------------------------------------------------------------
# Fetching Web Content
# -----------------------------------------------------------------------------
def fetch_content(driver: webdriver.Edge, url: str) -> (bool, str):
    """
    Navigates to the specified URL and returns (success, page_content_or_error).
    """
    try:
        driver.get(url)
        # Simple sleep to allow basic page load
        time.sleep(2)
        content = driver.page_source
        logging.info(f"Fetched URL successfully: {url}")
        return True, content
    except TimeoutException:
        logging.error(f"Timeout while loading URL: {url}")
        return False, "Error: Page load timed out."
    except WebDriverException as e:
        logging.error(f"WebDriverException while loading URL: {url}. Error: {e}")
        return False, str(e)

# -----------------------------------------------------------------------------
# ID Extraction
# -----------------------------------------------------------------------------
def extract_ids(content: str) -> list:
    """
    Scans the full page content for MFE UUIDs and any patterns in OTHER_PATTERNS.
    Returns a list of matching strings, or ['None found'] if none appear.
    """
    ids = []

    # UUID matches
    uuid_matches = re.findall(UUID_PATTERN, content)
    if uuid_matches:
        ids.extend(uuid_matches)
        logging.info(f"Found UUID patterns: {uuid_matches}")

    # Other patterns
    for pattern in OTHER_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            ids.extend(matches)
            logging.info(f"Found pattern '{pattern}': {matches}")

    if not ids:
        logging.info("No matching IDs found.")
        return ["None found"]
    return ids

# -----------------------------------------------------------------------------
# Utility: Replace remoteEntry.js with settings.json
# -----------------------------------------------------------------------------
def replace_remote_entry(url: str) -> str:
    """
    Returns the corresponding settings.json URL by replacing 'remoteEntry.js'.
    """
    new_url = url.rsplit('remoteEntry.js', 1)[0] + 'settings.json'
    logging.info(f"Constructed settings.json URL: {new_url}")
    return new_url

# -----------------------------------------------------------------------------
# Processing Single Record
# -----------------------------------------------------------------------------
def process_record(driver: webdriver.Edge, record: dict) -> dict:
    """
    For a single record dict (with a 'URL' key), fetch remoteEntry.js, extract IDs,
    then fetch settings.json, parse JSON if valid, and return an augmented dict.
    """
    result = record.copy()

    # Fetch remoteEntry.js
    success, content_or_error = fetch_content(driver, record['URL'])
    if success:
        result['remoteEntry_status'] = 'Success'
        extracted_ids = extract_ids(content_or_error)
        result['MFE_IDs'] = '; '.join(extracted_ids)
    else:
        result['remoteEntry_status'] = content_or_error
        result['MFE_IDs'] = 'N/A'

    # Fetch settings.json
    settings_url = replace_remote_entry(record['URL'])
    success, content_or_error = fetch_content(driver, settings_url)
    if success:
        result['settings_status'] = 'Success'
        try:
            json_content = json.loads(content_or_error)
            result['settings_json'] = json.dumps(json_content)  # Store full JSON as string
            logging.info(f"Parsed JSON successfully for URL: {settings_url}")
        except json.JSONDecodeError:
            result['settings_status'] = 'Error: Invalid JSON'
            result['settings_json'] = 'N/A'
            logging.error(f"Invalid JSON from: {settings_url}")
    else:
        result['settings_status'] = content_or_error
        result['settings_json'] = 'N/A'

    return result

# -----------------------------------------------------------------------------
# Main Flow
# -----------------------------------------------------------------------------
def main():
    """
    Main function:
      1. Initializes the browser
      2. Reads & cleans data from Excel
      3. Iterates over records and processes each URL
      4. Saves results to CSV
      5. Shuts down the browser
    """
    driver = initialize_browser()

    try:
        # Read Excel data
        df = read_and_clean_data(EXCEL_FILE, SHEET_NAME)
        records = df.to_dict(orient='records')
        logging.info(f"Total records to process: {len(records)}")

        results = []
        for idx, record in enumerate(records, start=1):
            logging.info(f"Processing {idx}/{len(records)}: {record['URL']}")
            processed_result = process_record(driver, record)
            results.append(processed_result)

            # Simple rate limiting
            time.sleep(RATE_LIMIT_SECONDS)

        # Convert results to DataFrame and save
        results_df = pd.DataFrame(results)
        results_df.to_csv(OUTPUT_FILE, index=False)
        logging.info(f"Results saved to '{OUTPUT_FILE}'")

    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")

    finally:
        driver.quit()
        logging.info("Closed the Edge browser.")

# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    main()
