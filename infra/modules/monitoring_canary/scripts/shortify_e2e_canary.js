const synthetics = require('Synthetics');
const log = require('SyntheticsLogger');
const http = require('http');
const https = require('https');

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function parseJsonSafe(raw, contextName) {
  try {
    return JSON.parse(raw);
  } catch (e) {
    throw new Error(`${contextName}: JSON parse failed. body=${String(raw).substring(0, 1000)}`);
  }
}

async function readResponseBody(res) {
  let body = '';
  await new Promise((resolve, reject) => {
    res.on('data', (chunk) => {
      body += chunk;
    });
    res.on('end', resolve);
    res.on('error', reject);
  });
  return body;
}

/**
 * 단일 HTTP 요청 (redirect follow 없음)
 * - GET /{shortId} 리다이렉트 검증용
 */
function doSingleRequest(options, payload, label = 'HTTP') {
  const client = options.protocol === 'https:' ? https : http;

  return new Promise((resolve, reject) => {
    const startedAt = Date.now();
    let settled = false;

    const safeReject = (err) => {
      if (settled) return;
      settled = true;
      reject(err);
    };

    const safeResolve = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };

    log.info(`[${label}] request:init method=${options.method} host=${options.hostname} path=${options.path}`);

    const req = client.request(options, (res) => {
      log.info(`[${label}] response:headers status=${res.statusCode}`);

      let body = '';
      let chunkCount = 0;

      res.on('data', (chunk) => {
        chunkCount += 1;
        body += chunk;
        if (chunkCount <= 3) {
          log.info(`[${label}] response:data chunk#${chunkCount} len=${chunk.length}`);
        }
      });

      res.on('end', () => {
        const elapsed = Date.now() - startedAt;
        log.info(`[${label}] response:end bytes=${Buffer.byteLength(body)} elapsedMs=${elapsed}`);
        safeResolve({
          statusCode: res.statusCode,
          headers: res.headers || {},
          body
        });
      });

      res.on('error', (err) => {
        const elapsed = Date.now() - startedAt;
        log.error(`[${label}] response:error elapsedMs=${elapsed} err=${err.message}`);
        safeReject(err);
      });
    });

    // ---- socket 단계 추적
    req.on('socket', (socket) => {
      log.info(`[${label}] socket:assigned`);

      socket.on('lookup', (err, address, family, host) => {
        log.info(
          `[${label}] socket:lookup host=${host} address=${address || '-'} family=${family || '-'} err=${err ? err.message : 'none'}`
        );
      });

      socket.on('connect', () => {
        log.info(`[${label}] socket:connect`);
      });

      socket.on('secureConnect', () => {
        log.info(`[${label}] socket:secureConnect tls=yes`);
      });

      socket.on('timeout', () => {
        log.error(`[${label}] socket:timeout`);
      });

      socket.on('close', (hadError) => {
        log.info(`[${label}] socket:close hadError=${hadError}`);
      });

      socket.on('error', (err) => {
        log.error(`[${label}] socket:error err=${err.message}`);
      });
    });

    // ---- 요청 타임아웃 (소켓 inactivity)
    req.setTimeout(15000, () => {
      const elapsed = Date.now() - startedAt;
      const err = new Error(`[${label}] request timeout (15s), elapsedMs=${elapsed}`);
      log.error(err.message);
      req.destroy(err);
    });

    // ---- 요청 자체 에러
    req.on('error', (err) => {
      const elapsed = Date.now() - startedAt;
      log.error(`[${label}] request:error elapsedMs=${elapsed} err=${err.message}`);
      safeReject(err);
    });

    // ---- payload 쓰기
    if (payload) {
      log.info(`[${label}] request:write payloadBytes=${Buffer.byteLength(payload)}`);
      req.write(payload);
    }

    req.end();
    log.info(`[${label}] request:end called`);
  });
}

exports.handler = async () => {
  const handlerStartedAt = Date.now();

  try {
    log.info('[VERSION] shortify_e2e_canary debug-v2');

    const baseUrl = process.env.API_BASE_URL;
    const testShortenUrl = process.env.TEST_SHORTEN_URL || 'https://example.com/canary';
    const testShortenTitle = process.env.TEST_SHORTEN_TITLE || 'synthetics-canary-test';
    const aiPeriod = process.env.AI_PERIOD || 'P#30MIN';

    assert(baseUrl, 'API_BASE_URL env is required');

    const normalizedBase = baseUrl.replace(/\/+$/, '');
    const base = new URL(normalizedBase);

    log.info(`[INIT] API_BASE_URL=${normalizedBase}`);
    log.info(`[INIT] TEST_SHORTEN_URL=${testShortenUrl}`);
    log.info(`[INIT] TEST_SHORTEN_TITLE=${testShortenTitle}`);
    log.info(`[INIT] AI_PERIOD=${aiPeriod}`);

    const commonRequest = {
      hostname: base.hostname,
      port: base.port ? Number(base.port) : (base.protocol === 'https:' ? 443 : 80),
      protocol: base.protocol,
      headers: {
        'User-Agent': 'synthetics-canary',
        'X-Synthetic-Test': 'true',
        'Connection': 'close'
      },
      timeout: 15000,
      requestTimeout: 15000,
      responseTimeout: 15000
    };

  // =========================================================
  // STEP 1) POST /shorten
  // =========================================================
  const shortenPayload = JSON.stringify({
    url: testShortenUrl,
    title: testShortenTitle
  });

  const shortenOptions = {
    ...commonRequest,
    method: 'POST',
    path: '/shorten',
    headers: {
      ...commonRequest.headers,
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(shortenPayload)
    }
  };

  let shortenStatusCode;
  let shortenHeaders = {};
  let shortenRawBody = '';

  log.info('[STEP1] About to call POST /shorten');

  const postRes = await doSingleRequest({
    hostname: commonRequest.hostname,
    port: commonRequest.port,
    protocol: commonRequest.protocol,
    method: 'POST',
    path: '/shorten',
    headers: {
      ...commonRequest.headers,
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(shortenPayload)
    }
  }, shortenPayload, 'POST_shorten');
  
  shortenStatusCode = postRes.statusCode;
  shortenHeaders = postRes.headers || {};
  shortenRawBody = postRes.body || '';
  
  log.info(`[POST_shorten] status=${shortenStatusCode}`);
  log.info(`[POST_shorten] headers=${JSON.stringify(shortenHeaders)}`);
  log.info(`[POST_shorten] body=${shortenRawBody.substring(0, 1000)}`);

  assert([200, 201].includes(shortenStatusCode), `POST /shorten expected 200/201 but got ${shortenStatusCode}`);

  const shortenJson = parseJsonSafe(shortenRawBody, 'POST /shorten');

  // API 스펙에 따라 필드명 다를 수 있으니 약간 유연하게
  const shortId = shortenJson.shortId || shortenJson.id;
  const shortUrl = shortenJson.shortUrl || shortenJson.urlShort || shortenJson.url;

  assert(shortId, 'POST /shorten response missing shortId');
  assert(shortUrl, 'POST /shorten response missing shortUrl');

  log.info(`[STEP1] Extracted shortId=${shortId}`);
  log.info(`[STEP1] Extracted shortUrl=${shortUrl}`);

  // =========================================================
  // STEP 2) GET /{shortId} (redirect no-follow)
  // - executeHttpStep 대신 단일 요청으로 최초 응답만 검증
  // =========================================================
  const redirectOptions = {
    hostname: commonRequest.hostname,
    port: commonRequest.port,
    protocol: commonRequest.protocol,
    method: 'GET',
    path: `/${encodeURIComponent(shortId)}`,
    headers: {
      ...commonRequest.headers
    }
  };

  log.info(`[STEP2] About to call GET /${shortId} (no redirect follow)`);

  const redirectRes = await doSingleRequest(redirectOptions, null, 'GET_shortid_redirect');
  const redirectStatusCode = redirectRes.statusCode;
  const redirectHeaders = redirectRes.headers || {};

  log.info(`[GET_shortid_redirect] status=${redirectStatusCode}`);
  log.info(`[GET_shortid_redirect] headers=${JSON.stringify(redirectHeaders)}`);

  assert([301, 302].includes(redirectStatusCode), `GET /{shortId} expected 301/302 but got ${redirectStatusCode}`);

  const locationHeader = redirectHeaders.location || redirectHeaders.Location;
  assert(locationHeader, 'GET /{shortId} missing Location header');

  // 가능하면 원본 URL 확인 (추적 파라미터 붙을 수 있어 startsWith)
  assert(
    locationHeader.startsWith(testShortenUrl),
    `GET /{shortId} Location mismatch. expected startsWith=${testShortenUrl}, actual=${locationHeader}`
  );

  // =========================================================
  // STEP 3) GET /stats/{shortId}
  // - 스키마는 환경마다 다를 수 있어 "핵심 존재 여부" 위주로 검증
  // =========================================================
  const statsOptions = {
    ...commonRequest,
    method: 'GET',
    path: `/stats/${encodeURIComponent(shortId)}`
  };

  let statsStatusCode;
  let statsHeaders = {};
  let statsRawBody = '';

  log.info(`[STEP3] About to call GET /stats/${shortId}`);

  const statsRes = await doSingleRequest({
    hostname: commonRequest.hostname,
    port: commonRequest.port,
    protocol: commonRequest.protocol,
    method: 'GET',
    path: `/stats/${encodeURIComponent(shortId)}`,
    headers: {
      ...commonRequest.headers
    }
  }, null, 'GET_stats_by_shortid');
  
  statsStatusCode = statsRes.statusCode;
  statsHeaders = statsRes.headers || {};
  statsRawBody = statsRes.body || '';
  
  log.info(`[GET_stats_by_shortid] status=${statsStatusCode}`);
  log.info(`[GET_stats_by_shortid] headers=${JSON.stringify(statsHeaders)}`);
  log.info(`[GET_stats_by_shortid] body=${statsRawBody.substring(0, 1500)}`);

  assert(statsStatusCode === 200, `GET /stats/{shortId} expected 200 but got ${statsStatusCode}`);

  const statsJson = parseJsonSafe(statsRawBody, 'GET /stats/{shortId}');

  // ---- 필수성 검증 (너의 실제 API 응답 구조에 맞춰 유연하게)
  // shortId 기준 조회 여부 확인
  if (statsJson.shortId) {
    assert(
      statsJson.shortId === shortId,
      `GET /stats/{shortId} shortId mismatch. expected=${shortId}, actual=${statsJson.shortId}`
    );
  }

  // 네가 말한 clicks / stats 구조가 있으면 통과
  // 또는 실제 구현(totalClicks / timeseries / referrers 등)도 통과하도록 허용
  const hasClicksLike =
    Object.prototype.hasOwnProperty.call(statsJson, 'clicks') ||
    Object.prototype.hasOwnProperty.call(statsJson, 'totalClicks');

  const hasStatsLike =
    Object.prototype.hasOwnProperty.call(statsJson, 'stats') ||
    Object.prototype.hasOwnProperty.call(statsJson, 'timeseries') ||
    Object.prototype.hasOwnProperty.call(statsJson, 'clicksByHour') ||      // ✅ 실제 응답
    Object.prototype.hasOwnProperty.call(statsJson, 'clicksByDay') ||       // ✅ 실제 응답
    Object.prototype.hasOwnProperty.call(statsJson, 'clicksByReferer') ||   // ✅ 실제 응답
    Object.prototype.hasOwnProperty.call(statsJson, 'referrers') ||         // 호환용
    Object.prototype.hasOwnProperty.call(statsJson, 'referers') ||          // 철자 변형 호환
    Object.prototype.hasOwnProperty.call(statsJson, 'topReferer') ||        // ✅ 실제 응답
    Object.prototype.hasOwnProperty.call(statsJson, 'peakHour'); 

  assert(hasClicksLike, 'GET /stats/{shortId} response missing clicks-like field (clicks or totalClicks)');
  assert(hasStatsLike, 'GET /stats/{shortId} response missing stats-like field (stats/timeseries/referrers/etc)');

  // =========================================================
  // STEP 4) GET /ai/latest?period=P%2330MIN
  // =========================================================
  const encodedPeriod = encodeURIComponent(aiPeriod);
  const aiPath = `/ai/latest?period=${encodedPeriod}`;

  const aiOptions = {
    ...commonRequest,
    method: 'GET',
    path: aiPath
  };

  let aiStatusCode;
  let aiHeaders = {};
  let aiRawBody = '';

  log.info(`[STEP4] About to call GET ${aiPath}`);

  const aiRes = await doSingleRequest({
    hostname: commonRequest.hostname,
    port: commonRequest.port,
    protocol: commonRequest.protocol,
    method: 'GET',
    path: aiPath,
    headers: {
      ...commonRequest.headers
    }
  }, null, 'GET_ai_latest');
  
  aiStatusCode = aiRes.statusCode;
  aiHeaders = aiRes.headers || {};
  aiRawBody = aiRes.body || '';
  
  log.info(`[GET_ai_latest] status=${aiStatusCode}`);
  log.info(`[GET_ai_latest] headers=${JSON.stringify(aiHeaders)}`);
  log.info(`[GET_ai_latest] body=${aiRawBody.substring(0, 1500)}`);

  assert(aiStatusCode === 200, `GET /ai/latest expected 200 but got ${aiStatusCode}`);

  const aiJson = parseJsonSafe(aiRawBody, 'GET /ai/latest');

  const aiPeriodLike = aiJson.periodKey || aiJson.period;
  assert(aiPeriodLike, 'GET /ai/latest response missing periodKey/period');
  
  assert(aiJson.aiGeneratedAt, 'GET /ai/latest response missing aiGeneratedAt');

  // 선택 필드(aiTrend, aiInsight)는 없어도 실패 처리 안 함
  if (!Object.prototype.hasOwnProperty.call(aiJson, 'aiTrend')) {
    log.info('[GET_ai_latest] aiTrend is missing (allowed)');
  }
  if (!Object.prototype.hasOwnProperty.call(aiJson, 'aiInsight')) {
    log.info('[GET_ai_latest] aiInsight is missing (allowed)');
  }

   log.info(`✅ Canary completed successfully (POST /shorten -> redirect -> stats -> ai/latest) totalMs=${Date.now() - handlerStartedAt}`);
  } catch (err) {
    log.error(`❌ Canary failed totalMs=${Date.now() - handlerStartedAt} err=${err?.message}`);
    log.error(err?.stack || String(err));
    throw err;
  }
};