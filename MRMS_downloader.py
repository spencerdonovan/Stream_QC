# -*- coding: utf-8 -*-
"""
Created on Mon Aug 17 14:54:41 2026

@author: Charles.Donovan
"""
import os
import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path
import boto3
from botocore import UNSIGNED
from botocore.config import Config

# Uses Python Path function and uses relative path (working directory) to create folder where files are stored
LOCAL_DATA_DIR = Path("mrms_local_archive")

# The specific, public folder where NOAA shares their weather datasets
BUCKET_NAME = "noaa-mrms-pds"

# Setup AWS Client
s3_client = boto3.client(
    "s3",
    region_name="us-east-1",
    config=Config(signature_version=UNSIGNED)
)


def download_and_extract(s3_key: str, destination_path: Path) -> bool:
    """Downloads a .gz file from S3 and extracts it to a clean .grib2 file."""
    if destination_path.exists():
        return False  # Skip if file already exists locally

    # Ensure parent directory exists
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temp_gz_path = destination_path.with_suffix(".grib2.gz")

    try:
        # Download compressed file
        s3_client.download_file(BUCKET_NAME, s3_key, str(temp_gz_path))

        # Decompress directly to final destination
        with gzip.open(temp_gz_path, "rb") as f_in:
            with open(destination_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        return True
    except Exception as e:
        print(f"MRMS download error for {s3_key}: {type(e).__name__}: {e}")
        print(f"Requested MRMS date is not available in the S3 bucket yet for {s3_key}.")
        if destination_path.exists():
            destination_path.unlink()
        return False
    finally:
        # Clean up temporary compressed file
        if temp_gz_path.exists():
            temp_gz_path.unlink()


def sync_mrms_archive(start_date: datetime, end_date: datetime):
    """Loops over date ranges to populate the local archive folder."""
    current_date = start_date
    hour_str = "080000"

    print(
        f"Syncing MRMS archive from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}...")

    while current_date <= end_date:
        date_str = current_date.strftime("%Y%m%d")
        timestamp_str = f"{date_str}-{hour_str}"

        # Setup S3 Keys
        s3_key_qpe = f"CONUS/RadarOnly_QPE_24H_00.00/{date_str}/MRMS_RadarOnly_QPE_24H_00.00_{timestamp_str}.grib2.gz"
        s3_key_rqi = f"CONUS/RadarQualityIndex_00.00/{date_str}/MRMS_RadarQualityIndex_00.00_{timestamp_str}.grib2.gz"

        # Setup Local Output Destinations
        local_qpe_file = LOCAL_DATA_DIR / "qpe" / \
            f"MRMS_RadarOnly_QPE_24H_{timestamp_str}.grib2"
        local_rqi_file = LOCAL_DATA_DIR / "rqi" / \
            f"MRMS_RQI_{timestamp_str}.grib2"

        # Run downloads
        if download_and_extract(s3_key_qpe, local_qpe_file):
            print(f" Saved QPE: {local_qpe_file.name}")
        if download_and_extract(s3_key_rqi, local_rqi_file):
            print(f" Saved RQI: {local_rqi_file.name}")

        current_date += timedelta(days=1)

    print("Archive sync complete.")

#%%
if __name__ == "__main__":
    # --- Mode 1: Historical Backfill Run ---
    history_start = datetime(2026, 8, 1)
    history_end = datetime(2026, 9, 27)
    sync_mrms_archive(history_start, history_end)

    # --- Mode 2: Daily Increment Run ---
    # To add new data as it becomes available later, uncomment the lines below:
    # today = datetime.utcnow()
    # yesterday = today - timedelta(days=1)
    # sync_mrms_archive(yesterday, yesterday)
