#!/usr/bin/env python3
"""
SeaRates Tracking API Scraper
Automated scraper for GitHub Actions - sends data to PHP API endpoint

Features:
- Captures full API response from SeaRates
- Sends tracking data to FreightManager API
- Supports multiple BOL numbers from bol_list.txt
- Saves results locally as backup
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
    Scrape SeaRates tracking API and capture full response
    """
    chrome_options = Options()
    
    # Required for GitHub Actions (headless mode)
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    # Enable performance logging to capture network traffic
    chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        # Open tracking page
        main_url = f"https://www.searates.com/container/tracking/?number={tracking_number}&sealine=AUTO&shipment-type=sea"
        print(f"[+] Opening: {main_url}")
        driver.get(main_url)
        
        # Wait for API call to complete
        print("[+] Waiting for API response...")
        time.sleep(10)
        
        # Target API endpoint pattern
        target_api = "tracking-system/reverse/tracking"
        
        # Get performance logs to find API response
        logs = driver.get_log('performance')
        target_request_id = None
        found_url = None
        
        # Find the API request in network logs
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
                        print(f"[✓] Found API endpoint")
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
                if validate_response(api_data):
                    print("[✓] Valid API response captured!")
                    return {
                        'success': True,
                        'data': api_data,
                        'tracking_number': tracking_number,
                        'captured_at': datetime.now().isoformat()
                    }
                else:
                    print(f"[!] Invalid response structure: {api_data.get('message', 'unknown')}")
                    return {
                        'success': False,
                        'error': api_data.get('message', 'Invalid response structure'),
                        'tracking_number': tracking_number,
                        'raw_response': api_data
                    }
                    
            except Exception as e:
                print(f"[✗] Error extracting response: {str(e)}")
                return {
                    'success': False,
                    'error': str(e),
                    'tracking_number': tracking_number
                }
        else:
            print("[✗] API endpoint not found in network logs")
            return {
                'success': False,
                'error': 'API endpoint not found',
                'tracking_number': tracking_number
            }
            
    except Exception as e:
        print(f"[✗] Unexpected error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'tracking_number': tracking_number
        }
        
    finally:
        print("[+] Closing browser...")
        driver.quit()


def validate_response(data):
    """Validate API response has expected structure"""
    if not isinstance(data, dict):
        return False
    
    # Check top-level structure
    if data.get('status') != 'success':
        return False
    
    # Check data section exists
    data_section = data.get('data', {})
    if not data_section:
        return False
    
    # Check required keys
    expected_keys = ['metadata', 'locations', 'route', 'vessels', 'containers']
    return all(key in data_section for key in expected_keys)


def send_to_api(api_data, api_url, api_key):
    """
    Send tracking data to PHP API endpoint
    """
    if not api_url or not api_key:
        print("[!] API credentials not configured, skipping API send")
        return None
    
    try:
        print(f"[+] Sending to API: {api_url[:50]}...")
        
        # The full API response is sent directly
        # The PHP endpoint expects the full JSON structure
        response = requests.post(
            api_url,
            headers={
                'Content-Type': 'application/json',
                'X-API-KEY': api_key
            },
            json=api_data,
            timeout=30
        )
        
        print(f"[+] API Response: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"[✓] API Success: {result.get('status', 'unknown')}")
            return result
        else:
            print(f"[✗] API Error: {response.text[:200]}")
            return {'error': response.text, 'status_code': response.status_code}
            
    except Exception as e:
        print(f"[✗] API Send Error: {str(e)}")
        return {'error': str(e)}


def save_results(tracking_number, data, results_dir='results'):
    """Save tracking data to JSON file"""
    os.makedirs(results_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if data.get('success') and data.get('data'):
        # Save full API response
        filename = f"tracking_{tracking_number}_full.json"
        filepath = os.path.join(results_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data['data'], f, indent=2, ensure_ascii=False)
        
        print(f"[✓] Saved: {filepath}")
        
        # Also save a summary
        summary = extract_summary(data['data'])
        summary_file = os.path.join(results_dir, f"tracking_{tracking_number}_summary.json")
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        return filepath
    else:
        # Save error info
        filename = f"tracking_{tracking_number}_error_{timestamp}.json"
        filepath = os.path.join(results_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"[!] Saved error: {filepath}")
        return filepath


def extract_summary(api_data):
    """Extract key summary information from API response"""
    data = api_data.get('data', {})
    metadata = data.get('metadata', {})
    route = data.get('route', {})
    
    # Build locations map
    locations = {loc['id']: f"{loc['name']}, {loc['country_code']}"
                for loc in data.get('locations', [])}
    
    # Get route info
    pol_loc_id = route.get('pol', {}).get('location')
    pod_loc_id = route.get('pod', {}).get('location')
    
    return {
        'tracking_number': metadata.get('number'),
        'status': metadata.get('status'),
        'sealine': metadata.get('sealine_name'),
        'sealine_code': metadata.get('sealine'),
        'origin': locations.get(pol_loc_id, 'Unknown'),
        'destination': locations.get(pod_loc_id, 'Unknown'),
        'departure_date': route.get('pol', {}).get('date'),
        'arrival_date': route.get('pod', {}).get('date'),
        'containers_count': len(data.get('containers', [])),
        'vessels_count': len(data.get('vessels', [])),
        'updated_at': metadata.get('updated_at')
    }


def print_summary(summary):
    """Print formatted summary"""
    print("\n" + "="*60)
    print("TRACKING SUMMARY")
    print("="*60)
    print(f"BOL Number:   {summary.get('tracking_number', 'N/A')}")
    print(f"Status:       {summary.get('status', 'N/A')}")
    print(f"Carrier:      {summary.get('sealine', 'N/A')} ({summary.get('sealine_code', '')})")
    print(f"Origin:       {summary.get('origin', 'N/A')}")
    print(f"Destination:  {summary.get('destination', 'N/A')}")
    print(f"Departure:    {summary.get('departure_date', 'N/A')}")
    print(f"ETA:          {summary.get('arrival_date', 'N/A')}")
    print(f"Containers:   {summary.get('containers_count', 0)}")
    print(f"Vessels:      {summary.get('vessels_count', 0)}")
    print(f"Last Update:  {summary.get('updated_at', 'N/A')}")
    print("="*60 + "\n")


def load_bol_list(filepath='bol_list.txt'):
    """Load BOL numbers from file"""
    bol_numbers = []
    
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if line and not line.startswith('#'):
                    bol_numbers.append(line)
    except FileNotFoundError:
        print(f"[!] {filepath} not found")
    
    return bol_numbers


def main():
    """Main execution"""
    print("="*60)
    print("SeaRates Tracking API Scraper")
    print("="*60)
    print(f"Started at: {datetime.now().isoformat()}\n")
    
    # Get API credentials from environment
    api_url = os.environ.get('PHP_API_URL', '')
    api_key = os.environ.get('PHP_API_KEY', '')
    
    if api_url and api_key:
        print(f"[✓] API endpoint configured")
    else:
        print("[!] API credentials not set - will only save locally")
    
    # Get BOL numbers
    if len(sys.argv) > 1:
        # Single BOL from command line
        bol_numbers = [sys.argv[1]]
        print(f"[+] Tracking single BOL: {sys.argv[1]}")
    else:
        # Load from bol_list.txt
        bol_numbers = load_bol_list()
        if not bol_numbers:
            print("[!] No BOL numbers found, using default")
            bol_numbers = ['3100124492']
    
    print(f"[+] Processing {len(bol_numbers)} BOL(s)\n")
    
    # Track results
    results = {
        'success': [],
        'failed': [],
        'api_sent': [],
        'api_failed': []
    }
    
    # Process each BOL
    for idx, bol in enumerate(bol_numbers, 1):
        print(f"\n{'='*60}")
        print(f"[{idx}/{len(bol_numbers)}] Processing BOL: {bol}")
        print("="*60)
        
        # Scrape tracking data
        scrape_result = scrape_searates_api(bol)
        
        # Save locally
        save_results(bol, scrape_result)
        
        if scrape_result.get('success'):
            results['success'].append(bol)
            
            # Print summary
            summary = extract_summary(scrape_result['data'])
            print_summary(summary)
            
            # Send to API
            if api_url and api_key:
                api_result = send_to_api(scrape_result['data'], api_url, api_key)
                
                if api_result and not api_result.get('error'):
                    results['api_sent'].append(bol)
                else:
                    results['api_failed'].append(bol)
        else:
            results['failed'].append(bol)
            print(f"[✗] Failed: {scrape_result.get('error', 'Unknown error')}")
        
        # Wait between requests to avoid rate limiting
        if idx < len(bol_numbers):
            print("\n[+] Waiting 15 seconds before next request...")
            time.sleep(15)
    
    # Final summary
    print("\n" + "="*60)
    print("FINAL RESULTS")
    print("="*60)
    print(f"Total BOLs:      {len(bol_numbers)}")
    print(f"Successful:      {len(results['success'])}")
    print(f"Failed:          {len(results['failed'])}")
    print(f"API Sent:        {len(results['api_sent'])}")
    print(f"API Failed:      {len(results['api_failed'])}")
    
    if results['failed']:
        print(f"\nFailed BOLs: {', '.join(results['failed'])}")
    
    print("\n" + "="*60)
    print(f"Completed at: {datetime.now().isoformat()}")
    print("="*60)
    
    # Exit with error if any failed
    if results['failed']:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
