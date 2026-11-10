/**
 * Snacky Studio - Phase 7 Scale & Performance k6 Benchmark Suite
 *
 * Tests API throughput, latency profiles, and cache hit efficiency under
 * smoke, stress, and spike traffic patterns.
 *
 * Usage:
 *   k6 run scripts/k6_benchmark.js
 *   k6 run --env BASE_URL=http://localhost:8000 --env API_KEY=snk_live_test scripts/k6_benchmark.js
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

// Custom Metrics
const errorRate = new Rate('custom_error_rate');
const healthLatency = new Trend('health_req_duration');
const metadataLatency = new Trend('metadata_req_duration');
const apiV1Latency = new Trend('api_v1_req_duration');
const cacheHitCounter = new Counter('cache_hits_simulated');

// Benchmark Configuration & Scenarios
export const options = {
  scenarios: {
    // 1. Smoke test: Verify baseline health with low load
    smoke: {
      executor: 'constant-vus',
      vus: 5,
      duration: '30s',
      gracefulStop: '5s',
      tags: { scenario: 'smoke' },
    },
    // 2. Stress test: Ramp up to evaluate sustained concurrency
    stress: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '20s', target: 20 },
        { duration: '30s', target: 50 },
        { duration: '10s', target: 0 },
      ],
      gracefulRampDown: '5s',
      startTime: '35s',
      tags: { scenario: 'stress' },
    },
    // 3. Spike test: High-volume burst to test cache cushioning & rate limiting
    spike: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '5s', target: 100 },
        { duration: '20s', target: 100 },
        { duration: '5s', target: 0 },
      ],
      gracefulRampDown: '5s',
      startTime: '100s',
      tags: { scenario: 'spike' },
    },
  },
  thresholds: {
    // 95% of all requests must complete within 100ms; 99% within 250ms
    http_req_duration: ['p(95)<100', 'p(99)<250'],
    // Less than 1% failure rate overall
    http_req_failed: ['rate<0.01'],
    // Health check must be ultra-fast (<25ms p95)
    health_req_duration: ['p(95)<25'],
    // Metadata cached lookups should remain sub-50ms under load
    metadata_req_duration: ['p(95)<50'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';
const API_KEY = __ENV.API_KEY || '';

export default function () {
  const commonHeaders = {
    'Accept': 'application/json',
    'User-Agent': 'k6-load-benchmark/1.0',
  };

  if (API_KEY) {
    commonHeaders['Authorization'] = `Bearer ${API_KEY}`;
  }

  // Group 1: High-Frequency Read Operations (Health & Prometheus Metrics)
  group('Liveness & Readiness', () => {
    const res = http.get(`${BASE_URL}/health/ready`, { headers: commonHeaders });
    healthLatency.add(res.timings.duration);
    const passed = check(res, {
      'ready endpoint returns 200': (r) => r.status === 200,
      'ready latency < 50ms': (r) => r.timings.duration < 50,
    });
    if (!passed) errorRate.add(1);
  });

  // Group 2: Prometheus Metrics Scraping
  group('Observability Metrics Scrape', () => {
    const res = http.get(`${BASE_URL}/metrics`, { headers: commonHeaders });
    check(res, {
      'metrics endpoint returns 200': (r) => r.status === 200,
      'metrics format is text/plain': (r) => r.headers['Content-Type'] && r.headers['Content-Type'].includes('text/plain'),
    });
  });

  // Group 3: Hot Metadata & Tasks Listing (Tests Promoted Column Indexes & Redis Caching)
  group('Metadata & History Query', () => {
    const res = http.get(`${BASE_URL}/api/history`, { headers: commonHeaders });
    metadataLatency.add(res.timings.duration);
    const passed = check(res, {
      'history returns 200 or 401 (if auth required)': (r) => r.status === 200 || r.status === 401,
      'response duration < 100ms': (r) => r.timings.duration < 100,
    });
    if (!passed && res.status !== 401) {
      errorRate.add(1);
    } else {
      cacheHitCounter.add(1);
    }
  });

  // Group 4: V1 API Endpoint (Idempotent listing)
  group('V1 API Endpoints', () => {
    const res = http.get(`${BASE_URL}/api/v1/tasks?limit=10`, { headers: commonHeaders });
    apiV1Latency.add(res.timings.duration);
    check(res, {
      'v1 tasks responds safely': (r) => r.status === 200 || r.status === 401,
    });
  });

  sleep(0.1 + Math.random() * 0.2); // Jittered sleep between 100ms-300ms
}

