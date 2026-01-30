#!/usr/bin/env python3
"""
SeaRates Scraper with CDP Network Monitoring + HTML Scraping
Captures API response AND HTML data for GitHub Actions
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
        """Initialize scraper"""
        self.sb = None
        self.captured_api_data = None
        
    def track_bol(self, bol_number, sealine="AUTO"):
        """Track shipment with API capture + HTML scraping"""
        
        with SB(uc=True, headless=True, xvfb=True) as sb:
            self.sb = sb
            
            try:
                print(f"\n{'='*70}")
                print(f"TRACKING BOL: {bol_number}")
                print(f"SEALINE: {sealine}")
                print(f"{'='*70}\n")
                
                # Build URL
                url = f"https://www.searates.com/container/tracking/?number={bol_number}&sealine={sealine}&shipment-type=sea"
                
                # STEP 1: Enable CDP Network monitoring BEFORE opening page
                print("[1/8] Enabling CDP Network monitoring...")
                try:
                    sb.driver.execute_cdp_cmd('Network.enable', {})
                    print("   ✓ Network monitoring enabled")
                except Exception as e:
                    print(f"   ⚠ CDP not available: {e}")
                
                # STEP 2: Open page with Cloudflare bypass
                print("[2/8] Opening page with Cloudflare bypass...")
                sb.uc_open_with_reconnect(url, reconnect_time=4)
                
                print("[3/8] Bypassing Cloudflare challenge...")
                sb.uc_gui_click_captcha()
                sb.sleep(3)
                
                # STEP 3: Wait for tracking data + API calls
                print("[4/8] Waiting for tracking data + API calls...")
                sb.sleep(6)
                
                # STEP 4: Capture API response from CDP
                print("[5/8] Capturing API response...")
                self.captured_api_data = self._capture_api_response(sb, bol_number)
                
                # STEP 5: Extract HTML data (as before)
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
                
                # Return to Route tab
                try:
                    sb.uc_click(f"[data-test-id='openedCard-routes-tab-{bol_number}']", reconnect_time=2)
                    sb.sleep(2)
                except:
                    pass
                
                # Screenshot
                print("[8/8] Taking screenshot...")
                screenshot = f"searates_{bol_number}_{int(time.time())}.png"
                sb.save_screenshot(screenshot)
                tracking_data['screenshot'] = screenshot
                print(f"   ✓ Screenshot saved: {screenshot}\n")
                
                # Combine HTML + API data
                return {
                    'html_data': tracking_data,
                    'api_data': self.captured_api_data
                }
                
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
    
    def _capture_api_response(self, sb, bol_number):
        """Capture API response using CDP Network monitoring"""
        target_api = "tracking-system/reverse/tracking"
        
        try:
            # Get network logs via CDP
            perf_script = """
            return performance.getEntries()
                .filter(e => e.name && e.name.includes('tracking-system/reverse/tracking'))
                .map(e => ({
                    url: e.name,
                    duration: e.duration,
                    startTime: e.startTime
                }));
            """
            
            entries = sb.driver.execute_script(perf_script)
            
            if not entries or len(entries) == 0:
                print("   ⚠ No API calls found in performance logs")
                return None
            
            print(f"   ✓ Found {len(entries)} API call(s)")
            api_url = entries[0]['url']
            print(f"   ✓ API URL: {api_url[:80]}...")
            
            # Method 1: Try to fetch from cache
            print("   [+] Attempting to fetch API response...")
            
            fetch_script = f"""
            var callback = arguments[arguments.length - 1];
            fetch('{api_url}', {{
                credentials: 'include',
                cache: 'force-cache'
            }})
            .then(r => r.json())
            .then(data => callback({{success: true, data: data}}))
            .catch(e => callback({{success: false, error: e.toString()}}));
            """
            
            result = sb.driver.execute_async_script(fetch_script)
            
            if result.get('success') and result.get('data'):
                api_data = result['data']
                
                # Check for rate limit
                if api_data.get('message') == 'API_KEY_LIMIT_REACHED':
                    print("   ⚠ SeaRates API rate limit reached (1 search/day)")
                    print("   ℹ️ HTML data captured successfully")
                    return {
                        'status': 'rate_limited',
                        'message': 'Free tier limit reached',
                        'raw_response': api_data
                    }
                
                # Success!
                if api_data.get('status') == 'success':
                    size = len(json.dumps(api_data))
                    print(f"   ✓ SUCCESS! Captured API response ({size:,} bytes)")
                    
                    # Validate structure
                    data_section = api_data.get('data', {})
                    containers = data_section.get('containers', [])
                    vessels = data_section.get('vessels', [])
                    
                    print(f"   ✓ Containers: {len(containers)}")
                    print(f"   ✓ Vessels: {len(vessels)}")
                    
                    return {
                        'status': 'success',
                        'source': 'fetch_cache',
                        'data': api_data,
                        'size_bytes': size,
                        'captured_at': datetime.now().isoformat()
                    }
            
            print("   ⚠ Could not fetch API response")
            return None
            
        except Exception as e:
            print(f"   ✗ API capture error: {e}")
            return None
    
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
    print(f"\n✓ JSON saved: {json_file}")
    
    # Save API data separately if available
    if data.get('api_data') and data['api_data'].get('status') == 'success':
        api_file = f"data/{filename}_API_FULL.json"
        with open(api_file, 'w', encoding='utf-8') as f:
            json.dump(data['api_data']['data'], f, indent=2, ensure_ascii=False)
        
        size = data['api_data'].get('size_bytes', 0)
        print(f"✓ API data saved: {api_file} ({size:,} bytes)")
    
    # Save text report
    report_file = f"data/{filename}_report.txt"
    html_data = data.get('html_data', {})
    
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("="*70 + "\n")
        f.write("SEARATES TRACKING REPORT\n")
        f.write("="*70 + "\n\n")
        
        f.write(f"Reference: {html_data.get('reference_number', 'N/A')}\n")
        f.write(f"Status: {html_data.get('status', 'N/A')}\n")
        f.write(f"Carrier: {html_data.get('carrier', 'N/A')}\n")
        f.write(f"Route: {html_data.get('origin', 'N/A')} → {html_data.get('destination', 'N/A')}\n\n")
        
        f.write("VESSELS:\n")
        for i, v in enumerate(html_data.get('vessels', []), 1):
            f.write(f"[{i}] {v.get('vessel_name', 'N/A')} - Voyage {v.get('voyage', 'N/A')}\n")
        
        f.write("\nCONTAINERS:\n")
        for i, c in enumerate(html_data.get('containers', []), 1):
            f.write(f"[{i}] {c.get('container_number', 'N/A')}\n")
        
        f.write("\nROUTE EVENTS:\n")
        for i, e in enumerate(html_data.get('route_events', []), 1):
            status = "✓" if e.get('is_completed') else "○"
            f.write(f"[{i}] {status} {e.get('location')}: {e.get('description')}\n")
        
        # API capture status
        f.write("\n" + "="*70 + "\n")
        f.write("API CAPTURE STATUS\n")
        f.write("="*70 + "\n")
        
        api_data = data.get('api_data')
        if api_data:
            if api_data.get('status') == 'success':
                f.write(f"✓ API captured successfully ({api_data.get('size_bytes', 0):,} bytes)\n")
            elif api_data.get('status') == 'rate_limited':
                f.write("⚠ API rate limited (HTML data captured)\n")
        else:
            f.write("✗ API not captured (HTML data captured)\n")
    
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
    print(f"Processing {len(bol_numbers)} BOL(s)\n")
    
    scraper = SeaRatesScraper()
    all_results = []
    
    for bol in bol_numbers:
        results = scraper.track_bol(bol, "AUTO")
        
        if 'error' not in results:
            html_data = results.get('html_data', {})
            api_data = results.get('api_data', {})
            
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
            
            if api_data and api_data.get('status') == 'success':
                print(f"API Captured: ✓ YES! ({api_data.get('size_bytes', 0):,} bytes)")
            elif api_data and api_data.get('status') == 'rate_limited':
                print(f"API Captured: ⚠ RATE LIMITED")
            else:
                print(f"API Captured: ✗ NO (HTML data available)")
            
            # Save results
            save_results(results, f"searates_{bol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            
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
    save_results({'bols': all_results, 'total': len(bol_numbers)}, f"combined_{timestamp}")
    
    print("\n" + "="*70)
    print(f"✓ COMPLETED: {len(bol_numbers)} BOL(S)")
    print("="*70)


if __name__ == "__main__":
    main()
