import asyncio
import httpx
import argparse
import time
import sys
import statistics

async def make_request(client, url, idx):
    alert = {
        "metric": "memory_bytes",
        "value": 500_000_000.0,
        "mean": 100_000_000.0,
        "stddev": 5_000_000.0,
        "z_score": 80.0,
        "fired_at": time.time() + idx,
    }
    start = time.time()
    try:
        response = await client.post(url, json=alert)
        latency = time.time() - start
        if response.status_code != 200:
            return {"status": "error", "error": f"HTTP {response.status_code}", "latency": latency}
        data = response.json()
        
        # Validating usable diagnosis
        if not data.get("root_cause"):
            return {"status": "error", "error": "Missing root_cause", "latency": latency}
        if not data.get("recommended_action"):
            return {"status": "error", "error": "Missing recommended_action", "latency": latency}
        if not data.get("runbook_id"):
            return {"status": "error", "error": "Missing runbook_id", "latency": latency}
            
        return {"status": "success", "latency": latency}
    except httpx.TimeoutException:
        latency = time.time() - start
        return {"status": "timeout", "latency": latency}
    except Exception as e:
        latency = time.time() - start
        return {"status": "error", "error": str(e), "latency": latency}

async def run_load_test(url, num_requests, concurrency):
    print(f"Starting load test against {url}")
    print(f"Total requests: {num_requests}, Concurrency: {concurrency}")
    
    timeout = httpx.Timeout(120.0) # Larger timeout for the client itself so we can see real latencies
    
    # We use a semaphore to limit concurrency
    sem = asyncio.Semaphore(concurrency)
    
    async def bound_request(client, idx):
        async with sem:
            return await make_request(client, url, idx)
            
    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [bound_request(client, i) for i in range(num_requests)]
        results = await asyncio.gather(*tasks)
        
    successes = [r for r in results if r["status"] == "success"]
    timeouts = [r for r in results if r["status"] == "timeout"]
    errors = [r for r in results if r["status"] == "error"]
    
    latencies = [r["latency"] for r in results]
    success_latencies = [r["latency"] for r in successes]
    
    print("=" * 40)
    print("LOAD TEST RESULTS")
    print("=" * 40)
    print(f"Total requests: {len(results)}")
    print(f"Successful: {len(successes)} ({len(successes)/len(results)*100:.1f}%)")
    print(f"Failed: {len(errors)} ({len(errors)/len(results)*100:.1f}%)")
    print(f"Timeouts: {len(timeouts)} ({len(timeouts)/len(results)*100:.1f}%)")
    
    if latencies:
        print(f"\nOverall Average latency: {statistics.mean(latencies):.2f}s")
        print(f"Overall Maximum latency: {max(latencies):.2f}s")
    
    if success_latencies:
        print(f"Success Average latency: {statistics.mean(success_latencies):.2f}s")
        if len(success_latencies) >= 2:
            p95 = statistics.quantiles(success_latencies, n=100)[94]
            print(f"Success p95 latency: {p95:.2f}s")
        print(f"Success Max latency: {max(success_latencies):.2f}s")
        
    for e in errors:
        print(f"Error: {e.get('error')}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load test diagnosis agent")
    parser.add_argument("--url", default="http://localhost:8001/diagnose", help="Diagnosis endpoint URL")
    parser.add_argument("--requests", type=int, default=10, help="Total requests to send")
    parser.add_argument("--concurrency", type=int, default=2, help="Max concurrent requests")
    
    args = parser.parse_args()
    asyncio.run(run_load_test(args.url, args.requests, args.concurrency))
