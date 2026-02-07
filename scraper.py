from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import json
import time
import sys

def run_pipeline(tracking_number, keep_browser_open=False):
    """
    Scrape Tracking API - Automated mode for CI/CD
    """
    chrome_options = Options()
    
    # Required for GitHub Actions
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--disable-extensions')
    
    # Enable performance logging
    chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        # Open tracking page
        main_url = f"https://www.searates.com/container/tracking/?number={tracking_number}&sealine=AUTO&shipment-type=sea"
        print(f"[+] Opening tracking page")
        driver.get(main_url)
        
        # Wait for API call
        print("[+] Waiting for data stream...")
        time.sleep(8)
        
        # Target API endpoint
        target_api = "tracking-system/reverse/tracking"
        
        # Get performance logs
        logs = driver.get_log('performance')
        target_request_id = None
        found_url = None
        
        # Find the API request
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
                        print(f"[✓] Data stream located")
                        break
            except:
                continue
        
        # Get response body
        if target_request_id:
            try:
                response_body = driver.execute_cdp_cmd('Network.getResponseBody', {
                    'requestId': target_request_id
                })
                body_content = response_body.get('body', '')
                api_data = json.loads(body_content)
                
                # Validate response structure
                print("\n[+] Validating data structure...")
                is_valid = validate_response(api_data)
                
                if is_valid:
                    print("[✓] Data structure is valid!")
                    
                    # Save full response
                    output_file = f"tracking_{tracking_number}_full.json"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(api_data, f, indent=2, ensure_ascii=False)
                    print(f"[✓] Saved to: {output_file}")
                    
                    # Extract and save key info
                    extracted = extract_key_info(api_data)
                    extracted_file = f"tracking_{tracking_number}_summary.json"
                    with open(extracted_file, 'w', encoding='utf-8') as f:
                        json.dump(extracted, f, indent=2, ensure_ascii=False)
                    print(f"[✓] Saved summary to: {extracted_file}")
                    
                    # Display summary
                    print_summary(extracted)
                    
                    return api_data
                else:
                    print("[!] Warning: partial data match")
                    return api_data
                    
            except Exception as e:
                print(f"[✗] Error processing data: {str(e)}")
                return None
        else:
            print("[✗] Data stream source not found")
            return None
            
    except Exception as e:
        print(f"[✗] Unexpected error: {str(e)}")
        return None
        
    finally:
        print("\n[+] Releasing resources...")
        driver.quit()

def validate_response(data):
    """Validate response structure"""
    if not isinstance(data, dict):
        return False
    return True

def extract_key_info(api_data):
    """Extract key information"""
    data = api_data.get('data', {})
    metadata = data.get('metadata', {})
    route = data.get('route', {})
    
    # Get location names
    locations = {loc['id']: loc['name'] + ', ' + loc['country']
                for loc in data.get('locations', [])}
    
    # Extract route summary
    route_summary = {}
    if 'prepol' in route:
        route_summary['origin'] = locations.get(route['prepol']['location'], 'Unknown')
        route_summary['departure_date'] = route['prepol']['date']
    
    if 'pod' in route:
        route_summary['destination'] = locations.get(route['pod']['location'], 'Unknown')
        route_summary['eta'] = route['pod']['date']
        route_summary['eta_predictive'] = route['pod'].get('predictive_eta')
    
    # Extract container info
    containers_summary = []
    for container in data.get('containers', []):
        events = container.get('events', [])
        latest_event = events[-1] if events else {}
        
        containers_summary.append({
            'number': container['number'],
            'type': container.get('size_type', 'Unknown'),
            'status': container['status'],
            'latest_event': {
                'description': latest_event.get('description'),
                'date': latest_event.get('date'),
                'location': locations.get(latest_event.get('location'), 'Unknown')
            }
        })
    
    # Extract vessel info
    vessels_summary = [
        {
            'name': v['name'],
            'imo': v.get('imo'),
            'flag': v.get('flag')
        }
        for v in data.get('vessels', [])
    ]
    
    return {
        'tracking_number': metadata.get('number'),
        'shipping_line': metadata.get('sealine_name'),
        'status': metadata.get('status'),
        'updated_at': metadata.get('updated_at'),
        'route': route_summary,
        'containers': containers_summary,
        'vessels': vessels_summary,
        'total_containers': len(containers_summary)
    }

def print_summary(extracted):
    """Print a formatted summary"""
    print("\n" + "="*60)
    print("TRACKING SUMMARY")
    print("="*60)
    print(f"Tracking Number: {extracted['tracking_number']}")
    print(f"Updated: {extracted['updated_at']}")
    print("="*60)

# Main execution
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scraper.py <tracking_number>")
        sys.exit(1)
        
    tracking_number = sys.argv[1]
    
    print("="*60)
    print("Tracking Data Pipeline")
    print("="*60)
    
    api_data = run_pipeline(tracking_number, keep_browser_open=False)
    
    if api_data:
        print("\n[✓] Pipeline completed successfully.")
        sys.exit(0)
    else:
        print("\n[✗] Pipeline failed.")
        sys.exit(1)
