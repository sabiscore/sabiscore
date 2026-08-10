"""
Deployment Validation Script
Polls backend and frontend until all endpoints return 200, validates model loading
"""

import sys
import time
import json
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError


def colored(text: str, color: str) -> str:
    """Simple ANSI color wrapper"""
    colors = {
        'green': '\033[92m',
        'yellow': '\033[93m',
        'red': '\033[91m',
        'blue': '\033[94m',
        'reset': '\033[0m'
    }
    return f"{colors.get(color, '')}{text}{colors['reset']}"


def check_endpoint(base_url: str, path: str, expected_status=200, timeout=15) -> tuple[bool, str]:
    """Check a single endpoint with timeout"""
    try:
        req = Request(f"{base_url}{path}", headers={"User-Agent": "SabiScore-Deploy-Validator/1.0"})
        with urlopen(req, timeout=timeout) as response:
            status = response.getcode()
            body = response.read()
            
            if status == expected_status:
                # Try to parse JSON for details
                try:
                    data = json.loads(body)
                    detail = json.dumps(data, indent=2)[:200]  # First 200 chars
                    return True, f"Status {status} ✓ - {detail}"
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return True, f"Status {status} ✓"
            else:
                return False, f"Status {status} (expected {expected_status})"
    except HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except URLError as e:
        return False, f"Network error: {e.reason}"
    except Exception as e:
        return False, f"Error: {str(e)}"


def validate_backend(base_url: str) -> dict:
    """Validate all critical backend endpoints"""
    print(colored(f"\n{'='*70}", 'blue'))
    print(colored("BACKEND VALIDATION", 'blue'))
    print(colored(f"{'='*70}", 'blue'))
    print(f"Target: {base_url}\n")
    
    results = {}
    endpoints = [
        ("/health", 200, "Basic health check"),
        ("/health/live", 200, "Liveness probe"),
        ("/health/ready", 200, "Readiness probe (models loaded)"),
        ("/openapi.json", 200, "OpenAPI schema"),
        ("/api/v1/matches/upcoming", 200, "Upcoming matches endpoint"),
        ("/api/v1/predictions/value-bets/today", 200, "Value bets endpoint"),
    ]
    
    for path, expected, description in endpoints:
        print(f"Testing {path:40} ... ", end="", flush=True)
        success, message = check_endpoint(base_url, path, expected)
        results[path] = success
        
        if success:
            print(colored("✓ PASS", 'green'), f"- {message}")
        else:
            print(colored("✗ FAIL", 'red'), f"- {message}")
    
    # Special validation for /health/ready to check model status
    print("\nValidating model loading status ... ", end="", flush=True)
    try:
        req = Request(f"{base_url}/health/ready", headers={"User-Agent": "SabiScore-Deploy-Validator/1.0"})
        with urlopen(req, timeout=15) as response:
            data = json.loads(response.read())
            models_loaded = data.get('models', False)
            
            if models_loaded:
                print(colored("✓ Models loaded successfully", 'green'))
                results['_models_loaded'] = True
            else:
                error_msg = data.get('model_error', 'Unknown error')
                print(colored(f"✗ Models not loaded: {error_msg}", 'red'))
                results['_models_loaded'] = False
    except Exception as e:
        print(colored(f"✗ Could not verify model status: {e}", 'red'))
        results['_models_loaded'] = False
    
    return results


def validate_frontend(base_url: str) -> dict:
    """Validate critical frontend endpoints and assets"""
    print(colored(f"\n{'='*70}", 'blue'))
    print(colored("FRONTEND VALIDATION", 'blue'))
    print(colored(f"{'='*70}", 'blue'))
    print(f"Target: {base_url}\n")
    
    results = {}
    endpoints = [
        ("/", 200, "Homepage"),
        ("/favicon.ico", 200, "Favicon"),
        ("/api/v1/health", 200, "API proxy to backend"),
    ]
    
    for path, expected, description in endpoints:
        print(f"Testing {path:40} ... ", end="", flush=True)
        success, message = check_endpoint(base_url, path, expected)
        results[path] = success
        
        if success:
            print(colored("✓ PASS", 'green'), f"- {message}")
        else:
            print(colored("✗ FAIL", 'red'), f"- {message}")
    
    return results


def poll_until_ready(backend_url: str, frontend_url: str = None, max_attempts=20, interval=30):
    """Poll endpoints until all pass or max attempts reached"""
    print(colored(f"\n{'='*70}", 'blue'))
    print(colored("DEPLOYMENT VALIDATION - POLLING MODE", 'blue'))
    print(colored(f"{'='*70}\n", 'blue'))
    print(f"Backend:  {backend_url}")
    if frontend_url:
        print(f"Frontend: {frontend_url}")
    print(f"Max attempts: {max_attempts}")
    print(f"Interval: {interval}s\n")
    
    for attempt in range(1, max_attempts + 1):
        print(colored(f"\n--- Attempt {attempt}/{max_attempts} ---", 'yellow'))
        
        # Validate backend
        backend_results = validate_backend(backend_url)
        backend_passed = all(v for k, v in backend_results.items() if not k.startswith('_'))
        models_loaded = backend_results.get('_models_loaded', False)
        
        # Validate frontend if provided
        frontend_passed = True
        if frontend_url:
            frontend_results = validate_frontend(frontend_url)
            frontend_passed = all(frontend_results.values())
        
        # Check if everything passed
        if backend_passed and frontend_passed and models_loaded:
            print(colored(f"\n{'='*70}", 'green'))
            print(colored("✓ ALL VALIDATION CHECKS PASSED!", 'green'))
            print(colored(f"{'='*70}", 'green'))
            print(f"Deployment is ready after {attempt} attempt(s)")
            return 0
        
        # Report status
        print(colored("\nStatus Summary:", 'yellow'))
        print(f"  Backend: {colored('✓ PASS', 'green') if backend_passed else colored('✗ FAIL', 'red')}")
        print(f"  Models:  {colored('✓ LOADED', 'green') if models_loaded else colored('✗ NOT LOADED', 'red')}")
        if frontend_url:
            print(f"  Frontend: {colored('✓ PASS', 'green') if frontend_passed else colored('✗ FAIL', 'red')}")
        
        if attempt < max_attempts:
            print(f"\nWaiting {interval}s before retry...")
            time.sleep(interval)
        else:
            print(colored(f"\n{'='*70}", 'red'))
            print(colored("✗ DEPLOYMENT VALIDATION FAILED", 'red'))
            print(colored(f"{'='*70}", 'red'))
            print("Max attempts reached. Some endpoints are still failing.")
            return 1
    
    return 1


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python scripts/validate_deployment.py <backend_url> [frontend_url]")
        print("\nExamples:")
        print("  python scripts/validate_deployment.py https://your-backend.example.com")
        print("  python scripts/validate_deployment.py https://your-backend.example.com https://your-web.example.com")
        print("\nOptions:")
        print("  --poll    Poll until ready (max 20 attempts, 30s interval)")
        return 1
    
    backend_url = sys.argv[1].rstrip('/')
    frontend_url = sys.argv[2].rstrip('/') if len(sys.argv) > 2 else None
    
    # Check for --poll flag
    if '--poll' in sys.argv:
        return poll_until_ready(backend_url, frontend_url)
    
    # Single validation run
    backend_results = validate_backend(backend_url)
    backend_passed = all(v for k, v in backend_results.items() if not k.startswith('_'))
    models_loaded = backend_results.get('_models_loaded', False)
    
    frontend_passed = True
    if frontend_url:
        frontend_results = validate_frontend(frontend_url)
        frontend_passed = all(frontend_results.values())
    
    # Summary
    print(colored(f"\n{'='*70}", 'blue'))
    print(colored("VALIDATION SUMMARY", 'blue'))
    print(colored(f"{'='*70}", 'blue'))
    print(f"Backend:  {colored('✓ PASS', 'green') if backend_passed else colored('✗ FAIL', 'red')}")
    print(f"Models:   {colored('✓ LOADED', 'green') if models_loaded else colored('✗ NOT LOADED', 'red')}")
    if frontend_url:
        print(f"Frontend: {colored('✓ PASS', 'green') if frontend_passed else colored('✗ FAIL', 'red')}")
    
    if backend_passed and frontend_passed and models_loaded:
        print(colored("\n✓ Deployment validation successful!", 'green'))
        return 0
    else:
        print(colored("\n✗ Deployment validation failed. Check logs above.", 'red'))
        return 1


if __name__ == "__main__":
    sys.exit(main())
