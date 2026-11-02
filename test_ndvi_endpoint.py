#!/usr/bin/env python3
"""Test script to verify NDVI endpoint response."""

import requests
import json

url = "http://localhost:8000/api/surfaces/ndvi/latest"

print("=" * 80)
print("TESTING NDVI ENDPOINT")
print("=" * 80)
print(f"\nURL: {url}\n")

try:
    response = requests.get(url)
    
    print(f"HTTP Status: {response.status_code}")
    print(f"Status OK: {response.ok}")
    print(f"Content-Type: {response.headers.get('Content-Type')}")
    print(f"Content-Length: {response.headers.get('Content-Length')}")
    
    print("\n" + "=" * 80)
    print("RESPONSE BODY")
    print("=" * 80)
    
    if response.ok:
        try:
            data = response.json()
            print(json.dumps(data, indent=2))
            
            print("\n" + "=" * 80)
            print("DATA STRUCTURE VALIDATION")
            print("=" * 80)
            print(f"Has 'metric': {'metric' in data}")
            print(f"Has 'image_url': {'image_url' in data}")
            print(f"Has 'coordinates': {'coordinates' in data}")
            print(f"Has 'generated_at': {'generated_at' in data}")
            
            if 'image_url' in data:
                print(f"\nImage URL: {data['image_url']}")
                full_url = f"http://localhost:8000{data['image_url']}"
                print(f"Full Image URL: {full_url}")
                
                # Test image URL
                print(f"\nTesting image URL accessibility...")
                img_response = requests.head(full_url)
                print(f"Image HTTP Status: {img_response.status_code}")
                print(f"Image Content-Type: {img_response.headers.get('Content-Type')}")
                print(f"Image Content-Length: {img_response.headers.get('Content-Length')}")
                
            if 'coordinates' in data:
                print(f"\nCoordinates: {data['coordinates']}")
                
        except json.JSONDecodeError as e:
            print(f"ERROR: Failed to parse JSON")
            print(f"Error: {e}")
            print(f"Response text: {response.text[:500]}")
    else:
        print(f"ERROR Response:")
        print(response.text)
        
except requests.exceptions.ConnectionError as e:
    print(f"ERROR: Could not connect to server")
    print(f"Error: {e}")
except Exception as e:
    print(f"ERROR: Unexpected error")
    print(f"Error: {e}")

print("\n" + "=" * 80)
