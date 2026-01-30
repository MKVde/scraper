#!/usr/bin/env python3

"""
SeaRates Scraper for GitHub Actions
FIXED: CDP Network monitoring BEFORE page load to capture API response
"""

import os
import sys
from seleniumbase import SB
from bs4 import BeautifulSoup
import time
import json
from datetime import datetime
import re
import threading

class SeaRatesScraper:
    def __init__(self):
        """Initialize with UC Mode enabled"""
        self.sb = None
        self.captured_api_response = None

    def track_bol_with_api(self, bol_number, sealine="AUTO"):
        """
        FIXED: Network monitoring BEFORE page load
        """
        with SB(uc=True, headless=True, xvfb=True) as sb:
            self.sb = sb
            
            try:
                print(f"\n{'='*70}")
                print(f"TRACKING BOL: {bol_number}")
                print(f"SEALINE: {sealine}")
                print(f"{'='*70}\n")
                
                url = f"https://www.searates.com/container/tracking/?number={bol_number}&sealine={sealine}&shipment-type=sea"
                
                # CRITICAL: Enable CDP Network monitoring FIRST
                print("[1/9] Enabling CDP Network monitoring...")
                self._enable_network_capture(sb)
                
                # STEP 2: Open page (network already monitoring)
                print("[2/9] Opening page with Cloudflare bypass...")
                sb.uc_open_with_reconnect(url, reconnect_time=4)
                
                print("[3/9] Bypassing Cloudflare challenge...")
                sb.uc_gui_click_captcha()
                sb.sleep(3)
                
                print("[4/9] Waiting for tracking data + API calls...")
                sb.sleep(10)  # Give time for API call
                
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
                
                # STEP 6: Get captured API response
                print("\n[8/9] Retrieving captured API response...")
                api_data = self._get_captured_response(sb)
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

    def _enable_network_capture(self, sb):
        """
        Enable CDP Network domain and start capturing responses
        This MUST run BEFORE opening the page
        """
        try:
            # Enable Network domain
            sb.driver.execute_cdp_cmd('Network.enable', {})
            print("   ✓ CDP Network domain enabled")
            
            # Also inject JavaScript interceptor as backup
            intercept_script = """
            (function() {
                console.log('[SEARATES] Installing backup interceptor...');
                
                const originalXHR = XMLHttpRequest.prototype.open;
                const originalSend = XMLHttpRequest.prototype.send;
                
                XMLHttpRequest.prototype.open = function(method, url) {
                    this._url = url;
                    this._method = method;
                    return originalXHR.apply(this, arguments);
                };
                
                XMLHttpRequest.prototype.send = function() {
                    this.addEventListener('load', function() {
                        if (this._url && this._url.includes('tracking-system/reverse/tracking')) {
                            try {
                                const data = JSON.parse(this.responseText);
                                window.__SEARATES_API__ = data;
                                console.log('[SEARATES] ✓ Backup captured API');
                            } catch(e) {}
                        }
                    });
                    return originalSend.apply(this, arguments);
                };
                
                // Also override fetch
                const originalFetch = window.fetch;
                window.fetch = function(url, options) {
                    return originalFetch.apply(this, arguments).then(response => {
                        if (url.includes('tracking-system/reverse/tracking')) {
                            response.clone().json().then(data => {
                                window.__SEARATES_API__ = data;
                                console.log('[SEARATES] ✓ Backup captured via fetch');
                            }).catch(e => {});
                        }
                        return response;
                    });
                };
                
                console.log('[SEARATES] ✓ Backup interceptor ready');
            })();
            """
            
            # Inject before page loads
            sb.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': intercept_script
            })
            print("   ✓ Backup JavaScript interceptor injected")
            
        except Exception as e:
            print(f"   ⚠ Network monitoring setup failed: {e}")

    def _get_captured_response(self, sb):
        """
        Retrieve the captured API response using multiple methods
        """
        try:
            print("   [+] Method 1: Checking JavaScript backup...")
            
            # Check JavaScript backup first (most reliable)
            check_script = "return window.__SEARATES_API__ || null;"
            api_data = sb.driver.execute_script(check_script)
            
            if api_data and isinstance(api_data, dict):
                if api_data.get('status') == 'success':
                    size = len(json.dumps(api_data))
                    print(f"   ✓ SUCCESS! Captured from JavaScript backup ({size:,} bytes)")
                    return {
                        'success': True,
                        'source': 'javascript_backup',
                        'data': api_data,
                        'captured_at': datetime.now().isoformat(),
                        'size_bytes': size
                    }
                elif api_data.get('message') == 'API_KEY_LIMIT_REACHED':
                    print("   ⚠ API rate limit reached")
                    return {
                        'success': False,
                        'error': 'API_KEY_LIMIT_REACHED',
                        'note': 'Free tier: 1 search/day',
                        'raw_response': api_data
                    }
            
            # Method 2: Try CDP Network.getResponseBody
            print("   [+] Method 2: Checking CDP performance logs...")
            
            try:
                # Get performance entries to find request ID
                perf_script = """
                return performance.getEntries()
                    .filter(e => e.name && e.name.includes('tracking-system/reverse/tracking'))
                    .map(e => ({url: e.name, duration: e.duration}));
                """
                entries = sb.driver.execute_script(perf_script)
                
                if entries and len(entries) > 0:
                    print(f"   ✓ Found {len(entries)} API call(s)")
                    
                    # Try to get logs (may not work in UC mode)
                    try:
                        logs = sb.driver.get_log('performance')
                        target_request_id = None
                        
                        for log in logs:
                            try:
                                message = json.loads(log['message'])['message']
                                if message.get('method') == 'Network.responseReceived':
                                    params = message['params']
                                    response = params['response']
                                    if 'tracking-system/reverse/tracking' in response['url']:
                                        target_request_id = params['requestId']
                                        print(f"   ✓ Found request ID: {target_request_id[:20]}...")
                                        break
                            except:
                                continue
                        
                        if target_request_id:
                            response_body = sb.driver.execute_cdp_cmd('Network.getResponseBody', {
                                'requestId': target_request_id
                            })
                            body_content = response_body.get('body', '')
                            api_data = json.loads(body_content)
                            
                            if api_data:
                                size = len(json.dumps(api_data))
                                print(f"   ✓ SUCCESS! Captured via CDP ({size:,} bytes)")
                                return {
                                    'success': True,
                                    'source': 'cdp_performance_logs',
                                    'data': api_data,
                                    'captured_at': datetime.now().isoformat(),
                                    'size_bytes': size
                                }
                    except Exception as e:
                        print(f"   ⚠ Performance logs not available: {e}")
                else:
                    print("   ⚠ No API calls found in performance entries")
                    
            except Exception as e:
                print(f"   ⚠ CDP method failed: {e}")
            
            # Method 3: Try to re-fetch (will use cache/cost 0 calls)
            print("   [+] Method 3: Attempting cached fetch...")
            
            try:
                # Get the API URL from performance
                api_url_script = """
                const entries = performance.getEntries()
                    .filter(e => e.name && e.name.includes('tracking-system/reverse/tracking'));
                return entries.length > 0 ? entries[0].name : null;
                """
                api_url = sb.driver.execute_script(api_url_script)
                
                if api_url:
                    print(f"   ✓ Found API URL (length: {len(api_url)})")
                    
                    # Try async fetch (might be cached)
                    fetch_script = f"""
                    var callback = arguments[arguments.length - 1];
                    fetch('{api_url}', {{
                        credentials: 'include',
                        cache: 'force-cache'
                    }})
                    .then(r => r.json())
                    .then(data => callback(data))
                    .catch(e => callback(null));
                    """
                    
                    api_data = sb.driver.execute_async_script(fetch_script)
                    
                    if api_data and isinstance(api_data, dict):
                        size = len(json.dumps(api_data))
                        print(f"   ✓ SUCCESS! Fetched from cache ({size:,} bytes)")
                        return {
                            'success': True,
                            'source': 'cached_fetch',
                            'data': api_data,
                            'captured_at': datetime.now().isoformat(),
                            'size_bytes': size
                        }
            except Exception as e:
                print(f"   ⚠ Cached fetch failed: {e}")
            
            # All methods failed
            print("   ✗ All capture methods failed")
            return {
                'success': False,
                'error': 'All capture methods exhausted',
                'note': 'HTML scraping captured all visible data'
            }
            
        except Exception as e:
            print(f"   ✗ Capture error: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e),
                'note': 'HTML data captured successfully'
            }

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
    print("SEARATES SCRAPER - FIXED CDP CAPTURE")
    print("="*70)
    print(f"Processing {len(bol_numbers)} BOL(s)\n")
    
    scraper = SeaRatesScraper()
    all_results = []
    
    for bol in bol_numbers:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # COMBINED: HTML + FULL API in ONE browser session
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
            print(f"Containers: {len(results.get('containers', []))}")
            
            # Check if FULL API was captured
            api_resp = results.get('api_response', {})
            if api_resp.get('success'):
                size = api_resp.get('size_bytes', 0)
                source = api_resp.get('source', 'unknown')
                print(f"API Captured: ✓ YES! ({size:,} bytes via {source})")
            else:
                error = api_resp.get('error', 'unknown')
                print(f"API Captured: ✗ No ({error})")
            
            # Save HTML data
            save_results(results, f"searates_html_{bol}_{timestamp}")
            
            # Save FULL API data separately if captured
            if api_resp.get('success') and api_resp.get('data'):
                api_file = f"data/searates_api_FULL_{bol}_{timestamp}.json"
                with open(api_file, 'w', encoding='utf-8') as f:
                    json.dump(api_resp['data'], f, indent=2, ensure_ascii=False)
                size = len(json.dumps(api_resp['data']))
                print(f"✓ FULL API saved: {api_file} ({size:,} bytes)")
            
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
