#!/usr/bin/env python3
"""
SeaRates Scraper with API Capture + HTML Scraping
Combines CDP Network monitoring with HTML scraping
"""

import os
import sys
from seleniumbase import SB
from bs4 import BeautifulSoup
import time
import json
from datetime import datetime
import re

class SeaRatesScraper:
    def __init__(self):
        """Initialize with UC Mode enabled"""
        self.sb = None
        self.captured_api = None

    def track_bol(self, bol_number, sealine="AUTO"):
        """Track shipment with API capture + HTML scraping"""
        
        # Use xvfb for virtual display in GitHub Actions
        with SB(uc=True, headless=True, xvfb=True) as sb:
            self.sb = sb
            
            try:
                print(f"\n{'='*70}")
                print(f"TRACKING BOL: {bol_number}")
                print(f"SEALINE: {sealine}")
                print(f"{'='*70}\n")
                
                url = f"https://www.searates.com/container/tracking/?number={bol_number}&sealine={sealine}&shipment-type=sea"
                
                # ============================================================
                # PHASE 1: ENABLE CDP NETWORK MONITORING (BEFORE PAGE LOADS)
                # ============================================================
                print("[1/8] Enabling CDP Network monitoring...")
                self._enable_network_capture(sb)
                print("   ✓ Network capture enabled")
                
                # ============================================================
                # PHASE 2: OPEN PAGE WITH CLOUDFLARE BYPASS
                # ============================================================
                print("[2/8] Opening page with Cloudflare bypass...")
                sb.uc_open_with_reconnect(url, reconnect_time=4)
                
                print("[3/8] Bypassing Cloudflare challenge...")
                sb.uc_gui_click_captcha()
                sb.sleep(3)
                
                # ============================================================
                # PHASE 3: WAIT FOR API CALL + CAPTURE IT
                # ============================================================
                print("[4/8] Waiting for tracking data + API call...")
                sb.sleep(5)  # Wait for API call to complete
                
                # Capture the API response
                print("[5/8] Capturing API response...")
                api_data = self._capture_api_response(sb, bol_number)
                
                # ============================================================
                # PHASE 4: HTML SCRAPING (ORIGINAL CODE - UNCHANGED)
                # ============================================================
                print("[6/8] Extracting HTML tracking information...")
                tracking_data = self._extract_basic_data(sb)
                
                # Click Vessel tab
                print("\n[7/8] Switching to Vessel tab...")
                try:
                    sb.uc_click(f"[data-test-id='openedCard-vessels-tab-{bol_number}']", reconnect_time=2)
                    sb.sleep(3)
                    self._extract_vessel_data(sb, tracking_data)
                except Exception as e:
                    print(f"   ⚠ Could not access Vessel tab: {e}")
                
                # Click Containers tab
                print("\n   Switching to Containers tab...")
                try:
                    sb.uc_click(f"[data-test-id='openedCard-containers-tab-{bol_number}']", reconnect_time=2)
                    sb.sleep(3)
                    self._extract_containers_data(sb, tracking_data)
                except Exception as e:
                    print(f"   ⚠ Could not access Containers tab: {e}")
                
                # Screenshot
                print("[8/8] Taking screenshot...")
                screenshot = f"searates_{bol_number}_{int(time.time())}.png"
                sb.save_screenshot(screenshot)
                tracking_data['screenshot'] = screenshot
                print(f"   ✓ Screenshot saved: {screenshot}\n")
                
                # ============================================================
                # COMBINE API + HTML DATA
                # ============================================================
                result = {
                    'bol_number': bol_number,
                    'captured_at': datetime.now().isoformat(),
                    'api_response': api_data,
                    'html_data': tracking_data
                }
                
                return result
                
            except Exception as e:
                print(f"\n❌ ERROR: {str(e)}")
                import traceback
                traceback.print_exc()
                
                screenshot = f"error_{int(time.time())}.png"
                try:
                    sb.save_screenshot(screenshot)
                except:
                    pass
                
                return {'error': str(e), 'screenshot': screenshot}

    def _enable_network_capture(self, sb):
        """Enable CDP Network domain to capture API requests"""
        try:
            # Enable Network domain via CDP
            sb.driver.execute_cdp_cmd('Network.enable', {})
            
            # Store captured responses
            sb.driver.execute_cdp_cmd('Network.setCacheDisabled', {'cacheDisabled': False})
            
        except Exception as e:
            print(f"   ⚠ Could not enable CDP Network: {e}")

    def _capture_api_response(self, sb, bol_number):
        """Capture the API response from network logs"""
        target_api = "tracking-system/reverse/tracking"
        
        try:
            # Method 1: Try to get from browser's performance logs
            print(f"   [+] Looking for API: {target_api}")
            
            # Check if the API call was made by inspecting network activity
            # We'll use JavaScript to check for the API call
            check_script = """
            // Check if fetch/XHR was made
            const entries = performance.getEntries().filter(e => 
                e.name && e.name.includes('tracking-system/reverse/tracking')
            );
            return entries.length > 0 ? entries[0].name : null;
            """
            
            api_url = sb.driver.execute_script(check_script)
            
            if api_url:
                print(f"   ✓ Found API call: {api_url}")
                
                # Try to fetch the response (might be cached)
                fetch_script = f"""
                var callback = arguments[arguments.length - 1];
                fetch('{api_url}', {{
                    credentials: 'include',
                    cache: 'force-cache'
                }})
                .then(response => response.json())
                .then(data => callback(data))
                .catch(error => callback(null));
                """
                
                try:
                    api_data = sb.driver.execute_async_script(fetch_script)
                    
                    if api_data:
                        # Validate response
                        if self._validate_api_response(api_data):
                            size = len(json.dumps(api_data))
                            print(f"   ✓ API captured successfully ({size:,} bytes)")
                            
                            # Save API response immediately
                            self._save_api_response(api_data, bol_number)
                            return api_data
                        else:
                            print(f"   ⚠ API response validation failed")
                            return api_data
                    
                except Exception as e:
                    print(f"   ⚠ Could not fetch API response: {e}")
            
            else:
                print(f"   ⚠ API call not found in performance logs")
            
            return None
            
        except Exception as e:
            print(f"   ✗ Error capturing API: {e}")
            return None

    def _validate_api_response(self, data):
        """Validate API response structure"""
        if not isinstance(data, dict):
            return False
        
        # Check for rate limit error
        if data.get('message') == 'API_KEY_LIMIT_REACHED':
            print(f"   ⚠ Rate limit reached (Free tier: 1 search/day)")
            return False
        
        expected_keys = ['status', 'message', 'data']
        if not all(key in data for key in expected_keys):
            return False
        
        if data.get('status') != 'success':
            return False
        
        data_section = data.get('data', {})
        expected_data_keys = ['metadata', 'containers', 'vessels']
        
        return all(key in data_section for key in expected_data_keys)

    def _save_api_response(self, api_data, bol_number):
        """Save API response to JSON file"""
        os.makedirs('data', exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        api_file = f"data/searates_api_{bol_number}_{timestamp}.json"
        
        with open(api_file, 'w', encoding='utf-8') as f:
            json.dump(api_data, f, indent=2, ensure_ascii=False)
        
        print(f"   ✓ API saved: {api_file}")

    def _extract_basic_data(self, sb):
        """Extract all basic tracking information from HTML"""
        soup = BeautifulSoup(sb.get_page_source(), 'html.parser')
        
        data = {
            'reference_number': None,
            'reference_type': None,
            'status': None,
            'carrier': None,
            'container_count': 0,
            'container_type': None,
            'origin': None,
            'destination': None,
            'actual_departure': None,
            'actual_arrival': None,
            'estimated_departure': None,
            'estimated_arrival': None,
            'coordinates': {'from': None, 'to': None},
            'route_events': [],
            'vessels': [],
            'containers': [],
            'scraped_at': datetime.now().isoformat()
        }
        
        # Extract reference number
        ref_elem = soup.find(attrs={'data-reference': True})
        if ref_elem:
            data['reference_number'] = ref_elem.get('data-reference')
            print(f"   ✓ Reference: {data['reference_number']}")
        
        # Extract reference type
        type_elem = soup.find(attrs={'data-test-id': 'card-reference-type'})
        if type_elem:
            data['reference_type'] = type_elem.get_text(strip=True)
            print(f"   ✓ Type: {data['reference_type']}")
        
        # Extract status
        status_elem = soup.find(attrs={'data-test-id': re.compile(r'card-status-')})
        if status_elem:
            data['status'] = status_elem.get_text(strip=True)
            print(f"   ✓ Status: {data['status']}")
        
        # Extract carrier
        carrier_img = soup.find('img', class_=re.compile(r'.*RhAQya.*'))
        if carrier_img and carrier_img.get('alt'):
            data['carrier'] = carrier_img.get('alt')
            print(f"   ✓ Carrier: {data['carrier']}")
        
        # Extract container count and type
        container_info = soup.find('div', class_=re.compile(r'.*NVumUP.*'))
        if container_info:
            text = container_info.get_text(strip=True)
            count_match = re.search(r'(\d+)\s*x', text)
            if count_match:
                data['container_count'] = int(count_match.group(1))
            
            type_match = re.search(r"x\s*(.+)", text)
            if type_match:
                data['container_type'] = type_match.group(1).strip()
            
            print(f"   ✓ Containers: {data['container_count']} x {data['container_type']}")
        
        # Extract origin
        origin_elem = soup.find(attrs={'data-test-id': re.compile(r'card-direction-from-')})
        if origin_elem:
            data['origin'] = origin_elem.get_text(strip=True)
            print(f"   ✓ Origin: {data['origin']}")
        
        # Extract destination
        dest_elem = soup.find(attrs={'data-test-id': re.compile(r'card-direction-to-')})
        if dest_elem:
            data['destination'] = dest_elem.get_text(strip=True)
            print(f"   ✓ Destination: {data['destination']}")
        
        # Extract dates
        date_section = soup.find('div', class_=re.compile(r'.*tOGj0n.*'))
        if date_section:
            date_texts = date_section.find_all('div', class_=re.compile(r'.*LPPMfj.*'))
            for date_text in date_texts:
                text = date_text.get_text(strip=True)
                if 'ATD' in text:
                    data['actual_departure'] = text.replace('ATD', '').strip()
                elif 'ATA' in text:
                    data['actual_arrival'] = text.replace('ATA', '').strip()
                elif 'ETD' in text:
                    data['estimated_departure'] = text.replace('ETD', '').strip()
                elif 'ETA' in text:
                    data['estimated_arrival'] = text.replace('ETA', '').strip()
        
        print(f"   ✓ Departure: {data['actual_departure'] or data['estimated_departure'] or 'N/A'}")
        print(f"   ✓ Arrival: {data['actual_arrival'] or data['estimated_arrival'] or 'N/A'}")
        
        # Extract route events
        self._extract_route_events(soup, data)
        
        return data

    def _extract_route_events(self, soup, data):
        """Extract route events timeline"""
        location_blocks = soup.find_all('div', class_=re.compile(r'.*CL5ccK.*'))
        
        if location_blocks:
            print(f"\n   ✓ Found {len(location_blocks)} location(s) in Route:")
            
            for block in location_blocks:
                location_elem = block.find('div', class_=re.compile(r'.*XMtlrn.*'))
                if not location_elem:
                    continue
                
                location = location_elem.get_text(strip=True)
                
                event_containers = block.find_all('div', class_=re.compile(r'.*WJvyRD.*'))
                if len(event_containers) >= 2:
                    descriptions_div = event_containers[0]
                    timestamps_div = event_containers[1]
                    
                    event_descs = descriptions_div.find_all('div', class_=re.compile(r'.*jKvQbb.*'))
                    timestamps = timestamps_div.find_all('div', class_=re.compile(r'.*jKvQbb.*'))
                    
                    for idx, desc_elem in enumerate(event_descs):
                        event = {
                            'location': location,
                            'description': desc_elem.get_text(strip=True),
                            'timestamp': timestamps[idx].get_text(strip=True) if idx < len(timestamps) else None,
                            'is_completed': 'SbA_5C' in desc_elem.get('class', [])
                        }
                        
                        data['route_events'].append(event)
                        
                        status_icon = "✓" if event['is_completed'] else "○"
                        print(f"     {status_icon} {location}: {event['description']} - {event['timestamp'] or 'Pending'}")

    def _extract_vessel_data(self, sb, data):
        """Extract vessel information"""
        soup = BeautifulSoup(sb.get_page_source(), 'html.parser')
        vessel_blocks = soup.find_all('div', class_=re.compile(r'.*g0DglG.*'))
        
        print(f"   ✓ Found {len(vessel_blocks)} vessel(s)\n")
        
        for idx, vessel_block in enumerate(vessel_blocks, 1):
            vessel = {
                'vessel_name': None, 'voyage': None,
                'loading_port': None, 'discharge_port': None,
                'atd': None, 'ata': None, 'etd': None, 'eta': None
            }
            
            fields = vessel_block.find_all('div', class_=re.compile(r'.*V3_o9s.*'))
            for field in fields:
                label_elem = field.find('div', class_=re.compile(r'.*HKyeYq.*'))
                value_elem = field.find('div', class_=re.compile(r'.*BGIaYF.*'))
                
                if label_elem and value_elem:
                    label = label_elem.get_text(strip=True)
                    value = value_elem.get_text(strip=True)
                    
                    mapping = {
                        'Vessel': 'vessel_name', 'Voyage': 'voyage',
                        'Loading': 'loading_port', 'Discharge': 'discharge_port',
                        'ATD': 'atd', 'ATA': 'ata', 'ETD': 'etd', 'ETA': 'eta'
                    }
                    
                    if label in mapping:
                        vessel[mapping[label]] = value
            
            data['vessels'].append(vessel)
            
            print(f"   [{idx}] Vessel: {vessel['vessel_name']}")
            print(f"       Voyage: {vessel['voyage']}")
            print(f"       Route: {vessel['loading_port']} → {vessel['discharge_port']}")
            print(f"       Departure: {vessel['atd'] or vessel['etd'] or 'N/A'}")
            print(f"       Arrival: {vessel['ata'] or vessel['eta'] or 'N/A'}\n")

    def _extract_containers_data(self, sb, data):
        """Extract container information"""
        soup = BeautifulSoup(sb.get_page_source(), 'html.parser')
        container_numbers = soup.find_all(string=re.compile(r'^[A-Z]{4}\d{7}$'))
        
        if container_numbers:
            print(f"   ✓ Found {len(container_numbers)} container(s)\n")
            
            for idx, container_num in enumerate(container_numbers, 1):
                container = {
                    'container_number': container_num.strip(),
                    'type': None, 'size': None, 'status': None
                }
                
                data['containers'].append(container)
                print(f"   [{idx}] Container: {container['container_number']}")
        else:
            print("   ⚠ No individual container details found")


def save_results(data, filename='searates_tracking'):
    """Save results to JSON and TXT"""
    os.makedirs('data', exist_ok=True)
    
    # Save combined JSON
    json_file = f"data/{filename}.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\n✓ Combined JSON saved: {json_file}")
    
    # Save HTML report
    html_data = data.get('html_data', {})
    report_file = f"data/{filename}_report.txt"
    
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("="*70 + "\n")
        f.write("SEARATES TRACKING REPORT\n")
        f.write("="*70 + "\n\n")
        
        f.write(f"Reference: {html_data.get('reference_number', 'N/A')}\n")
        f.write(f"Status: {html_data.get('status', 'N/A')}\n")
        f.write(f"Carrier: {html_data.get('carrier', 'N/A')}\n")
        f.write(f"Route: {html_data.get('origin', 'N/A')} → {html_data.get('destination', 'N/A')}\n\n")
        
        # API Status
        api_data = data.get('api_response')
        if api_data:
            if api_data.get('status') == 'success':
                f.write("API Status: ✓ Captured (Full data available)\n\n")
            else:
                f.write(f"API Status: {api_data.get('message', 'Failed')}\n\n")
        else:
            f.write("API Status: Not captured\n\n")
        
        f.write("VESSELS:\n")
        for i, v in enumerate(html_data.get('vessels', []), 1):
            f.write(f"[{i}] {v.get('vessel_name', 'N/A')} - Voyage {v.get('voyage', 'N/A')}\n")
        
        f.write("\nROUTE EVENTS:\n")
        for i, e in enumerate(html_data.get('route_events', []), 1):
            status = "✓" if e.get('is_completed') else "○"
            f.write(f"[{i}] {status} {e.get('location')}: {e.get('description')}\n")
    
    print(f"✓ Report saved: {report_file}")


def main():
    # Read BOL numbers from bol_list.txt
    try:
        with open('bol_list.txt', 'r') as f:
            bol_numbers = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except FileNotFoundError:
        print("⚠ bol_list.txt not found, using default BOL")
        bol_numbers = ["3100124492"]
    
    print("\n" + "="*70)
    print("SEARATES SCRAPER - API CAPTURE + HTML SCRAPING")
    print("="*70)
    print(f"Processing {len(bol_numbers)} BOL number(s)\n")
    
    scraper = SeaRatesScraper()
    all_results = []
    
    for bol in bol_numbers:
        results = scraper.track_bol(bol, "AUTO")
        
        if 'error' not in results:
            html_data = results.get('html_data', {})
            api_data = results.get('api_response')
            
            print("\n" + "="*70)
            print(f"SCRAPE SUMMARY - {bol}")
            print("="*70)
            print(f"Reference: {html_data.get('reference_number', 'N/A')}")
            print(f"Status: {html_data.get('status', 'N/A')}")
            print(f"Carrier: {html_data.get('carrier', 'N/A')}")
            print(f"Route: {html_data.get('origin', 'N/A')} → {html_data.get('destination', 'N/A')}")
            print(f"Vessels: {len(html_data.get('vessels', []))}")
            print(f"Events: {len(html_data.get('route_events', []))}")
            print(f"Containers: {len(html_data.get('containers', []))}")
            
            if api_data:
                if api_data.get('status') == 'success':
                    size = len(json.dumps(api_data))
                    print(f"API Captured: ✓ YES! ({size:,} bytes)")
                else:
                    print(f"API Captured: ⚠ {api_data.get('message', 'Failed')}")
            else:
                print(f"API Captured: ✗ NO")
            
            # Save results
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            save_results(results, f"searates_{bol}_{timestamp}")
            
            all_results.append(results)
        else:
            print(f"\n❌ Failed: {bol} - {results['error']}")
            all_results.append(results)
        
        # Wait between BOLs
        if len(bol_numbers) > 1:
            print("\n⏳ Waiting 10 seconds before next BOL...")
            time.sleep(10)
    
    # Save combined results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    save_results({
        'bols': all_results,
        'total': len(bol_numbers),
        'processed_at': timestamp
    }, f"combined_{timestamp}")
    
    print("\n" + "="*70)
    print(f"✓ COMPLETED: {len(bol_numbers)} BOL(S)")
    print("="*70)


if __name__ == "__main__":
    main()
