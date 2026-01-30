#!/usr/bin/env python3
"""
SeaRates API Scraper - Full API Capture
Uses Selenium with CDP to capture the complete tracking API response
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import json
import time
import sys
import os
import requests
from datetime import datetime


def scrape_searates_api(tracking_number):
    """
    Scrape SeaRates tracking API using CDP network capture
    Returns the full API JSON response
    """
    chrome_options = Options()
    
    # Required for GitHub Actions headless mode
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--disable-extensions')
    
    # Enable performance logging for CDP
    chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        # Open tracking page
        url = f"https://www.searates.com/container/tracking/?number={tracking_number}&sealine=AUTO&shipment-type=sea"
        print(f"[+] Opening: {url}")
        driver.get(url)
        
        # Wait for API call to complete
        print("[+] Waiting for API response...")
        time.sleep(8)
        
        # Target API endpoint
        target_api = "tracking-system/reverse/tracking"
        
        # Get performance logs
        logs = driver.get_log('performance')
        target_request_id = None
        found_url = None
        
        # Find the API request in logs
        for log in logs:
            try:
                message = json.loads(log['message'])['message']
                if message.get('method') == 'Network.responseReceived':
                    params = message['params']
                    response = params['response']
                    response_url = response['url']
                    
                    if target_api in response_url and response.get('status') == 200:
                        target_request_id = params['requestId']
                        found_url = response_url
                        print(f"[✓] Found API: {response_url[:80]}...")
                        break
            except:
                continue
        
        # Get response body using CDP
        if target_request_id:
            try:
                response_body = driver.execute_cdp_cmd('Network.getResponseBody', {
                    'requestId': target_request_id
                })
                body_content = response_body.get('body', '')
                api_data = json.loads(body_content)
                
                # Validate response structure
                print("\n[+] Validating response structure...")
                is_valid = validate_response(api_data)
                
                if is_valid:
                    print("[✓] Response structure is correct!")
                    return api_data
                else:
                    print("[!] Warning: Response structure doesn't match expected format")
                    print(f"[!] Keys found: {list(api_data.keys())}")
                    return api_data
                    
            except Exception as e:
                print(f"[✗] Error extracting response: {str(e)}")
                return None
        else:
            print("[✗] Target API not found in network logs")
            return None
            
    except Exception as e:
        print(f"[✗] Unexpected error: {str(e)}")
        return None
        
    finally:
        print("\n[+] Closing browser...")
        driver.quit()


def validate_response(data):
    """Validate API response has expected structure"""
    if not isinstance(data, dict):
        return False
    
    expected_keys = ['status', 'message', 'data']
    if not all(key in data for key in expected_keys):
        return False
    
    if data.get('status') != 'success':
        return False
    
    data_section = data.get('data', {})
    expected_data_keys = ['metadata', 'locations', 'route', 'vessels', 'containers']
    return all(key in data_section for key in expected_data_keys)


def send_to_php_api(api_data, php_url, api_key):
    """Send the full API data to PHP endpoint"""
    try:
        print(f"\n[+] Sending data to PHP API...")
        
        headers = {
            'X-API-KEY': api_key,
            'Content-Type': 'application/json'
        }
        
        response = requests.post(
            php_url,
            headers=headers,
            json=api_data,
            timeout=30
        )
        
        print(f"[+] Response status: {response.status_code}")
        print(f"[+] Response body: {response.text}")
        
        return response.status_code == 200
        
    except Exception as e:
        print(f"[✗] Failed to send to API: {str(e)}")
        return False


def print_summary(api_data):
    """Print a formatted summary of tracking data"""
    data = api_data.get('data', {})
    metadata = data.get('metadata', {})
    containers = data.get('containers', [])
    vessels = data.get('vessels', [])
    locations = {loc['id']: loc for loc in data.get('locations', [])}
    route = data.get('route', {})
    
    # Get POL/POD
    pol_id = route.get('pol', {}).get('location')
    pod_id = route.get('pod', {}).get('location')
    pol = locations.get(pol_id, {})
    pod = locations.get(pod_id, {})
    
    print("\n" + "="*60)
    print("TRACKING SUMMARY")
    print("="*60)
    print(f"BOL Number: {metadata.get('number')}")
    print(f"Shipping Line: {metadata.get('sealine_name')} ({metadata.get('sealine')})")
    print(f"Status: {metadata.get('status')}")
    print(f"Updated: {metadata.get('updated_at')}")
    
    print("\n--- ROUTE ---")
    print(f"From: {pol.get('name', 'N/A')}, {pol.get('country', '')}")
    print(f"To: {pod.get('name', 'N/A')}, {pod.get('country', '')}")
    print(f"ETD: {route.get('pol', {}).get('date', 'N/A')}")
    print(f"ETA: {route.get('pod', {}).get('date', 'N/A')}")
    
    print(f"\n--- CONTAINERS ({len(containers)}) ---")
    for idx, container in enumerate(containers[:3], 1):
        print(f"{idx}. {container.get('number')} - {container.get('size_type')} - {container.get('status')}")
    if len(containers) > 3:
        print(f"... and {len(containers) - 3} more containers")
    
    print("\n--- VESSELS ---")
    for vessel in vessels:
        imo = vessel.get('imo') or 'N/A'
        print(f"- {vessel.get('name')} (IMO: {imo}, Flag: {vessel.get('flag', 'N/A')})")
    
    print("="*60)


def main():
    """Main entry point"""
    # Get tracking number from argument or bol_list.txt
    if len(sys.argv) > 1:
        tracking_numbers = [sys.argv[1]]
    else:
        try:
            with open('bol_list.txt', 'r') as f:
                tracking_numbers = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        except FileNotFoundError:
            print("[!] No tracking number provided and bol_list.txt not found")
            sys.exit(1)
    
    # Get API credentials from environment
    php_url = os.environ.get('PHP_API_URL', '')
    php_api_key = os.environ.get('PHP_API_KEY', '')
    
    print("="*60)
    print("SeaRates API Scraper - Full API Capture")
    print("="*60)
    print(f"Tracking {len(tracking_numbers)} BOL(s)")
    
    # Create results directory
    os.makedirs('results', exist_ok=True)
    
    success_count = 0
    
    for tracking_number in tracking_numbers:
        print(f"\n{'='*60}")
        print(f"Processing: {tracking_number}")
        print("="*60)
        
        # Scrape the API
        api_data = scrape_searates_api(tracking_number)
        
        if api_data:
            # Print summary
            print_summary(api_data)
            
            # Save to file
            output_file = f"results/tracking_{tracking_number}_full.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(api_data, f, indent=2, ensure_ascii=False)
            print(f"\n[✓] Saved to: {output_file}")
            
            # Send to PHP API if credentials are set
            if php_url and php_api_key:
                if send_to_php_api(api_data, php_url, php_api_key):
                    print("[✓] Successfully sent to PHP API")
                    success_count += 1
                else:
                    print("[✗] Failed to send to PHP API")
            else:
                print("[!] PHP API credentials not set - skipping API send")
                success_count += 1  # Still count as success if file was saved
        else:
            print(f"\n[✗] Failed to scrape: {tracking_number}")
        
        # Wait between requests
        if len(tracking_numbers) > 1:
            print("\n[+] Waiting 10 seconds before next request...")
            time.sleep(10)
    
    print(f"\n{'='*60}")
    print(f"COMPLETED: {success_count}/{len(tracking_numbers)} successful")
    print("="*60)
    
    # Exit with appropriate code
    sys.exit(0 if success_count > 0 else 1)


if __name__ == "__main__":
    main()
