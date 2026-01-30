#!/usr/bin/env python3
"""
SeaRates Unified Scraper - GitHub Actions Ready
Combines: Full API capture + HTML scraping + Cloudflare bypass
"""

import os
import sys
from seleniumbase import SB
from bs4 import BeautifulSoup
import time
import json
from datetime import datetime
import re

class UnifiedSeaRatesScraper:
    def __init__(self):
        """Initialize unified scraper"""
        self.sb = None
        self.api_captured = False

    def track(self, bol_number, sealine="AUTO"):
        """
        Unified tracking with API + HTML fallback
        """
        with SB(uc=True, headless=True, xvfb=True) as sb:
            self.sb = sb
            
            try:
                print(f"\n{'='*70}")
                print(f"🚢 TRACKING: {bol_number} | SEALINE: {sealine}")
                print(f"{'='*70}\n")
                
                url = f"https://www.searates.com/container/tracking/?number={bol_number}&sealine={sealine}&shipment-type=sea"
                
                # STEP 1: Enable network capture BEFORE page load
                print("[1/10] 🔧 Enabling API capture...")
                self._enable_api_capture(sb)
                
                # STEP 2: Open page with Cloudflare bypass
                print("[2/10] 🌐 Opening page (bypassing Cloudflare)...")
                sb.uc_open_with_reconnect(url, reconnect_time=4)
                
                print("[3/10] 🛡️  Handling Cloudflare challenge...")
                sb.uc_gui_click_captcha()
                sb.sleep(3)
                
                print("[4/10] ⏳ Waiting for tracking data & API...")
                sb.sleep(10)  # Wait for all API calls
                
                # STEP 3: Capture FULL API response (PRIMARY METHOD)
                print("\n[5/10] 📡 Capturing FULL API response...")
                api_data = self._capture_full_api(sb)
                
                # STEP 4: Extract HTML data (FALLBACK + VALIDATION)
                print("\n[6/10] 📄 Extracting HTML data...")
                html_data = self._extract_basic_data(sb, bol_number)
                
                # STEP 5: Extract vessel details
                print("\n[7/10] 🚢 Extracting vessel information...")
                try:
                    sb.uc_click(f"[data-test-id='openedCard-vessels-tab-{bol_number}']", reconnect_time=2)
                    sb.sleep(3)
                    self._extract_vessel_data(sb, html_data)
                except Exception as e:
                    print(f"   ⚠️  Vessel tab: {e}")
                
                # STEP 6: Extract container details
                print("\n[8/10] 📦 Extracting container information...")
                try:
                    sb.uc_click(f"[data-test-id='openedCard-containers-tab-{bol_number}']", reconnect_time=2)
                    sb.sleep(3)
                    self._extract_containers_data(sb, html_data)
                except Exception as e:
                    print(f"   ⚠️  Containers tab: {e}")
                
                # STEP 7: Take screenshot
                print("\n[9/10] 📸 Taking screenshot...")
                screenshot = f"searates_{bol_number}_{int(time.time())}.png"
                sb.save_screenshot(screenshot)
                print(f"   ✅ {screenshot}")
                
                # STEP 8: Combine results
                print("\n[10/10] 🔄 Combining results...")
                result = self._merge_data(api_data, html_data, screenshot, bol_number)
                
                self._print_summary(result)
                
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

    def _enable_api_capture(self, sb):
        """
        Enable CDP + JavaScript interceptors to capture API
        """
        try:
            # Method 1: CDP Network
            sb.driver.execute_cdp_cmd('Network.enable', {})
            
            # Method 2: Enable performance logging
            sb.driver.execute_cdp_cmd('Performance.enable', {})
            
            print("   ✅ CDP Network enabled")
            
            # Method 3: JavaScript XHR/Fetch interceptor (MOST RELIABLE)
            intercept_script = """
            (function() {
                console.log('[UNIFIED] Installing API interceptor...');
                
                // Store API data globally
                window.__SEARATES_API__ = null;
                window.__API_CAPTURED__ = false;
                
                // Intercept XMLHttpRequest
                const originalOpen = XMLHttpRequest.prototype.open;
                const originalSend = XMLHttpRequest.prototype.send;
                
                XMLHttpRequest.prototype.open = function(method, url) {
                    this._url = url;
                    this._method = method;
                    return originalOpen.apply(this, arguments);
                };
                
                XMLHttpRequest.prototype.send = function() {
                    this.addEventListener('load', function() {
                        if (this._url && this._url.includes('tracking-system/reverse/tracking')) {
                            try {
                                const data = JSON.parse(this.responseText);
                                window.__SEARATES_API__ = data;
                                window.__API_CAPTURED__ = true;
                                console.log('[UNIFIED] ✓ XHR API captured!', data);
                            } catch(e) {
                                console.error('[UNIFIED] Parse error:', e);
                            }
                        }
                    });
                    return originalSend.apply(this, arguments);
                };
                
                // Intercept Fetch API
                const originalFetch = window.fetch;
                window.fetch = function(url, options) {
                    return originalFetch.apply(this, arguments).then(response => {
                        if (url.includes('tracking-system/reverse/tracking')) {
                            response.clone().json().then(data => {
                                window.__SEARATES_API__ = data;
                                window.__API_CAPTURED__ = true;
                                console.log('[UNIFIED] ✓ Fetch API captured!', data);
                            }).catch(e => console.error('[UNIFIED] Fetch parse error:', e));
                        }
                        return response;
                    });
                };
                
                console.log('[UNIFIED] ✓ Interceptor ready!');
            })();
            """
            
            # Inject BEFORE page loads
            sb.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': intercept_script
            })
            
            print("   ✅ JavaScript interceptor injected")
            
        except Exception as e:
            print(f"   ⚠️  Setup warning: {e}")

    def _capture_full_api(self, sb):
        """
        Capture FULL API response using multiple methods
        Priority: JavaScript backup > CDP logs > Performance API
        """
        result = {
            'success': False,
            'source': None,
            'data': None,
            'error': None,
            'captured_at': datetime.now().isoformat()
        }
        
        # METHOD 1: JavaScript backup (MOST RELIABLE)
        print("   [Method 1] Checking JavaScript interceptor...")
        try:
            check_script = "return window.__SEARATES_API__ || null;"
            api_data = sb.driver.execute_script(check_script)
            
            if api_data and isinstance(api_data, dict):
                if api_data.get('status') == 'success':
                    size = len(json.dumps(api_data))
                    print(f"   ✅ SUCCESS! JavaScript captured {size:,} bytes")
                    result['success'] = True
                    result['source'] = 'javascript_interceptor'
                    result['data'] = api_data
                    result['size_bytes'] = size
                    self.api_captured = True
                    return result
                elif api_data.get('message') == 'API_KEY_LIMIT_REACHED':
                    print("   ⚠️  API rate limit reached")
                    result['error'] = 'rate_limit'
                    result['data'] = api_data
                    return result
        except Exception as e:
            print(f"   ⚠️  Method 1 failed: {e}")
        
        # METHOD 2: CDP Performance Logs
        print("   [Method 2] Checking CDP performance logs...")
        try:
            logs = sb.driver.get_log('performance')
            target_request_id = None
            
            for log in logs:
                try:
                    message = json.loads(log['message'])['message']
                    if message.get('method') == 'Network.responseReceived':
                        params = message['params']
                        response = params['response']
                        response_url = response['url']
                        
                        if 'tracking-system/reverse/tracking' in response_url and response.get('status') == 200:
                            target_request_id = params['requestId']
                            print(f"   ✅ Found request ID: {target_request_id[:20]}...")
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
                    print(f"   ✅ SUCCESS! CDP captured {size:,} bytes")
                    result['success'] = True
                    result['source'] = 'cdp_performance_logs'
                    result['data'] = api_data
                    result['size_bytes'] = size
                    self.api_captured = True
                    return result
        except Exception as e:
            print(f"   ⚠️  Method 2 failed: {e}")
        
        # METHOD 3: Performance API entries
        print("   [Method 3] Checking Performance API...")
        try:
            perf_script = """
            return performance.getEntries()
                .filter(e => e.name && e.name.includes('tracking-system/reverse/tracking'))
                .map(e => ({url: e.name, duration: e.duration}));
            """
            entries = sb.driver.execute_script(perf_script)
            
            if entries and len(entries) > 0:
                api_url = entries[0]['url']
                print(f"   ✅ Found API URL")
                
                # Try cached fetch
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
                    print(f"   ✅ SUCCESS! Cached fetch {size:,} bytes")
                    result['success'] = True
                    result['source'] = 'cached_fetch'
                    result['data'] = api_data
                    result['size_bytes'] = size
                    self.api_captured = True
                    return result
        except Exception as e:
            print(f"   ⚠️  Method 3 failed: {e}")
        
        # All methods failed
        print("   ❌ All API capture methods failed")
        result['error'] = 'all_methods_failed'
        return result

    def _extract_basic_data(self, sb, bol_number):
        """Extract data from HTML (fallback + validation)"""
        soup = BeautifulSoup(sb.get_page_source(), 'html.parser')
        
        data = {
            'bol_number': bol_number,
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
            'route_events': [],
            'vessels': [],
            'containers': [],
            'scraped_at': datetime.now().isoformat()
        }
        
        # Extract reference
        ref_elem = soup.find(attrs={'data-reference': True})
        if ref_elem:
            data['reference_number'] = ref_elem.get('data-reference')
            print(f"   ✅ Reference: {data['reference_number']}")
        
        # Extract type
        type_elem = soup.find(attrs={'data-test-id': 'card-reference-type'})
        if type_elem:
            data['reference_type'] = type_elem.get_text(strip=True)
            print(f"   ✅ Type: {data['reference_type']}")
        
        # Extract status
        status_elem = soup.find(attrs={'data-test-id': re.compile(r'card-status-')})
        if status_elem:
            data['status'] = status_elem.get_text(strip=True)
            print(f"   ✅ Status: {data['status']}")
        
        # Extract carrier
        carrier_img = soup.find('img', class_=re.compile(r'.*RhAQya.*'))
        if carrier_img and carrier_img.get('alt'):
            data['carrier'] = carrier_img.get('alt')
            print(f"   ✅ Carrier: {data['carrier']}")
        
        # Extract origin/destination
        origin_elem = soup.find(attrs={'data-test-id': re.compile(r'card-direction-from-')})
        if origin_elem:
            data['origin'] = origin_elem.get_text(strip=True)
            
        dest_elem = soup.find(attrs={'data-test-id': re.compile(r'card-direction-to-')})
        if dest_elem:
            data['destination'] = dest_elem.get_text(strip=True)
            
        if data['origin'] and data['destination']:
            print(f"   ✅ Route: {data['origin']} → {data['destination']}")
        
        # Extract route events
        self._extract_route_events(soup, data)
        
        return data

    def _extract_route_events(self, soup, data):
        """Extract timeline events"""
        location_blocks = soup.find_all('div', class_=re.compile(r'.*CL5ccK.*'))
        if location_blocks:
            print(f"   ✅ Route events: {len(location_blocks)}")
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

    def _extract_vessel_data(self, sb, data):
        """Extract vessel information from vessels tab"""
        soup = BeautifulSoup(sb.get_page_source(), 'html.parser')
        vessel_blocks = soup.find_all('div', class_=re.compile(r'.*g0DglG.*'))
        
        print(f"   ✅ Vessels found: {len(vessel_blocks)}")
        
        for vessel_block in vessel_blocks:
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

    def _extract_containers_data(self, sb, data):
        """Extract container details from containers tab"""
        soup = BeautifulSoup(sb.get_page_source(), 'html.parser')
        container_numbers = soup.find_all(string=re.compile(r'^[A-Z]{4}\d{7}$'))
        
        print(f"   ✅ Containers found: {len(container_numbers)}")
        
        for container_num in container_numbers:
            container = {
                'container_number': container_num.strip(),
                'type': None,
                'size': None,
                'status': None
            }
            data['containers'].append(container)

    def _merge_data(self, api_data, html_data, screenshot, bol_number):
        """
        Merge API and HTML data
        Priority: API > HTML (HTML as validation/fallback)
        """
        result = {
            'bol_number': bol_number,
            'scraped_at': datetime.now().isoformat(),
            'screenshot': screenshot,
            'data_sources': []
        }
        
        # If API captured successfully
        if api_data['success'] and api_data['data']:
            result['api_response'] = api_data
            result['data_sources'].append(f"API ({api_data['source']})")
            
            # Save FULL API data separately
            result['tracking_data'] = api_data['data']
            
        else:
            result['api_response'] = api_data
            result['data_sources'].append("API (failed)")
        
        # Always include HTML data (validation + fallback)
        result['html_data'] = html_data
        result['data_sources'].append("HTML scraping")
        
        return result

    def _print_summary(self, result):
        """Print execution summary"""
        print(f"\n{'='*70}")
        print("📊 SCRAPING SUMMARY")
        print(f"{'='*70}")
        print(f"BOL: {result['bol_number']}")
        print(f"Data Sources: {', '.join(result['data_sources'])}")
        
        if result['api_response']['success']:
            api = result['api_response']
            print(f"✅ API Captured: YES ({api['size_bytes']:,} bytes via {api['source']})")
            
            # Show API data summary
            if api['data']:
                metadata = api['data'].get('data', {}).get('metadata', {})
                print(f"   Status: {metadata.get('status', 'N/A')}")
                print(f"   Sealine: {metadata.get('sealine_name', 'N/A')}")
                print(f"   Containers: {len(api['data'].get('data', {}).get('containers', []))}")
        else:
            print(f"❌ API Captured: NO ({result['api_response'].get('error', 'unknown')})")
        
        # Show HTML data
        html = result['html_data']
        print(f"\n📄 HTML Data:")
        print(f"   Status: {html.get('status', 'N/A')}")
        print(f"   Carrier: {html.get('carrier', 'N/A')}")
        print(f"   Route: {html.get('origin', 'N/A')} → {html.get('destination', 'N/A')}")
        print(f"   Vessels: {len(html.get('vessels', []))}")
        print(f"   Route Events: {len(html.get('route_events', []))}")
        print(f"   Containers: {len(html.get('containers', []))}")
        
        print(f"\n📸 Screenshot: {result['screenshot']}")
        print(f"{'='*70}\n")


def save_results(data, bol_number):
    """Save all results to organized files"""
    os.makedirs('data', exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # 1. Save complete unified data
    unified_file = f"data/unified_{bol_number}_{timestamp}.json"
    with open(unified_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ Unified data: {unified_file}")
    
    # 2. Save FULL API response separately (if captured)
    if data['api_response']['success'] and data['api_response']['data']:
        api_file = f"data/api_full_{bol_number}_{timestamp}.json"
        with open(api_file, 'w', encoding='utf-8') as f:
            json.dump(data['api_response']['data'], f, indent=2, ensure_ascii=False)
        size = len(json.dumps(data['api_response']['data']))
        print(f"✅ FULL API data: {api_file} ({size:,} bytes)")
    
    # 3. Save HTML data separately
    html_file = f"data/html_{bol_number}_{timestamp}.json"
    with open(html_file, 'w', encoding='utf-8') as f:
        json.dump(data['html_data'], f, indent=2, ensure_ascii=False)
    print(f"✅ HTML data: {html_file}")
    
    # 4. Save text report
    report_file = f"data/report_{bol_number}_{timestamp}.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("="*70 + "\n")
        f.write("SEARATES UNIFIED TRACKING REPORT\n")
        f.write("="*70 + "\n\n")
        f.write(f"BOL: {bol_number}\n")
        f.write(f"Scraped: {data['scraped_at']}\n")
        f.write(f"Sources: {', '.join(data['data_sources'])}\n\n")
        
        if data['api_response']['success']:
            f.write("✅ FULL API DATA CAPTURED\n\n")
            api_data = data['api_response']['data']
            metadata = api_data.get('data', {}).get('metadata', {})
            f.write(f"Status: {metadata.get('status')}\n")
            f.write(f"Sealine: {metadata.get('sealine_name')}\n")
            f.write(f"Updated: {metadata.get('updated_at')}\n\n")
        
        html = data['html_data']
        f.write("HTML DATA:\n")
        f.write(f"Status: {html.get('status')}\n")
        f.write(f"Carrier: {html.get('carrier')}\n")
        f.write(f"Route: {html.get('origin')} → {html.get('destination')}\n")
        f.write(f"Vessels: {len(html.get('vessels', []))}\n")
        f.write(f"Containers: {len(html.get('containers', []))}\n")
    
    print(f"✅ Report: {report_file}")


def main():
    # Read BOL numbers from file or use default
    try:
        with open('bol_list.txt', 'r') as f:
            bol_numbers = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except FileNotFoundError:
        # Fallback to command line or default
        if len(sys.argv) > 1:
            bol_numbers = [sys.argv[1]]
        else:
            bol_numbers = ["3100124492"]
        print(f"⚠️  bol_list.txt not found, using: {bol_numbers}")
    
    print("\n" + "="*70)
    print("🚀 SEARATES UNIFIED SCRAPER")
    print("   API Capture + HTML Scraping + Cloudflare Bypass")
    print("="*70)
    print(f"📋 Processing {len(bol_numbers)} BOL(s)\n")
    
    scraper = UnifiedSeaRatesScraper()
    all_results = []
    
    for idx, bol in enumerate(bol_numbers, 1):
        print(f"\n{'='*70}")
        print(f"BOL {idx}/{len(bol_numbers)}: {bol}")
        print(f"{'='*70}")
        
        # Run unified scraper
        result = scraper.track(bol, "AUTO")
        
        if 'error' not in result:
            # Save individual results
            save_results(result, bol)
            all_results.append(result)
        else:
            print(f"❌ Failed to scrape {bol}")
            all_results.append(result)
        
        # Wait between BOLs (rate limiting)
        if idx < len(bol_numbers):
            print("\n⏳ Waiting 10 seconds before next BOL...")
            time.sleep(10)
    
    # Save combined results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    combined_file = f"data/combined_{timestamp}.json"
    combined_data = {
        'total_bols': len(bol_numbers),
        'successful': len([r for r in all_results if 'error' not in r]),
        'failed': len([r for r in all_results if 'error' in r]),
        'results': all_results,
        'generated_at': datetime.now().isoformat()
    }
    
    with open(combined_file, 'w', encoding='utf-8') as f:
        json.dump(combined_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*70}")
    print(f"✅ COMPLETED: {len(bol_numbers)} BOL(S)")
    print(f"   Success: {combined_data['successful']}")
    print(f"   Failed: {combined_data['failed']}")
    print(f"   Combined: {combined_file}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
