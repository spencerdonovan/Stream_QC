# Generic API fetch with retry logic
import requests
import time


def fetch_json(url, timeout=15, retries=3, backoff=1.5):
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            print(f"HTTP {r.status_code} -> {url}")
        except Exception as e:
            print(f"Request failed (attempt {attempt}/{retries}): {e}")

        if attempt < retries:
            sleep_time = backoff ** attempt
            print(f"Retrying in {sleep_time:.1f} seconds...")
            time.sleep(sleep_time)

    print(f"Failed to fetch after {retries} attempts -> {url}")
    return None
