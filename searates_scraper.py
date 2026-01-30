#!/usr/bin/env python3

"""
SeaRates Scraper for GitHub Actions
Automated container tracking with Cloudflare bypass + API Response Capture
OPTIMIZED: Single page load for both HTML and API capture
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

    def track_bol_with_api(self, bol_number, sealine="AUTO"):
        """
        COMBINED METHOD: Track shipment AND capture API in ONE browser session
        This saves your free daily search limit!
        """
        with SB(uc=True, headless=True, xvfb=True) as sb:
            self.sb = sb
            
            try:
                print(f"\n{'='*70}")
                print(f"TRACKING BOL: {bol_number}")
                print(f"SEALINE: {sealine}")
                print(f"{'='*70}\n")
                
                url = f"https://www.searates.com/container/tracking/?number={bol_number}&sealine={sealine}&shipment-type=sea"
                
                # STEP 1: Enable network monitoring BEFORE opening page
                print("[1/9] Enabling network monitoring...")
                try:
                    sb.driver.execute_cdp_cmd('Network.enable', {})
                    print("   ✓ Network monitoring enabled")
                except Exception as e:
                    print(f"   ⚠ CDP not available: {e}")
                
                # STEP 2: Open page with Cloudflare bypass
                print("[2/9] Opening page with Cloudflare bypass...")
                sb.uc_open_with_reconnect(url, reconnect_time=4)
                
                print("[3/9] Bypassing Cloudflare challenge...")
                sb.uc_gui_click_captcha()
                sb.sleep(3)
                
                print("[4/9] Waiting for tracking data + API calls...")
                sb.sleep(8)  # Wait for both HTML rendering AND API calls
                
                # STEP 3: Extract HTML data
                print("[5/9] Extracting basic tracking information...")
                tracking_data = self._extract_basic_data(sb)
                
                # STEP 4: Click Vessel tab
                print("\n[6/9] Switching to Vessel tab...")
                try:
                    sb.uc_click(f"[data-test-id='openedCard-vessels-tab-{bol_number}']", reconnect_time=2)
                    sb.sleep(3)
                    self._extract_vessel_data(sb, tracking_data)
                except Exception as e:
                    print(f"   ⚠ Could not access Vessel tab: {e}")
                
                # STEP 5: Click Containers tab
                print("\n[7/9] Switching to Containers tab...")
                try:
                    sb.uc_click(f"[data-test-id='openedCard-containers-tab-{bol_number}']", reconnect_time=2)
                    sb.sleep(3)
                    self._extract_containers_data(sb, tracking_data)
                except Exception as e:
                    print(f"   ⚠ Could not access Containers tab: {e}")
                
                # STEP 6: Capture API response (using Chrome DevTools Protocol)
                print("\n[8/9] Capturing API response...")
                api_data = self._capture_api_from_session(sb, bol_number)
                tracking_data['api_response'] = api_data
                
                # STEP 7: Screenshot
                print("[9/9] Taking screenshot...")
                screenshot = f"searates_{bol_number}_{int(time.time())}.png"
                sb.save_screenshot(screenshot)
                tracking_data['screenshot'] = screenshot
                print(f"   ✓ Screenshot saved: {screenshot}\n")
                
                return tracking_data
                
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

    def _capture_api_from_session(self, sb, bol_number):
        """
        Capture API response that already loaded in the page
        Extract from browser's internal state instead of making new request
        """
        try:
            # Method 1: Extract from window.__NUXT__ or similar global state
            print("   [+] Checking window objects...")
            
            window_check_script = """
            // Check common places where React/Next.js/Nuxt store data
            const checks = [];
            
            // Check __NEXT_DATA__
            if (window.__NEXT_DATA__) {
                checks.push({source: '__NEXT_DATA__', data: window.__NEXT_DATA__});
            }
            
            // Check __NUXT__
            if (window.__NUXT__) {
                checks.push({source: '__NUXT__', data: window.__NUXT__});
            }
            
            // Check Redux store
            if (window.__REDUX_DEVTOOLS_EXTENSION__) {
                try {
                    const state = window.__REDUX_DEVTOOLS_EXTENSION__.getState();
                    checks.push({source: 'redux', data: state});
                } catch(e) {}
            }
            
            // Check for tracking data in data attributes
            const trackingCards = document.querySelectorAll('[data-tracking-data]');
            if (trackingCards.length > 0) {
                try {
                    const data = JSON.parse(trackingCards[0].getAttribute('data-tracking-data'));
                    checks.push({source: 'data-attribute', data: data});
                } catch(e) {}
            }
            
            return checks;
            """
            
            window_data = sb.driver.execute_script(window_check_script)
            
            if window_data and len(window_data) > 0:
                for item in window_data:
                    print(f"   ✓ Found data in {item['source']}")
                    # Try to extract tracking data from the structure
                    extracted = self._extract_tracking_from_window_data(item['data'])
                    if extracted:
                        return {
                            'success': True,
                            'source': f"window_{item['source']}",
                            'data': extracted,
                            'captured_at': datetime.now().isoformat()
                        }
            
            # Method 2: Parse from page HTML/JSON embedded data
            print("   [+] Checking embedded JSON...")
            
            json_script = """
            // Look for JSON-LD or embedded JSON in script tags
            const scripts = document.querySelectorAll('script[type="application/json"]');
            const jsonData = [];
            
            for (let script of scripts) {
                try {
                    const data = JSON.parse(script.textContent);
                    if (data && typeof data === 'object') {
                        jsonData.push(data);
                    }
                } catch(e) {}
            }
            
            return jsonData;
            """
            
            embedded_json = sb.driver.execute_script(json_script)
            
            if embedded_json and len(embedded_json) > 0:
                for data in embedded_json:
                    if isinstance(data, dict) and 'containers' in str(data).lower():
                        print(f"   ✓ Found embedded tracking data")
                        return {
                            'success': True,
                            'source': 'embedded_json',
                            'data': data,
                            'captured_at': datetime.now().isoformat()
                        }
            
            # Method 3: If all else fails, note that HTML scraping worked
            print("   ⚠ Could not extract API format")
            print("   ℹ️ HTML scraping captured all visible data")
            return {
                'success': False,
                'error': 'API format not accessible',
                'note': 'All tracking data was captured via HTML scraping'
            }
            
        except Exception as e:
            print(f"   ⚠ Capture error: {e}")
            return {
                'success': False,
                'error': str(e),
                'note': 'HTML data captured successfully'
            }

    def _extract_tracking_from_window_data(self, data):
        """Helper to extract tracking data from window objects"""
        try:
            # Try different possible structures
            if isinstance(data, dict):
                # Check if it's the API response format
                if 'data' in data and 'containers' in data.get('data', {}):
                    return data
                
                # Check nested structures
                for key in ['props', 'pageProps', 'initialState', 'tracking', 'shipment']:
                    if key in data:
                        nested = data[key]
                        if isinstance(nested, dict) and 'containers' in nested:
                            return {'status': 'success', 'data': nested}
            
            return None
        except:
            return None

    def _extract_basic_data(self, sb):
        """Extract all basic tracking information"""
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
        
        # Extract coordinates
        coord_from = soup.find('input', attrs={'name': 'coord_from'})
        coord_to = soup.find('input', attrs={'name': 'coord_to'})
        if coord_from and coord_from.get('value'):
            try:
                data['coordinates']['from'] = json.loads(coord_from.get('value'))
            except:
                pass
        if coord_to and coord_to.get('value'):
            try:
                data['coordinates']['to'] = json.loads(coord_to.get('value'))
            except:
                pass
        
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
    
    json_file = f"data/{filename}.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\n✓ JSON saved: {json_file}")
    
    report_file = f"data/{filename}_report.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("="*70 + "\n")
        f.write("SEARATES TRACKING REPORT\n")
        f.write("="*70 + "\n\n")
        
        f.write(f"Reference: {data.get('reference_number', 'N/A')}\n")
        f.write(f"Status: {data.get('status', 'N/A')}\n")
        f.write(f"Carrier: {data.get('carrier', 'N/A')}\n")
        f.write(f"Route: {data.get('origin', 'N/A')} → {data.get('destination', 'N/A')}\n\n")
        
        f.write("VESSELS:\n")
        for i, v in enumerate(data.get('vessels', []), 1):
            f.write(f"[{i}] {v.get('vessel_name', 'N/A')} - Voyage {v.get('voyage', 'N/A')}\n")
        
        f.write("\nROUTE EVENTS:\n")
        for i, e in enumerate(data.get('route_events', []), 1):
            status = "✓" if e.get('is_completed') else "○"
            f.write(f"[{i}] {status} {e.get('location')}: {e.get('description')}\n")
    
    print(f"✓ Report saved: {report_file}")


def main():
    # Read BOL numbers
    try:
        with open('bol_list.txt', 'r') as f:
            bol_numbers = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except FileNotFoundError:
        print("⚠ bol_list.txt not found")
        bol_numbers = ["3100124492"]
    
    print("\n" + "="*70)
    print("SEARATES SCRAPER - OPTIMIZED (Single Page Load)")
    print("="*70)
    print(f"Processing {len(bol_numbers)} BOL(s)\n")
    
    scraper = SeaRatesScraper()
    all_results = []
    
    for bol in bol_numbers:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # COMBINED: HTML + API in ONE browser session
        results = scraper.track_bol_with_api(bol, "AUTO")
        
        if 'error' not in results:
            print("\n" + "="*70)
            print(f"SCRAPE SUMMARY - {bol}")
            print("="*70)
            print(f"Reference: {results.get('reference_number', 'N/A')}")
            print(f"Status: {results.get('status', 'N/A')}")
            print(f"Carrier: {results.get('carrier', 'N/A')}")
            print(f"Route: {results.get('origin', 'N/A')} → {results.get('destination', 'N/A')}")
            print(f"Vessels: {len(results.get('vessels', []))}")
            print(f"Events: {len(results.get('route_events', []))}")
            
            # Check if API was captured
            api_resp = results.get('api_response', {})
            if api_resp.get('success'):
                print(f"API Captured: ✓ Yes (via {api_resp.get('source')})")
            else:
                print(f"API Captured: ✗ No ({api_resp.get('error', 'unknown')})")
            
            # Save HTML data
            save_results(results, f"searates_html_{bol}_{timestamp}")
            
            # Save API data separately if captured
            if api_resp.get('success'):
                api_file = f"data/searates_api_{bol}_{timestamp}.json"
                with open(api_file, 'w', encoding='utf-8') as f:
                    json.dump(api_resp, f, indent=2, ensure_ascii=False)
                print(f"✓ API saved: {api_file}")
            
            all_results.append(results)
        else:
            print(f"\n❌ Failed: {bol}")
            all_results.append(results)
        
        # Wait between BOLs
        if len(bol_numbers) > 1:
            print("\n⏳ Waiting 10 seconds...")
            time.sleep(10)
    
    # Save combined
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    save_results({'bols': all_results, 'total': len(bol_numbers)}, f"combined_{timestamp}")
    
    print("\n" + "="*70)
    print(f"✓ COMPLETED: {len(bol_numbers)} BOL(S)")
    print("="*70)


if __name__ == "__main__":
    main()
