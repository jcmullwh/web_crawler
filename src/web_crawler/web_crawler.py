import pandas as pd
import requests
import re
import time
import json
from urllib.parse import urljoin
from pathlib import Path

# Configuration
EXCEL_FILE = 'master_urls.xlsx'  # Path to your Excel file
SHEET_NAME = 'master URL list'
OUTPUT_FILE = 'crawler_results.csv'
RATE_LIMIT_SECONDS = 1  # Delay between requests to avoid overwhelming servers

# Patterns
UUID_PATTERN = r'MFE_[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
OTHER_PATTERNS = [
    r'PAYMENTS_MFE',
    r'payments_tracking',
    # Add more patterns as needed
]

def read_and_clean_data(file: str, sheet: str) -> pd.DataFrame:
    """Read the Excel file and clean the URLs."""
    df = pd.read_excel(file, sheet_name=sheet)
    # Strip whitespace
    df['URL'] = df['URL'].str.strip()
    # Ensure URLs end with 'remoteEntry.js'
    df['URL'] = df['URL'].apply(lambda x: x if x.endswith('remoteEntry.js') else (x.rstrip('/') + '/remoteEntry.js'))
    # Drop duplicates based on URL
    df = df.drop_duplicates(subset=['URL'])
    return df

def fetch_url(url: str) -> tuple[bool, str]:
    """Fetch a URL and return success status and content or error message."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return True, response.text
    except requests.RequestException as e:
        return False, str(e)

def extract_ids(content: str) -> list:
    """Extract MFE_UUID and other pattern IDs from the content."""
    ids = []
    # Find MFE_UUID
    uuid_matches = re.findall(UUID_PATTERN, content)
    ids.extend(uuid_matches)
    # Find other patterns near the beginning (e.g., first 1000 characters)
    snippet = content[:1000]
    for pattern in OTHER_PATTERNS:
        matches = re.findall(pattern, snippet, re.IGNORECASE)
        ids.extend(matches)
    return ids if ids else ["None found"]

def replace_remote_entry(url: str) -> str:
    """Replace 'remoteEntry.js' with 'settings.json' in the URL."""
    return url.rsplit('remoteEntry.js', 1)[0] + 'settings.json'

def process_record(record: dict) -> dict:
    """Process a single URL record."""
    result = record.copy()
    
    # Fetch remoteEntry.js
    success, content_or_error = fetch_url(record['URL'])
    if success:
        result['remoteEntry_status'] = 'Success'
        extracted_ids = extract_ids(content_or_error)
        result['MFE_IDs'] = '; '.join(extracted_ids)
    else:
        result['remoteEntry_status'] = f'Error: {content_or_error}'
        result['MFE_IDs'] = 'N/A'
    
    # Fetch settings.json
    settings_url = replace_remote_entry(record['URL'])
    success, content_or_error = fetch_url(settings_url)
    if success:
        result['settings_status'] = 'Success'
        try:
            json_content = json.loads(content_or_error)
            result['settings_json'] = json.dumps(json_content)  # Store as string
        except json.JSONDecodeError:
            result['settings_status'] = 'Error: Invalid JSON'
            result['settings_json'] = 'N/A'
    else:
        result['settings_status'] = f'Error: {content_or_error}'
        result['settings_json'] = 'N/A'
    
    return result

def main():
    # Read and clean data
    df = read_and_clean_data(EXCEL_FILE, SHEET_NAME)
    records = df.to_dict(orient='records')
    
    results = []
    total = len(records)
    for idx, record in enumerate(records, 1):
        print(f'Processing {idx}/{total}: {record["URL"]}')
        processed = process_record(record)
        results.append(processed)
        time.sleep(RATE_LIMIT_SECONDS)  # Rate limiting
    
    # Convert results to DataFrame
    results_df = pd.DataFrame(results)
    
    # Save to CSV
    results_df.to_csv(OUTPUT_FILE, index=False)
    print(f'Results saved to {OUTPUT_FILE}')

if __name__ == '__main__':
    main()
